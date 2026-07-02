# Steam Inventory Manager V2

A modern Python desktop application for scanning Steam inventories, reading Steam Community Market prices and managing your complete inventory locally.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)

---

# Features

- ✅ Scan Steam inventories
- ✅ CS2 support
- ✅ Dota 2 support
- ✅ Team Fortress 2 support
- ✅ Steam Community Items / Trading Cards
- ✅ Read Steam Community Market prices
- ✅ Buy Orders
- ✅ Sell Orders
- ✅ Sell Order Count
- ✅ Buy Order Count
- ✅ Local SQLite database
- ✅ Inventory cache
- ✅ Market cache
- ✅ CSV Export
- ✅ Search
- ✅ Price sorting
- ✅ Total inventory value
- ✅ Double click to open Steam Market
- ✅ Automatic cache
- ✅ Modern Dark Theme

---

# Planned Features

- ⏳ Steam Login Support
- ⏳ Item Thumbnails
- ⏳ Price History Graphs
- ⏳ Wishlist
- ⏳ Favorites
- ⏳ Multiple Steam Accounts
- ⏳ Automatic Background Price Updates
- ⏳ Inventory Statistics
- ⏳ Profit/Loss Tracking
- ⏳ Discord Rich Presence
- ⏳ Steam Trade URL Support
- ⏳ Excel Export
- ⏳ Price Alerts
- ⏳ Multiple Languages

---

# Supported Games

| Game | AppID |
|-------|-------|
| Counter-Strike 2 | 730 |
| Dota 2 | 570 |
| Team Fortress 2 | 440 |
| Steam Community Items | 753 |

More games can easily be added.

---

# Installation

## Clone Repository

```bash
git clone https://github.com/USERNAME/steam-inventory-manager.git
cd steam-inventory-manager
```

---

## Install Python Packages

```bash
pip install requests
pip install pandas
pip install playwright
pip install pillow
pip install beautifulsoup4
```

or

```bash
pip install -r requirements.txt
```

---

## Install Chromium

```bash
playwright install chromium
```

---

## Start

```bash
python steam_inventory_manager_v2.py
```

---

# How it works

1. Scan your Steam inventory.
2. Inventory is stored locally.
3. Steam Community Market pages are read.
4. Prices are stored in SQLite.
5. Next startup loads instantly from the database.
6. Prices can be refreshed at any time.

---

# Database

The application stores all data locally.

```
steam_inventory.db
```

Tables:

```
inventory
prices
```

No information is uploaded anywhere.

---

# Cache

Prices are cached locally.

Default cache duration:

```
24 Hours
```

This prevents unnecessary Steam requests.

---

# CSV Export

Current inventory can be exported as

```
steam_inventory_manager_export.csv
```

---

# Search

Search works for

- Item Name
- Item Type

---

# Steam Community Market

Double click any item to open

```
https://steamcommunity.com/market/
```

directly in your browser.

---

# Project Structure

```
steam_inventory_manager_v2.py
steam_inventory.db
requirements.txt
README.md
```

---

# Requirements

- Python 3.11+
- Windows 10/11
- Steam Inventory set to **Public**

Steam Privacy Settings:

```
Profile
    Public

Inventory
    Public
```

---

# Disclaimer

This project is **not affiliated with Valve Corporation or Steam**.

Steam®, Counter-Strike®, Dota®, Team Fortress® and all related trademarks belong to Valve Corporation.

---

# Contributing

Pull Requests are welcome.

If you have ideas for new features, feel free to open an Issue.

---

# Roadmap

## Version 2.1

- Item Images
- Better Market Parser
- Faster Multi Thread Scanner
- Better Database
- Automatic Updates

## Version 2.2

- Steam Login
- Price History
- Statistics
- Excel Export

## Version 3.0

- Portfolio Dashboard
- Multiple Accounts
- Cloud Sync
- Price Notifications
- Web Interface

---

# Screenshots

Coming soon.

---

# License

MIT License

Copyright (c) 2026

---

# Author

Developed with ❤️ using Python and Playwright.
