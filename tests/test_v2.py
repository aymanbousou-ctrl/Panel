"""Offline integration and regression tests using only bundled libraries."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]
from flipradar.config import Settings, load_settings, load_watchlist
from flipradar.db import Store
from flipradar.engine import Radar, delay_on_error
from flipradar.models import Listing, Product
from flipradar.pricing import evaluate
from flipradar.sources import tutti, ricardo, kleinanzeigen, Ebay
from flipradar.setup import init
from flipradar.retail import retail_price
from flipradar.sales import load_sales
from datetime import date


class Checks(unittest.TestCase):
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

    def test_send_dedupe_and_discount(self):
        with patch(
            "flipradar.engine.search",
            side_effect=[[self.listing(v)] for v in (350, 350, 348, 320)],
        ):
            for i in range(4):
                self.r.cycle([self.p])
        self.assertEqual(self.t.send.call_count, 2)
        self.assertTrue(self.db.already_alerted("tutti:123", 320))

    def test_queue_survives_restart(self):
        self.t.send.side_effect = [False, True]
        with patch("flipradar.engine.search", return_value=[self.listing()]):
            self.r.cycle([self.p])
        with sqlite3.connect(self.path / "demo.db") as conn:
            self.assertEqual(
                conn.execute("select count(*) from pending").fetchone()[0], 1
            )
        reloaded = Store(str(self.path / "demo.db"))
        try:
            with patch("flipradar.engine.search", return_value=[]):
                Radar(self.s, reloaded, self.t).cycle([self.p])
            self.assertEqual(self.t.send.call_count, 1)
            with patch("flipradar.engine.search", return_value=[self.listing()]):
                Radar(self.s, reloaded, self.t).cycle([self.p])
            self.assertTrue(reloaded.already_alerted("tutti:123", 350))
        finally:
            reloaded.close()

    def test_budget_costs_sales_retail_cap(self):
        self.s.germany_extra_chf = 25
        item = self.listing()
        item.platform = "ebay"
        item.price_chf = 350
        d = evaluate(item, self.p, [], self.s, [700] * 8, 600)
        self.assertEqual(
            (d.net_profit_chf, d.value_source, d.margin),
            (155, "verkauft", round(155 / 375, 4)),
        )
        self.assertIsNone(evaluate(item, self.p, [], self.s, [700] * 8, 380))
        item.price_chf = 2010
        self.assertIsNone(evaluate(item, self.p, [], self.s, [5000] * 8))
        csv = self.path / "sales.csv"
        csv.write_text(
            "sale_id,product,sold_on,price_chf\nx,RTX 4070,"
            + date.today().isoformat()
            + ",550\n"
        )
        self.assertEqual(load_sales(csv, 30)["RTX 4070"], [550])
        content = """<script type="application/ld+json">{"@type":"Product","sku":"321","offers":{"price":599,"priceCurrency":"CHF","availability":"https://schema.org/InStock","itemCondition":"https://schema.org/NewCondition"}}</script>"""
        self.assertEqual(retail_price(content, "321"), 599)
        self.assertIsNone(retail_price(content, "123"))

    def test_first_cycle_and_silent_mode(self):
        self.s.warmup_first_cycle = True
        with patch("flipradar.engine.search", return_value=[self.listing()]):
            self.r.cycle([self.p])
            self.r.cycle([self.p])
        with patch("flipradar.engine.search", return_value=[self.listing(300)]):
            self.r.cycle([self.p], alerts_enabled=False)
        self.t.send.assert_not_called()

    def test_missing_market_value_becomes_available(self):
        self.p.ref_price_chf = None
        with patch("flipradar.engine.search", return_value=[self.listing()]):
            self.r.cycle([self.p])
            self.t.send.assert_not_called()
            self.p.ref_price_chf = 600
            self.r.cycle([self.p])
            self.t.send.assert_called_once()

    def test_403_isolated_and_persistent(self):
        self.s.platforms = ["tutti", "kleinanzeigen"]

        def result(name, *args):
            if name == "tutti":
                raise HTTPError("example", 403, "Forbidden", {}, None)
            return []

        radar = Radar(self.s, self.db, self.t)
        with patch("flipradar.engine.search", side_effect=result) as fetch:
            result1 = radar.cycle([self.p] * 4)
            result2 = Radar(self.s, self.db, self.t).cycle([self.p] * 2)
        self.assertEqual(result1["tutti"]["Fehler"], 1)
        self.assertEqual(result2["kleinanzeigen"]["Suchen"], 2)
        self.assertEqual(sum(x.args[0] == "tutti" for x in fetch.call_args_list), 1)
        with HTTPError("x", 429, "", {"Retry-After": "400"}, None) as limit:
            self.assertEqual(delay_on_error(limit), 400)

    def test_bootstrap_v1(self):
        old = self.path / "Documents/FlipRadar_v1.2/flipradar"
        new = self.path / "v2"
        old.mkdir(parents=True)
        new.mkdir()
        (old / "config.yaml").write_text(
            "telegram: {token: dummy, chat_id: '123'}\nmin_margin: 0.23\n"
        )
        orig = Store(str(old / "flipradar.db"))
        row = self.listing()
        row.price_chf = 350
        orig.upsert(row, self.p.name)
        orig.mark_alerted(row.key, 350)
        orig.close()
        init(new, self.path)
        init(new, self.path)
        cfg = load_settings(new / "config.yaml")
        self.assertEqual((cfg.telegram_token, cfg.min_margin), ("dummy", 0.23))
        self.assertIn("ebay", cfg.platforms)
        self.assertEqual(len(load_watchlist(new / "watchlist.yaml")), 138)
        copy = Store(str(new / "flipradar.db"))
        self.assertTrue(copy.already_alerted(row.key, 350))
        copy.close()

    def test_ricardo_excludes_bids(self):
        def card(i, parts):
            return f'<a href="/de/a/test-{i}/"><img alt="RTX 4070" src="/images/{i}"/>{parts}</a>'

        html = (
            '<div data-testid="regular-results">'
            + card(12, "1.00 (0 Gebote)")
            + card(13, "1.00 (1 Gebot) <span>399.00</span> Sofort kaufen")
            + "</div>"
        )
        self.assertEqual(
            [(x.listing_id, x.price) for x in ricardo(html.encode())], [("13", 399.0)]
        )
        with self.assertRaises(ValueError):
            ricardo(b"<html>unavailable</html>")

    def test_tutti_page(self):
        row = {
            "listingID": "42",
            "localization": {"title": "RTX 4070"},
            "formattedPrice": "1'200.-",
        }
        data = {
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": {"listings": {"edges": [{"node": row}]}}
                                }
                            }
                        ]
                    }
                }
            }
        }
        items = tutti(
            (
                '<script id="__NEXT_DATA__" type="application/json">'
                + json.dumps(data)
                + "</script>"
            ).encode()
        )
        self.assertEqual((items[0].price, items[0].listing_id), (1200, "42"))
        with self.assertRaises(ValueError):
            tutti(b"<html>Forbidden</html>")

    def test_kleinanzeigen_page(self):
        a = '<article data-adid="123"><h3><a href="/s-anzeige/x/123-1-2">RTX 4070</a></h3><p class="text-secondary">350 € VB</p></article>'
        x = kleinanzeigen(a.encode())[0]
        self.assertEqual((x.price, x.currency, x.negotiable), (350, "EUR", True))

    def test_ebay_api_contract(self):
        item = {
            "itemId": "v1|123|0",
            "price": {"currency": "EUR", "value": "310.00"},
            "buyingOptions": ["FIXED_PRICE"],
            "itemLocation": {"country": "DE"},
            "itemWebUrl": "https://www.ebay.de/itm/123",
            "title": "RTX 4070",
        }
        api = Ebay(self.s)
        with patch(
            "flipradar.sources.read_json",
            side_effect=[
                {"access_token": "test", "expires_in": 3600},
                {"itemSummaries": [item, dict(item, buyingOptions=["AUCTION"])]},
                {"total": 0},
            ],
        ) as req:
            self.assertEqual([r.price for r in api.search(self.p)], [310])
            self.assertEqual(api.search(self.p), [])
            self.assertEqual(req.call_count, 3)
            self.assertEqual(
                req.call_args.kwargs["headers"]["X-EBAY-C-MARKETPLACE-ID"], "EBAY_DE"
            )


if __name__ == "__main__":
    unittest.main()
