# -*- coding: utf-8 -*-
"""
Konfiguratsija PAPER grid-bota. Versija 3.5.
Klyuchi Bybit NE nuzhny - bot beret tolko publichnye ceny.
V3.5: multisymbol - SYMBOLS cerez zapjatuju, dla kazhdoj pary
svoi fajly sostojanija (for_symbol).
"""
import os
from types import SimpleNamespace

# ============ TELEGRAM ============
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "VSTAV_TOKEN_BOTA")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ============ RYNOK (publichnye dannye) ============
SYMBOL = os.getenv("SYMBOL", "SOLUSDT")            # para po umolchaniju
# Neskolko par cerez zapjatuju, napr.: "SOLUSDT,BTCUSDT"
SYMBOLS = os.getenv("SYMBOLS", SYMBOL)
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
EQUITY_FILE = os.path.join(DATA_DIR, "equity.csv")
LOG_FILE = os.path.join(DATA_DIR, "bot.log")


def for_symbol(symbol):
    """V3.5: konfiguratsija-podkopija dla odnoj pary (svoi fajly)."""
    return SimpleNamespace(
        SYMBOL=symbol,
        TELEGRAM_TOKEN=TELEGRAM_TOKEN,
        ADMIN_ID=ADMIN_ID,
        POLL_SEC=POLL_SEC,
        QUOTE_PER_ORDER=QUOTE_PER_ORDER,
        STEP_PCT=STEP_PCT,
        LEVELS_PER_SIDE=LEVELS_PER_SIDE,
        FEE_PCT=FEE_PCT,
        SLIPPAGE_PCT=SLIPPAGE_PCT,
        DD_LIMIT_PCT=DD_LIMIT_PCT,
        START_BALANCE=START_BALANCE,
        STATE_FILE=os.path.join(DATA_DIR, "state_" + symbol + ".json"),
        TRADES_FILE=os.path.join(DATA_DIR, "trades_" + symbol + ".csv"),
        EQUITY_FILE=os.path.join(DATA_DIR, "equity_" + symbol + ".csv"),
        LOG_FILE=LOG_FILE,
    )


def symbol_list():
    """V3.5: spisok par iz SYMBOLS (bez probelov, v verhnem registre)."""
    return [s.strip().upper() for s in SYMBOLS.split(",") if s.strip()]
