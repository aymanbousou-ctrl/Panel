import csv
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]
from flipradar.config import Settings
from flipradar.models import Product, Listing
from flipradar.handel import profile, inventory, choose
from flipradar.engine import Radar
from flipradar.db import Store
from flipradar.discovery import record, expanded
from flipradar.pricing import evaluate


class Handel(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.db = Store(str(self.folder / "demo.db"))
        self.addCleanup(self.db.close)
        self.p = Product(
            "Makita DDF484",
            "werkzeug",
            "Makita DDF484",
            ["DDF484"],
            [],
            min_price_chf=30,
        )
        self.s = Settings(
            db_path=str(self.folder / "demo.db"),
            platforms=["tutti"],
            min_samples=8,
            warmup_first_cycle=False,
            request_delay_seconds=0,
            discovery=False,
        )
        self.tg = Mock()
        self.tg.send.return_value = True
        self.r = Radar(self.s, self.db, self.tg)

    def row(self, title="Makita DDF484", price=100, i=0):
        return Listing(
            "tutti",
            str(i),
            title,
            "https://example.invalid",
            price,
            "CHF",
            price_chf=price,
        )

    def test_lot_boundary_and_capital(self):
        self.s.shipping_chf = 0
        self.s.min_margin = 0.10
        lot = self.row("5x Makita DDF484 Gesamtpreis", 350)
        comps = [100] * 8
        self.assertEqual(profile(lot, self.p), (5, "Standard", ""))
        d = evaluate(lot, self.p, comps, self.s, units=5, available=350)
        self.assertEqual(d.net_profit_chf, 64)
        self.assertAlmostEqual(d.discount, 0.30)
        self.assertEqual(d.max_offer, 350)
        self.assertIsNone(
            evaluate(lot, self.p, comps, self.s, units=5, available=349.99)
        )
        lot.price_chf = 350.01
        self.assertIsNone(evaluate(lot, self.p, comps, self.s, units=5))
        self.assertIsNone(evaluate(lot, self.p, [100] * 7, self.s, units=5))

    def test_ambiguous_lots_and_state(self):
        for text in [
            "5x Makita DDF484 je Stück",
            "Makita DDF484 Bundle",
            "5 Stück Makita DDF484 je 70 CHF Gesamtpreis",
            "Makita DDF484 inkl. 5 Stück Bits Gesamtpreis",
            "5 Stück Makita DDF484 gemischt Gesamtpreis",
            "Makita DDF484 B-Ware ungetestet",
        ]:
            self.assertIsNone(profile(self.row(text), self.p), text)
        self.assertEqual(
            profile(self.row("5 Stück Makita DDF484 Paketpreis B-Ware"), self.p)[:2],
            (5, "B-Ware"),
        )

    def test_csv_closed_cohort(self):
        now = date.today()
        path = self.folder / "Bestand.csv"
        with path.open("w") as f:
            f.write("ID;Produkt;Einkaufstag;Einstand_CHF;Verkaufstag;Nettoerloes_CHF\n")
            for i in range(11):
                bought = now - timedelta(days=31 if i < 10 else 1)
                sold = now - timedelta(days=2) if i < 6 else None
                f.write(f"{i};Test;{bought};70;{sold or ''};{100 if sold else ''}\n")
        data, invested = inventory(path)
        a = data["Test"]
        self.assertEqual((a.rate(), a.recent, invested), ("60% (6/10)", 6, 350))
        self.assertEqual(a.profits, [30] * 6)

    def test_rotation_covers_models_and_prioritizes_profit(self):
        products = [Product(str(i), "x", str(i), [], []) for i in range(138)]
        data, _ = inventory(self.folder / "absent.csv")
        data["137"].recent = 4
        data["137"].profits = [45]
        seen = set()
        cursor = 0
        for _ in range(10):
            batch, cursor = choose(products, data, cursor, 30)
            self.assertIn(products[-1], batch)
            self.assertEqual(len(set(p.name for p in batch)), 30)
            seen.update(p.name for p in batch)
        self.assertEqual(len(seen), 138)

    def test_e2e_lot_comparables_and_report(self):
        self.s.shipping_chf = 0
        self.s.min_margin = 0.10
        rows = [self.row(i=i) for i in range(8)]
        lot = self.row("5x Makita DDF484 Gesamtpreis", 350, 200)
        with patch(
            "flipradar.engine.search",
            return_value=rows + [lot, self.row("Makita DDF484 B-Ware", 32, 201)],
        ):
            self.r.cycle([self.p])
        self.tg.send.assert_called_once()
        self.assertIn("5 Stück", self.tg.send.call_args.args[0])
        self.assertIn("offen", self.tg.send.call_args.args[0])
        with (self.folder / "Trends.csv").open(encoding="utf-8-sig") as f:
            report = list(csv.reader(f, delimiter=";"))
        self.assertEqual(report[1][2:6], ["10", "0", "1", "0"])

    def test_model_discovery_requires_repeated_observations(self):
        rows = [self.row("Makita DDF999", 100, i) for i in range(4)]
        record(self.db, 0, rows[:3], [self.p])
        with self.db.conn:
            self.db.conn.execute(
                "UPDATE discoveries SET day=?",
                ((date.today() - timedelta(days=1)).isoformat(),),
            )
        record(self.db, 0, rows[:3], [self.p])
        self.assertEqual(len(expanded(self.db, [self.p], [])), 1)
        record(self.db, 0, rows, [self.p])
        self.assertEqual(expanded(self.db, [self.p], [])[1].name, "Makita DDF999")
        self.assertEqual(len(expanded(self.db, [self.p], ["Makita DDF999"])), 1)

    def test_bware_reserve_and_limits(self):
        unit = self.row("Makita DDF484 B-Ware", 40)
        d = evaluate(unit, self.p, [100] * 8, self.s, grade="B-Ware")
        self.assertEqual(d.reserve, 20)
        self.assertIsNone(
            evaluate(unit, self.p, [100] * 8, self.s, grade="B-Ware", available=59)
        )

    def test_purchase_split_and_partial_resale(self):
        from flipradar.bestand import add_purchase, sell, cents

        rows = []
        day = date.today().isoformat()
        add_purchase(rows, "Makita DDF484", day, 5, "350,03")
        self.assertEqual(sum(cents(r["Einstand_CHF"]) for r in rows), 35003)
        sell(rows[0], day, "90")
        with self.assertRaises(ValueError):
            sell(rows[0], day, "90")
        self.assertEqual(len([r for r in rows if not r["Verkaufstag"]]), 4)

    def test_all_standard_models_match_their_names(self):
        import os
        from flipradar.setup import init
        from flipradar.config import load_watchlist
        from flipradar.matcher import match_product

        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.folder)}):
            init(self.folder, self.folder)
        products = load_watchlist(self.folder / "watchlist.yaml")
        self.assertEqual(len(products), 138)
        for p in products:
            matched = match_product(self.row(p.name), products)
            self.assertEqual(matched.name if matched else None, p.name)

    def test_pending_rechecks_budget(self):
        self.s.min_margin = 0.10
        self.s.shipping_chf = 0
        lot = self.row("5x Makita DDF484 Gesamtpreis", 350, 101)
        singles = [self.row(i=i) for i in range(8)]
        self.tg.send.return_value = False
        with patch("flipradar.engine.search", return_value=singles + [lot]):
            self.r.cycle([self.p])
            self.s.portfolio_chf = 340
            self.r.cycle([self.p])
        self.tg.send.assert_called_once()
        self.assertEqual(
            self.db.conn.execute("SELECT COUNT(*) FROM pending").fetchone()[0], 0
        )

    def test_source_warms_after_recovery(self):
        from urllib.error import HTTPError

        self.s.warmup_first_cycle = True
        self.s.platforms = ["tutti", "ricardo"]
        radar = Radar(self.s, self.db, self.tg)
        self.p.ref_price_chf = 250

        def offline(name, *args):
            if name == "ricardo":
                raise HTTPError("test", 403, "Forbidden", {}, None)
            return []

        with patch("flipradar.engine.search", side_effect=offline):
            radar.cycle([self.p])
        with self.db.conn:
            self.db.conn.execute("DELETE FROM pauses")
        row = self.row(i=50)
        row.platform = "ricardo"
        with patch(
            "flipradar.engine.search",
            side_effect=lambda name, *args: [row] if name == "ricardo" else [],
        ):
            radar.cycle([self.p])
        self.tg.send.assert_not_called()

    def test_variant_separation(self):
        car = Product("Toyota Yaris", "auto", "Yaris", ["yaris"], [])
        a = self.row("Toyota Yaris 2013 120'000 km")
        b = self.row("Toyota Yaris 2021 20.000 km")
        self.assertNotEqual(profile(a, car)[2], profile(b, car)[2])
        self.assertIn("2x50tkm", profile(a, car)[2])
        self.assertIn("?km", profile(self.row("Toyota Yaris 2013"), car)[2])
        phone = Product("Pixel 9 Pro", "handy", "Pixel 9 Pro", ["pixel 9 pro"], [])
        self.assertNotEqual(
            profile(self.row("Pixel 9 Pro 256GB"), phone),
            profile(self.row("Pixel 9 Pro 512 GB"), phone),
        )
