"""Eine Tabelle aller Plattformen: Anzeigename, Land und Waehrung.

Eine neue Quelle braucht hier einen Eintrag und eine Suchfunktion in sources.py.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    label: str
    country: str  # ISO-Land des Marktplatzes
    currency: str
    # Immer nur sammeln: Kosten fuer Kauf im Ausland sind dort noch nicht eingerechnet.
    collect_only: bool = False
    # Begriffe fuer Gesuche, Defekte und Tausch in der Landessprache der Plattform.
    exclude: tuple = ()


PLATFORMS = {
    "ricardo": Platform("Ricardo", "CH", "CHF"),
    "tutti": Platform("Tutti", "CH", "CHF"),
    "kleinanzeigen": Platform("Kleinanzeigen", "DE", "EUR"),
    "ebay": Platform("eBay.de", "DE", "EUR"),
    "marktplaats": Platform(
        "Marktplaats",
        "NL",
        "EUR",
        collect_only=True,
        exclude=(
            "gezocht", "gevraagd", "zoek", "zoeken", "defect", "kapot",
            "niet werkend", "werkt niet", "onderdelen", "reparatie", "ruil",
            "ruilen", "huur", "huren", "te huur", "verhuur", "lege doos",
        ),
    ),
}


def label(name):
    return PLATFORMS[name].label if name in PLATFORMS else name


def country(name):
    return PLATFORMS[name].country if name in PLATFORMS else ""


def excluded_terms(name):
    return PLATFORMS[name].exclude if name in PLATFORMS else ()
