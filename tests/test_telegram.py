"""Tests fuer Telegram-Fehlerbehandlung und Quellenstatus."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]
from flipradar.config import Settings
from flipradar.db import Store
from flipradar.engine import Radar
from flipradar.models import Listing, Product
from flipradar.notify import Telegram

TOKEN = "123456789:" + "A" * 35


def error(code, description="", retry=None):
    body = {"ok": False, "error_code": code, "description": description}
    if retry:
        body["parameters"] = {"retry_after": retry}
    return HTTPError("https://api.telegram.org/botX/sendMessage", code, "x", {}, io.BytesIO(json.dumps(body).encode()))


class TelegramChecks(unittest.TestCase):
    def tg(self, token=TOKEN, chat="42"):
        return Telegram(token, chat)

    def test_reasons_are_clear_and_never_contain_the_token(self):
        cases = [
            (error(401, "Unauthorized"), "Token ungültig"),
            (error(404, "Not Found"), "Token unbekannt"),
            (error(400, "Bad Request: chat not found"), "Chat-ID unbekannt"),
            (error(403, "Forbidden: bot was blocked by the user"), "nicht schreiben"),
            (error(500, "oops"), "Telegram-Server"),
        ]
        for exc, expected in cases:
            t = self.tg()
            with patch("flipradar.notify.read_json", side_effect=exc):
                self.assertFalse(t.send("Test"))
            self.assertIn(expected, t.last_error)
            self.assertNotIn(TOKEN, t.last_error)
        t = self.tg()
        with patch("flipradar.notify.read_json", side_effect=URLError("getaddrinfo failed")):
            self.assertFalse(t.send("Test"))
        self.assertIn("Keine Verbindung", t.last_error)
        self.assertNotIn("getaddrinfo", t.last_error)

    def test_rate_limit_waits_then_continues(self):
        t = self.tg()
        with patch("flipradar.notify.read_json", side_effect=error(429, "Too Many Requests", 7)) as call:
            self.assertFalse(t.send("a"))
            self.assertFalse(t.send("b"))
        self.assertEqual(call.call_count, 1)
        self.assertIn("7 s", t.last_error)
        t.resume_at = 0
        with patch("flipradar.notify.read_json", return_value={"ok": True}):
            self.assertTrue(t.send("c"))
        self.assertEqual(t.last_error, "")

    def test_parse_error_falls_back_to_plain_text(self):
        t = self.tg()
        with patch(
            "flipradar.notify.read_json",
            side_effect=[error(400, "Bad Request: can't parse entities: Unsupported start tag"), {"ok": True}],
        ) as call:
            self.assertTrue(t.send("<b>RTX 4070 &amp; Co</b> <3"))
        second = json.loads(call.call_args_list[1].kwargs["data"])
        self.assertNotIn("parse_mode", second)
        self.assertEqual(second["text"], "RTX 4070 & Co <3")

    def test_pasted_whitespace_is_removed_and_bad_urls_do_not_crash(self):
        t = Telegram(" " + TOKEN + "\r\n", " 42\n")
        self.assertEqual((t.token, t.chat_id), (TOKEN, "42"))
        from http.client import InvalidURL

        with patch("flipradar.notify.read_json", side_effect=InvalidURL("x")):
            self.assertFalse(t.send("a"))

    def test_check_distinguishes_every_cause(self):
        self.assertIn("kein Bot-Token", self.tg(token="").check()[1])
        self.assertIn("Format", self.tg(token="abc def").check()[1])
        self.assertIn("keine Chat-ID", self.tg(chat="").check()[1])
        with patch("flipradar.notify.read_json", side_effect=error(401, "Unauthorized")):
            ok, message = self.tg().check()
        self.assertFalse(ok)
        self.assertIn("Token ungültig", message)
        with patch(
            "flipradar.notify.read_json",
            side_effect=[{"ok": True, "result": {"username": "mein_bot"}}, error(400, "Bad Request: chat not found")],
        ):
            ok, message = self.tg().check()
        self.assertFalse(ok)
        self.assertIn("@mein_bot ist gültig, aber: Chat-ID unbekannt", message)
        with patch(
            "flipradar.notify.read_json",
            side_effect=[{"ok": True, "result": {"username": "mein_bot"}}, {"ok": True}],
        ):
            self.assertEqual(self.tg().check(), (True, "Telegram funktioniert (Bot @mein_bot)."))


class EbayCheck(unittest.TestCase):
    def check(self, *effects, keys=("id", "secret")):
        from types import SimpleNamespace
        from flipradar.sources import Ebay

        api = Ebay(SimpleNamespace(ebay_client_id=keys[0], ebay_client_secret=keys[1]))
        with patch("flipradar.sources.read_json", side_effect=list(effects)):
            return api.check()

    def err(self, code, body):
        return HTTPError("https://api.ebay.com/x", code, "x", {}, io.BytesIO(json.dumps(body).encode()))

    def test_causes(self):
        self.assertIn("fehlt", self.check(keys=("", ""))[1])
        self.assertIn("Produktions-Schlüssel", self.check(self.err(401, {"error": "invalid_client"}))[1])
        token = {"access_token": "t", "expires_in": 3600}
        self.assertIn("Produktionsfreigabe", self.check(token, self.err(403, {"errors": []}))[1])
        self.assertIn("ausgeschöpft", self.check(token, self.err(429, {}))[1])
        self.assertIn("Verbindung", self.check(URLError("x"))[1])
        self.assertEqual(self.check(token, {"total": 0}), (True, "eBay-Zugang funktioniert."))


class StatusChecks(unittest.TestCase):
    def test_status_and_start_line(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = Store(str(Path(temp.name) / "d.db"))
        self.addCleanup(db.close)
        s = Settings(platforms=["tutti", "marktplaats"], collect_only=["marktplaats"], discovery=False,
                     request_delay_seconds=0, warmup_first_cycle=False)
        s.db_path = str(Path(temp.name) / "d.db")
        p = Product("RTX 4070", "gpu", "rtx 4070", ["4070"], [], ref_price_chf=600)
        item = Listing("tutti", "1", "RTX 4070", "https://www.tutti.ch/de/vi/1", 350, "CHF")
        with self.assertLogs("flipradar", level="INFO") as logs:
            radar = Radar(s, db, Mock())
            with patch("flipradar.engine.search", side_effect=lambda name, *a: [item] if name == "tutti" else (_ for _ in ()).throw(ValueError("kaputt"))):
                radar.cycle([p])
        text = "\n".join(logs.output)
        self.assertIn("Telegram-Alarme von: tutti | nur sammeln: marktplaats", text)
        self.assertIn("Status tutti: letzter Abruf", text)
        self.assertIn("Status marktplaats", text)
        self.assertIn("ValueError kaputt", text)
        row = db.conn.execute("select last_ok,last_new from source_status where platform='tutti'").fetchone()
        self.assertTrue(row[0] and row[1])


if __name__ == "__main__":
    unittest.main()
