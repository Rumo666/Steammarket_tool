import tkinter as tk
from tkinter import ttk, messagebox
import requests
import pandas as pd
import threading
import time
import webbrowser
import re
import sqlite3
from urllib.parse import quote
from playwright.sync_api import sync_playwright

STEAM_ID = "76561197962868893"

APPS = {
    "CS2": {"appid": 730, "contextid": 2},
    "Dota 2": {"appid": 570, "contextid": 2},
    "Team Fortress 2": {"appid": 440, "contextid": 2},
    "Steam Items / Trading Cards": {"appid": 753, "contextid": 6},
}

DB_FILE = "steam_inventory.db"
CACHE_HOURS = 24


def db():
    con = sqlite3.connect(DB_FILE)
    con.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game TEXT,
            appid INTEGER,
            contextid INTEGER,
            item_name TEXT,
            type TEXT,
            market_link TEXT,
            amount INTEGER,
            marketable INTEGER,
            tradable INTEGER,
            last_scan REAL,
            UNIQUE(appid, item_name)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appid INTEGER,
            item_name TEXT,
            sell_price TEXT,
            buy_order TEXT,
            sell_count TEXT,
            buy_count TEXT,
            price_number REAL,
            last_update REAL,
            UNIQUE(appid, item_name)
        )
    """)
    con.commit()
    return con


def parse_price(text):
    if not text or text == "Kein Preis":
        return 0.0
    cleaned = str(text).replace("€", "").replace(".", "").replace(",", ".").strip()
    m = re.search(r"\d+(\.\d+)?", cleaned)
    return float(m.group()) if m else 0.0


def market_link(appid, item):
    return f"https://steamcommunity.com/market/listings/{appid}/{quote(item)}"


def get_inventory(appid, contextid):
    url = f"https://steamcommunity.com/inventory/{STEAM_ID}/{appid}/{contextid}"
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    return r.json()


class MarketBrowser:
    def __init__(self):
        self.p = sync_playwright().start()
        self.browser = self.p.chromium.launch(headless=True)
        self.page = self.browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"
        )

    def close(self):
        self.browser.close()
        self.p.stop()

    def read(self, url):
        try:
            self.page.goto(url, wait_until="networkidle", timeout=45000)
            time.sleep(2)
            text = self.page.inner_text("body")

            sell_price = "Kein Preis"
            buy_order = "Kein Preis"
            sell_count = ""
            buy_count = ""

            m = re.search(r"Starting at:\s*(€\s?[0-9,.]+)", text)
            if m:
                sell_price = m.group(1).replace(" ", "")

            m = re.search(r"(\d+)\s+for sale", text)
            if m:
                sell_count = m.group(1)

            m = re.search(r"(\d+)\s+requests to buy at\s*(€\s?[0-9,.]+)", text)
            if m:
                buy_count = m.group(1)
                buy_order = m.group(2).replace(" ", "")

            return {
                "sell_price": sell_price,
                "buy_order": buy_order,
                "sell_count": sell_count,
                "buy_count": buy_count,
                "price_number": parse_price(sell_price),
            }

        except Exception:
            return {
                "sell_price": "Kein Preis",
                "buy_order": "Kein Preis",
                "sell_count": "",
                "buy_count": "",
                "price_number": 0.0,
            }


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Steam Inventory Manager V2")
        self.root.geometry("1450x760")
        self.rows = []
        self.setup_style()
        self.setup_ui()
        db().close()

    def setup_style(self):
        self.root.configure(bg="#1e1e1e")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background="#1e1e1e", foreground="white")
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b")
        style.configure("Treeview.Heading", background="#3a3a3a", foreground="white")
        style.map("Treeview", background=[("selected", "#555555")])

    def setup_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Spiel:").pack(side="left")

        self.game_var = tk.StringVar(value="CS2")
        self.combo = ttk.Combobox(
            top,
            textvariable=self.game_var,
            values=list(APPS.keys()),
            state="readonly",
            width=30
        )
        self.combo.pack(side="left", padx=8)

        ttk.Button(top, text="Inventory scannen", command=self.start_scan_inventory).pack(side="left", padx=4)
        ttk.Button(top, text="Aus DB laden", command=self.load_from_db).pack(side="left", padx=4)
        ttk.Button(top, text="Preise aktualisieren", command=self.start_update_prices).pack(side="left", padx=4)
        ttk.Button(top, text="Nach Preis sortieren", command=self.sort_price).pack(side="left", padx=4)
        ttk.Button(top, text="Market öffnen", command=self.open_market).pack(side="left", padx=4)
        ttk.Button(top, text="CSV Export", command=self.export_csv).pack(side="left", padx=4)

        search_frame = ttk.Frame(self.root)
        search_frame.pack(fill="x", padx=10)

        ttk.Label(search_frame, text="Suche:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.apply_filter())
        ttk.Entry(search_frame, textvariable=self.search_var, width=50).pack(side="left", padx=8)

        self.total_label = ttk.Label(search_frame, text="Gesamtwert: €0,00")
        self.total_label.pack(side="right")

        self.status = ttk.Label(self.root, text="Bereit")
        self.status.pack(fill="x", padx=10, pady=5)

        cols = (
            "Spiel", "Item", "Typ", "Anzahl",
            "SellPreis", "BuyOrder", "SellAnzahl", "BuyAnzahl",
            "Gesamt", "MarketLink"
        )

        self.tree = ttk.Treeview(self.root, columns=cols, show="headings")

        for c in cols:
            self.tree.heading(c, text=c)

        self.tree.column("Spiel", width=150)
        self.tree.column("Item", width=370)
        self.tree.column("Typ", width=180)
        self.tree.column("Anzahl", width=70)
        self.tree.column("SellPreis", width=100)
        self.tree.column("BuyOrder", width=100)
        self.tree.column("SellAnzahl", width=90)
        self.tree.column("BuyAnzahl", width=90)
        self.tree.column("Gesamt", width=90)
        self.tree.column("MarketLink", width=330)

        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        sb = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda e: self.open_market())

    def set_status(self, text):
        self.root.after(0, lambda: self.status.config(text=text))

    def start_scan_inventory(self):
        threading.Thread(target=self.scan_inventory, daemon=True).start()

    def scan_inventory(self):
        game = self.game_var.get()
        appid = APPS[game]["appid"]
        contextid = APPS[game]["contextid"]

        self.set_status(f"Scanne Inventory: {game}")

        try:
            inv = get_inventory(appid, contextid)
        except Exception as e:
            messagebox.showerror("Fehler", str(e))
            return

        descs = inv.get("descriptions", [])
        con = db()
        count = 0
        seen = set()

        for item in descs:
            if item.get("marketable", 0) != 1:
                continue

            name = item.get("market_hash_name")
            if not name or name in seen:
                continue

            seen.add(name)

            con.execute("""
                INSERT OR REPLACE INTO inventory
                (game, appid, contextid, item_name, type, market_link, amount,
                 marketable, tradable, last_scan)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                game, appid, contextid, name, item.get("type", ""),
                market_link(appid, name), 1,
                item.get("marketable", 0), item.get("tradable", 0),
                time.time()
            ))

            count += 1

        con.commit()
        con.close()

        self.set_status(f"Inventory gespeichert: {count} Items")
        self.load_from_db()

    def load_from_db(self):
        game = self.game_var.get()
        appid = APPS[game]["appid"]

        con = db()
        cur = con.execute("""
            SELECT i.game, i.item_name, i.type, i.amount, i.market_link,
                   p.sell_price, p.buy_order, p.sell_count, p.buy_count,
                   COALESCE(p.price_number, 0)
            FROM inventory i
            LEFT JOIN prices p
            ON i.appid = p.appid AND i.item_name = p.item_name
            WHERE i.appid = ?
            ORDER BY i.item_name
        """, (appid,))

        self.rows = []

        for r in cur.fetchall():
            price_number = r[9] or 0
            amount = r[3] or 1
            total = round(price_number * amount, 2)

            self.rows.append({
                "Spiel": r[0],
                "Item": r[1],
                "Typ": r[2],
                "Anzahl": amount,
                "MarketLink": r[4],
                "SellPreis": r[5] or "Nicht geladen",
                "BuyOrder": r[6] or "Nicht geladen",
                "SellAnzahl": r[7] or "",
                "BuyAnzahl": r[8] or "",
                "PreisZahl": price_number,
                "Gesamt": total,
            })

        con.close()
        self.reload_table()

    def start_update_prices(self):
        threading.Thread(target=self.update_prices, daemon=True).start()

    def update_prices(self):
        if not self.rows:
            self.load_from_db()

        browser = MarketBrowser()
        con = db()

        try:
            for idx, row in enumerate(self.rows, 1):
                self.set_status(f"Lese Market {idx}/{len(self.rows)}: {row['Item']}")

                appid = APPS[row["Spiel"]]["appid"]
                item = row["Item"]

                old = con.execute("""
                    SELECT last_update FROM prices
                    WHERE appid = ? AND item_name = ?
                """, (appid, item)).fetchone()

                if old:
                    age = (time.time() - old[0]) / 3600
                    if age < CACHE_HOURS:
                        continue

                data = browser.read(row["MarketLink"])

                con.execute("""
                    INSERT OR REPLACE INTO prices
                    (appid, item_name, sell_price, buy_order,
                     sell_count, buy_count, price_number, last_update)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    appid, item,
                    data["sell_price"], data["buy_order"],
                    data["sell_count"], data["buy_count"],
                    data["price_number"], time.time()
                ))

                con.commit()
                time.sleep(1.5)

        finally:
            con.close()
            browser.close()

        self.set_status("Preise aktualisiert")
        self.load_from_db()

    def reload_table(self):
        self.tree.delete(*self.tree.get_children())

        q = self.search_var.get().lower().strip()
        total_value = 0.0

        for row in self.rows:
            if q and q not in row["Item"].lower() and q not in row["Typ"].lower():
                continue

            total_value += row["Gesamt"]

            self.tree.insert("", "end", values=(
                row["Spiel"],
                row["Item"],
                row["Typ"],
                row["Anzahl"],
                row["SellPreis"],
                row["BuyOrder"],
                row["SellAnzahl"],
                row["BuyAnzahl"],
                f"{row['Gesamt']:.2f}",
                row["MarketLink"],
            ))

        self.total_label.config(
            text=f"Gesamtwert: €{total_value:.2f}".replace(".", ",")
        )

    def apply_filter(self):
        self.reload_table()

    def sort_price(self):
        self.rows.sort(key=lambda x: x["Gesamt"], reverse=True)
        self.reload_table()
        self.set_status("Nach Preis sortiert")

    def open_market(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Hinweis", "Bitte Item auswählen.")
            return
        values = self.tree.item(sel[0], "values")
        webbrowser.open(values[9])

    def export_csv(self):
        if not self.rows:
            messagebox.showinfo("Hinweis", "Keine Daten.")
            return

        df = pd.DataFrame(self.rows)
        df.to_csv("steam_inventory_manager_export.csv", index=False, encoding="utf-8-sig")
        messagebox.showinfo("Export", "Gespeichert als steam_inventory_manager_export.csv")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()