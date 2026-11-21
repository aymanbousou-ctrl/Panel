"""Telegram-Benachrichtigungen."""

from __future__ import annotations

import html
import logging
import time

import json
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


class Telegram:
    def __init__(self, token: str, chat_id: str, timeout: float = 15.0):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self.resume_at = 0

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        if time.monotonic() < self.resume_at:
            return False
        if not self.configured:
            log.warning("Telegram nicht eingerichtet – Nachricht nur im Log:\n%s", text)
            return False
        try:
            answer = read_json(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data=json.dumps(
                    {
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "link_preview_options": {"is_disabled": True},
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            return answer.get("ok") is True
        except (OSError, ValueError) as exc:
            if isinstance(exc, HTTPError):
                if exc.code == 429:
                    try:
                        delay = int(
                            json.loads(exc.read(16384))
                            .get("parameters", {})
                            .get("retry_after", 60)
                        )
                    except (ValueError, OSError, AttributeError, TypeError):
                        delay = 60
                    self.resume_at = time.monotonic() + max(1, delay)
                exc.close()
            log.error(
                "Telegram-Versand fehlgeschlagen (%s)",
                exc.code if isinstance(exc, HTTPError) else type(exc).__name__,
            )
            return False
