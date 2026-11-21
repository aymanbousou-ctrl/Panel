"""Publicly displayed listings and the official eBay Browse API."""

import base64
from http.client import HTTPException
import json
import math
import re
import time
from urllib.error import HTTPError
from urllib.parse import quote, quote_plus, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup
from .models import Listing
from .apify import run_actor
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
                        description=str(item["localization"].get("description") or ""),
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


def marktplaats(data):
    """Liest die Suchergebnisse aus __NEXT_DATA__.

    'FIXED' ist ein Festpreis. 'MIN_BID' (Bieden vanaf) ist ein Mindestgebot und wird
    als verhandelbar markiert. 'FAST_BID' hat keinen Preis und bleibt draussen.
    """
    script = page(data).find("script", id="__NEXT_DATA__")
    if not script:
        raise ValueError("Marktplaats-Suchergebnisse fehlen im HTML")
    rows = json.loads(script.get_text())["props"]["pageProps"][
        "searchRequestAndResponse"
    ]["listings"]
    if not isinstance(rows, list):
        raise ValueError("Marktplaats-Seitenformat unbekannt")
    result = {}
    for row in rows:
        info = row.get("priceInfo")
        sku, title, path = row.get("itemId"), row.get("title"), row.get("vipUrl")
        if not (sku and title and isinstance(info, dict) and "priceType" in info):
            raise ValueError("Marktplaats-Inseratformat unbekannt")
        cents = info.get("priceCents")
        if (
            info["priceType"] not in ("FIXED", "MIN_BID")
            or row.get("reserved")
            or not isinstance(cents, int)
            or cents <= 0
            or not str(path).startswith("/v/")
        ):
            continue
        place = row.get("location") or {}
        result[str(sku)] = Listing(
            "marktplaats",
            str(sku),
            title,
            urljoin("https://www.marktplaats.nl", path),
            cents / 100,
            "EUR",
            location=place.get("cityName") or "",
            description=row.get("description") or "",
            negotiable=info["priceType"] == "MIN_BID",
        )
    return list(result.values())


def vinted(data):
    """Liest die Inserate aus den Trefferkarten der Katalogseite (vinted.de).

    Als Preis zaehlt, was die Kaeuferin zahlt: Artikelpreis inklusive Kaeuferschutz,
    ohne Versand. Zustand und Marke stehen in der Beschreibung.
    """
    soup = page(data)
    result = {}
    for card in soup.select('[data-testid="grid-item"]'):
        box = card.select_one('[data-testid^="product-item-id-"]')
        link = card.select_one('a[data-testid$="--overlay-link"]')
        if not box or not link:
            raise ValueError("Vinted-Inseratformat unbekannt")
        sku = box["data-testid"].split("product-item-id-", 1)[1]
        path = urlsplit(link.get("href", "")).path
        label = link.get("title", "")
        base = card.select_one('[data-testid$="price-text"]')
        total = card.select_one('[data-testid$="breakdown"]')
        # Titel steht vor ", Marke: ..." bzw. ", Zustand: ..." im Link-Titel.
        title = re.split(r", (?:Marke|Zustand): ", label, maxsplit=1)[0].strip()
        price = parse_price(
            (total or base).get_text(" ", strip=True) if (total or base) else None,
            "EUR",
        )[0]
        if not (sku.isdecimal() and path.startswith("/items/") and title):
            raise ValueError("Vinted-Inseratformat unbekannt")
        brand = card.select_one('[data-testid$="description-title"]')
        state = card.select_one('[data-testid$="description-subtitle"]')
        details = [
            part
            for part in (
                "Marke: " + brand.get_text(" ", strip=True) if brand else "",
                "Zustand: " + state.get_text(" ", strip=True) if state else "",
            )
            if part
        ]
        if price:
            result[sku] = Listing(
                "vinted",
                sku,
                title,
                urljoin("https://www.vinted.de", path),
                price,
                "EUR",
                description=", ".join(details),
            )
    if not result and not soup.select('[class*="feed-grid"]'):
        raise ValueError("Vinted-Ergebnisbereich fehlt")
    return list(result.values())


SUBITO_ACTOR = "epicscrapers/subito-scraper"


def subito_listings(rows):
    """Wandelt die Ergebnisse des Apify-Scrapers in Inserate um."""
    if not isinstance(rows, list):
        raise ValueError("Subito-Antwort ist keine Liste")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not {"page_url", "title"} <= row.keys():
            raise ValueError("Subito-Inseratformat unbekannt")
        parts = urlsplit(str(row["page_url"]))
        sku = re.search(r"-(\d+)\.htm$", parts.path)
        price = row.get("price")
        price = price.get("value") if isinstance(price, dict) else None
        if (
            parts.scheme != "https"
            or parts.hostname != "www.subito.it"
            or not sku
            or not row["title"]
            or row.get("type", "In vendita") != "In vendita"
            or isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not math.isfinite(price)
            or price <= 0
        ):
            continue
        place = row.get("geo") or {}
        city = place.get("city") or ""
        code = place.get("province_code")
        result[sku[1]] = Listing(
            "subito",
            sku[1],
            row["title"],
            f"https://www.subito.it{parts.path}",
            float(price),
            "EUR",
            location=f"{city} ({code})" if city and code else city,
            description=row.get("description") or "",
        )
    return list(result.values())


def _cap_eur(p, settings):
    """Hoechstpreis in EUR aus dem CHF-Budget (spart Treffer und damit Kosten)."""
    return math.ceil(
        min(settings.max_price_chf, p.max_price_chf or settings.max_price_chf)
        / settings.eur_to_chf
    )


def subito(p, settings):
    return subito_listings(
        run_actor(
            SUBITO_ACTOR,
            {
                "enrichPhone": False,
                "enrichShop": False,
                "enrichUserAccount": False,
                "maxItemsPerQuery": settings.apify_max_results,
                "proxyConfiguration": {"useApifyProxy": True},
                "shippableOnly": False,
                "searchKeywords": [p.query_for("subito")],
                "sortOrder": "datedesc",
                "maxPrice": _cap_eur(p, settings),
            },
            settings.apify_token,
        )
    )


WALLAPOP_ACTOR = "blackfalcondata/wallapop-scraper"
LEBONCOIN_ACTOR = "clearpath/leboncoin-api"


def _number(value):
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    return float(value) if ok and math.isfinite(value) and value > 0 else None


def wallapop_listings(rows):
    """Wandelt die Ergebnisse des Wallapop-Scrapers in Inserate um."""
    if not isinstance(rows, list):
        raise ValueError("Wallapop-Antwort ist keine Liste")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not {"title", "url"} <= row.keys():
            raise ValueError("Wallapop-Inseratformat unbekannt")
        parts = urlsplit(str(row["url"]))
        sku = row.get("itemId") or row.get("listingId")
        price = _number(row.get("price"))
        if (
            parts.scheme != "https"
            or parts.hostname != "es.wallapop.com"
            or not parts.path.startswith("/item/")
            or not sku
            or not row["title"]
            or price is None
            or row.get("currency") != "EUR"
            or row.get("reserved")
        ):
            continue
        result[str(sku)] = Listing(
            "wallapop",
            str(sku),
            row["title"],
            f"https://es.wallapop.com{parts.path}",
            price,
            "EUR",
            location=row.get("city") or "",
            description=row.get("description") or "",
        )
    return list(result.values())


def wallapop(p, settings):
    return wallapop_listings(
        run_actor(
            WALLAPOP_ACTOR,
            {
                "query": [p.query_for("wallapop")],
                "country": "ES",
                "sortBy": "newest",
                "maxPrice": _cap_eur(p, settings),
                "maxResults": settings.apify_max_results,
                "includeDetails": False,
                "includeSellerProfile": False,
            },
            settings.apify_token,
        )
    )


def leboncoin_listings(rows):
    """Wandelt die Ergebnisse des Leboncoin-Scrapers in Inserate um."""
    if not isinstance(rows, list):
        raise ValueError("Leboncoin-Antwort ist keine Liste")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not {"list_id", "subject", "url"} <= row.keys():
            raise ValueError("Leboncoin-Inseratformat unbekannt")
        parts = urlsplit(str(row["url"]))
        price = _number(row.get("price_euros"))
        if price is None and _number(row.get("price_cents")):
            price = row["price_cents"] / 100
        place = row.get("location")
        place = place if isinstance(place, dict) else {}
        if (
            parts.scheme != "https"
            or parts.hostname != "www.leboncoin.fr"
            or not parts.path.startswith("/ad/")
            or not row["subject"]
            or price is None
            or row.get("ad_type", "offer") != "offer"
            or row.get("status", "active") != "active"
        ):
            continue
        sku = str(row["list_id"])
        result[sku] = Listing(
            "leboncoin",
            sku,
            row["subject"],
            f"https://www.leboncoin.fr{parts.path}",
            price,
            "EUR",
            location=place.get("city_label") or place.get("city") or "",
            description=row.get("body") or "",
        )
    return list(result.values())


def leboncoin(p, settings):
    rows = run_actor(
        LEBONCOIN_ACTOR,
        {
            "searchQuery": p.query_for("leboncoin"),
            # Der Scraper verlangt mindestens 10; ueberzaehlige Treffer verwerfen wir.
            "adLimit": max(10, settings.apify_max_results),
            "price_max_filter": _cap_eur(p, settings),
            "sortBy": "time",
            "includeSeller": False,
            "includePhone": False,
        },
        settings.apify_token,
    )
    return leboncoin_listings(rows)[: settings.apify_max_results]


APIFY_SOURCES = {"subito": subito, "wallapop": wallapop, "leboncoin": leboncoin}


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

    def check(self):
        """Test fuer Einstellungen und Diagnose. Ergebnis: (ok, Meldung auf Deutsch)."""
        if not (self.settings.ebay_client_id and self.settings.ebay_client_secret):
            return False, "App-ID oder Cert-ID fehlt."
        try:
            self.authorize()
            read_json(
                "https://api.ebay.com/buy/browse/v1/item_summary/search?"
                + urlencode({"q": "test", "limit": 1}),
                headers={
                    "Authorization": "Bearer " + self.token,
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY_DE",
                },
            )
        except HTTPError as exc:
            try:
                body = json.dumps(json.loads(exc.read(16384))).lower()
            except (ValueError, OSError, AttributeError):
                body = ""
            exc.close()
            if exc.code in (400, 401) and "invalid_client" in body:
                return False, (
                    "eBay lehnt die Schlüssel ab. Es müssen Produktions-Schlüssel sein "
                    "(App-ID und Cert-ID), keine Sandbox-Schlüssel."
                )
            if exc.code == 403:
                return False, (
                    "Die Schlüssel sind gültig, aber für die Browse API fehlt die "
                    "Produktionsfreigabe."
                )
            if exc.code == 429:
                return False, "Das eBay-Tageskontingent dieser Schlüssel ist ausgeschöpft."
            return False, f"eBay meldet einen Fehler (HTTP {exc.code})."
        except (OSError, ValueError, KeyError, HTTPException):
            return False, "Keine Verbindung zu eBay oder unerwartete Antwort."
        return True, "eBay-Zugang funktioniert."

    def search(self, product):
        if time.monotonic() >= self.expires:
            self.authorize()
        params = urlencode(
            {
                "q": product.query_for("ebay"),
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
            condition_id = str(item.get("conditionId", ""))
            if condition_id == "7000":
                continue
            condition = (
                "refurbished"
                if condition_id in {"2000", "2010", "2020", "2030", "2500"}
                else ""
            )
            value = float(price["value"])
            if math.isfinite(value) and value > 0:
                rows.append(
                    Listing(
                        "ebay",
                        item["itemId"],
                        item["title"],
                        url,
                        value,
                        "EUR",
                        description=condition,
                    )
                )
        return rows


def search(name, p, settings, ebay):
    if name == "ebay":
        return ebay.search(p)
    if name in APIFY_SOURCES:
        return APIFY_SOURCES[name](p, settings)[: settings.max_results_per_search]
    if name == "tutti":
        url = "https://www.tutti.ch/de/q?" + urlencode({"query": p.query_for("tutti")})
        parser = tutti
    elif name == "ricardo":
        url = "https://www.ricardo.ch/de/s/" + quote(p.query_for("ricardo"), safe="") + "/"
        parser = ricardo
    elif name == "kleinanzeigen":
        slug = re.sub(r"[^a-z0-9äöüß]+", "-", p.query_for("kleinanzeigen").lower()).strip("-")
        cap = math.ceil(
            max(
                settings.lot_budget_chf,
                min(settings.max_price_chf, p.max_price_chf or settings.max_price_chf),
            )
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
    elif name == "vinted":
        url = "https://www.vinted.de/catalog?" + urlencode({"search_text": p.query_for("vinted")})
        parser = vinted
    elif name == "marktplaats":
        url = "https://www.marktplaats.nl/q/" + quote_plus(p.query_for("marktplaats")) + "/"
        parser = marktplaats
    else:
        raise ValueError("Unbekannte Plattform")
    return parser(read(url)[0])[: settings.max_results_per_search]
