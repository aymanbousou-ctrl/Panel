"""Gemeinsame Datenstrukturen."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Listing:
    """Ein Inserat, normalisiert über alle Plattformen."""

    platform: str  # "ricardo" | "tutti" | "kleinanzeigen"
    listing_id: str  # ID auf der Plattform
    title: str
    url: str
    price: float | None  # Preis in Originalwährung
    currency: str  # "CHF" | "EUR"
    price_chf: float | None = None
    location: str = ""
    description: str = ""
    negotiable: bool = False  # "VB" / Verhandlungsbasis
    seen_at: datetime = field(default_factory=now_utc)

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.listing_id}"


@dataclass
class Product:
    """Ein Eintrag der Watchlist."""

    name: str
    category: str
    query: str
    include: list[
        str
    ]  # alle müssen im Titel vorkommen (eine Gruppe = Alternativen mit "|")
    exclude: list[str]
    min_price_chf: float = 0.0  # darunter = Zubehör/Fake/Defekt
    max_price_chf: float | None = None
    ref_price_chf: float | None = None  # optionaler manueller Marktwert
    kleinanzeigen_url: str | None = None
    tutti_category: str | None = None  # z. B. cars, cellPhones, consolesGames
    platforms: list[str] | None = None  # None = alle aktiven
    retail_url: str | None = None


@dataclass
class Deal:
    listing: Listing
    product: Product
    market_value_chf: float
    value_source: str  # "median" | "referenz"
    sample_size: int
    net_profit_chf: float
    margin: float
    retail_chf: float | None = None
    germany_extra_chf: float = 0
    units: int = 1
    max_offer: float = 0
    discount: float = 0
    reserve: float = 0
    grade: str = "Standard"
    spread: str = ""
