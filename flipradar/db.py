"""SQLite-Speicher: gesehene Inserate, Preisverlauf, gesendete Alarme."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    key          TEXT PRIMARY KEY,
    platform     TEXT NOT NULL,
    listing_id   TEXT NOT NULL,
    product      TEXT,
    title        TEXT,
    url          TEXT,
    price_chf    REAL,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listings_product ON listings(product, last_seen);
CREATE TABLE IF NOT EXISTS candidates (key TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS retail (url TEXT PRIMARY KEY, checked REAL NOT NULL, price REAL);
CREATE TABLE IF NOT EXISTS pending (key TEXT PRIMARY KEY, price REAL NOT NULL, message TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (
    key          TEXT NOT NULL,
    price_chf    REAL NOT NULL,
    sent_at      TEXT NOT NULL,
    PRIMARY KEY (key, price_chf)
);
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def get(self, key: str):
        cur = self.conn.execute(
            "SELECT price_chf, product FROM listings WHERE key = ?", (key,)
        )
        return cur.fetchone()

    def upsert(
        self, listing: Listing, product_name: str | None, track: bool = True
    ) -> str:
        """Speichert ein Inserat. Rückgabe: 'neu', 'billiger' oder 'bekannt'."""
        now = _iso(listing.seen_at)
        row = self.get(listing.key)
        if row is None:
            self.conn.execute(
                "INSERT INTO listings (key, platform, listing_id, product, title, url, price_chf, first_seen, last_seen)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    listing.key,
                    listing.platform,
                    listing.listing_id,
                    product_name,
                    listing.title,
                    listing.url,
                    listing.price_chf,
                    now,
                    now,
                ),
            )
            status = "neu"
        else:
            old_price = row[0]
            self.conn.execute(
                "UPDATE listings SET last_seen = ?, price_chf = ?, product = ?, title = ? WHERE key = ?",
                (now, listing.price_chf, product_name, listing.title, listing.key),
            )
            if old_price != listing.price_chf or row[1] != product_name:
                self.conn.execute("DELETE FROM pending WHERE key=?", (listing.key,))
                self.conn.execute("DELETE FROM candidates WHERE key=?", (listing.key,))
            if listing.price_chf and (
                old_price is None or listing.price_chf < old_price * 0.97
            ):
                status = "billiger"
            else:
                status = "bekannt"
        if track and product_name and status in ("neu", "billiger"):
            self.conn.execute(
                "INSERT OR IGNORE INTO candidates VALUES(?)", (listing.key,)
            )
        self.conn.commit()
        return status

    def eligible(self, key):
        return (
            self.conn.execute("SELECT 1 FROM candidates WHERE key=?", (key,)).fetchone()
            is not None
        )

    def comparable_prices(
        self,
        product_name: str,
        lookback_days: int,
        exclude_key: str | None = None,
        platforms: list[str] | None = None,
    ) -> list[float]:
        since = _iso(datetime.now(timezone.utc) - timedelta(days=lookback_days))
        sql = "SELECT key, price_chf FROM listings WHERE product = ? AND last_seen >= ? AND price_chf > 0"
        params: list = [product_name, since]
        if platforms:
            sql += f" AND platform IN ({','.join('?' * len(platforms))})"
            params += platforms
        cur = self.conn.execute(sql, params)
        return [price for key, price in cur.fetchall() if key != exclude_key]

    def already_alerted(self, key: str, price_chf: float) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM alerts WHERE key = ? AND price_chf <= ?", (key, price_chf)
        )
        return cur.fetchone() is not None

    def mark_alerted(self, key: str, price_chf: float) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO alerts (key, price_chf, sent_at) VALUES (?,?,?)",
            (key, price_chf, _iso(datetime.now(timezone.utc))),
        )
        self.conn.execute("DELETE FROM candidates WHERE key=?", (key,))
        self.conn.execute(
            "DELETE FROM pending WHERE key=? AND price=?", (key, price_chf)
        )
        self.conn.commit()

    def queue(self, key, price, message):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO pending VALUES (?,?,?)", (key, price, message)
            )

    def deliver(self, telegram, attempted=()):
        for key, price, message in self.conn.execute(
            "SELECT key,price,message FROM pending"
        ).fetchall():
            if (key, price) in attempted:
                continue
            if telegram.send(message):
                self.mark_alerted(key, price)
                logging.getLogger("flipradar").info("Telegram gesendet: %s", key)

    def stats(self, lookback_days=None, platforms=None) -> list[tuple]:
        filters = ["product IS NOT NULL", "price_chf > 0"]
        params = []
        if lookback_days is not None:
            filters.append("last_seen >= ?")
            params.append(
                _iso(datetime.now(timezone.utc) - timedelta(days=lookback_days))
            )
        if platforms:
            filters.append("platform IN (" + ",".join("?" for _ in platforms) + ")")
            params.extend(platforms)
        cur = self.conn.execute(
            "SELECT product, COUNT(*), ROUND(AVG(price_chf),0), MIN(price_chf), MAX(price_chf)"
            " FROM listings WHERE "
            + " AND ".join(filters)
            + " GROUP BY product ORDER BY product",
            params,
        )
        return cur.fetchall()
