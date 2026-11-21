"""Erkennt, welches Watchlist-Produkt ein Inserat ist."""

from __future__ import annotations

from functools import lru_cache
import re
import unicodedata

from .models import Listing, Product


@lru_cache(maxsize=8192)
def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").lower()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\b(rtx|gtx|rx)(?=\d)", r"\1 ", text)
    text = re.sub(r"(\d)(ti|super|xtx)\b", r"\1 \2", text)
    text = re.sub(r"[^a-z0-9+]+", " ", text)
    return f" {text.strip()} "


def _contains(norm_text: str, term: str) -> bool:
    """Ganzes-Wort-Treffer, damit '4070' nicht in '40700' oder 'ti' nicht in 'titan' trifft."""
    t = normalize(term).strip()
    if not t:
        return False
    return f" {t} " in norm_text


def matches(listing: Listing, product: Product, use_description: bool = False) -> bool:
    text = listing.title + (" " + listing.description if use_description else "")
    norm = normalize(text)
    for group in product.include:
        # "rtx 4070|rtx4070" = eine der Varianten muss vorkommen
        if not any(_contains(norm, alt) for alt in group.split("|")):
            return False
    for word in product.exclude:
        if _contains(norm, word):
            return False
    return True


def match_product(listing: Listing, products: list[Product]) -> Product | None:
    """Gibt das spezifischste passende Produkt zurück (meiste Include-Begriffe)."""
    hits = [p for p in products if matches(listing, p)]
    if not hits:
        return None
    return max(hits, key=lambda p: (len(p.include), sum(len(g) for g in p.include)))
