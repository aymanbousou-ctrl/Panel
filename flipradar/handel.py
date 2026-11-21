"""Local inventory, comparable single units and rotating product discovery."""

import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

INVENTORY_FIELDS = [
    "ID",
    "Produkt",
    "Einkaufstag",
    "Einstand_CHF",
    "Verkaufstag",
    "Nettoerloes_CHF",
]
from statistics import median


def profile(item, product):
    text = (item.title + " " + item.description).casefold()
    title = item.title.casefold()
    if re.search(
        r"\b(reparaturservice|kaufgesuch|gesuch|suche|ankauf|defekt|ersatzteilspender|ohne funktion)\b",
        title,
    ):
        return None
    if re.search(
        r"\b(pro stück|je stück|je\s+\d+|einzelpreis|einzeln je|stückpreis|preis pro|jeweils|ab preis|per piece)\b",
        text,
    ):
        return None
    amounts = re.findall(
        r"(?<![\w.])(\d{1,3})\s*(?:stück\b|stk\b|[x×](?=\s*[a-z]))", title
    )
    qty = int(amounts[0]) if len(amounts) == 1 else 1
    if amounts or re.search(
        r"\b(konvolut|posten|lot|mischpaket|bundle|gesamtpreis|paketpreis)\b", title
    ):
        if (
            len(amounts) != 1
            or qty < 2
            or qty > 100
            or not re.search(
                r"gesamtpreis|paketpreis|preis für alle|preis für das (?:ganze )?paket",
                text,
            )
        ):
            return None
        if re.search(r"verschiedene|gemischt|diverse modelle|davon defekt", text):
            return None
    if re.search(
        r"\b(ungetestet|ungeprüft|defekt(?:e|er|es)?|beschädigt|bastlerware|funktionslos|funktion unbekannt)\b",
        text,
    ):
        return None
    if qty > 1:
        if re.search(
            r"\b(und|plus|inklusive|inkl|zuzüglich|teils|teilweise)\b|[+&]", title
        ):
            return None
        # An accessory count later in a title does not establish how many devices are sold.
        before = re.split(
            r"(?<![\w.])" + str(qty) + r"\s*(?:stück|stk|x|×)", title, maxsplit=1
        )[0]
        if re.search(r"\b(inkl|mit|dazu|plus)\b|[+]", before) or re.search(
            r"\b(davon|gemischt|verschiedene)\b", text
        ):
            return None
    grade = (
        "B-Ware"
        if re.search(
            r"\bb[ -]?ware\b|\bretoure\b|\brefurbished\b|\bgeneralüberholt\b", text
        )
        else "Standard"
    )
    tags = []
    if product.category == "handy":
        m = re.search(r"\b(64|128|256|512)\s*gb\b|\b1\s*tb\b", title)
        tags.append(m[0].replace(" ", "") if m else "?GB")
    if product.name.startswith("PS5"):
        tags.append(
            "Digital"
            if re.search("digital|ohne disc|ohne laufwerk", title)
            else "Disc"
            if re.search(r"\bdisc\b|mit laufwerk", title)
            else "?Laufwerk"
        )
    if product.category == "auto":
        year = re.search(r"\b(?:19[89]\d|20[012]\d)\b", title)
        km = re.search(r"\b(\d{1,3}(?:['’. ]\d{3}){1,2}|\d{3,7})\s*km\b", text)
        tags.extend(
            [
                str(int(year[0]) // 3 * 3) if year else "?Jahr",
                str(int(re.sub(r"\D", "", km[1])) // 50000) + "x50tkm" if km else "?km",
            ]
        )
    return qty, grade, " / ".join(tags)


@dataclass
class Sample:
    previous: int = 0
    recent: int = 0
    mature: int = 0
    fast: int = 0
    profits: list = field(default_factory=list)
    opportunities: int = 0
    imported_recent: int = 0
    imported_previous: int = 0

    def rate(self):
        return (
            f"{100 * self.fast / self.mature:.0f}% ({self.fast}/{self.mature})"
            if self.mature >= 10
            else f"offen (n={self.mature})"
        )


def inventory(path, today=None):
    today = today or date.today()
    samples = defaultdict(Sample)
    invested = 0.0
    if not Path(path).exists():
        return samples, invested
    seen = set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        if not set(INVENTORY_FIELDS).issubset(reader.fieldnames or []):
            raise ValueError(
                "Bestand.csv: Spalten fehlen. Bestand prüfen, bevor die Suche weitere Deals meldet."
            )
        for line, r in enumerate(reader, 2):
            try:
                key = r["ID"].strip()
                if not key or key in seen:
                    raise ValueError("ID")
                seen.add(key)
                p = r["Produkt"].strip()
                bought = date.fromisoformat(r["Einkaufstag"])
                sold = (
                    date.fromisoformat(r["Verkaufstag"]) if r["Verkaufstag"] else None
                )
                cost = float(r["Einstand_CHF"].replace(",", "."))
                if (
                    not p
                    or cost <= 0
                    or not math.isfinite(cost)
                    or bought > today
                    or sold
                    and not bought <= sold <= today
                ):
                    raise ValueError("Datum/Kosten")
                a = samples[p]
                if bought <= today - timedelta(days=30):
                    a.mature += 1
                    a.fast += int(bool(sold and (sold - bought).days <= 30))
                if sold:
                    income = float(r["Nettoerloes_CHF"].replace(",", "."))
                    if not math.isfinite(income) or income < 0:
                        raise ValueError("Nettoerlös")
                    days = (today - sold).days
                    a.recent += int(days < 7)
                    a.previous += int(7 <= days < 14)
                    if days < 90:
                        a.profits.append(income - cost)
                else:
                    invested += cost
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ValueError(f"Bestand.csv Zeile {line}: {exc}") from exc
    return samples, invested


def choose(products, samples, cursor, limit):
    if len(products) <= limit:
        return products, 0
    # At least half of each batch explores the catalogue on a stable round-robin.
    n = max(1, limit // 2)
    rotation = [products[(cursor + i) % len(products)] for i in range(n)]

    def score(p):
        a = samples[p.name]
        roi_signal = median(a.profits) if a.profits else 0
        return (
            a.recent > a.previous and roi_signal > 0,
            a.imported_recent >= 3 and a.imported_recent > a.imported_previous,
            a.fast / a.mature if a.mature >= 10 else 0,
            roi_signal,
            a.recent,
            a.opportunities,
        )

    extras = [
        products[(cursor + n + i) % len(products)] for i in range(len(products) - n)
    ]
    extras.sort(key=score, reverse=True)
    return rotation + extras[: limit - n], (cursor + n) % len(products)


def write_trends(path, products, samples, db):
    """Separate the supply observed in search from the user's confirmed sales."""
    from datetime import datetime, time, timezone

    local_day = date.today()

    def cutoff(days):
        midnight = datetime.combine(local_day - timedelta(days=days), time.min)
        return midnight.astimezone(timezone.utc).isoformat(timespec="seconds")

    starts = [cutoff(6), cutoff(13)]
    offers = {
        p: (a, b)
        for p, a, b in db.conn.execute(
            """
        SELECT product,SUM(first_seen>=?),SUM(first_seen<?) FROM listings
        WHERE product IS NOT NULL AND first_seen>=? GROUP BY product""",
            (starts[0], *starts),
        )
    }
    days = {
        p: (a, b)
        for p, a, b in db.conn.execute(
            """
        SELECT product,SUM(day>=?),SUM(day<?) FROM scan WHERE day>=? GROUP BY product""",
            (
                (local_day - timedelta(days=6)).isoformat(),
                (local_day - timedelta(days=6)).isoformat(),
                (local_day - timedelta(days=13)).isoformat(),
            ),
        )
    }
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(
            [
                "Produkt",
                "Kategorie",
                "Neue Inserate 7 Tage",
                "Neue Inserate Vorwoche",
                "Suchtage 7 Tage",
                "Suchtage Vorwoche",
                "Eigene Verkäufe 7 Tage",
                "Eigene Verkäufe Vorwoche",
                "Binnen 30 Tagen verkauft",
                "Median Gewinn CHF 90 Tage",
                "Verkäufe mit Gewinnangabe 90 Tage",
                "Importierte Verkäufe 7 Tage",
                "Importierte Verkäufe Vorwoche",
                "Qualifizierte Inserate 7 Tage",
            ]
        )
        for p in products:
            a = samples[p.name]
            w.writerow(
                [
                    p.name,
                    p.category,
                    *offers.get(p.name, (0, 0)),
                    *days.get(p.name, (0, 0)),
                    a.recent,
                    a.previous,
                    a.rate(),
                    round(median(a.profits), 2) if a.profits else "",
                    len(a.profits),
                    a.imported_recent,
                    a.imported_previous,
                    a.opportunities,
                ]
            )
    temp.replace(path)
