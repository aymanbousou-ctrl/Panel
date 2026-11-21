"""First start and Windows settings. V1 is opened read-only."""

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def data_dir():
    return Path(
        os.environ.get("FLIPRADAR_DATA")
        or (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FlipRadarV21")
    ).resolve()


def save(path, text):
    tmp = path.with_suffix(".new")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def init(folder, home=None):
    if (folder / "config.yaml").exists():
        return
    home = home or Path.home()
    with tempfile.TemporaryDirectory(dir=folder) as stage:
        tmp = Path(stage)
        old = None
        for path in [home / "Documents", home / "Downloads"]:
            cfg = path / "FlipRadar_v1.2" / "flipradar" / "config.yaml"
            if cfg.is_file():
                old = cfg
                break
        previous = (
            Path(os.environ.get("LOCALAPPDATA", home)) / "FlipRadarV2" / "config.yaml"
        )
        if previous.is_file():
            old = previous
        cfg = (
            yaml.safe_load(
                (old or ROOT / "config.example.yaml").read_text(encoding="utf-8-sig")
            )
            or {}
        )
        cfg.setdefault("disabled_models", [])
        cfg.setdefault("portfolio_chf", cfg.get("max_price_chf", 2000))
        cfg.setdefault("lot_budget_chf", cfg.get("max_price_chf", 2000))
        cfg.setdefault("ebay", {"client_id": "", "client_secret": ""})
        cfg.setdefault(
            "apify",
            {"token": "", "products": [], "interval_minutes": 720, "max_results": 20},
        )
        platforms = cfg.setdefault("platforms", ["ricardo", "tutti", "kleinanzeigen"])
        if "ebay" not in platforms:
            platforms.append("ebay")
        watch = old.parent / "watchlist.yaml" if old else ROOT / "watchlist.yaml"
        shutil.copyfile(
            watch if watch.is_file() else ROOT / "watchlist.yaml",
            tmp / "watchlist.yaml",
        )
        watchdata = yaml.safe_load(
            (tmp / "watchlist.yaml").read_text(encoding="utf-8-sig")
        )
        cfg["disabled_models"] = list(
            dict.fromkeys(
                [
                    *cfg["disabled_models"],
                    *(
                        p["name"]
                        for p in watchdata["products"]
                        if not p.get("enabled", True)
                    ),
                ]
            )
        )
        names = {p["name"].casefold() for p in watchdata["products"]}
        extra = yaml.safe_load((ROOT / "katalog.yaml").read_text(encoding="utf-8"))
        watchdata["products"].extend(
            p for p in extra["products"] if p["name"].casefold() not in names
        )
        save(
            tmp / "watchlist.yaml",
            yaml.safe_dump(watchdata, allow_unicode=True, sort_keys=False),
        )
        (tmp / "Bestand.csv").write_text(
            "ID;Produkt;Einkaufstag;Einstand_CHF;Verkaufstag;Nettoerloes_CHF\n",
            encoding="utf-8-sig",
        )
        if old:
            db = old.parent / cfg.get("db_path", "flipradar.db")
            if db.is_file():
                source = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
                dest = sqlite3.connect(tmp / "flipradar.db")
                try:
                    source.backup(dest)
                    # Older Ricardo records can contain bids. Only V2 fixed prices may establish value.
                    tables = {
                        row[0]
                        for row in dest.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    if old != previous and "listings" in tables:
                        dest.execute(
                            "UPDATE listings SET product=NULL WHERE platform='ricardo'"
                        )
                    if "pending" in tables:
                        dest.execute("DELETE FROM pending")
                    dest.commit()
                finally:
                    dest.close()
                    source.close()
            if cfg.get("sales_csv") and (old.parent / cfg["sales_csv"]).is_file():
                shutil.copyfile(old.parent / cfg["sales_csv"], tmp / "sales.csv")
                cfg["sales_csv"] = "sales.csv"
            elif cfg.get("sales_csv"):
                print(
                    "Verkaufspreis-Datei fehlt. Import bei Bedarf in config.yaml erneut aktivieren."
                )
                cfg["sales_csv"] = ""
            print("Vorhandene Einstellungen uebernommen aus", old.parent)
        cfg.update(db_path="flipradar.db", log_path="flipradar.log")
        (tmp / "config.yaml").write_text(
            yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        for f in sorted(tmp.iterdir(), key=lambda p: p.name == "config.yaml"):
            os.replace(f, folder / f.name)


def edit(folder):
    import tkinter as tk
    from tkinter import ttk, messagebox

    cfgpath = folder / "config.yaml"
    cfg = yaml.safe_load(cfgpath.read_text(encoding="utf-8"))
    root = tk.Tk()
    root.title("FlipRadar 2.1 – Einstellungen")
    fields = [
        ("Telegram Bot-Token", "telegram", "token", True),
        ("Telegram Chat-ID", "telegram", "chat_id", False),
        ("eBay Produktions-App-ID", "ebay", "client_id", False),
        ("eBay Produktions-Cert-ID", "ebay", "client_secret", True),
        ("Apify API-Token (optional)", "apify", "token", True),
    ]
    entries = []
    for idx, (label, section, key, secret) in enumerate(fields):
        ttk.Label(root, text=label).grid(row=idx, column=0, sticky="w", padx=10, pady=5)
        box = ttk.Entry(root, width=55, show="*" if secret else "")
        box.grid(row=idx, column=1, padx=10, pady=5)
        box.insert(0, str((cfg.get(section) or {}).get(key) or ""))
        entries.append((section, key, box))
    numbers = []
    for idx, (label, key, default, factor) in enumerate(
        [
            ("Mindestgewinn auf den Einsatz (%)", "min_margin", 0.20, 100),
            ("Maximaler Kaufpreis (CHF)", "max_price_chf", 2000, 1),
            ("Zielintervall (Minuten)", "interval_minutes", 5, 1),
            ("Maximaler Gesamtpreis je Los (CHF)", "lot_budget_chf", 2000, 1),
            ("Gesamtkapital inkl. Bestand (CHF)", "portfolio_chf", 2000, 1),
            ("Mindest-Losrabatt (%)", "lot_discount", 0.30, 100),
            ("B-Ware Reserve je Einheit (CHF)", "b_reserve_chf", 20, 1),
            ("CHF je EUR", "eur_to_chf", 0.94, 1),
        ],
        start=len(fields),
    ):
        ttk.Label(root, text=label).grid(row=idx, column=0, sticky="w", padx=10, pady=5)
        box = ttk.Entry(root, width=18)
        box.grid(row=idx, column=1, sticky="w", padx=10, pady=5)
        box.insert(0, f"{cfg.get(key, default) * factor:g}")
        numbers.append((key, box, factor))

    def commit():
        import math

        try:
            values = {
                key: float(box.get().replace(",", ".")) / factor
                for key, box, factor in numbers
            }
            if (
                not all(
                    math.isfinite(v)
                    and (v >= 0 if k in {"lot_discount", "b_reserve_chf"} else v > 0)
                    for k, v in values.items()
                )
                or values["min_margin"] >= 5
                or values["lot_discount"] >= 1
                or not 1 <= values["interval_minutes"] <= 1440
            ):
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Eingaben prüfen",
                "Bitte gültige positive Zahlen eingeben. Intervall: 1 bis 1440 Minuten.",
            )
            return
        cfg.update(values)
        for section, key, box in entries:
            cfg.setdefault(section, {})[key] = box.get().strip()
        save(cfgpath, yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
        messagebox.showinfo("FlipRadar", "Gespeichert. Die Suche startet jetzt.")
        root.destroy()

    ttk.Button(root, text="Speichern und suchen", command=commit).grid(
        row=14, column=1, pady=12, sticky="e", padx=10
    )
    root.mainloop()
