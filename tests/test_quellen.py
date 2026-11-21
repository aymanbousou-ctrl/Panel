"""Tests fuer die zusaetzlichen Quellen (Marktplaats, Vinted, Apify-Quellen) und den Modus nur sammeln."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]
from flipradar.apify import run_actor
from flipradar.config import Settings, load_settings, load_watchlist
from flipradar.db import Store
from flipradar.engine import Radar
from flipradar.models import Listing, Product
from flipradar.pricing import evaluate
from flipradar.sources import (
    leboncoin_listings,
    marktplaats,
    subito_listings,
    vinted,
    wallapop_listings,
)


class Quellen(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        self.db = Store(str(self.path / "demo.db"))
        self.addCleanup(self.db.close)
        self.s = Settings(
            platforms=["tutti"],
            discovery=False,
            request_delay_seconds=0,
            warmup_first_cycle=False,
        )
        self.s.db_path = str(self.path / "demo.db")
        self.p = Product("RTX 4070", "gpu", "rtx 4070", ["4070"], [], ref_price_chf=600)
        self.t = Mock()
        self.t.send.return_value = True
        self.r = Radar(self.s, self.db, self.t)

    def listing(self, price=350):
        return Listing(
            "tutti", "123", "RTX 4070", "https://www.tutti.ch/de/vi/123", price, "CHF"
        )

    def test_collect_only_stores_but_never_alerts(self):
        self.s.collect_only = ["tutti"]
        radar = Radar(self.s, self.db, self.t)
        with patch("flipradar.engine.search", return_value=[self.listing(300)]):
            radar.cycle([self.p])
            radar.cycle([self.p])
        self.t.send.assert_not_called()
        self.assertEqual(self.db.stats()[0][1], 1)
        self.assertFalse(self.db.eligible("tutti:123"))
        # Nach dem Ausschalten loest erst eine neue Sichtung mit tieferem Preis aus.
        self.s.collect_only = []
        radar = Radar(self.s, self.db, self.t)
        with patch("flipradar.engine.search", return_value=[self.listing(300)]):
            radar.cycle([self.p])
        self.t.send.assert_not_called()
        with patch("flipradar.engine.search", return_value=[self.listing(250)]):
            radar.cycle([self.p])
        self.t.send.assert_called_once()

    def test_collect_only_config_validation(self):
        cfg = self.path / "config.yaml"
        cfg.write_text("platforms: [tutti]\ncollect_only: [Tutti]\n")
        self.assertEqual(load_settings(cfg).collect_only, ["tutti"])
        cfg.write_text("platforms: [tutti]\ncollect_only: [ricardo]\n")
        with self.assertRaises(ValueError):
            load_settings(cfg)
        cfg.write_text("platforms: [tutti, nirgendwo]\n")
        with self.assertRaises(ValueError):
            load_settings(cfg)

    def test_extra_costs_only_for_german_platforms(self):
        self.s.germany_extra_chf = 25
        for platform, extra in (("kleinanzeigen", 25), ("ebay", 25), ("tutti", 0)):
            item = self.listing()
            item.platform, item.price_chf = platform, 350
            deal = evaluate(item, self.p, [], self.s)
            self.assertEqual(deal.germany_extra_chf, extra)

    def test_marktplaats_page(self):
        def row(sku, kind, cents, **extra):
            return {
                "itemId": sku,
                "title": "RTX 4070 " + sku,
                "description": "Videokaart",
                "priceInfo": {"priceCents": cents, "priceType": kind},
                "location": {"cityName": "Utrecht"},
                "vipUrl": "/v/computers-en-software/videokaarten/" + sku + "-x",
                **extra,
            }

        rows = [
            row("m1", "FIXED", 77995),
            row("m2", "MIN_BID", 60000),
            row("m3", "FAST_BID", 0),
            row("m4", "FIXED", 50000, reserved=True),
            row("m5", "FIXED", 50000, vipUrl="https://boese.example/v/x"),
            row("m1", "FIXED", 77995),
        ]

        def html(listings):
            data = {"props": {"pageProps": {"searchRequestAndResponse": {"listings": listings}}}}
            return (
                '<script id="__NEXT_DATA__" type="application/json">'
                + json.dumps(data)
                + "</script>"
            ).encode()

        items = marktplaats(html(rows))
        self.assertEqual([(i.listing_id, i.negotiable) for i in items], [("m1", False), ("m2", True)])
        x = items[0]
        self.assertEqual((x.listing_id, x.price, x.currency, x.location), ("m1", 779.95, "EUR", "Utrecht"))
        self.assertEqual(x.url.split("/v/")[0], "https://www.marktplaats.nl")
        self.assertEqual(marktplaats(html([])), [])
        with self.assertRaises(ValueError):
            marktplaats(b"<html>Forbidden</html>")
        with self.assertRaises(ValueError):
            marktplaats(html([{"itemId": "m9", "title": "x"}]))
        with self.assertRaises(KeyError):
            marktplaats(b'<script id="__NEXT_DATA__">{"props":{"pageProps":{}}}</script>')

    def test_marktplaats_is_forced_collect_only_and_filters_dutch_wants(self):
        cfg = self.path / "config.yaml"
        cfg.write_text("platforms: [tutti, marktplaats]\n")
        self.assertEqual(load_settings(cfg).collect_only, ["marktplaats"])
        self.s.platforms = ["marktplaats"]
        self.s.collect_only = ["marktplaats"]
        wanted = Listing("marktplaats", "m7", "GEZOCHT: RTX 4070", "https://www.marktplaats.nl/v/x", 100, "EUR")
        offer = Listing("marktplaats", "m8", "RTX 4070 videokaart", "https://www.marktplaats.nl/v/y", 400, "EUR")
        with patch("flipradar.engine.search", return_value=[wanted, offer]):
            Radar(self.s, self.db, self.t).cycle([self.p])
        rows = dict(self.db.conn.execute("select listing_id, product from listings"))
        self.assertEqual(rows, {"m7": None, "m8": "RTX 4070"})
        self.t.send.assert_not_called()

    def test_vinted_page(self):
        def card(sku, label, price, total):
            return (
                '<div data-testid="grid-item"><div data-testid="product-item-id-%s">'
                '<a data-testid="product-item-id-%s--overlay-link" href="/items/%s-x?referrer=catalog" title="%s"></a>'
                '<div data-testid="product-item-id-%s--description-title">NVIDIA</div>'
                '<div data-testid="product-item-id-%s--description-subtitle">Gut</div>'
                '<div data-testid="product-item-id-%s--price-text">%s</div>'
                '<div data-testid="product-item-id-%s--breakdown">%s inkl.</div></div></div>'
                % (sku, sku, sku, label, sku, sku, sku, price, sku, total)
            )

        html = (
            '<div class="x-feed-grid">'
            + card("11", "RTX 4070, Marke: NVIDIA, Zustand: Gut, 599,99 \u20ac", "599,99 \u20ac", "1.630,69 \u20ac")
            + card("11", "RTX 4070, Marke: NVIDIA", "599,99 \u20ac", "1.630,69 \u20ac")
            + "</div>"
        )
        items = vinted(html.encode())
        self.assertEqual(len(items), 1)
        x = items[0]
        self.assertEqual((x.listing_id, x.title, x.price, x.currency), ("11", "RTX 4070", 1630.69, "EUR"))
        self.assertEqual(x.url, "https://www.vinted.de/items/11-x")
        self.assertEqual(x.description, "Marke: NVIDIA, Zustand: Gut")
        self.assertEqual(vinted(b'<div class="a-feed-grid"></div>'), [])
        with self.assertRaises(ValueError):
            vinted(b"<html>Forbidden</html>")
        with self.assertRaises(ValueError):
            vinted(b'<div data-testid="grid-item"><p>neu</p></div>')

    def test_subito_rows_and_apify_call(self):
        def row(**extra):
            return {
                "type": "In vendita",
                "title": "iPhone 15 Pro",
                "description": "Come nuovo",
                "page_url": "https://www.subito.it/telefonia/iphone-15-pro-salerno-669178404.htm",
                "price": {"value": 500, "formatted": "500 \u20ac"},
                "geo": {"city": "Salerno", "province_code": "SA"},
                **extra,
            }

        rows = [
            row(),
            row(),
            row(type="Cercasi", page_url="https://www.subito.it/x/a-1.htm"),
            row(price=None, page_url="https://www.subito.it/x/b-2.htm"),
            row(page_url="https://boese.example/x/c-3.htm"),
            row(page_url="https://www.subito.it/x/ohne-nummer"),
        ]
        items = subito_listings(rows)
        self.assertEqual(len(items), 1)
        x = items[0]
        self.assertEqual((x.listing_id, x.price, x.currency, x.location), ("669178404", 500.0, "EUR", "Salerno (SA)"))
        self.assertEqual(x.url, "https://www.subito.it/telefonia/iphone-15-pro-salerno-669178404.htm")
        self.assertEqual(subito_listings([]), [])
        with self.assertRaises(ValueError):
            subito_listings({"error": "x"})
        with self.assertRaises(ValueError):
            subito_listings([{"foo": 1}])
        with patch("flipradar.apify.read_json", return_value=[]) as call:
            run_actor("epicscrapers/subito-scraper", {"a": 1}, "geheim")
        url = call.call_args.args[0]
        self.assertIn("/acts/epicscrapers~subito-scraper/run-sync-get-dataset-items", url)
        self.assertNotIn("geheim", url)
        self.assertEqual(call.call_args.kwargs["headers"]["Authorization"], "Bearer geheim")
        with patch("flipradar.apify.read_json", return_value={"error": 1}):
            with self.assertRaises(ValueError):
                run_actor("a/b", {}, "t")
        with self.assertRaises(ValueError):
            run_actor("../../x", {}, "t")

    def test_paid_source_runs_only_for_chosen_products_with_interval(self):
        self.s.platforms = ["subito"]
        self.s.apify_token = "t"
        self.s.apify_products = ["RTX 4070"]
        other = Product("PS5", "konsole", "ps5", ["ps5"], [])
        radar = Radar(self.s, self.db, self.t)
        with patch("flipradar.engine.search", return_value=[]) as fetch:
            radar.cycle([self.p, other])
            radar.cycle([self.p, other])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[1].name, "RTX 4070")
        self.s.apify_interval_minutes = 10
        with self.db.conn:
            self.db.conn.execute("update paid_runs set last = last - 700")
        with patch("flipradar.engine.search", return_value=[]) as fetch:
            radar.cycle([self.p, other])
        self.assertEqual(fetch.call_count, 1)

    def test_paid_failure_is_not_retried_within_interval(self):
        self.s.platforms = ["subito"]
        self.s.apify_token = "t"
        self.s.apify_products = ["RTX 4070"]
        radar = Radar(self.s, self.db, self.t)
        with patch("flipradar.engine.search", side_effect=ValueError("kaputt")) as fetch:
            radar.cycle([self.p])
            radar.cycle([self.p])
        self.assertEqual(fetch.call_count, 1)

    def test_paid_source_needs_token_and_config(self):
        self.s.platforms = ["subito"]
        self.assertEqual(Radar(self.s, self.db, self.t).platforms, [])
        cfg = self.path / "config.yaml"
        cfg.write_text(
            "platforms: [subito]\napify: {token: abc, products: [PS5], interval_minutes: 60, max_results: 5}\n"
        )
        s = load_settings(cfg)
        self.assertEqual(
            (s.apify_token, s.apify_products, s.apify_interval_minutes, s.apify_max_results, s.collect_only),
            ("abc", ["PS5"], 60, 5, ["subito"]),
        )
        cfg.write_text("platforms: [subito]\napify: {interval_minutes: 1}\n")
        with self.assertRaises(ValueError):
            load_settings(cfg)

    def test_subito_input_and_platform_queries(self):
        p = Product("PS5", "konsole", "ps5 konsole", ["ps5"], [], queries={"subito": "ps5"})
        self.assertEqual((p.query_for("subito"), p.query_for("tutti")), ("ps5", "ps5 konsole"))
        self.s.apify_token, self.s.max_price_chf, self.s.eur_to_chf = "t", 2000, 0.94
        with patch("flipradar.sources.run_actor", return_value=[]) as call:
            from flipradar.sources import subito

            subito(p, self.s)
        payload = call.call_args.args[1]
        self.assertEqual(payload["searchKeywords"], ["ps5"])
        self.assertEqual((payload["sortOrder"], payload["maxPrice"]), ("datedesc", 2128))
        self.assertEqual(payload["maxItemsPerQuery"], self.s.apify_max_results)
        wl = self.path / "w.yaml"
        wl.write_text("products:\n  - name: PS5\n    query: ps5 konsole\n    queries: {Subito: ps5}\n")
        self.assertEqual(load_watchlist(wl)[0].queries, {"subito": "ps5"})
        self.assertEqual(
            [x for x in load_watchlist(ROOT / "watchlist.yaml") if x.name == "PS5"][0].query_for("marktplaats"),
            "ps5",
        )

    def test_wallapop_and_leboncoin_rows(self):
        wp = {
            "listingId": "d4b5",
            "itemId": "nzxe1prppp62",
            "title": "Sony PlayStation 5 (PS5) Fortnite 1TB",
            "price": 350,
            "currency": "EUR",
            "url": "https://es.wallapop.com/item/sony-playstation-5-ps5-fortnite-1tb-1326545630",
            "city": "Madrid",
            "reserved": False,
        }
        rows = [
            wp,
            dict(wp),
            dict(wp, itemId="x2", reserved=True),
            dict(wp, itemId="x3", price=None),
            dict(wp, itemId="x4", currency="GBP"),
            dict(wp, itemId="x5", url="https://boese.example/item/a"),
        ]
        items = wallapop_listings(rows)
        self.assertEqual(len(items), 1)
        x = items[0]
        self.assertEqual((x.listing_id, x.price, x.currency, x.location), ("nzxe1prppp62", 350.0, "EUR", "Madrid"))
        self.assertEqual(wallapop_listings([]), [])
        with self.assertRaises(ValueError):
            wallapop_listings([{"foo": 1}])
        with self.assertRaises(ValueError):
            wallapop_listings({"x": 1})

        lb = {
            "list_id": 3313947781,
            "subject": "Ps5,ps4.les indestructibles",
            "body": "Jeux",
            "status": "active",
            "ad_type": "offer",
            "price": [5],
            "price_cents": 500,
            "price_euros": 5,
            "url": "https://www.leboncoin.fr/ad/jeux_video/3313947781",
            "location": {"city": "Lyon", "city_label": "Lyon 69003"},
        }
        rows = [
            lb,
            dict(lb, list_id=2, ad_type="demand"),
            dict(lb, list_id=3, status="expired"),
            dict(lb, list_id=4, price_euros=None, price_cents=1250),
            dict(lb, list_id=5, price_euros=None, price_cents=None),
            dict(lb, list_id=6, url="https://boese.example/ad/x/6"),
        ]
        items = leboncoin_listings(rows)
        self.assertEqual([(i.listing_id, i.price) for i in items], [("3313947781", 5.0), ("4", 12.5)])
        self.assertEqual(items[0].location, "Lyon 69003")
        self.assertEqual(items[0].url, "https://www.leboncoin.fr/ad/jeux_video/3313947781")
        with self.assertRaises(ValueError):
            leboncoin_listings([{"subject": "x"}])

    def test_wallapop_and_leboncoin_actor_input(self):
        from flipradar.sources import search

        p = Product("PS5", "konsole", "ps5 konsole", ["ps5"], [], queries={"wallapop": "ps5", "leboncoin": "ps5"})
        self.s.apify_token, self.s.apify_max_results = "t", 5
        self.s.max_price_chf, self.s.eur_to_chf = 2000, 0.94
        with patch("flipradar.sources.run_actor", return_value=[]) as call:
            search("wallapop", p, self.s, None)
            search("leboncoin", p, self.s, None)
        wp, lb = call.call_args_list
        self.assertEqual(wp.args[0], "blackfalcondata/wallapop-scraper")
        self.assertEqual(wp.args[1]["query"], ["ps5"])
        self.assertEqual((wp.args[1]["sortBy"], wp.args[1]["maxPrice"], wp.args[1]["maxResults"]), ("newest", 2128, 5))
        self.assertEqual(lb.args[0], "clearpath/leboncoin-api")
        self.assertEqual(lb.args[1]["searchQuery"], "ps5")
        self.assertEqual((lb.args[1]["sortBy"], lb.args[1]["adLimit"]), ("time", 10))
        self.assertFalse(lb.args[1]["includeSeller"] or lb.args[1]["includePhone"])
        cfg = self.path / "config.yaml"
        cfg.write_text("platforms: [wallapop, leboncoin, subito]\n")
        self.assertEqual(load_settings(cfg).collect_only, ["leboncoin", "subito", "wallapop"])


if __name__ == "__main__":
    unittest.main()
