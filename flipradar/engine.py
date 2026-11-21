"""Independent source state, price comparisons and durable alert delivery."""

import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from .sources import Ebay, search
from .matcher import has_any, match_product
from .platforms import excluded_terms
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
        self.platforms = list(dict.fromkeys(settings.platforms))
        self.collect_only = set(settings.collect_only)
        if "ebay" in self.platforms and not (
            settings.ebay_client_id and settings.ebay_client_secret
        ):
            self.platforms.remove("ebay")
            log.warning(
                "eBay.de inaktiv: Produktionsschluessel fehlen. Beim Start E fuer Einstellungen waehlen."
            )
        self.store.conn.executescript("""
            CREATE TABLE IF NOT EXISTS pauses(platform TEXT PRIMARY KEY, until REAL, reason TEXT);
            CREATE TABLE IF NOT EXISTS state(name TEXT PRIMARY KEY);
        """)

    def cycle(self, products, alerts_enabled=True):
        s, db = self.s, self.store
        warm = (
            s.warmup_first_cycle
            and not db.conn.execute("SELECT 1 FROM state WHERE name='ready'").fetchone()
            and not db.stats()
        )
        if warm:
            log.info(
                "Erstlauf: Vergleichspreise sammeln. Danach sind Deal-Alarme aktiv."
            )
        prices = refresh_prices(products, db)
        sold = load_sales(s.sales_csv, s.lookback_days)
        paused = {
            n
            for n, end, msg in db.conn.execute("SELECT * FROM pauses")
            if self._paused(n, end, msg)
        }
        stats = {n: Counter() for n in self.platforms}
        attempted = set()
        for pos, product in enumerate(products, 1):
            log.info("Suche %d/%d: %s", pos, len(products), product.name)
            candidates = {}
            active = [
                name
                for name in self.platforms
                if name not in paused
                and (not product.platforms or name in product.platforms)
            ]
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
                    paused.add(name)
                    continue
                count["Suchen"] += 1
                count["Inserate"] += len(listings)
                log.info("%s: %d Inserate", name, len(listings))
                for item in listings:
                    item.price_chf = to_chf(item, s)
                    matched = match_product(item, products)
                    if matched and has_any(item.title, excluded_terms(name)):
                        matched = None
                    if matched and matched.platforms and name not in matched.platforms:
                        matched = None
                    # Keep accessory and implausibly low prices out of the Swiss median.
                    if matched and (
                        not item.price_chf or item.price_chf < matched.min_price_chf
                    ):
                        matched = None
                    status = db.upsert(
                        item,
                        matched.name if matched else None,
                        track=not warm and alerts_enabled and name not in self.collect_only,
                    )
                    if status == "neu":
                        count["neu"] += 1
                    if (
                        matched
                        and alerts_enabled
                        and not warm
                        and name not in self.collect_only
                        and db.eligible(item.key)
                    ):
                        candidates[item.key] = (item, matched)
            for item, matched in candidates.values():
                comps = db.comparable_prices(
                    matched.name, s.lookback_days, item.key, s.value_platforms
                )
                comps = [price for price in comps if price >= matched.min_price_chf]
                deal = evaluate(
                    item,
                    matched,
                    comps,
                    s,
                    sold.get(matched.name),
                    prices.get(matched.name),
                )
                if not deal or db.already_alerted(item.key, item.price_chf):
                    continue
                if (item.key, item.price_chf) in attempted:
                    continue
                msg = format_deal(deal)
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
        if not warm and alerts_enabled:
            db.deliver(self.telegram, attempted)
        if any(c["Suchen"] for c in stats.values()):
            with db.conn:
                db.conn.execute("INSERT OR IGNORE INTO state VALUES('ready')")
        for n, c in stats.items():
            log.info(
                "%s: %d erfolgreiche Suchen, %d Inserate, %d neu, %d Deals%s",
                n,
                c["Suchen"],
                c["Inserate"],
                c["neu"],
                c["Deals"],
                " (pausiert)" if n in paused else " (nur sammeln)" if n in self.collect_only else "",
            )
        pending = db.conn.execute("SELECT COUNT(*) FROM pending").fetchone()[0]
        log.info("Durchlauf fertig. Telegram ausstehend: %d", pending)
        return stats

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
