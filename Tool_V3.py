# Tool_V4.py
# pip install requests pandas pillow

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
from PIL import Image, ImageTk
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# Einstellungen
# ============================================================

STEAM_ID = "76561197962868893"

APPS = {
    "CS2": {"appid": 730, "contextid": 2},
    "Dota 2": {"appid": 570, "contextid": 2},
    "Team Fortress 2": {"appid": 440, "contextid": 2},
    "Steam Items / Trading Cards": {"appid": 753, "contextid": 6},
}

DB_FILE = "steam_inventory.db"

CURRENCY = 3
COUNTRY = "DE"

REQUEST_TIMEOUT = 8
MAX_PRICE_WORKERS = 4

ICON_SIZE = 56
DETAIL_SIZE = 320
HOVER_SIZE = 260

# Wichtig:
# Tabellenbilder bleiben aus, damit die GUI nicht einfriert.
# Detail- und Hover-Bilder bleiben aktiv.
SHOW_TABLE_ICONS = False


# ============================================================
# Hilfsfunktionen
# ============================================================

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
            icon_url TEXT,
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
            source TEXT,
            last_update REAL,
            UNIQUE(appid, item_name)
        )
    """)

    ensure_column(con, "inventory", "game", "TEXT")
    ensure_column(con, "inventory", "appid", "INTEGER")
    ensure_column(con, "inventory", "contextid", "INTEGER")
    ensure_column(con, "inventory", "item_name", "TEXT")
    ensure_column(con, "inventory", "type", "TEXT")
    ensure_column(con, "inventory", "market_link", "TEXT")
    ensure_column(con, "inventory", "icon_url", "TEXT")
    ensure_column(con, "inventory", "amount", "INTEGER")
    ensure_column(con, "inventory", "marketable", "INTEGER")
    ensure_column(con, "inventory", "tradable", "INTEGER")
    ensure_column(con, "inventory", "last_scan", "REAL")

    ensure_column(con, "prices", "appid", "INTEGER")
    ensure_column(con, "prices", "item_name", "TEXT")
    ensure_column(con, "prices", "sell_price", "TEXT")
    ensure_column(con, "prices", "buy_order", "TEXT")
    ensure_column(con, "prices", "sell_count", "TEXT")
    ensure_column(con, "prices", "buy_count", "TEXT")
    ensure_column(con, "prices", "price_number", "REAL")
    ensure_column(con, "prices", "source", "TEXT")
    ensure_column(con, "prices", "last_update", "REAL")

    con.commit()
    return con


def ensure_column(con, table, column, definition):
    cur = con.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]

    if column not in cols:
        try:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            con.commit()
        except sqlite3.OperationalError:
            pass


def parse_price(text):
    if not text:
        return 0.0

    if str(text) in ("Kein Preis", "Nicht geladen", "Nicht verfügbar", "Fehler"):
        return 0.0

    s = str(text)
    s = s.replace("€", "")
    s = s.replace("EUR", "")
    s = s.replace("--", "")
    s = s.replace("&nbsp;", "")
    s = s.replace(" ", "")
    s = s.strip()

    if "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")

    m = re.search(r"\d+(\.\d+)?", s)

    if not m:
        return 0.0

    try:
        return float(m.group())
    except Exception:
        return 0.0


def euro(value):
    try:
        return f"€{float(value):.2f}".replace(".", ",")
    except Exception:
        return "Kein Preis"


def market_link(appid, item):
    return f"https://steamcommunity.com/market/listings/{appid}/{quote(item, safe='')}"


def steam_icon_url(icon_url):
    if not icon_url:
        return ""

    if icon_url.startswith("http"):
        return icon_url

    return f"https://community.cloudflare.steamstatic.com/economy/image/{icon_url}"


def clean_int(value):
    try:
        s = str(value)
        s = re.sub(r"\D", "", s)
        return int(s) if s else 0
    except Exception:
        return 0


def request_headers(language="de"):
    if language == "en":
        accept_language = "en-US,en;q=0.9,de;q=0.8"
    else:
        accept_language = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"

    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
            "Gecko/20100101 Firefox/128.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "application/json,text/plain,*/*;q=0.8",
        "Accept-Language": accept_language,
        "Connection": "close",
    }


# ============================================================
# Steam Inventory
# ============================================================

def get_inventory_all(appid, contextid, stop_checker=None):
    all_assets = []
    all_descriptions = {}

    start_assetid = None

    while True:
        if stop_checker and stop_checker():
            break

        url = f"https://steamcommunity.com/inventory/{STEAM_ID}/{appid}/{contextid}"

        params = {
            "l": "english",
            "count": 5000,
        }

        if start_assetid:
            params["start_assetid"] = start_assetid

        r = requests.get(
            url,
            params=params,
            headers=request_headers("en"),
            timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()

        data = r.json()

        assets = data.get("assets", [])
        descriptions = data.get("descriptions", [])

        all_assets.extend(assets)

        for desc in descriptions:
            key = (str(desc.get("classid")), str(desc.get("instanceid")))
            all_descriptions[key] = desc

        if not data.get("more_items"):
            break

        start_assetid = data.get("last_assetid")

        if not start_assetid:
            break

        time.sleep(0.2)

    return {
        "assets": all_assets,
        "descriptions": list(all_descriptions.values())
    }


# ============================================================
# Preisparser
# ============================================================

def get_priceoverview(appid, item_name):
    try:
        url = "https://steamcommunity.com/market/priceoverview/"

        params = {
            "appid": appid,
            "currency": CURRENCY,
            "market_hash_name": item_name,
        }

        r = requests.get(
            url,
            params=params,
            headers=request_headers("de"),
            timeout=REQUEST_TIMEOUT
        )

        if r.status_code != 200:
            return None

        data = r.json()

        if not data.get("success"):
            return None

        price = data.get("lowest_price") or data.get("median_price")
        volume = data.get("volume", "")

        if not price:
            return None

        price_number = parse_price(price)

        if price_number <= 0:
            return None

        return {
            "sell_price": price,
            "buy_order": "Nicht verfügbar",
            "sell_count": str(volume),
            "buy_count": "",
            "price_number": price_number,
            "source": "priceoverview",
        }

    except Exception:
        return None


def parse_listing_prices_from_html(html):
    prices = []

    # Neue/React-Listings:
    # \"unPricePerUnit\":1391,\"unFeePerUnit\":208
    pattern_unit = (
        r'\\?"unPricePerUnit\\?"\s*:\s*(\d+)'
        r'.{0,300}?'
        r'\\?"unFeePerUnit\\?"\s*:\s*(\d+)'
    )

    for m in re.finditer(pattern_unit, html, flags=re.DOTALL):
        try:
            price_cents = int(m.group(1))
            fee_cents = int(m.group(2))
            total = (price_cents + fee_cents) / 100.0

            if total > 0:
                prices.append(total)
        except Exception:
            pass

    # Alternative:
    # \"unPrice\":1466,\"unFee\":219
    pattern_normal = (
        r'\\?"unPrice\\?"\s*:\s*(\d+)'
        r'.{0,300}?'
        r'\\?"unFee\\?"\s*:\s*(\d+)'
    )

    for m in re.finditer(pattern_normal, html, flags=re.DOTALL):
        try:
            price_cents = int(m.group(1))
            fee_cents = int(m.group(2))
            total = (price_cents + fee_cents) / 100.0

            if total > 0:
                prices.append(total)
        except Exception:
            pass

    # Alternative:
    # \"strSubtotal\":\"€16.85\"
    subtotal_matches = re.findall(
        r'\\?"strSubtotal\\?"\s*:\s*\\?"([^"\\]+)',
        html
    )

    for text in subtotal_matches:
        p = parse_price(text)

        if p > 0:
            prices.append(p)

    if not prices:
        return None

    # Kleinster gefundener Listingpreis
    lowest = min(prices)

    return {
        "sell_price": euro(lowest),
        "buy_order": "Nicht verfügbar",
        "sell_count": str(len(prices)),
        "buy_count": "",
        "price_number": lowest,
        "source": "listing_html",
    }


def parse_price_history_from_html(html):
    # Beispiel:
    # \"time\":1418860800,\"price_median\":0.1762,\"purchases\":158
    matches = re.findall(
        r'\\?"time\\?"\s*:\s*(\d+)'
        r'\s*,\s*\\?"price_median\\?"\s*:\s*([0-9.]+)'
        r'\s*,\s*\\?"purchases\\?"\s*:\s*(\d+)',
        html
    )

    if not matches:
        matches = re.findall(
            r'"time"\s*:\s*(\d+)'
            r'\s*,\s*"price_median"\s*:\s*([0-9.]+)'
            r'\s*,\s*"purchases"\s*:\s*(\d+)',
            html
        )

    parsed = []

    for t, price, purchases in matches:
        try:
            timestamp = int(t)
            price_value = float(price)
            volume = int(purchases)

            if price_value > 0:
                parsed.append((timestamp, price_value, volume))
        except Exception:
            pass

    if not parsed:
        return None

    parsed.sort(key=lambda x: x[0])
    last_time, last_price, last_volume = parsed[-1]

    return {
        "sell_price": euro(last_price),
        "buy_order": "Nicht verfügbar",
        "sell_count": str(last_volume),
        "buy_count": "",
        "price_number": last_price,
        "source": "price_median",
    }


def get_market_page_price(appid, item_name):
    try:
        url = market_link(appid, item_name) + "?l=english"

        r = requests.get(
            url,
            headers=request_headers("en"),
            timeout=REQUEST_TIMEOUT
        )

        if r.status_code != 200:
            return None

        html = r.text

        listing_data = parse_listing_prices_from_html(html)

        if listing_data and listing_data["price_number"] > 0:
            return listing_data

        history_data = parse_price_history_from_html(html)

        if history_data and history_data["price_number"] > 0:
            return history_data

        return None

    except Exception:
        return None


def get_best_price(appid, item_name):
    # 1. Schneller API-Endpunkt
    data = get_priceoverview(appid, item_name)

    if data and data["price_number"] > 0:
        return data

    # 2. Neue Steam-Market-Seite / React-HTML
    data = get_market_page_price(appid, item_name)

    if data and data["price_number"] > 0:
        return data

    return {
        "sell_price": "Kein Preis",
        "buy_order": "Nicht verfügbar",
        "sell_count": "",
        "buy_count": "",
        "price_number": 0.0,
        "source": "none",
    }


# ============================================================
# GUI
# ============================================================

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Steam Inventory Manager Tool V4")
        self.root.geometry("1650x900")

        self.rows = []
        self.image_cache = {}
        self.hover_window = None
        self.last_hover_item = None
        self.sort_state = {}

        self.stop_event = threading.Event()
        self.task_id = 0
        self.executor = None

        self.setup_style()
        self.setup_ui()

        db().close()

    # --------------------------------------------------------

    def setup_style(self):
        self.root.configure(bg="#111111")

        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background="#111111", foreground="#ffffff")
        style.configure("TLabel", background="#111111", foreground="#ffffff")
        style.configure("TFrame", background="#111111")

        style.configure(
            "TButton",
            background="#2d2d2d",
            foreground="#ffffff",
            padding=6
        )

        style.map(
            "TButton",
            background=[("active", "#3d6fb6")],
            foreground=[("active", "#ffffff")]
        )

        style.configure(
            "TCombobox",
            fieldbackground="#2b2b2b",
            background="#2b2b2b",
            foreground="#ffffff",
            arrowcolor="#ffffff"
        )

        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#2b2b2b")],
            foreground=[("readonly", "#ffffff")]
        )

        style.configure(
            "TEntry",
            fieldbackground="#2b2b2b",
            foreground="#ffffff"
        )

        style.configure(
            "Treeview",
            background="#222222",
            foreground="#ffffff",
            fieldbackground="#222222",
            rowheight=40
        )

        style.configure(
            "Treeview.Heading",
            background="#333333",
            foreground="#ffffff",
            font=("Segoe UI", 10, "bold")
        )

        style.map(
            "Treeview",
            background=[("selected", "#4b4b4b")],
            foreground=[("selected", "#ffffff")]
        )

    # --------------------------------------------------------

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
            width=32
        )
        self.combo.pack(side="left", padx=8)

        ttk.Button(top, text="Inventory scannen", command=self.start_scan_inventory).pack(side="left", padx=4)
        ttk.Button(top, text="STOP", command=self.stop_current_task).pack(side="left", padx=4)
        ttk.Button(top, text="Aus DB laden", command=self.load_from_db).pack(side="left", padx=4)
        ttk.Button(top, text="Preise aktualisieren", command=self.start_update_prices).pack(side="left", padx=4)
        ttk.Button(top, text="Preise neu erzwingen", command=self.start_force_update_prices).pack(side="left", padx=4)
        ttk.Button(top, text="Market öffnen", command=self.open_market).pack(side="left", padx=4)
        ttk.Button(top, text="CSV Export", command=self.export_csv).pack(side="left", padx=4)

        search_frame = ttk.Frame(self.root)
        search_frame.pack(fill="x", padx=10)

        ttk.Label(search_frame, text="Suche:").pack(side="left")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.apply_filter())

        ttk.Entry(
            search_frame,
            textvariable=self.search_var,
            width=55
        ).pack(side="left", padx=8)

        self.total_label = ttk.Label(search_frame, text="Gesamtwert: €0,00")
        self.total_label.pack(side="right")

        self.status = ttk.Label(self.root, text="Bereit")
        self.status.pack(fill="x", padx=10, pady=5)

        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=10, pady=10)

        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True)

        right = ttk.Frame(main)
        right.pack(side="right", fill="y", padx=(12, 0))

        cols = (
            "Spiel",
            "Item",
            "Typ",
            "Anzahl",
            "Preis",
            "Quelle",
            "Volumen",
            "Gesamt"
        )

        self.tree = ttk.Treeview(left, columns=cols, show="tree headings")

        self.tree.heading("#0", text="Bild")
        self.tree.column("#0", width=70, stretch=False, anchor="center")

        for c in cols:
            self.tree.heading(c, text=c, command=lambda col=c: self.sort_by_column(col))

        self.tree.column("Spiel", width=120)
        self.tree.column("Item", width=430)
        self.tree.column("Typ", width=220)
        self.tree.column("Anzahl", width=80)
        self.tree.column("Preis", width=110)
        self.tree.column("Quelle", width=130)
        self.tree.column("Volumen", width=90)
        self.tree.column("Gesamt", width=110)

        self.tree.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")

        self.tree.bind("<Double-1>", lambda e: self.open_market())
        self.tree.bind("<<TreeviewSelect>>", self.update_detail)
        self.tree.bind("<Motion>", self.on_tree_motion)
        self.tree.bind("<Leave>", self.hide_hover)

        self.detail_title = ttk.Label(
            right,
            text="Detailansicht",
            font=("Segoe UI", 14, "bold")
        )
        self.detail_title.pack(pady=(0, 10))

        self.detail_image_label = tk.Label(right, bg="#111111")
        self.detail_image_label.pack(pady=8)

        self.detail_text = tk.Text(
            right,
            width=42,
            height=24,
            bg="#1b1b1b",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=("Segoe UI", 10)
        )
        self.detail_text.pack(fill="y")

    # --------------------------------------------------------

    def set_status(self, text):
        self.root.after(0, lambda: self.status.config(text=text))

    def show_error(self, title, text):
        self.root.after(0, lambda: messagebox.showerror(title, text))

    def stop_current_task(self):
        self.stop_event.set()
        self.task_id += 1

        if self.executor:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

            self.executor = None

        self.set_status("Stop angefordert...")

    def new_task(self):
        self.stop_current_task()
        time.sleep(0.05)

        self.stop_event.clear()
        self.task_id += 1

        return self.task_id

    def is_stopped(self, task_id):
        return self.stop_event.is_set() or task_id != self.task_id

    # --------------------------------------------------------

    def get_image(self, url, size):
        if not url:
            return None

        key = f"{url}|{size}"

        if key in self.image_cache:
            return self.image_cache[key]

        try:
            r = requests.get(
                url,
                headers=request_headers("de"),
                timeout=REQUEST_TIMEOUT
            )
            r.raise_for_status()

            img = Image.open(BytesIO(r.content)).convert("RGBA")
            img.thumbnail((size, size))

            canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

            x = (size - img.width) // 2
            y = (size - img.height) // 2

            canvas.paste(img, (x, y), img)

            photo = ImageTk.PhotoImage(canvas)
            self.image_cache[key] = photo

            return photo

        except Exception:
            return None

    # --------------------------------------------------------
    # Scan
    # --------------------------------------------------------

    def start_scan_inventory(self):
        game = self.game_var.get()
        task_id = self.new_task()

        threading.Thread(
            target=self.scan_inventory,
            args=(task_id, game),
            daemon=True
        ).start()

    def scan_inventory(self, task_id, game):
        appid = APPS[game]["appid"]
        contextid = APPS[game]["contextid"]

        self.set_status(f"Scanne Inventory: {game}")

        try:
            inv = get_inventory_all(
                appid,
                contextid,
                stop_checker=lambda: self.is_stopped(task_id)
            )
        except Exception as e:
            if not self.is_stopped(task_id):
                self.show_error("Fehler beim Inventory-Scan", str(e))
            return

        if self.is_stopped(task_id):
            self.set_status("Scan gestoppt")
            return

        descriptions = inv.get("descriptions", [])
        assets = inv.get("assets", [])

        counts = {}

        for asset in assets:
            key = (str(asset.get("classid")), str(asset.get("instanceid")))

            try:
                amount = int(asset.get("amount", 1))
            except Exception:
                amount = 1

            counts[key] = counts.get(key, 0) + amount

        con = db()
        count = 0
        seen = set()

        try:
            for item in descriptions:
                if self.is_stopped(task_id):
                    self.set_status("Scan gestoppt")
                    return

                marketable = item.get("marketable", 0)

                if not marketable:
                    continue

                name = item.get("market_hash_name")

                if not name:
                    continue

                if name in seen:
                    continue

                seen.add(name)

                key = (str(item.get("classid")), str(item.get("instanceid")))
                amount = counts.get(key, 1)
                icon = steam_icon_url(item.get("icon_url", ""))

                con.execute("""
                    INSERT OR REPLACE INTO inventory
                    (
                        game,
                        appid,
                        contextid,
                        item_name,
                        type,
                        market_link,
                        icon_url,
                        amount,
                        marketable,
                        tradable,
                        last_scan
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    game,
                    appid,
                    contextid,
                    name,
                    item.get("type", ""),
                    market_link(appid, name),
                    icon,
                    amount,
                    1 if item.get("marketable") else 0,
                    1 if item.get("tradable") else 0,
                    time.time()
                ))

                count += 1

            con.commit()

        finally:
            con.close()

        if self.is_stopped(task_id):
            self.set_status("Scan gestoppt")
            return

        self.set_status(f"Inventory gespeichert: {count} Items")
        self.root.after(0, self.load_from_db)

    # --------------------------------------------------------
    # Preise
    # --------------------------------------------------------

    def start_update_prices(self):
        game = self.game_var.get()
        task_id = self.new_task()

        threading.Thread(
            target=self.update_prices,
            args=(task_id, game, False),
            daemon=True
        ).start()

    def start_force_update_prices(self):
        game = self.game_var.get()
        task_id = self.new_task()

        threading.Thread(
            target=self.update_prices,
            args=(task_id, game, True),
            daemon=True
        ).start()

    def get_inventory_rows_for_game(self, game):
        appid = APPS[game]["appid"]

        con = db()

        try:
            cur = con.execute("""
                SELECT
                    game,
                    appid,
                    item_name,
                    type,
                    amount
                FROM inventory
                WHERE appid = ?
                ORDER BY item_name
            """, (appid,))

            rows = []

            for r in cur.fetchall():
                rows.append({
                    "Spiel": r[0],
                    "AppID": r[1],
                    "Item": r[2],
                    "Typ": r[3],
                    "Anzahl": r[4] or 1,
                })

            return rows

        finally:
            con.close()

    def update_prices(self, task_id, game, force):
        rows = self.get_inventory_rows_for_game(game)
        total = len(rows)

        if not rows:
            self.set_status("Keine Items für Preisupdate gefunden")
            return

        self.set_status(f"Starte Preisupdate: {total} Items")

        def worker(row):
            if self.is_stopped(task_id):
                return None

            appid = row["AppID"]
            item = row["Item"]

            if not force:
                con_local = db()

                try:
                    old_price = con_local.execute("""
                        SELECT sell_price, price_number
                        FROM prices
                        WHERE appid = ? AND item_name = ?
                    """, (appid, item)).fetchone()
                finally:
                    con_local.close()

                if old_price:
                    old_text = old_price[0]
                    old_number = old_price[1] or 0

                    if old_text not in ("Kein Preis", "Nicht geladen", "", None) and old_number > 0:
                        return None

            data = get_best_price(appid, item)

            return appid, item, data

        done = 0

        executor = ThreadPoolExecutor(max_workers=MAX_PRICE_WORKERS)
        self.executor = executor

        futures = [executor.submit(worker, row) for row in rows]

        con = db()

        try:
            for future in as_completed(futures):
                if self.is_stopped(task_id):
                    self.set_status("Preisupdate gestoppt")
                    break

                done += 1
                self.set_status(f"Preisupdate {done}/{total}")

                try:
                    result = future.result()
                except Exception:
                    continue

                if not result:
                    continue

                appid, item, data = result

                con.execute("""
                    INSERT OR REPLACE INTO prices
                    (
                        appid,
                        item_name,
                        sell_price,
                        buy_order,
                        sell_count,
                        buy_count,
                        price_number,
                        source,
                        last_update
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    appid,
                    item,
                    data["sell_price"],
                    data["buy_order"],
                    data["sell_count"],
                    data["buy_count"],
                    data["price_number"],
                    data["source"],
                    time.time()
                ))

                con.commit()

        finally:
            con.close()

            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

            if self.executor is executor:
                self.executor = None

        if self.is_stopped(task_id):
            self.set_status("Preisupdate gestoppt")
            return

        self.set_status("Preise aktualisiert")
        self.root.after(0, self.load_from_db)

    # --------------------------------------------------------
    # DB laden / Tabelle
    # --------------------------------------------------------

    def load_from_db(self):
        game = self.game_var.get()
        appid = APPS[game]["appid"]

        con = db()

        try:
            cur = con.execute("""
                SELECT
                    i.game,
                    i.item_name,
                    i.type,
                    i.amount,
                    i.market_link,
                    i.icon_url,
                    p.sell_price,
                    p.buy_order,
                    p.sell_count,
                    p.buy_count,
                    COALESCE(p.price_number, 0),
                    COALESCE(p.source, '')
                FROM inventory i
                LEFT JOIN prices p
                    ON i.appid = p.appid
                    AND i.item_name = p.item_name
                WHERE i.appid = ?
                ORDER BY i.item_name
            """, (appid,))

            self.rows = []

            for r in cur.fetchall():
                price_number = r[10] or 0.0
                amount = r[3] or 1
                total = round(price_number * amount, 2)

                source = r[11] or "Nicht geladen"

                self.rows.append({
                    "Spiel": r[0],
                    "Item": r[1],
                    "Typ": r[2],
                    "Anzahl": amount,
                    "MarketLink": r[4],
                    "IconURL": r[5] or "",
                    "Preis": r[6] or "Nicht geladen",
                    "Quelle": source,
                    "Volumen": r[8] or "",
                    "BuyOrder": r[7] or "Nicht verfügbar",
                    "BuyAnzahl": r[9] or "",
                    "PreisZahl": price_number,
                    "Gesamt": total,
                })

        finally:
            con.close()

        self.reload_table()

    def reload_table(self):
        self.tree.delete(*self.tree.get_children())

        q = self.search_var.get().lower().strip()
        total_value = 0.0

        for idx, row in enumerate(self.rows):
            if q and q not in row["Item"].lower() and q not in row["Typ"].lower():
                continue

            total_value += row["Gesamt"]

            img = None

            if SHOW_TABLE_ICONS:
                img = self.get_image(row["IconURL"], ICON_SIZE)

            iid = str(idx)

            values = (
                row["Spiel"],
                row["Item"],
                row["Typ"],
                row["Anzahl"],
                row["Preis"],
                row["Quelle"],
                row["Volumen"],
                f"{row['Gesamt']:.2f}",
            )

            # WICHTIG:
            # values=values muss hier explizit stehen.
            # Genau das hat deinen TclError ausgelöst.
            self.tree.insert(
                "",
                "end",
                iid=iid,
                image=img,
                values=values
            )

        self.total_label.config(
            text=f"Gesamtwert: €{total_value:.2f}".replace(".", ",")
        )

    # --------------------------------------------------------
    # Sortierung / Filter
    # --------------------------------------------------------

    def sort_by_column(self, col):
        reverse = self.sort_state.get(col, False)

        numeric = {"Anzahl", "Volumen", "Gesamt", "Preis"}

        if col in numeric:
            def key_func(x):
                if col == "Gesamt":
                    return float(x.get("Gesamt", 0))

                if col == "Preis":
                    return parse_price(x.get("Preis", "0"))

                if col == "Volumen":
                    return clean_int(x.get("Volumen", "0"))

                return clean_int(x.get(col, "0"))
        else:
            def key_func(x):
                return str(x.get(col, "")).lower()

        self.rows.sort(key=key_func, reverse=reverse)
        self.sort_state[col] = not reverse

        self.reload_table()

    def apply_filter(self):
        self.reload_table()

    # --------------------------------------------------------
    # Detail / Hover
    # --------------------------------------------------------

    def get_row_by_iid(self, iid):
        try:
            return self.rows[int(iid)]
        except Exception:
            return None

    def update_detail(self, event=None):
        sel = self.tree.selection()

        if not sel:
            return

        row = self.get_row_by_iid(sel[0])

        if not row:
            return

        img = self.get_image(row["IconURL"], DETAIL_SIZE)

        self.detail_image_label.config(image=img)
        self.detail_image_label.image = img

        self.detail_text.delete("1.0", "end")

        self.detail_text.insert("end", f"{row['Item']}\n\n")
        self.detail_text.insert("end", f"Spiel: {row['Spiel']}\n")
        self.detail_text.insert("end", f"Typ: {row['Typ']}\n")
        self.detail_text.insert("end", f"Anzahl: {row['Anzahl']}\n\n")
        self.detail_text.insert("end", f"Preis: {row['Preis']}\n")
        self.detail_text.insert("end", f"Quelle: {row['Quelle']}\n")
        self.detail_text.insert("end", f"Volumen: {row['Volumen']}\n")
        self.detail_text.insert(
            "end",
            f"Gesamt: €{row['Gesamt']:.2f}\n\n".replace(".", ",")
        )
        self.detail_text.insert("end", f"Market:\n{row['MarketLink']}\n")

    def on_tree_motion(self, event):
        iid = self.tree.identify_row(event.y)

        if not iid:
            self.hide_hover()
            return

        if iid == self.last_hover_item:
            return

        self.last_hover_item = iid

        row = self.get_row_by_iid(iid)

        if row:
            self.show_hover(row)

    def show_hover(self, row):
        self.hide_hover()

        self.hover_window = tk.Toplevel(self.root)
        self.hover_window.wm_overrideredirect(True)
        self.hover_window.configure(bg="#0f0f0f")

        x = self.root.winfo_pointerx() + 20
        y = self.root.winfo_pointery() + 20

        self.hover_window.geometry(f"+{x}+{y}")

        frame = tk.Frame(self.hover_window, bg="#0f0f0f", bd=2, relief="solid")
        frame.pack()

        tk.Label(
            frame,
            text=row["Item"],
            bg="#0f0f0f",
            fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            wraplength=320,
            justify="center"
        ).pack(padx=10, pady=(8, 4))

        img = self.get_image(row["IconURL"], HOVER_SIZE)

        img_label = tk.Label(frame, image=img, bg="#0f0f0f")
        img_label.image = img
        img_label.pack(padx=10, pady=6)

        text = (
            f"{row['Spiel']}\n"
            f"{row['Typ']}\n\n"
            f"Preis: {row['Preis']}\n"
            f"Quelle: {row['Quelle']}\n"
            f"Volumen: {row['Volumen']}"
        )

        tk.Label(
            frame,
            text=text,
            bg="#0f0f0f",
            fg="#dddddd",
            font=("Segoe UI", 10),
            justify="center"
        ).pack(padx=10, pady=(0, 10))

    def hide_hover(self, event=None):
        self.last_hover_item = None

        if self.hover_window:
            self.hover_window.destroy()
            self.hover_window = None

    # --------------------------------------------------------
    # Aktionen
    # --------------------------------------------------------

    def open_market(self):
        sel = self.tree.selection()

        if not sel:
            messagebox.showinfo("Hinweis", "Bitte Item auswählen.")
            return

        row = self.get_row_by_iid(sel[0])

        if row:
            webbrowser.open(row["MarketLink"])

    def export_csv(self):
        if not self.rows:
            messagebox.showinfo("Hinweis", "Keine Daten.")
            return

        df = pd.DataFrame(self.rows)

        df.to_csv(
            "steam_inventory_manager_export.csv",
            index=False,
            encoding="utf-8-sig"
        )

        messagebox.showinfo(
            "Export",
            "Gespeichert als steam_inventory_manager_export.csv"
        )


# ============================================================
# Start
# ============================================================

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()