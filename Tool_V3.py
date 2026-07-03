# Tool_V8.py
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
import html as html_lib
from urllib.parse import quote
from PIL import Image, ImageTk
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError


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

REQUEST_TIMEOUT = 10
MAX_PRICE_WORKERS = 4
MAX_THUMB_WORKERS = 8

ICON_SIZE = 56
DETAIL_SIZE = 320
HOVER_SIZE = 260

SHOW_TABLE_ICONS = True
DEBUG_PRICES = True


# ============================================================
# Datenbank
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
            last_scan REAL
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
            trend_7d REAL,
            trend_30d REAL,
            history_points INTEGER,
            last_sale_time INTEGER,
            last_update REAL
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appid INTEGER,
            item_name TEXT,
            timestamp INTEGER,
            price_median REAL,
            purchases INTEGER,
            scanned_at REAL
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
    ensure_column(con, "prices", "trend_7d", "REAL")
    ensure_column(con, "prices", "trend_30d", "REAL")
    ensure_column(con, "prices", "history_points", "INTEGER")
    ensure_column(con, "prices", "last_sale_time", "INTEGER")
    ensure_column(con, "prices", "last_update", "REAL")

    ensure_column(con, "price_history", "appid", "INTEGER")
    ensure_column(con, "price_history", "item_name", "TEXT")
    ensure_column(con, "price_history", "timestamp", "INTEGER")
    ensure_column(con, "price_history", "price_median", "REAL")
    ensure_column(con, "price_history", "purchases", "INTEGER")
    ensure_column(con, "price_history", "scanned_at", "REAL")

    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_inventory_app_item
        ON inventory(appid, item_name)
    """)

    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_prices_app_item
        ON prices(appid, item_name)
    """)

    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_history_app_item_time
        ON price_history(appid, item_name, timestamp)
    """)

    con.commit()
    return con


def ensure_column(con, table, column, definition):
    try:
        cur = con.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]

        if column not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            con.commit()
    except sqlite3.OperationalError:
        pass


# ============================================================
# Hilfsfunktionen
# ============================================================

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
    s = s.replace("\xa0", "")
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


def percent_text(value):
    if value is None:
        return ""

    try:
        v = float(value)
    except Exception:
        return ""

    if abs(v) < 0.01:
        return "0,00%"

    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%".replace(".", ",")


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


def int_safe(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def request_headers(language="de", json_mode=False, referer=None):
    if language == "en":
        accept_language = "en-US,en;q=0.9,de;q=0.8"
    else:
        accept_language = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
            "Gecko/20100101 Firefox/128.0"
        ),
        "Accept-Language": accept_language,
        "Connection": "close",
    }

    if json_mode:
        headers["Accept"] = "application/json,text/javascript,*/*;q=0.01"
        headers["X-Requested-With"] = "XMLHttpRequest"
    else:
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "application/json,text/plain,*/*;q=0.8"
        )

    if referer:
        headers["Referer"] = referer

    return headers


def debug_price(item, source, price):
    if DEBUG_PRICES:
        print(f"[PREIS] {source:20} | {str(price):>12} | {item}")


def normalize_text_variants(text):
    """
    Steam liefert React-/SSR-Daten teilweise unterschiedlich escaped:
    "price_median"
    \"price_median\"
    \\\"price_median\\\"
    &quot;price_median&quot;

    Diese Funktion erzeugt mehrere Varianten, damit der Parser mehr findet.
    """
    variants = []
    seen = set()

    def add(value):
        if value is None:
            return
        if value not in seen:
            seen.add(value)
            variants.append(value)

    s = text or ""

    for _ in range(6):
        add(s)

        h = html_lib.unescape(s)
        add(h)

        s2 = h
        s2 = s2.replace("\\u0022", '"')
        s2 = s2.replace("\\u0026", "&")
        s2 = s2.replace("\\u003c", "<")
        s2 = s2.replace("\\u003e", ">")
        s2 = s2.replace("\\/", "/")

        s2 = s2.replace('\\\\\\"', '"')
        s2 = s2.replace('\\\\"', '"')
        s2 = s2.replace('\\"', '"')

        s2 = s2.replace("\\\\", "\\")

        add(s2)

        if s2 == s:
            break

        s = s2

    return variants


def weighted_average(entries):
    total_value = 0.0
    total_weight = 0

    for _, price, purchases in entries:
        weight = max(int(purchases), 1)
        total_value += float(price) * weight
        total_weight += weight

    if total_weight <= 0:
        return 0.0

    return total_value / total_weight


def calc_history_stats(entries):
    if not entries:
        return {
            "last_price": 0.0,
            "last_volume": "",
            "last_time": None,
            "trend_7d": None,
            "trend_30d": None,
            "history_points": 0,
            "avg_7d": 0.0,
            "avg_30d": 0.0,
        }

    clean = []

    for t, p, v in entries:
        try:
            t = int(t)
            p = float(p)
            v = int(v)

            if p > 0:
                clean.append((t, p, max(v, 0)))
        except Exception:
            pass

    if not clean:
        return {
            "last_price": 0.0,
            "last_volume": "",
            "last_time": None,
            "trend_7d": None,
            "trend_30d": None,
            "history_points": 0,
            "avg_7d": 0.0,
            "avg_30d": 0.0,
        }

    clean.sort(key=lambda x: x[0])

    last_time, last_price, last_volume = clean[-1]

    seven_days = 7 * 24 * 60 * 60
    thirty_days = 30 * 24 * 60 * 60

    entries_7d = [e for e in clean if e[0] >= last_time - seven_days]
    entries_30d = [e for e in clean if e[0] >= last_time - thirty_days]

    avg_7d = weighted_average(entries_7d) if entries_7d else 0.0
    avg_30d = weighted_average(entries_30d) if entries_30d else 0.0

    trend_7d = None
    trend_30d = None

    if avg_7d > 0:
        trend_7d = ((last_price - avg_7d) / avg_7d) * 100.0

    if avg_30d > 0:
        trend_30d = ((last_price - avg_30d) / avg_30d) * 100.0

    return {
        "last_price": last_price,
        "last_volume": str(last_volume),
        "last_time": last_time,
        "trend_7d": trend_7d,
        "trend_30d": trend_30d,
        "history_points": len(clean),
        "avg_7d": avg_7d,
        "avg_30d": avg_30d,
    }


# ============================================================
# Steam Inventory
# ============================================================

def get_inventory_all(appid, contextid, stop_checker=None):
    count_options = [2000, 1000, 500]
    last_error = None

    for count_value in count_options:
        try:
            print(f"[SCAN] Versuche modernen Inventory-Endpunkt mit count={count_value}")

            return get_inventory_all_modern(
                appid,
                contextid,
                count_value,
                stop_checker=stop_checker
            )

        except requests.exceptions.HTTPError as e:
            last_error = e
            response = getattr(e, "response", None)

            if response is not None:
                print(f"[SCAN] HTTP Fehler {response.status_code} bei count={count_value}")

                if response.status_code == 400:
                    continue

            raise

        except Exception as e:
            last_error = e
            print(f"[SCAN] Fehler bei count={count_value}: {e}")
            continue

    print("[SCAN] Nutze Legacy Inventory-Endpunkt als Fallback")

    try:
        return get_inventory_legacy_json(
            appid,
            contextid,
            stop_checker=stop_checker
        )
    except Exception:
        if last_error:
            raise last_error
        raise


def get_inventory_all_modern(appid, contextid, count_value, stop_checker=None):
    all_assets = []
    all_descriptions = {}

    start_assetid = None

    while True:
        if stop_checker and stop_checker():
            break

        url = f"https://steamcommunity.com/inventory/{STEAM_ID}/{appid}/{contextid}"

        params = {
            "l": "english",
            "count": count_value,
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

        print(f"[SCAN] Assets bisher: {len(all_assets)} | Beschreibungen: {len(all_descriptions)}")

        if not data.get("more_items"):
            break

        start_assetid = data.get("last_assetid")

        if not start_assetid:
            break

        time.sleep(0.15)

    return {
        "assets": all_assets,
        "descriptions": list(all_descriptions.values())
    }


def get_inventory_legacy_json(appid, contextid, stop_checker=None):
    if stop_checker and stop_checker():
        return {
            "assets": [],
            "descriptions": []
        }

    url = f"https://steamcommunity.com/profiles/{STEAM_ID}/inventory/json/{appid}/{contextid}"

    params = {
        "l": "english"
    }

    r = requests.get(
        url,
        params=params,
        headers=request_headers("en"),
        timeout=REQUEST_TIMEOUT
    )

    r.raise_for_status()

    data = r.json()

    if not data.get("success"):
        raise Exception("Legacy Inventory-Endpunkt konnte das Inventory nicht laden.")

    rg_inventory = data.get("rgInventory", {})
    rg_descriptions = data.get("rgDescriptions", {})

    assets = []
    descriptions = []

    for assetid, asset in rg_inventory.items():
        asset_copy = dict(asset)

        if "assetid" not in asset_copy:
            asset_copy["assetid"] = assetid

        if "id" in asset_copy and "assetid" not in asset_copy:
            asset_copy["assetid"] = asset_copy["id"]

        assets.append(asset_copy)

    for key, desc in rg_descriptions.items():
        desc_copy = dict(desc)

        parts = key.split("_")

        if "classid" not in desc_copy and len(parts) >= 1:
            desc_copy["classid"] = parts[0]

        if "instanceid" not in desc_copy and len(parts) >= 2:
            desc_copy["instanceid"] = parts[1]

        descriptions.append(desc_copy)

    print(f"[SCAN] Legacy Assets: {len(assets)} | Beschreibungen: {len(descriptions)}")

    return {
        "assets": assets,
        "descriptions": descriptions
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
            headers=request_headers("de", json_mode=True),
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

        debug_price(item_name, "priceoverview", price)

        return {
            "sell_price": price,
            "buy_order": "Nicht verfügbar",
            "sell_count": str(volume),
            "buy_count": "",
            "price_number": price_number,
            "source": "priceoverview",
            "trend_7d": None,
            "trend_30d": None,
            "history_points": 0,
            "last_sale_time": None,
            "history_entries": [],
        }

    except Exception as e:
        if DEBUG_PRICES:
            print(f"[PREIS] priceoverview Fehler bei {item_name}: {e}")
        return None


def get_render_price(appid, item_name):
    try:
        ref = market_link(appid, item_name)
        url = ref + "/render/"

        params = {
            "query": "",
            "start": 0,
            "count": 10,
            "country": COUNTRY,
            "language": "german",
            "currency": CURRENCY,
            "sort_column": "price",
            "sort_dir": "asc",
        }

        r = requests.get(
            url,
            params=params,
            headers=request_headers("de", json_mode=True, referer=ref),
            timeout=REQUEST_TIMEOUT
        )

        if r.status_code != 200:
            return None

        try:
            data = r.json()
        except Exception:
            return None

        if not data.get("success"):
            return None

        listinginfo = data.get("listinginfo", {})

        if not listinginfo:
            return None

        prices = []

        for listing in listinginfo.values():
            converted_price = listing.get("converted_price")
            converted_fee = listing.get("converted_fee")

            if converted_price is not None:
                cents = int_safe(converted_price) + int_safe(converted_fee)

                if cents > 0:
                    prices.append(cents / 100.0)
                    continue

            price = listing.get("price")
            fee = listing.get("fee")

            if price is not None:
                cents = int_safe(price) + int_safe(fee)

                if cents > 0:
                    prices.append(cents / 100.0)

        if not prices:
            return None

        lowest = min(prices)
        total_count = data.get("total_count", len(prices))

        debug_price(item_name, "render", euro(lowest))

        return {
            "sell_price": euro(lowest),
            "buy_order": "Nicht verfügbar",
            "sell_count": str(total_count),
            "buy_count": "",
            "price_number": lowest,
            "source": "render",
            "trend_7d": None,
            "trend_30d": None,
            "history_points": 0,
            "last_sale_time": None,
            "history_entries": [],
        }

    except Exception as e:
        if DEBUG_PRICES:
            print(f"[PREIS] render Fehler bei {item_name}: {e}")
        return None


def parse_listing_prices_from_html(html):
    prices = []

    field_price_patterns = [
        (
            r'\\*"unPricePerUnit\\*"\s*:\s*(\d+)'
            r'.{0,700}?'
            r'\\*"unFeePerUnit\\*"\s*:\s*(\d+)'
        ),
        (
            r'\\*"unPrice\\*"\s*:\s*(\d+)'
            r'.{0,700}?'
            r'\\*"unFee\\*"\s*:\s*(\d+)'
        ),
    ]

    for variant in normalize_text_variants(html):
        for pattern in field_price_patterns:
            for m in re.finditer(pattern, variant, flags=re.DOTALL):
                try:
                    price_cents = int(m.group(1))
                    fee_cents = int(m.group(2))
                    total = (price_cents + fee_cents) / 100.0

                    if total > 0:
                        prices.append(total)
                except Exception:
                    pass

        subtotal_pattern = r'\\*"strSubtotal\\*"\s*:\s*\\*"([^"\\]+)'

        for text in re.findall(subtotal_pattern, variant, flags=re.DOTALL):
            p = parse_price(text)

            if p > 0:
                prices.append(p)

    if not prices:
        return None

    lowest = min(prices)

    return {
        "sell_price": euro(lowest),
        "buy_order": "Nicht verfügbar",
        "sell_count": str(len(prices)),
        "buy_count": "",
        "price_number": lowest,
        "source": "listing_html",
        "trend_7d": None,
        "trend_30d": None,
        "history_points": 0,
        "last_sale_time": None,
        "history_entries": [],
    }


def parse_price_history_entries(html):
    entries = []

    pattern = (
        r'\\*"time\\*"\s*:\s*(\d+)'
        r'.{0,180}?'
        r'\\*"price_median\\*"\s*:\s*([0-9.]+)'
        r'.{0,120}?'
        r'\\*"purchases\\*"\s*:\s*(\d+)'
    )

    for variant in normalize_text_variants(html):
        matches = re.findall(pattern, variant, flags=re.DOTALL)

        for t, price, purchases in matches:
            try:
                timestamp = int(t)
                price_value = float(price)
                volume = int(purchases)

                if price_value > 0:
                    entries.append((timestamp, price_value, volume))
            except Exception:
                pass

    if not entries:
        return []

    dedup = {}

    for t, price, purchases in entries:
        dedup[t] = (t, price, purchases)

    result = list(dedup.values())
    result.sort(key=lambda x: x[0])

    return result


def price_from_history_entries(entries):
    stats = calc_history_stats(entries)

    if stats["last_price"] <= 0:
        return None

    return {
        "sell_price": euro(stats["last_price"]),
        "buy_order": "Nicht verfügbar",
        "sell_count": stats["last_volume"],
        "buy_count": "",
        "price_number": stats["last_price"],
        "source": "history_last",
        "trend_7d": stats["trend_7d"],
        "trend_30d": stats["trend_30d"],
        "history_points": stats["history_points"],
        "last_sale_time": stats["last_time"],
        "history_entries": entries,
    }


def get_market_page_data(appid, item_name):
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

        history_entries = parse_price_history_entries(html)
        history_data = price_from_history_entries(history_entries)

        if DEBUG_PRICES:
            if history_entries:
                print(f"[HISTORY] {len(history_entries):4} Punkte | {item_name}")
            else:
                print(f"[HISTORY]    0 Punkte | {item_name}")

        listing_data = parse_listing_prices_from_html(html)

        if listing_data and listing_data["price_number"] > 0:
            if history_data:
                listing_data["history_entries"] = history_entries
                listing_data["trend_7d"] = history_data["trend_7d"]
                listing_data["trend_30d"] = history_data["trend_30d"]
                listing_data["history_points"] = history_data["history_points"]
                listing_data["last_sale_time"] = history_data["last_sale_time"]

            debug_price(item_name, "listing_html", listing_data["sell_price"])
            return listing_data

        if history_data and history_data["price_number"] > 0:
            debug_price(item_name, "history_last", history_data["sell_price"])
            return history_data

        return None

    except Exception as e:
        if DEBUG_PRICES:
            print(f"[PREIS] market_page Fehler bei {item_name}: {e}")
        return None


def get_best_price(appid, item_name):
    data = get_render_price(appid, item_name)

    if data and data["price_number"] > 0:
        return data

    data = get_priceoverview(appid, item_name)

    if data and data["price_number"] > 0:
        return data

    data = get_market_page_data(appid, item_name)

    if data and data["price_number"] > 0:
        return data

    debug_price(item_name, "none", "Kein Preis")

    return {
        "sell_price": "Kein Preis",
        "buy_order": "Nicht verfügbar",
        "sell_count": "",
        "buy_count": "",
        "price_number": 0.0,
        "source": "none",
        "trend_7d": None,
        "trend_30d": None,
        "history_points": 0,
        "last_sale_time": None,
        "history_entries": [],
    }


# ============================================================
# GUI
# ============================================================

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Steam Inventory Manager Tool V8")
        self.root.geometry("1780x920")

        self.rows = []
        self.image_cache = {}

        self.table_thumb_cache = {}
        self.table_thumb_jobs = set()
        self.iid_icon_url = {}
        self.thumb_executor = ThreadPoolExecutor(max_workers=MAX_THUMB_WORKERS)

        self.hover_window = None
        self.last_hover_item = None
        self.sort_state = {}

        self.stop_event = threading.Event()
        self.task_id = 0
        self.executor = None

        self.setup_style()
        self.setup_ui()

        db().close()

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
            rowheight=66
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
        ttk.Button(top, text="Verlauf aktualisieren", command=self.start_update_history).pack(side="left", padx=4)
        ttk.Button(top, text="Market öffnen", command=self.open_market).pack(side="left", padx=4)
        ttk.Button(top, text="CSV Export", command=self.export_csv).pack(side="left", padx=4)
        ttk.Button(top, text="History CSV", command=self.export_history_csv).pack(side="left", padx=4)

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

        self.filter_no_price = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            search_frame,
            text="nur ohne Preis",
            variable=self.filter_no_price,
            command=self.apply_filter
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
            "Trend7T",
            "Trend30T",
            "History",
            "Gesamt"
        )

        self.tree = ttk.Treeview(left, columns=cols, show="tree headings")

        self.tree.heading("#0", text="Bild")
        self.tree.column("#0", width=78, stretch=False, anchor="center")

        for c in cols:
            self.tree.heading(c, text=c, command=lambda col=c: self.sort_by_column(col))

        self.tree.column("Spiel", width=105)
        self.tree.column("Item", width=390)
        self.tree.column("Typ", width=200)
        self.tree.column("Anzahl", width=70)
        self.tree.column("Preis", width=95)
        self.tree.column("Quelle", width=115)
        self.tree.column("Volumen", width=80)
        self.tree.column("Trend7T", width=85)
        self.tree.column("Trend30T", width=90)
        self.tree.column("History", width=75)
        self.tree.column("Gesamt", width=95)

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
            width=44,
            height=28,
            bg="#1b1b1b",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=("Segoe UI", 10)
        )
        self.detail_text.pack(fill="y")

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
    # Inventory Scan
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
                    DELETE FROM inventory
                    WHERE appid = ? AND item_name = ?
                """, (
                    appid,
                    name
                ))

                con.execute("""
                    INSERT INTO inventory
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
    # DB-Zeilen
    # --------------------------------------------------------

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
                AND id IN (
                    SELECT MAX(id)
                    FROM inventory
                    WHERE appid = ?
                    GROUP BY item_name
                )
                ORDER BY item_name
            """, (appid, appid))

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
                        ORDER BY last_update DESC
                        LIMIT 1
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

        self.run_price_worker(task_id, rows, worker, "Preisupdate")

    # --------------------------------------------------------
    # Verlauf separat aktualisieren
    # --------------------------------------------------------

    def start_update_history(self):
        game = self.game_var.get()
        task_id = self.new_task()

        threading.Thread(
            target=self.update_history,
            args=(task_id, game),
            daemon=True
        ).start()

    def update_history(self, task_id, game):
        rows = self.get_inventory_rows_for_game(game)
        total = len(rows)

        if not rows:
            self.set_status("Keine Items für Verlauf gefunden")
            return

        self.set_status(f"Starte Verlauf-Update: {total} Items")

        def worker(row):
            if self.is_stopped(task_id):
                return None

            appid = row["AppID"]
            item = row["Item"]

            data = get_market_page_data(appid, item)

            if data:
                return appid, item, data

            return appid, item, {
                "sell_price": "Kein Preis",
                "buy_order": "Nicht verfügbar",
                "sell_count": "",
                "buy_count": "",
                "price_number": 0.0,
                "source": "none",
                "trend_7d": None,
                "trend_30d": None,
                "history_points": 0,
                "last_sale_time": None,
                "history_entries": [],
            }

        self.run_price_worker(task_id, rows, worker, "Verlauf-Update")

    def run_price_worker(self, task_id, rows, worker_func, label):
        total = len(rows)
        done = 0

        executor = ThreadPoolExecutor(max_workers=MAX_PRICE_WORKERS)
        self.executor = executor

        futures = [executor.submit(worker_func, row) for row in rows]

        con = db()

        try:
            for future in as_completed(futures):
                if self.is_stopped(task_id):
                    self.set_status(f"{label} gestoppt")
                    break

                done += 1
                self.set_status(f"{label} {done}/{total}")

                try:
                    result = future.result()
                except CancelledError:
                    continue
                except Exception as e:
                    if DEBUG_PRICES:
                        print(f"[PREIS] Worker-Fehler: {e}")
                    continue

                if not result:
                    continue

                appid, item, data = result

                self.save_price_and_history(con, appid, item, data)

        finally:
            con.close()

            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

            if self.executor is executor:
                self.executor = None

        if self.is_stopped(task_id):
            self.set_status(f"{label} gestoppt")
            return

        self.set_status(f"{label} fertig")
        self.root.after(0, self.load_from_db)

    def save_price_and_history(self, con, appid, item, data):
        con.execute("""
            DELETE FROM prices
            WHERE appid = ? AND item_name = ?
        """, (
            appid,
            item
        ))

        con.execute("""
            INSERT INTO prices
            (
                appid,
                item_name,
                sell_price,
                buy_order,
                sell_count,
                buy_count,
                price_number,
                source,
                trend_7d,
                trend_30d,
                history_points,
                last_sale_time,
                last_update
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            appid,
            item,
            data.get("sell_price", "Kein Preis"),
            data.get("buy_order", "Nicht verfügbar"),
            data.get("sell_count", ""),
            data.get("buy_count", ""),
            data.get("price_number", 0.0),
            data.get("source", "none"),
            data.get("trend_7d"),
            data.get("trend_30d"),
            data.get("history_points", 0),
            data.get("last_sale_time"),
            time.time()
        ))

        history_entries = data.get("history_entries", [])

        if history_entries:
            con.execute("""
                DELETE FROM price_history
                WHERE appid = ? AND item_name = ?
            """, (
                appid,
                item
            ))

            scanned_at = time.time()

            con.executemany("""
                INSERT INTO price_history
                (
                    appid,
                    item_name,
                    timestamp,
                    price_median,
                    purchases,
                    scanned_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                (
                    appid,
                    item,
                    int(t),
                    float(price),
                    int(purchases),
                    scanned_at
                )
                for t, price, purchases in history_entries
            ])

        con.commit()

    # --------------------------------------------------------
    # DB laden / Tabelle
    # --------------------------------------------------------

    def load_from_db(self):
        game = self.game_var.get()
        appid = APPS[game]["appid"]

        con = db()

        try:
            cur = con.execute("""
                WITH latest_inventory AS (
                    SELECT *
                    FROM inventory
                    WHERE appid = ?
                    AND id IN (
                        SELECT MAX(id)
                        FROM inventory
                        WHERE appid = ?
                        GROUP BY item_name
                    )
                ),
                latest_prices AS (
                    SELECT *
                    FROM prices
                    WHERE id IN (
                        SELECT MAX(id)
                        FROM prices
                        GROUP BY appid, item_name
                    )
                )
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
                    COALESCE(p.source, ''),
                    p.trend_7d,
                    p.trend_30d,
                    COALESCE(p.history_points, 0),
                    p.last_sale_time
                FROM latest_inventory i
                LEFT JOIN latest_prices p
                    ON i.appid = p.appid
                    AND i.item_name = p.item_name
                ORDER BY i.item_name
            """, (appid, appid))

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
                    "Trend7T": r[12],
                    "Trend30T": r[13],
                    "History": r[14] or 0,
                    "LastSaleTime": r[15],
                    "Gesamt": total,
                })

        finally:
            con.close()

        self.reload_table()

    def reload_table(self):
        self.tree.delete(*self.tree.get_children())
        self.iid_icon_url.clear()

        q = self.search_var.get().lower().strip()
        total_value = 0.0
        only_no_price = self.filter_no_price.get()

        for idx, row in enumerate(self.rows):
            if q and q not in row["Item"].lower() and q not in row["Typ"].lower():
                continue

            if only_no_price and row["PreisZahl"] > 0:
                continue

            total_value += row["Gesamt"]

            iid = str(idx)
            self.iid_icon_url[iid] = row["IconURL"]

            values = (
                row["Spiel"],
                row["Item"],
                row["Typ"],
                row["Anzahl"],
                row["Preis"],
                row["Quelle"],
                row["Volumen"],
                percent_text(row["Trend7T"]),
                percent_text(row["Trend30T"]),
                row["History"],
                f"{row['Gesamt']:.2f}",
            )

            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=values
            )

            if SHOW_TABLE_ICONS and row["IconURL"]:
                self.load_table_thumbnail_async(iid, row["IconURL"])

        self.total_label.config(
            text=f"Gesamtwert: €{total_value:.2f}".replace(".", ",")
        )

    def load_table_thumbnail_async(self, iid, url):
        if not url:
            return

        key = f"{url}|table"

        if key in self.table_thumb_cache:
            try:
                if self.tree.exists(iid) and self.iid_icon_url.get(iid) == url:
                    self.tree.item(iid, image=self.table_thumb_cache[key])
            except Exception:
                pass
            return

        if key in self.table_thumb_jobs:
            return

        self.table_thumb_jobs.add(key)

        def worker():
            pil_image = None

            try:
                r = requests.get(
                    url,
                    headers=request_headers("de"),
                    timeout=REQUEST_TIMEOUT
                )
                r.raise_for_status()

                img = Image.open(BytesIO(r.content)).convert("RGBA")
                img.thumbnail((ICON_SIZE, ICON_SIZE))

                canvas = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))

                x = (ICON_SIZE - img.width) // 2
                y = (ICON_SIZE - img.height) // 2

                canvas.paste(img, (x, y), img)
                pil_image = canvas

            except Exception:
                pil_image = None

            def finish():
                self.table_thumb_jobs.discard(key)

                if pil_image is None:
                    return

                try:
                    photo = ImageTk.PhotoImage(pil_image)
                    self.table_thumb_cache[key] = photo

                    if self.tree.exists(iid) and self.iid_icon_url.get(iid) == url:
                        self.tree.item(iid, image=photo)

                except Exception:
                    pass

            self.root.after(0, finish)

        try:
            self.thumb_executor.submit(worker)
        except Exception:
            pass

    # --------------------------------------------------------
    # Sortierung / Filter
    # --------------------------------------------------------

    def sort_by_column(self, col):
        reverse = self.sort_state.get(col, False)

        numeric = {"Anzahl", "Volumen", "Gesamt", "Preis", "Trend7T", "Trend30T", "History"}

        if col in numeric:
            def key_func(x):
                if col == "Gesamt":
                    return float(x.get("Gesamt", 0))
                if col == "Preis":
                    return parse_price(x.get("Preis", "0"))
                if col == "Volumen":
                    return clean_int(x.get("Volumen", "0"))
                if col == "Trend7T":
                    return float(x.get("Trend7T") or 0)
                if col == "Trend30T":
                    return float(x.get("Trend30T") or 0)
                if col == "History":
                    return int(x.get("History") or 0)

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
        self.detail_text.insert("end", f"Trend 7 Tage: {percent_text(row['Trend7T'])}\n")
        self.detail_text.insert("end", f"Trend 30 Tage: {percent_text(row['Trend30T'])}\n")
        self.detail_text.insert("end", f"History-Punkte: {row['History']}\n")
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
            f"Volumen: {row['Volumen']}\n"
            f"7T: {percent_text(row['Trend7T'])}\n"
            f"30T: {percent_text(row['Trend30T'])}"
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

    def export_history_csv(self):
        game = self.game_var.get()
        appid = APPS[game]["appid"]

        con = db()

        try:
            df = pd.read_sql_query("""
                SELECT
                    appid,
                    item_name,
                    datetime(timestamp, 'unixepoch') AS datum,
                    price_median,
                    purchases,
                    datetime(scanned_at, 'unixepoch') AS gescannt
                FROM price_history
                WHERE appid = ?
                ORDER BY item_name, timestamp
            """, con, params=(appid,))
        finally:
            con.close()

        if df.empty:
            messagebox.showinfo("Hinweis", "Keine History-Daten vorhanden.")
            return

        filename = f"steam_price_history_{game.replace(' ', '_')}.csv"

        df.to_csv(
            filename,
            index=False,
            encoding="utf-8-sig"
        )

        messagebox.showinfo(
            "Export",
            f"Gespeichert als {filename}"
        )


# ============================================================
# Start
# ============================================================

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
