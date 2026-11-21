"""FlipRadar 2.1. Run from any working directory."""

import argparse
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from logging.handlers import RotatingFileHandler

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "vendor"), str(ROOT)]
from flipradar.config import load_settings, load_watchlist
from flipradar.db import Store
from flipradar.engine import Radar
from flipradar.notify import Telegram
from flipradar.platforms import PLATFORMS
from flipradar.setup import data_dir, edit, init
from flipradar.sources import Ebay, search


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "mode",
        choices=[
            "run",
            "once",
            "bestand",
            "settings",
            "diagnose",
            "stats",
            "test-telegram",
        ],
        default="run",
        nargs="?",
    )
    ap.add_argument(
        "--no-alerts",
        action="store_true",
        help="Nur sammeln, Telegram-Versand aussetzen",
    )
    args = ap.parse_args()
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    os.chdir(folder)
    if args.mode == "bestand" and (folder / "config.yaml").exists():
        from flipradar.bestand import edit as edit_bestand

        edit_bestand(folder, load_watchlist(folder / "watchlist.yaml"))
        return 0
    guard = sqlite3.connect(folder / "instance.lock.sqlite", timeout=0)
    try:
        guard.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError:
        print("Ein V2-Fenster verwendet diesen Datenordner bereits.")
        return 1
    try:
        init(folder)
        if args.mode == "bestand":
            from flipradar.bestand import edit as edit_bestand

            edit_bestand(folder, load_watchlist(folder / "watchlist.yaml"))
            return 0
        if args.mode == "settings":
            edit(folder)
        s = load_settings(folder / "config.yaml")
        products = load_watchlist(folder / "watchlist.yaml")
        if not products:
            raise ValueError("Watchlist enthaelt keine aktiven Produkte.")
        log = logging.getLogger("flipradar")
        logger = RotatingFileHandler(
            s.log_path, maxBytes=4_000_000, backupCount=3, encoding="utf-8"
        )
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            handlers=[logging.StreamHandler(sys.stdout), logger],
        )
        tg = Telegram(s.telegram_token, s.telegram_chat_id)
        log.info("FlipRadar 2.1 | Python %s | %s", sys.version.split()[0], folder)
        log.info(
            "%d Produkte | Schwelle %.0f %% | bis %.0f CHF | Zielintervall %.1f Minuten",
            len(products),
            s.min_margin * 100,
            s.max_price_chf,
            s.interval_minutes,
        )
        if args.mode == "test-telegram":
            if args.no_alerts:
                return 0
            return 0 if tg.send("FlipRadar 2.1 – Telegram-Test erfolgreich.") else 1
        if args.mode == "stats":
            db = Store(s.db_path)
            try:
                rows = db.stats(s.lookback_days, s.value_platforms)
                for name, n, avg, lo, hi in rows:
                    print(f"{name}: {n} Vergleichspreise, Spanne {lo:g}–{hi:g} CHF")
                if not rows:
                    print("Noch keine Schweizer Vergleichspreise gesammelt.")
            finally:
                db.close()
            return 0
        if not tg.configured:
            log.warning(
                "Telegram fehlt. Mit E beim Start einrichten. Deals bleiben vorgemerkt."
            )
        if args.mode == "diagnose":
            ebay = Ebay(s)
            failures = 0
            for name in s.platforms:
                if name == "ebay" and not (s.ebay_client_id and s.ebay_client_secret):
                    log.warning("eBay.de: Zugangsdaten fehlen")
                    continue
                if PLATFORMS[name].paid:
                    if not s.apify_token:
                        log.warning("%s: Apify-Token fehlt", name)
                        continue
                    log.info(
                        "%s: kostenpflichtiger Testlauf, bis zu %d Treffer",
                        name,
                        s.apify_max_results,
                    )
                product = next(
                    (p for p in products if not p.platforms or name in p.platforms),
                    None,
                )
                if product is None:
                    continue
                try:
                    rows = search(name, product, s, ebay)
                    log.info(
                        "%s / %s: %d lesbare Inserate", name, product.name, len(rows)
                    )
                except Exception as exc:
                    failures += 1
                    log.warning(
                        "%s: %s %s", name, type(exc).__name__, getattr(exc, "code", "")
                    )
            if (
                not args.no_alerts
                and tg.configured
                and not tg.send("FlipRadar 2.1 – Telegram-Test erfolgreich.")
            ):
                failures += 1
            return int(bool(failures))
        db = Store(s.db_path)
        try:
            radar = Radar(s, db, tg)
            while True:
                started = time.monotonic()
                report = radar.cycle(products, alerts_enabled=not args.no_alerts)
                if args.mode == "once":
                    return 0 if any(c["Suchen"] for c in report.values()) else 1
                delay = max(30, s.interval_minutes * 60 - (time.monotonic() - started))
                log.info("Naechster Durchlauf in %.1f Minuten.", delay / 60)
                time.sleep(delay)
        finally:
            db.close()
    finally:
        guard.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("FlipRadar beendet.")
    except Exception as exc:
        print(f"Startfehler ({type(exc).__name__}): {exc}", file=sys.stderr)
        sys.exit(1)
