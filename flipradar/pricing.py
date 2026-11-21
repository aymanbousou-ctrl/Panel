"""Preise lesen, Marktwert schätzen, Deals berechnen."""

from __future__ import annotations

import re
from statistics import median

from .config import Settings
from .models import Deal, Listing, Product
from .platforms import country

_NUM = re.compile(r"\d[\d'’ .,]*")


def parse_price(raw, currency_hint: str = "CHF") -> tuple[float | None, bool]:
    """Liest Preise wie 'CHF 1'250.–', '450.-', '1.200 € VB', '99,90 €', 450.0.

    Gibt (Preis, verhandelbar) zurück. Kein Zahlenwert (z. B. 'VB', 'Gratis') -> None.
    """
    if raw is None:
        return None, False
    if isinstance(raw, (int, float)):
        return (float(raw) if raw > 0 else None), False
    text = str(raw).strip()
    negotiable = bool(re.search(r"\bVB\b|verhandel", text, re.I))
    m = _NUM.search(text)
    if not m:
        return None, negotiable
    num = m.group(0).strip().replace("'", "").replace("’", "").replace(" ", "")
    num = num.rstrip(".,")
    if currency_hint == "EUR":
        # Deutsches Format: 1.200,50
        if "," in num:
            num = num.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+", num):
            num = num.replace(".", "")
    else:
        # Schweizer Format: 1'250.50 / 1250.– / 1,250.00
        if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", num):
            num = num.replace(",", "")
        elif "," in num and "." not in num:
            num = num.replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+", num):
            num = num.replace(".", "")
    try:
        value = float(num)
    except ValueError:
        return None, negotiable
    return (value if value > 0 else None), negotiable


def to_chf(listing: Listing, settings: Settings) -> float | None:
    if listing.price is None:
        return None
    if listing.currency == "EUR":
        return round(listing.price * settings.eur_to_chf, 2)
    return round(listing.price, 2)


def robust_median(prices: list[float]) -> float | None:
    """Median nach Ausreisser-Filter (Zubehör, Fantasiepreise)."""
    clean = sorted(p for p in prices if p and p > 0)
    if not clean:
        return None
    m = median(clean)
    kept = [p for p in clean if 0.5 * m <= p <= 2.0 * m]
    return median(kept) if kept else m


def market_value(
    product: Product, comparable_prices: list[float], settings: Settings
) -> tuple[float | None, str, int]:
    """Marktwert in CHF. Median der Vergleichsinserate * asking_price_factor,
    sonst manueller Referenzpreis. Rückgabe: (Wert, Quelle, Anzahl)."""
    n = len(comparable_prices)
    if n >= settings.min_samples:
        med = robust_median(comparable_prices)
        if med:
            return round(med * settings.asking_price_factor, 2), "median", n
    if product.ref_price_chf:
        return product.ref_price_chf, "referenz", n
    return None, "zu wenig Daten", n


def evaluate(
    listing: Listing,
    product: Product,
    comparable_prices: list[float],
    settings: Settings,
    sold_prices: list[float] | None = None,
    retail_chf: float | None = None,
    units: int = 1,
    grade: str = "Standard",
    available: float | None = None,
) -> Deal | None:
    """Prüft, ob ein Inserat die Deal-Kriterien erfüllt."""
    price = listing.price_chf
    if price is None or price <= 0:
        return None
    max_price = min(
        settings.max_price_chf, product.max_price_chf or settings.max_price_chf
    )
    if units > 1:
        max_price = min(
            settings.lot_budget_chf,
            (product.max_price_chf or settings.lot_budget_chf) * units,
        )
    if price > max_price or price / units < product.min_price_chf:
        return None
    if sold_prices and len(sold_prices) >= settings.min_samples:
        value, source, n = robust_median(sold_prices), "verkauft", len(sold_prices)
    else:
        value, source, n = market_value(product, comparable_prices, settings)
    if not value:
        return None
    if retail_chf is not None:
        value = min(value, retail_chf)
    extra = settings.germany_extra_chf if country(listing.platform) == "DE" else 0
    available = settings.portfolio_chf if available is None else available
    reserve = settings.b_reserve_chf * units if grade == "B-Ware" else 0
    if price + extra + reserve > available:
        return None
    discount = 0.0
    if units > 1:
        if len(comparable_prices) < settings.min_samples:
            return None
        discount = 1 - price / (units * median(comparable_prices))
        if discount + 1e-9 < settings.lot_discount:
            return None
    value *= units
    net_profit = (
        value * (1 - settings.sell_fee_pct)
        - settings.shipping_chf * units
        - price
        - extra
        - reserve
    )
    margin = net_profit / (price + extra + reserve)
    if margin < settings.min_margin or net_profit < settings.min_profit_chf:
        return None
    return Deal(
        units=units,
        grade=grade,
        reserve=reserve,
        discount=discount,
        spread=(
            f"{min(comparable_prices):.0f}–{max(comparable_prices):.0f} CHF/Stk."
            if comparable_prices
            else ""
        ),
        max_offer=max(
            0,
            min(
                max_price,
                available - extra - reserve,
                (value * (1 - settings.sell_fee_pct) - settings.shipping_chf * units)
                / (1 + settings.min_margin)
                - extra
                - reserve,
                value * (1 - settings.sell_fee_pct)
                - settings.shipping_chf * units
                - extra
                - reserve
                - settings.min_profit_chf,
                units * median(comparable_prices) * (1 - settings.lot_discount)
                if units > 1
                else max_price,
            ),
        ),
        listing=listing,
        product=product,
        retail_chf=retail_chf,
        germany_extra_chf=extra,
        market_value_chf=round(value, 2),
        value_source=source,
        sample_size=n,
        net_profit_chf=round(net_profit, 2),
        margin=round(margin, 4),
    )
