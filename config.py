# -*- coding: utf-8 -*-
"""
Konfiguratsija PAPER grid-bota. Versija 2.2.
Klyuchi Bybit NE nuzhny - bot beret tolko publichnye ceny.
"""
import os

# ============ TELEGRAM ============
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "VSTAV_TOKEN_BOTA")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ============ RYNOK (publichnye dannye) ============
SYMBOL = os.getenv("SYMBOL", "SOLUSDT")
POLL_SEC = int(os.getenv("POLL_SEC", "10"))

# ============ SETKA (znachenija po umolchaniju) ============
QUOTE_PER_ORDER = float(os.getenv("QUOTE_PER_ORDER", "10.0"))
STEP_PCT = float(os.getenv("STEP_PCT", "0.012"))
LEVELS_PER_SIDE = int(os.getenv("LEVELS_PER_SIDE", "4"))

# ============ KOMISSIJA I REALIZM ============
FEE_PCT = float(os.getenv("FEE_PCT", "0.001"))
SLIPPAGE_PCT = float(os.getenv("SLIPPAGE_PCT", "0.0005"))   # 0.05% proskalzyvanie

# ============ ZASHCHITA ============
DD_LIMIT_PCT = float(os.getenv("DD_LIMIT_PCT", "0.05"))     # dnevnoj limit prosadki 5%

# ============ BANK ============
START_BALANCE = float(os.getenv("START_BALANCE", "100.0"))

# ============ FAJLY ============
# Esli podkljuchen Railway Volume - zadaj peremennuju DATA_DIR=/data
DATA_DIR = os.getenv("DATA_DIR", ".")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
TRADES_FILE = os.path.join(DATA_DIR, "trades.csv")
LOG_FILE = os.path.join(DATA_DIR, "bot.log")
