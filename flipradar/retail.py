"""Aktuelle Neupreise für explizit zugeordnete Schweizer Shopartikel."""

import json
import logging
import math
import time
from urllib.parse import urlparse

from .net import read
from bs4 import BeautifulSoup

log = logging.getLogger("flipradar")
SHOPS = {"www.galaxus.ch", "www.digitec.ch"}


def product_id(url):
    path = urlparse(url)
    if (
        path.scheme != "https"
        or path.hostname not in SHOPS
        or "/product/" not in path.path
    ):
        return None
    number = path.path.rstrip("/").rsplit("-", 1)[-1]
    return number if number.isdecimal() else None


def retail_price(html, sku):
    soup = BeautifulSoup(html, "html.parser")
    prices = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if (
                not isinstance(node, dict)
                or node.get("@type") != "Product"
                or str(node.get("sku")) != sku
            ):
                continue
            offers = node.get("offers", [])
            for offer in offers if isinstance(offers, list) else [offers]:
                if not isinstance(offer, dict) or offer.get("priceCurrency") != "CHF":
                    continue
                if str(offer.get("availability")).split("/")[-1] != "InStock":
                    continue
                if str(offer.get("itemCondition")).split("/")[-1] != "NewCondition":
                    continue
                try:
                    price = float(offer["price"])
                except (TypeError, ValueError, KeyError):
                    continue
                if math.isfinite(price) and price > 0:
                    prices.append(price)
    return min(prices, default=None)


def refresh_prices(products, store):
    prices = {}
    for product in products:
        url = product.retail_url
        if not url:
            continue
        row = store.conn.execute(
            "SELECT checked, price FROM retail WHERE url=?", (url,)
        ).fetchone()
        now = time.time()
        if row and now - row[0] < 3600:
            price = row[1]
        else:
            sku = product_id(url)
            if not sku:
                log.warning("Ungueltiger Shoplink fuer %s", product.name)
                continue
            try:
                body, final_url = read(url, timeout=12)
                price = (
                    retail_price(body, sku) if product_id(final_url) == sku else None
                )
            except (OSError, ValueError) as exc:
                log.warning("Neupreis %s: %s", product.name, type(exc).__name__)
                price = None
            if price is None:
                log.warning("Kein bestätigter Neupreis: %s", product.name)
            with store.conn:
                store.conn.execute(
                    "INSERT OR REPLACE INTO retail VALUES (?,?,?)", (url, now, price)
                )
        if price is not None:
            prices[product.name] = price
    return prices
