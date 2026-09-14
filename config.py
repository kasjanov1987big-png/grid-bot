# -*- coding: utf-8 -*-
"""
Конфигурация PAPER grid-бота.
Ключи Bybit НЕ нужны — бот берёт только публичные цены.
"""
import os

# ============ TELEGRAM ============
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "ВСТАВЬ_ТОКЕН_БОТА")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))   # твой Telegram ID (узнай у @userinfobot)

# ============ РЫНОК (публичные данные) ============
SYMBOL = os.getenv("SYMBOL", "SOLUSDT")
POLL_SEC = int(os.getenv("POLL_SEC", "10"))   # как часто проверять цену и исполнения

# ============ СЕТКА ============
QUOTE_PER_ORDER = float(os.getenv("QUOTE_PER_ORDER", "10.0"))  # USDT на один ордер
STEP_PCT = float(os.getenv("STEP_PCT", "0.012"))               # шаг 1.2%
LEVELS_PER_SIDE = int(os.getenv("LEVELS_PER_SIDE", "4"))       # 4 вверх + 4 вниз

# ============ КОМИССИЯ (симуляция) ============
FEE_PCT = float(os.getenv("FEE_PCT", "0.001"))   # 0.1% как на Bybit спот

# ============ БАНК ============
START_BALANCE = float(os.getenv("START_BALANCE", "100.0"))  # стартовые виртуальные USDT

# ============ ФАЙЛЫ ============
STATE_FILE = "state.json"
TRADES_FILE = "trades.csv"
LOG_FILE = "bot.log"
