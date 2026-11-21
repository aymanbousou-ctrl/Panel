"""Vergleichspreise aus eigenen, abgeschlossenen Verkäufen in CHF."""

import csv
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


def load_sales(path: str, lookback_days: int, samples=None) -> dict[str, list[float]]:
    prices = defaultdict(list)
    if not path:
        return prices
    today = date.today()
    earliest = today - timedelta(days=lookback_days)
    seen = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"sale_id", "product", "sold_on", "price_chf"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"{path}: CSV braucht {', '.join(sorted(required))}")
        for row in reader:
            try:
                sale_id = row["sale_id"].strip()
                product = row["product"].strip()
                sold = date.fromisoformat(row["sold_on"].strip())
                price = float(row["price_chf"])
                if not sale_id or not product or not math.isfinite(price) or price <= 0:
                    raise ValueError("ungültige Verkaufsdaten")
                if sale_id in seen:
                    raise ValueError(f"doppelte sale_id {sale_id}")
                seen.add(sale_id)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError(f"{path}, Zeile {reader.line_num}: {exc}") from exc
            if samples is not None and 0 <= (today - sold).days < 14:
                sample = samples[product]
                if (today - sold).days < 7:
                    sample.imported_recent += 1
                else:
                    sample.imported_previous += 1
            if earliest <= sold <= today:
                prices[product].append(price)
    return prices
