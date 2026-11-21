"""Find additional named models in a rotating general search."""

import re
from datetime import date, timedelta
from .models import Product
from .matcher import match_product
from .handel import profile

# Narrow patterns keep generic titles and mixed parcels out of new product rules.
FAMILIES = [
    ("werkzeug", "Makita Akkuschrauber", r"\b(Makita)\s+((?:DDF|DHP)\d{3})\b"),
    (
        "handy",
        "Samsung Galaxy Ultra",
        r"\b(?:Samsung\s+)?(Galaxy)\s+(S\d{2}\s+Ultra)\b",
    ),
    (
        "werkzeug",
        "Bosch Professional GSR",
        r"\b(Bosch)\s+(?:Professional\s+)?(GSR\s+\d{2}V-\d{2,3})\b",
    ),
    ("kamera", "Sony Alpha Kamera", r"\b(Sony)\s+(?:Alpha\s+)?(A[6-9]\d{3})\b"),
    (
        "handy",
        "Google Pixel Pro",
        r"\b(?:Google\s+)?(Pixel)\s+(\d{1,2}\s+Pro(?:\s+XL)?)\b",
    ),
    ("konsole", "Nintendo Switch", r"\b(Nintendo)\s+(Switch\s+(?:OLED|Lite|[2-9]))\b"),
    (
        "auto",
        "Toyota Gebrauchtwagen",
        r"\b(Toyota)\s+(Prius|RAV4|Auris|Avensis|Camry|C-HR)\b",
    ),
    ("haushalt", "Dyson Akkusauger", r"\b(Dyson)\s+(V\d{1,2})\b"),
    ("audio", "Sony WH Kopfhörer", r"\b(Sony)\s+(WH-1000XM\d)\b"),
    ("werkzeug", "Fluke Multimeter", r"\b(Fluke)\s+([123]\d{2}[A-Z]?)\b"),
]


def init_discovery(db):
    db.conn.executescript("""
        CREATE TABLE IF NOT EXISTS discoveries(model TEXT,category TEXT,brand TEXT,code TEXT,key TEXT,day TEXT,
            PRIMARY KEY(model,key));
        CREATE INDEX IF NOT EXISTS discoveries_day ON discoveries(day);
        CREATE TABLE IF NOT EXISTS discovered_models(model TEXT PRIMARY KEY,category TEXT,brand TEXT,code TEXT);
        CREATE TABLE IF NOT EXISTS probe_cursor(id INTEGER PRIMARY KEY,position INTEGER);
    """)


def new_product(model, category, brand, code):
    return Product(
        model,
        category,
        model,
        [brand, code],
        [
            "defekt",
            "für",
            "kompatibel",
            "ersatz",
            "ersatzteile",
            "nur karton",
            "tasche",
            "hülle",
            "zubehör",
            "adapter",
            "ohne gerät",
            "gehäuse",
            "ersatzakku",
        ],
        min_price_chf=20,
    )


def probe_product(db):
    row = db.conn.execute("SELECT position FROM probe_cursor WHERE id=1").fetchone()
    pos = (row[0] if row else 0) % len(FAMILIES)
    category, query, _ = FAMILIES[pos]
    return Product(query, category, query, [], []), pos


def record(db, pos, items, known):
    category, _, pattern = FAMILIES[pos]
    day = date.today().isoformat()
    with db.conn:
        for item in items:
            hit = re.search(pattern, item.title, re.I)
            if not hit or match_product(item, known):
                continue
            brand = hit[1].title()
            code = re.sub(r"\s+", " ", hit[2].upper())
            model = brand + " " + code
            product = new_product(model, category, brand, code)
            if (
                not match_product(item, [product])
                or not profile(item, product)
                or not item.price
                or item.price <= 0
            ):
                continue
            db.conn.execute(
                "INSERT OR IGNORE INTO discoveries VALUES(?,?,?,?,?,?)",
                (model, category, brand, code, item.key, day),
            )
        db.conn.execute(
            """INSERT OR IGNORE INTO discovered_models
            SELECT model,category,brand,code FROM discoveries WHERE day>=? AND model NOT IN (SELECT model FROM discovered_models)
            GROUP BY model,category,brand,code HAVING COUNT(*)>=4 AND COUNT(DISTINCT day)>=2
            ORDER BY COUNT(*) DESC LIMIT max(0,50-(SELECT count(*) FROM discovered_models))""",
            ((date.today() - timedelta(days=27)).isoformat(),),
        )


def expanded(db, base, disabled):
    names = {p.name.casefold() for p in base} | {n.casefold() for n in disabled}
    result = list(base)
    for model, category, brand, code in db.conn.execute(
        "SELECT * FROM discovered_models ORDER BY model"
    ):
        if model.casefold() not in names:
            result.append(new_product(model, category, brand, code))
    return result
