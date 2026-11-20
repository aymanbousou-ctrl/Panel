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
        or (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FlipRadarV2")
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
        cfg = (
            yaml.safe_load(
                (old or ROOT / "config.example.yaml").read_text(encoding="utf-8-sig")
            )
            or {}
        )
        cfg.setdefault("ebay", {"client_id": "", "client_secret": ""})
        platforms = cfg.setdefault("platforms", ["ricardo", "tutti", "kleinanzeigen"])
        if "ebay" not in platforms:
            platforms.append("ebay")
        watch = old.parent / "watchlist.yaml" if old else ROOT / "watchlist.yaml"
        shutil.copyfile(
            watch if watch.is_file() else ROOT / "watchlist.yaml",
            tmp / "watchlist.yaml",
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
                    if "listings" in tables:
                        dest.execute(
                            "UPDATE listings SET product=NULL WHERE platform='ricardo'"
                        )
                    if "pending" in tables:
                        dest.execute("DELETE FROM pending WHERE key LIKE 'ricardo:%'")
                    dest.commit()
                finally:
                    dest.close()
                    source.close()
            if cfg.get("sales_csv"):
                shutil.copyfile(old.parent / cfg["sales_csv"], tmp / "sales.csv")
                cfg["sales_csv"] = "sales.csv"
            print("V1-Einstellungen uebernommen aus", old.parent)
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
    root.title("FlipRadar 2.0 – Einstellungen")
    fields = [
        ("Telegram Bot-Token", "telegram", "token", True),
        ("Telegram Chat-ID", "telegram", "chat_id", False),
        ("eBay Produktions-App-ID", "ebay", "client_id", False),
        ("eBay Produktions-Cert-ID", "ebay", "client_secret", True),
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
                not all(math.isfinite(v) and v > 0 for v in values.values())
                or values["min_margin"] >= 5
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
        row=9, column=1, pady=12, sticky="e", padx=10
    )
    root.mainloop()
