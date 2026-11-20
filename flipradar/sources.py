"""Publicly displayed listings and the official eBay Browse API."""

import base64
import json
import math
import re
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup
from .models import Listing
from .net import read, read_json
from .pricing import parse_price


def page(data):
    return BeautifulSoup(data.decode("utf-8"), "html.parser")


def tutti(data):
    soup = page(data)
    script = soup.find("script", id="__NEXT_DATA__")
    if not script:
        raise ValueError("Tutti-Suchergebnisse fehlen im HTML")
    queries = json.loads(script.get_text())["props"]["pageProps"]["dehydratedState"][
        "queries"
    ]
    for query in queries:
        block = query.get("state", {}).get("data")
        if isinstance(block, dict) and isinstance(block.get("listings"), dict):
            rows = block["listings"]["edges"]
            result = []
            for row in rows:
                item = row["node"]
                sku = str(item["listingID"])
                title = item["localization"]["title"]
                if not sku.isdecimal() or not title:
                    continue
                price, vb = parse_price(item.get("formattedPrice"), "CHF")
                place = item.get("postcodeInformation") or {}
                result.append(
                    Listing(
                        "tutti",
                        sku,
                        title,
                        "https://www.tutti.ch/de/vi/" + sku,
                        price,
                        "CHF",
                        location=place.get("locationName") or "",
                        negotiable=vb,
                    )
                )
            return result
    raise ValueError("Tutti-Seitenformat unbekannt")


def ricardo(data):
    soup = page(data)
    cards = soup.select_one('[data-testid="regular-results"]')
    if cards is None:
        if re.search(
            r"\b(?:0 (?:Ergebnisse|Resultate)|keine (?:Ergebnisse|Resultate) gefunden)\b",
            soup.get_text(" ", strip=True),
            re.I,
        ):
            return []
        raise ValueError("Ricardo-Ergebnisbereich fehlt")
    result = {}
    names = {}
    schema = soup.select_one("script#srps-json-ld")
    if schema:
        for graph in json.loads(schema.get_text()).get("@graph", []):
            for entry in graph.get("itemListElement", []):
                item = entry.get("item") or {}
                names[urlsplit(item.get("url", "")).path] = item.get("name", "")
    for anchor in cards.select('a[href^="/de/a/"]'):
        path = anchor["href"]
        sku = re.search(r"-(\d+)/?$", path)
        label = anchor.get_text(" ", strip=True)
        # The card may quote BOTH a current bid and a buy-now price.
        price = re.search(r"([\d][\d'’]*[.]\d{2})\s+Sofort kaufen\b", label, re.I)
        if not price or not sku:
            continue
        picture = anchor.find("img", alt=True, src=re.compile(r"/images/"))
        title = names.get(path) or (picture["alt"] if picture else "")
        if not title:
            continue
        key = sku[1]
        result[key] = Listing(
            "ricardo",
            key,
            title,
            urljoin("https://www.ricardo.ch", path),
            parse_price(price[1])[0],
            "CHF",
        )
    if (
        not result
        and cards.select('a[href^="/de/a/"]')
        and not re.search(r"Gebot", cards.get_text(" ", strip=True), re.I)
    ):
        raise ValueError("Ricardo-Preisformat unbekannt")
    return list(result.values())


def kleinanzeigen(data):
    soup = page(data)
    cards = soup.select("article[data-adid]")
    if (
        not cards
        and not soup.select_one("#srchrslt-nocontent")
        and not re.search(
            r"\b(?:Keine Anzeigen gefunden|0 Ergebnisse für)\b",
            soup.get_text(" ", strip=True),
            re.I,
        )
    ):
        raise ValueError("Kleinanzeigen-Ergebnisbereich fehlt")
    result = []
    for card in cards:
        link = card.select_one('h2 a[href^="/s-anzeige/"], h3 a[href^="/s-anzeige/"]')
        if not link:
            continue
        field = card.select_one(
            "p.text-secondary, p.aditem-main--middle--price-shipping--price"
        )
        price, vb = parse_price(
            field.get_text(" ", strip=True) if field else None, "EUR"
        )
        if field and field.find(["del", "s"]):
            field.find(["del", "s"]).decompose()
            price, vb = parse_price(field.get_text(" ", strip=True), "EUR")
        marker = card.select_one('[data-title="locationOutline"]')
        location = marker.parent.get_text(" ", strip=True) if marker else ""
        description = card.select_one(
            "p.text-onSurfaceSubdued, p.aditem-main--middle--description"
        )
        result.append(
            Listing(
                "kleinanzeigen",
                str(card["data-adid"]),
                link.get_text(" ", strip=True),
                urljoin("https://www.kleinanzeigen.de", link["href"]),
                price,
                "EUR",
                location=location,
                description=description.get_text(" ", strip=True)
                if description
                else "",
                negotiable=vb,
            )
        )
    if cards and not result:
        raise ValueError("Kleinanzeigen-Titel oder Links nicht erkannt")
    return result


class Ebay:
    def __init__(self, settings):
        self.settings = settings
        self.token = ""
        self.expires = 0

    def authorize(self):
        basic = base64.b64encode(
            f"{self.settings.ebay_client_id}:{self.settings.ebay_client_secret}".encode()
        ).decode()
        response = read_json(
            "https://api.ebay.com/identity/v1/oauth2/token",
            data=urlencode(
                {
                    "grant_type": "client_credentials",
                    "scope": "https://api.ebay.com/oauth/api_scope",
                }
            ).encode(),
            headers={
                "Authorization": "Basic " + basic,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        self.token = response["access_token"]
        self.expires = time.monotonic() + max(0, int(response["expires_in"]) - 60)

    def search(self, product):
        if time.monotonic() >= self.expires:
            self.authorize()
        params = urlencode(
            {
                "q": product.query,
                "sort": "newlyListed",
                "limit": min(200, self.settings.max_results_per_search),
                "filter": "buyingOptions:{FIXED_PRICE},itemLocationCountry:DE",
            }
        )
        try:
            result = read_json(
                "https://api.ebay.com/buy/browse/v1/item_summary/search?" + params,
                headers={
                    "Authorization": "Bearer " + self.token,
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY_DE",
                },
            )
        except HTTPError as exc:
            if exc.code == 401:
                self.expires = 0
            raise
        if "itemSummaries" not in result and result.get("total") != 0:
            raise ValueError("eBay-Antwort ohne Suchergebnisse oder Trefferzahl")
        rows = []
        for item in result.get("itemSummaries", []):
            price = item.get("price") or {}
            if price.get("currency") != "EUR" or "FIXED_PRICE" not in item.get(
                "buyingOptions", []
            ):
                continue
            if item.get("itemLocation", {}).get("country") != "DE":
                continue
            url = item.get("itemWebUrl", "")
            if urlsplit(url).scheme != "https" or urlsplit(url).hostname not in {
                "ebay.de",
                "www.ebay.de",
            }:
                continue
            value = float(price["value"])
            if math.isfinite(value) and value > 0:
                rows.append(
                    Listing("ebay", item["itemId"], item["title"], url, value, "EUR")
                )
        return rows


def search(name, p, settings, ebay):
    if name == "ebay":
        return ebay.search(p)
    if name == "tutti":
        url = "https://www.tutti.ch/de/q?" + urlencode({"query": p.query})
        parser = tutti
    elif name == "ricardo":
        url = "https://www.ricardo.ch/de/s/" + quote(p.query, safe="") + "/"
        parser = ricardo
    elif name == "kleinanzeigen":
        slug = re.sub(r"[^a-z0-9äöüß]+", "-", p.query.lower()).strip("-")
        cap = math.ceil(
            min(settings.max_price_chf, p.max_price_chf or settings.max_price_chf)
            / settings.eur_to_chf
        )
        url = (
            p.kleinanzeigen_url
            or f"https://www.kleinanzeigen.de/s-preis::{cap}/{quote(slug)}/k0"
        )
        if (
            urlsplit(url).scheme != "https"
            or urlsplit(url).hostname != "www.kleinanzeigen.de"
        ):
            raise ValueError("Kleinanzeigen-URL ungueltig")
        parser = kleinanzeigen
    else:
        raise ValueError("Unbekannte Plattform")
    return parser(read(url)[0])[: settings.max_results_per_search]
