"""Einstellungen und Watchlist laden."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import Product


@dataclass
class Settings:
    telegram_token: str = ""
    telegram_chat_id: str = ""
    lot_budget_chf: float = 2000
    portfolio_chf: float = 2000
    lot_discount: float = 0.30
    b_reserve_chf: float = 20
    discovery: bool = True
    disabled_models: list[str] = field(default_factory=list)
    batch_size: int = 30
    ebay_daily_calls: int = 4000
    interval_minutes: float = 5.0
    min_margin: float = 0.20  # 20 % Netto-Marge
    max_price_chf: float = 2000.0
    eur_to_chf: float = 0.94  # Wechselkurs EUR -> CHF, selbst aktuell halten
    sell_fee_pct: float = 0.10  # Gebühr beim Weiterverkauf (Anteil vom Verkaufspreis)
    shipping_chf: float = 10.0  # Versand/Abholung pauschal pro Deal
    asking_price_factor: float = (
        0.92  # Angebotspreise liegen über echten Verkaufspreisen
    )
    min_samples: int = 8  # so viele Vergleichsinserate braucht ein Median
    lookback_days: int = 30
    warmup_first_cycle: bool = True  # erster Durchlauf: nur Daten sammeln, keine Alarme
    platforms: list[str] = field(
        default_factory=lambda: ["ricardo", "tutti", "kleinanzeigen", "ebay"]
    )
    # Marktwert nur aus diesen Plattformen (dort verkaufst du wieder)
    value_platforms: list[str] = field(default_factory=lambda: ["ricardo", "tutti"])
    max_results_per_search: int = 40
    request_delay_seconds: float = 3.0
    germany_extra_chf: float = 0
    sales_csv: str = ""
    min_profit_chf: float = 0.0
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    db_path: str = "flipradar.db"
    log_path: str = "flipradar.log"


def load_settings(path: str | Path) -> Settings:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    s = Settings()
    tg = data.get("telegram", {}) or {}
    s.telegram_token = os.environ.get("FLIPRADAR_TELEGRAM_TOKEN") or str(
        tg.get("token", "") or ""
    )
    s.telegram_chat_id = os.environ.get("FLIPRADAR_TELEGRAM_CHAT_ID") or str(
        tg.get("chat_id", "") or ""
    )
    ebay = data.get("ebay") or {}
    s.ebay_client_id = os.environ.get("FLIPRADAR_EBAY_ID") or str(
        ebay.get("client_id") or ""
    )
    s.ebay_client_secret = os.environ.get("FLIPRADAR_EBAY_SECRET") or str(
        ebay.get("client_secret") or ""
    )
    for key in (
        "discovery",
        "disabled_models",
        "lot_budget_chf",
        "portfolio_chf",
        "lot_discount",
        "b_reserve_chf",
        "batch_size",
        "ebay_daily_calls",
        "interval_minutes",
        "min_margin",
        "max_price_chf",
        "eur_to_chf",
        "sell_fee_pct",
        "shipping_chf",
        "asking_price_factor",
        "min_samples",
        "lookback_days",
        "warmup_first_cycle",
        "platforms",
        "value_platforms",
        "max_results_per_search",
        "request_delay_seconds",
        "db_path",
        "log_path",
        "min_profit_chf",
        "sales_csv",
        "germany_extra_chf",
    ):
        if key in data and data[key] is not None:
            setattr(s, key, data[key])
    s.platforms = [p.lower() for p in s.platforms]
    if data.get("kleinanzeigen_schriftliche_freigabe") is not True:
        s.platforms = [p for p in s.platforms if p != "kleinanzeigen"]
    if not (
        0 <= s.lot_discount < 1
        and s.portfolio_chf > 0
        and s.lot_budget_chf > 0
        and s.b_reserve_chf >= 0
        and isinstance(s.batch_size, int)
        and s.batch_size >= 1
        and s.ebay_daily_calls >= 1
    ):
        raise ValueError("Los-/Budgeteinstellungen unplausibel")
    s.value_platforms = [p.lower() for p in s.value_platforms]
    unknown = set(s.platforms) - {"ricardo", "tutti", "kleinanzeigen", "ebay"}
    if unknown:
        raise ValueError(f"Unbekannte Plattform(en) in config: {sorted(unknown)}")
    if not 0 < s.min_margin < 5:
        raise ValueError("min_margin als Anteil angeben, z. B. 0.20 für 20 %")
    if not 0 <= s.germany_extra_chf < float("inf") or not 0 < s.eur_to_chf < float(
        "inf"
    ):
        raise ValueError("germany_extra_chf >= 0, eur_to_chf > 0")
    if not (
        1 <= s.max_results_per_search <= 200
        and 1 <= s.interval_minutes <= 1440
        and 0 <= s.sell_fee_pct < 1
        and s.min_samples >= 1
        and s.max_price_chf > 0
        and s.lookback_days > 0
        and s.shipping_chf >= 0
        and s.request_delay_seconds >= 0
    ):
        raise ValueError("Unplausible Such- oder Bewertungsparameter in config.yaml")
    if s.sales_csv:
        s.sales_csv = str(Path(path).parent / s.sales_csv)
    return s


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def load_watchlist(path: str | Path) -> list[Product]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    global_exclude = _as_list(data.get("exclude_global"))
    by_category = {
        k: _as_list(v) for k, v in (data.get("exclude_by_category") or {}).items()
    }
    products: list[Product] = []
    for item in data.get("products", []) or []:
        if item.get("enabled", True) is False:
            continue
        name = item["name"]
        category = item.get("category", "sonstiges")
        products.append(
            Product(
                name=name,
                category=category,
                query=item.get("query", name),
                include=_as_list(item.get("include")) or [name],
                exclude=global_exclude
                + by_category.get(category, [])
                + _as_list(item.get("exclude")),
                min_price_chf=float(item.get("min_price_chf", 0) or 0),
                max_price_chf=float(item["max_price_chf"])
                if item.get("max_price_chf")
                else None,
                ref_price_chf=float(item["ref_price_chf"])
                if item.get("ref_price_chf")
                else None,
                kleinanzeigen_url=item.get("kleinanzeigen_url"),
                retail_url=item.get("retail_url"),
                tutti_category=item.get("tutti_category"),
                platforms=[p.lower() for p in _as_list(item.get("platforms"))] or None,
            )
        )
    names = [p.name for p in products]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"Doppelte Produktnamen in watchlist: {sorted(dupes)}")
    return products
