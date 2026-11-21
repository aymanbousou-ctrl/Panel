"""Independent source state, price comparisons and durable alert delivery."""

import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from datetime import datetime, date, timedelta
from .discovery import init_discovery, probe_product, record, expanded, FAMILIES
from .handel import choose, inventory, profile, write_trends
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from .sources import Ebay, search
from .matcher import has_any, match_product
from .platforms import PLATFORMS, excluded_terms
from .notify import format_deal
from .sales import load_sales
from .retail import refresh_prices
from .pricing import to_chf, evaluate

log = logging.getLogger("flipradar")


def delay_on_error(exc):
    if isinstance(exc, HTTPError):
        if exc.code == 429:
            raw = exc.headers.get("Retry-After", "") if exc.headers else ""
            if raw.isdecimal():
                return max(60, int(raw))
            try:
                return max(
                    60, int(parsedate_to_datetime(raw).timestamp() - time.time())
                )
            except (TypeError, ValueError, OverflowError):
                return 1800
        if exc.code in (401, 403):
            return 3600
    return 300


class Radar:
    def __init__(self, settings, store, telegram):
        self.s, self.store, self.telegram = settings, store, telegram
        self.ebay = Ebay(settings)
        init_discovery(store)
        self.platforms = list(dict.fromkeys(settings.platforms))
        self.collect_only = set(settings.collect_only)
        for name in list(self.platforms):
            if PLATFORMS[name].paid and not settings.apify_token:
                self.platforms.remove(name)
                log.warning(
                    "%s inaktiv: Apify-Token fehlt. Beim Start E fuer Einstellungen waehlen.",
                    PLATFORMS[name].label,
                )
        if "ebay" in self.platforms and not (
            settings.ebay_client_id and settings.ebay_client_secret
        ):
            self.platforms.remove("ebay")
            log.warning(
                "eBay.de inaktiv: Produktionsschluessel fehlen. Beim Start E fuer Einstellungen waehlen."
            )
        log.info(
            "Telegram-Alarme von: %s | nur sammeln: %s",
            ", ".join(p for p in self.platforms if p not in self.collect_only) or "keiner Quelle",
            ", ".join(p for p in self.platforms if p in self.collect_only) or "keine",
        )
        self.store.conn.executescript("""
            CREATE TABLE IF NOT EXISTS source_status(platform TEXT PRIMARY KEY, last_ok REAL, last_new REAL, last_error TEXT, last_error_at REAL);
            CREATE TABLE IF NOT EXISTS paid_runs(platform TEXT, product TEXT, last REAL, PRIMARY KEY(platform, product));
            CREATE TABLE IF NOT EXISTS pauses(platform TEXT PRIMARY KEY, until REAL, reason TEXT);
            CREATE TABLE IF NOT EXISTS opportunities(key TEXT PRIMARY KEY,product TEXT,first_day TEXT);
            CREATE TABLE IF NOT EXISTS rotation(id INTEGER PRIMARY KEY, cursor INTEGER);
            CREATE TABLE IF NOT EXISTS warmed(platform TEXT,product TEXT,PRIMARY KEY(platform,product));
        """)

    def cycle(self, products, alerts_enabled=True):
        s, db = self.s, self.store
        products = (
            expanded(db, products, s.disabled_models) if s.discovery else products
        )
        today = date.today().isoformat()
        unknown = set(s.apify_products) - {p.name for p in products}
        if unknown:
            log.warning("apify.products nennt unbekannte Produkte: %s", sorted(unknown))
        folder = Path(s.db_path).resolve().parent
        samples, invested = inventory(folder / "Bestand.csv")
        sold = load_sales(s.sales_csv, s.lookback_days, samples)
        cutoff = (date.today() - timedelta(days=6)).isoformat()
        for name, n in db.conn.execute(
            "SELECT product,count(*) FROM opportunities WHERE first_day>=? GROUP BY product",
            (cutoff,),
        ):
            samples[name].opportunities = n
        available = max(0, s.portfolio_chf - invested)
        cursor = db.conn.execute("SELECT cursor FROM rotation WHERE id=1").fetchone()
        batch, next_cursor = choose(
            products, samples, cursor[0] if cursor else 0, s.batch_size
        )
        log.info(
            "%d von %d Produkten in dieser Runde. Freies Kapital %.2f CHF.",
            len(batch),
            len(products),
            available,
        )
        prices = refresh_prices(batch, db)
        paused = {
            n
            for n, end, msg in db.conn.execute("SELECT * FROM pauses")
            if self._paused(n, end, msg)
        }
        stats = {n: Counter() for n in self.platforms}
        attempted = set()
        probe, probe_pos = probe_product(db)
        jobs = list(batch) + ([probe] if s.discovery and len(products) > 1 else [])
        for pos, product in enumerate(jobs, 1):
            log.info("Suche %d/%d: %s", pos, len(jobs), product.name)
            candidates = {}
            active = [
                name
                for name in self.platforms
                if name not in paused
                and (not product.platforms or name in product.platforms)
                and self._due(name, product)
            ]
            if "ebay" in active:
                with db.conn:
                    db.conn.execute("INSERT OR IGNORE INTO calls VALUES(?,0)", (today,))
                    used = db.conn.execute(
                        "UPDATE calls SET n=n+1 WHERE day=? AND n<?",
                        (today, s.ebay_daily_calls),
                    )
                if not used.rowcount:
                    active.remove("ebay")
                    paused.add("ebay")
                    log.warning("eBay-Tageslimit erreicht.")
            if not active:
                continue
            with ThreadPoolExecutor(max_workers=len(active)) as pool:
                replies = {
                    name: pool.submit(search, name, product, s, self.ebay)
                    for name in active
                }
            for name, reply in replies.items():
                count = stats[name]
                try:
                    listings = reply.result()
                except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                    delay = delay_on_error(exc)
                    reason = (
                        f"HTTP {exc.code}"
                        if isinstance(exc, HTTPError)
                        else f"{type(exc).__name__}"
                    )
                    if isinstance(exc, ValueError):
                        reason += " " + str(exc)[:130]
                    if isinstance(exc, HTTPError):
                        exc.close()
                    end = time.time() + delay
                    with db.conn:
                        db.conn.execute(
                            "INSERT OR REPLACE INTO pauses VALUES(?,?,?)",
                            (name, end, reason),
                        )
                    self._paused(name, end, reason)
                    count["Fehler"] += 1
                    self._note(name, error=reason)
                    paused.add(name)
                    continue
                count["Suchen"] += 1
                self._note(name)
                count["Inserate"] += len(listings)
                log.info("%s: %d Inserate", name, len(listings))
                if product is probe:
                    record(db, probe_pos, listings, products)
                    continue
                warm = (
                    s.warmup_first_cycle
                    and not db.conn.execute(
                        "SELECT 1 FROM warmed WHERE platform=? AND product=?",
                        (name, product.name),
                    ).fetchone()
                )
                for item in listings:
                    item.price_chf = to_chf(item, s)
                    matched = match_product(item, products)
                    if matched and has_any(item.title, excluded_terms(name)):
                        matched = None
                    details = profile(item, matched) if matched else None
                    if (
                        not details
                        or (matched.platforms and name not in matched.platforms)
                        or not item.price_chf
                        or item.price_chf / details[0] < matched.min_price_chf
                    ):
                        matched = None
                        count["ausgefiltert"] += 1
                    if matched:
                        units, grade, variant = details
                        db.conn.execute(
                            "INSERT OR REPLACE INTO profiles VALUES(?,?,?,?,?)",
                            (item.key, units, grade, variant, item.location or ""),
                        )
                    else:
                        db.conn.execute("DELETE FROM profiles WHERE key=?", (item.key,))
                    status = db.upsert(
                        item,
                        matched.name if matched else None,
                        track=not warm
                        and alerts_enabled
                        and name not in self.collect_only,
                    )
                    if status == "neu":
                        count["neu"] += 1
                    if (
                        matched
                        and not warm
                        and alerts_enabled
                        and name not in self.collect_only
                        and db.eligible(item.key)
                    ):
                        candidates[item.key] = (item, matched, *details)
                with db.conn:
                    db.conn.execute(
                        "INSERT OR IGNORE INTO warmed VALUES(?,?)", (name, product.name)
                    )
                    db.conn.execute(
                        "INSERT OR IGNORE INTO scan VALUES(?,?)", (product.name, today)
                    )
            for item, matched, units, grade, variant in candidates.values():
                if "?" in variant:
                    stats[item.platform]["Variante unklar"] += 1
                    continue
                comps = db.single_prices(matched, s, item, grade, variant)
                specific = bool(variant) or grade != "Standard"
                deal = evaluate(
                    item,
                    replace(matched, ref_price_chf=None) if specific else matched,
                    comps,
                    s,
                    None if specific else sold.get(matched.name),
                    prices.get(matched.name),
                    units,
                    grade,
                    available,
                )
                if not deal:
                    stats[item.platform]["Bewertung/Kaufregeln"] += 1
                    with db.conn:
                        db.conn.execute("DELETE FROM pending WHERE key=?", (item.key,))
                    continue
                if db.already_alerted(item.key, item.price_chf):
                    continue
                with db.conn:
                    added = db.conn.execute(
                        "INSERT OR IGNORE INTO opportunities VALUES(?,?,?)",
                        (item.key, matched.name, today),
                    )
                    samples[matched.name].opportunities += added.rowcount
                if (item.key, item.price_chf) in attempted:
                    continue
                msg = (
                    format_deal(deal)
                    + "\nEigene Verkäufe binnen 30 Tagen: "
                    + samples[matched.name].rate()
                    + f"\nEigene Verkäufe: {samples[matched.name].recent} in 7 Tagen, {samples[matched.name].previous} in der Vorwoche."
                )
                db.queue(item.key, item.price_chf, msg)
                attempted.add((item.key, item.price_chf))
                stats[item.platform]["Deals"] += 1
                if self.telegram.send(msg):
                    db.mark_alerted(item.key, item.price_chf)
                    log.info("Telegram gesendet: %s / %s", item.platform, matched.name)
                else:
                    log.warning(
                        "Telegram ausstehend: %s / %s", item.platform, matched.name
                    )
            time.sleep(max(0, s.request_delay_seconds))
        if alerts_enabled:
            db.expire_pending()
        with db.conn:
            if probe in jobs:
                db.conn.execute(
                    "INSERT OR REPLACE INTO probe_cursor VALUES(1,?)",
                    ((probe_pos + 1) % len(FAMILIES),),
                )
            db.conn.execute(
                "INSERT OR REPLACE INTO rotation VALUES(1,?)", (next_cursor,)
            )
        try:
            write_trends(folder / "Trends.csv", products, samples, db)
        except OSError as exc:
            log.warning(
                "Trends.csv konnte nicht aktualisiert werden. Datei ggf. in Excel schließen (%s).",
                type(exc).__name__,
            )
        for n, c in stats.items():
            if c["neu"]:
                self._note(n, new=True)
            self._log_status(n)
            log.info(
                "%s: %d erfolgreiche Suchen, %d Inserate, %d neu, %d Deals%s",
                n,
                c["Suchen"],
                c["Inserate"],
                c["neu"],
                c["Deals"],
                " (pausiert)"
                if n in paused
                else " (nur sammeln)"
                if n in self.collect_only
                else "",
            )
            if c["ausgefiltert"] or c["Variante unklar"] or c["Bewertung/Kaufregeln"]:
                log.info(
                    "%s: %d Artikel-/Preisfilter, %d unklare Variante, %d ohne passende Bewertung oder Kaufkriterien",
                    n,
                    c["ausgefiltert"],
                    c["Variante unklar"],
                    c["Bewertung/Kaufregeln"],
                )
        pending = db.conn.execute("SELECT COUNT(*) FROM pending").fetchone()[0]
        log.info("Durchlauf fertig. Telegram ausstehend: %d", pending)
        return stats

    def _note(self, name, error="", new=False):
        now = time.time()
        with self.store.conn:
            self.store.conn.execute(
                "INSERT OR IGNORE INTO source_status(platform) VALUES(?)", (name,)
            )
            if error:
                self.store.conn.execute(
                    "UPDATE source_status SET last_error=?, last_error_at=? WHERE platform=?",
                    (error[:160], now, name),
                )
            elif new:
                self.store.conn.execute(
                    "UPDATE source_status SET last_new=? WHERE platform=?", (now, name)
                )
            else:
                self.store.conn.execute(
                    "UPDATE source_status SET last_ok=? WHERE platform=?", (now, name)
                )

    def _log_status(self, name):
        row = self.store.conn.execute(
            "SELECT last_ok,last_new,last_error,last_error_at FROM source_status WHERE platform=?",
            (name,),
        ).fetchone()
        if not row:
            return

        def when(ts):
            return datetime.fromtimestamp(ts).strftime("%d.%m. %H:%M") if ts else "noch nie"

        ok, new, error, error_at = row
        log.info(
            "Status %s: letzter Abruf %s · letzte neue Inserate %s · letzter Fehler %s",
            name,
            when(ok),
            when(new),
            f"{when(error_at)} ({error})" if error else "keiner",
        )
        # Eine Suche kann funktionieren und trotzdem stundenlang dieselben Treffer liefern.
        if (
            not PLATFORMS[name].paid
            and ok
            and new
            and ok - new > 6 * 3600
        ):
            log.warning(
                "%s liefert seit mehr als 6 Stunden keine neuen Inserate. Suche oder Seite prüfen.",
                name,
            )

    def _due(self, name, product):
        """Bezahlte Quellen laufen nur fuer gewaehlte Produkte und mit Mindestabstand.

        Der Versuch wird sofort vermerkt, damit auch ein Fehlschlag nicht jeden
        Durchlauf erneut Geld kostet.
        """
        if not PLATFORMS[name].paid:
            return True
        if product.name not in self.s.apify_products:
            return False
        now = time.time()
        row = self.store.conn.execute(
            "SELECT last FROM paid_runs WHERE platform=? AND product=?",
            (name, product.name),
        ).fetchone()
        if row and now - row[0] < self.s.apify_interval_minutes * 60:
            return False
        with self.store.conn:
            self.store.conn.execute(
                "INSERT OR REPLACE INTO paid_runs VALUES(?,?,?)",
                (name, product.name, now),
            )
        return True

    @staticmethod
    def _paused(name, end, reason):
        if end <= time.time():
            return False
        log.warning(
            "%s pausiert bis %s (%s)",
            name,
            datetime.fromtimestamp(end).strftime("%d.%m. %H:%M"),
            reason,
        )
        return True
