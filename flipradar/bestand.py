"""Enter a purchase or individual resale without editing CSV by hand."""

import csv
import os
import sqlite3
from datetime import date
from decimal import Decimal
from uuid import uuid4

from .handel import INVENTORY_FIELDS as FIELDS


def cents(raw):
    value = Decimal(str(raw).replace(",", "."))
    if not value.is_finite() or value < 0 or value != value.quantize(Decimal(".01")):
        raise ValueError("Betrag in CHF mit höchstens zwei Nachkommastellen eingeben.")
    return int(value * 100)


def add_purchase(rows, product, day, qty, cost):
    day = date.fromisoformat(day)
    qty = int(qty)
    total = cents(cost)
    if not product.strip() or not 1 <= qty <= 100 or total < qty or day > date.today():
        raise ValueError("Produkt, Datum, Menge (1–100) und Gesamtkosten prüfen.")
    per, rest = divmod(total, qty)
    for i in range(qty):
        rows.append(
            dict(
                zip(
                    FIELDS,
                    [
                        uuid4().hex,
                        product,
                        day.isoformat(),
                        f"{(per + (i < rest)) / 100:.2f}",
                        "",
                        "",
                    ],
                )
            )
        )


def sell(row, day, net):
    when = date.fromisoformat(day)
    if (
        row["Verkaufstag"]
        or not date.fromisoformat(row["Einkaufstag"]) <= when <= date.today()
    ):
        raise ValueError("Verkaufsdatum und Verfügbarkeit prüfen.")
    revenue = cents(net)
    row.update(Verkaufstag=when.isoformat(), Nettoerloes_CHF=f"{revenue / 100:.2f}")


def edit(folder, products):
    import tkinter as tk
    from tkinter import ttk, messagebox
    from .handel import inventory
    from .discovery import expanded, init_discovery
    from .db import Store

    path = folder / "Bestand.csv"
    db = Store(str(folder / "flipradar.db"))
    try:
        init_discovery(db)
        names = [p.name for p in expanded(db, products, [])]
    finally:
        db.close()
    lock = sqlite3.connect(folder / "bestand.lock.sqlite", timeout=0)
    try:
        lock.execute("BEGIN EXCLUSIVE")
        root = tk.Tk()
        root.title("FlipRadar – Käufe und Verkäufe")
        box = ttk.Frame(root, padding=14)
        box.grid()
        inventory(path)
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        product = ttk.Combobox(box, values=sorted(names), width=38, state="readonly")

        def field(label, row, widget=None, value=""):
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", pady=4)
            widget = widget if widget is not None else ttk.Entry(box, width=25)
            widget.grid(row=row, column=1, sticky="w")
            if value:
                widget.insert(0, value)
            return widget

        field("Produkt", 0, product)
        bought = field("Einkaufsdatum (JJJJ-MM-TT)", 1, value=date.today().isoformat())
        quantity = field("Anzahl gleicher Einheiten", 2, value="1")
        cost = field("Gesamte tatsächliche Einkaufskosten (CHF)", 3)
        tree = ttk.Treeview(
            box,
            columns=("product", "day", "price"),
            show="headings",
            height=8,
            selectmode="browse",
        )
        for k, label in zip(
            tree["columns"], ("Offene Einheit", "Einkaufsdatum", "Einstand CHF")
        ):
            tree.heading(k, text=label)
        tree.grid(row=5, column=0, columnspan=2, pady=10)
        sold = field("Verkaufsdatum (JJJJ-MM-TT)", 6, value=date.today().isoformat())
        net = field("Erlös nach Verkaufskosten für diese Einheit (CHF)", 7)

        def refresh():
            tree.delete(*tree.get_children())
            for r in rows:
                if not r["Verkaufstag"]:
                    tree.insert(
                        "",
                        "end",
                        iid=r["ID"],
                        values=(r["Produkt"], r["Einkaufstag"], r["Einstand_CHF"]),
                    )

        def commit(is_sale):
            edited = [r.copy() for r in rows]
            try:
                if is_sale:
                    if not tree.selection():
                        raise ValueError("Eine offene Einheit in der Liste wählen.")
                    row = next(r for r in edited if r["ID"] == tree.selection()[0])
                    sell(row, sold.get(), net.get())
                else:
                    add_purchase(
                        edited, product.get(), bought.get(), quantity.get(), cost.get()
                    )
                tmp = path.with_suffix(".new")
                with tmp.open("w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=FIELDS, delimiter=";")
                    writer.writeheader()
                    writer.writerows(edited)
                os.replace(tmp, path)
            except (ValueError, ArithmeticError, OSError) as exc:
                messagebox.showerror("Eintrag prüfen", str(exc))
                return
            rows[:] = edited
            (net if is_sale else cost).delete(0, "end")
            refresh()

        ttk.Button(box, text="Einkauf eintragen", command=lambda: commit(False)).grid(
            row=4, column=1, sticky="w"
        )
        ttk.Button(
            box,
            text="Verkauf der gewählten Einheit eintragen",
            command=lambda: commit(True),
        ).grid(row=8, column=1, sticky="w")
        refresh()
        root.mainloop()
    finally:
        lock.close()
