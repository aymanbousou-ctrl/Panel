"""Telegram-Benachrichtigungen."""

from __future__ import annotations

import html
import logging
import re
import time

import json
from http.client import HTTPException
from urllib.error import HTTPError
from .net import read_json

from .models import Deal
from .platforms import label

log = logging.getLogger("flipradar")

def money(value: float) -> str:
    """1250.4 -> 1'250 (Schweizer Tausender-Trennung)."""
    return f"{value:,.0f}".replace(",", "'")


def format_deal(deal: Deal) -> str:
    l = deal.listing
    e = html.escape
    orig = (
        f" ({money(l.price)} EUR)"
        if l.currency == "EUR" and l.price is not None
        else ""
    )
    vb = " · VB" if l.negotiable else ""
    source = (
        f"Median aus {deal.sample_size} Inseraten"
        if deal.value_source == "median"
        else f"Referenzpreis (nur {deal.sample_size} Vergleichsinserate)"
    )
    if deal.value_source == "verkauft":
        source = f"Median aus {deal.sample_size} abgeschlossenen Verkäufen"
    lines = [
        f"🔥 <b>{e(deal.product.name)}</b> · {label(l.platform)}",
        e(l.title),
        "",
        f"💰 Preis: <b>{money(l.price_chf)} CHF</b>{orig}{vb}",
        f"📊 Marktwert: {money(deal.market_value_chf)} CHF ({source})",
        f"✅ Geschätzter Netto-Gewinn: <b>{money(deal.net_profit_chf)} CHF</b> ({deal.margin:.0%})",
    ]
    lines.append(f"Max. Einkaufspreis: {deal.max_offer:.2f} CHF · {deal.grade}")
    if deal.units > 1:
        lines.append(
            f"Los: {deal.units} Stück · Einkauf {l.price_chf / deal.units:.2f} CHF/Stk. · {deal.discount:.0%} unter Einzelangeboten"
        )
    if deal.reserve:
        lines.append(f"Zustandsreserve gesamt: {deal.reserve:.2f} CHF")
    if deal.spread:
        lines.append("Einzelangebote: " + deal.spread)
    if deal.retail_chf is not None:
        lines.append(f"Neupreis CH (Obergrenze): {money(deal.retail_chf)} CHF")
    if deal.germany_extra_chf:
        lines.append(f"Zusatzkosten DE: {money(deal.germany_extra_chf)} CHF")
    lines.append(f"Gesichtet (UTC): {l.seen_at:%Y-%m-%d %H:%M}")
    if l.location:
        lines.append(f"📍 {e(l.location)}")
    lines += ["", e(l.url)]
    return "\n".join(lines)


TOKEN_FORMAT = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


def _reason(code, description, retry):
    """Erklaert einen Telegram-Fehler auf Deutsch. Ohne Token, ohne URL."""
    text = (description or "").lower()
    if code == 401:
        return "Token ungültig oder widerrufen. Bot-Token bei @BotFather neu kopieren."
    if code == 404:
        return "Token unbekannt (Telegram findet den Bot nicht). Bot-Token prüfen."
    if code == 400 and "chat not found" in text:
        return (
            "Chat-ID unbekannt. Schreibe deinem Bot zuerst /start und prüfe die Chat-ID."
        )
    if code == 403:
        return "Der Bot darf dir nicht schreiben (blockiert oder aus dem Chat entfernt)."
    if code == 429:
        return f"Telegram-Ratenlimit, Wartezeit {retry or 60} s."
    if isinstance(code, int) and code >= 500:
        return f"Telegram-Server meldet Fehler (HTTP {code}), späterer Versuch."
    if code is None:
        return description
    return f"Telegram lehnt ab (HTTP {code}): {description}"


class Telegram:
    def __init__(self, token: str, chat_id: str, timeout: float = 15.0):
        # Leerzeichen und Zeilenumbrüche vom Einfügen würden die Adresse ungültig machen.
        self.token = (token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.timeout = timeout
        self.resume_at = 0
        self.last_error = ""

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def _call(self, method, payload):
        """Ein Aufruf. Ergebnis: ok, result, code, reason, retry, description."""
        out = dict(ok=False, result=None, code=None, retry=None, description="")
        try:
            answer = read_json(
                f"https://api.telegram.org/bot{self.token}/{method}",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            out.update(ok=answer.get("ok") is True, result=answer.get("result"))
            if not out["ok"]:
                out.update(code=answer.get("error_code"), description=str(answer.get("description", "")))
        except HTTPError as exc:
            try:
                body = json.loads(exc.read(16384))
            except (ValueError, OSError, AttributeError):
                body = {}
            exc.close()
            out.update(
                code=exc.code,
                description=str(body.get("description", "")),
                retry=(body.get("parameters") or {}).get("retry_after"),
            )
        except (OSError, ValueError, HTTPException) as exc:
            out.update(description=f"Keine Verbindung zu Telegram ({type(exc).__name__}). Internet prüfen.")
        out["reason"] = "" if out["ok"] else _reason(out["code"], out["description"], out["retry"])
        return out

    def _send(self, text, formatted):
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "link_preview_options": {"is_disabled": True},
        }
        if formatted:
            payload["parse_mode"] = "HTML"
        return self._call("sendMessage", payload)

    def send(self, text: str) -> bool:
        if time.monotonic() < self.resume_at:
            self.last_error = self.last_error or "Telegram-Ratenlimit, Wartezeit läuft noch."
            return False
        if not self.configured:
            self.last_error = "Telegram nicht eingerichtet."
            log.warning("Telegram nicht eingerichtet – Nachricht nur im Log:\n%s", text)
            return False
        res = self._send(text, True)
        if not res["ok"] and res["code"] == 400 and "parse entities" in res["description"].lower():
            # Ein Sonderzeichen im Inserat darf den Alarm nicht verhindern: ohne Formatierung erneut.
            res = self._send(html.unescape(re.sub(r"<[^>]+>", "", text)), False)
        if res["ok"]:
            self.last_error = ""
            return True
        if res["code"] == 429:
            self.resume_at = time.monotonic() + max(1, int(res["retry"] or 60))
        self.last_error = res["reason"]
        log.error("Telegram-Versand fehlgeschlagen: %s", res["reason"])
        return False

    def check(self):
        """Test fuer Einstellungen und Diagnose. Ergebnis: (ok, Meldung auf Deutsch)."""
        if not self.token:
            return False, "Es ist kein Bot-Token eingetragen."
        if not TOKEN_FORMAT.fullmatch(self.token):
            return (
                False,
                "Der Token hat nicht das Format 123456789:ABC... Bitte bei @BotFather neu kopieren.",
            )
        if not self.chat_id:
            return False, "Es ist keine Chat-ID eingetragen."
        me = self._call("getMe", {})
        if not me["ok"]:
            return False, me["reason"]
        name = (me["result"] or {}).get("username", "?")
        sent = self._send("FlipRadar – Telegram-Test erfolgreich.", False)
        if not sent["ok"]:
            return False, f"Bot @{name} ist gültig, aber: {sent['reason']}"
        return True, f"Telegram funktioniert (Bot @{name})."
