"""Eine Tabelle aller Plattformen: Anzeigename, Land und Waehrung.

Eine neue Quelle braucht hier einen Eintrag und eine Suchfunktion in sources.py.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    label: str
    country: str  # ISO-Land des Marktplatzes
    currency: str


PLATFORMS = {
    "ricardo": Platform("Ricardo", "CH", "CHF"),
    "tutti": Platform("Tutti", "CH", "CHF"),
    "kleinanzeigen": Platform("Kleinanzeigen", "DE", "EUR"),
    "ebay": Platform("eBay.de", "DE", "EUR"),
}


def label(name):
    return PLATFORMS[name].label if name in PLATFORMS else name


def country(name):
    return PLATFORMS[name].country if name in PLATFORMS else ""
