# -*- coding: utf-8 -*-
"""
Tochka vkhoda: paper grid-bot + Telegram-upravlenie.
Versija 3.5.
- Avto-resume: esli pri restarte (Railway redeploy/reboot) v state_<SYM>.json
  stojalo active=true, bot sam prodolzhaet rabotu bez knopki v Telegram.
- Multisymbol: neskolko par parallelno (SYMBOLS cerez zapjatuju v env),
  kazhdyj PaperBroker so svoimi fajlami. Knopka "Para" perekljuchaet.
"""
import asyncio
import logging
import os
import shutil
import sys

import config
from paper_bot import PaperBroker
from telegram_bot import TelegramController

os.makedirs(config.DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)


def validate():
    errors = []
    if "VSTAV" in config.TELEGRAM_TOKEN:
        errors.append("TELEGRAM_TOKEN ne zapolnen")
    if config.ADMIN_ID == 0:
        errors.append("ADMIN_ID ne zapolnen")
    if errors:
        print("OSHIbKA ZAPUSKA:")
        for e in errors:
            print("   - " + e)
        print("Zapolni peremennye okruzhenija v Railway.")
        return False
    return True


def migrate_legacy(symbols):
    """V3.5: odin raz kopirujet starye fajly (bez simvola v imeni)
    v fajly pervoj pary. Novye pary nachinajutsja s chistogo lista."""
    pairs = [
        ("state.json", "state_", ".json"),
        ("trades.csv", "trades_", ".csv"),
        ("equity.csv", "equity_", ".csv"),
    ]
    for old_name, pref, ext in pairs:
        old = os.path.join(config.DATA_DIR, old_name)
        if not os.path.exists(old):
            continue
        new = os.path.join(config.DATA_DIR, pref + symbols[0] + ext)
        if not os.path.exists(new):
            shutil.copyfile(old, new)
            print("Migracija: " + old_name + " -> " + os.path.basename(new))


async def main():
    if not validate():
        return

    symbols = config.symbol_list()
    if not symbols:
        print("Net ni odnoj pary v SYMBOLS")
        return

    migrate_legacy(symbols)

    brokers = {}
    for sym in symbols:
        brokers[sym] = PaperBroker(config.for_symbol(sym))

    tg = TelegramController(config.TELEGRAM_TOKEN, config.ADMIN_ID, brokers)

    # Avto-resume: kazhdyj zapushchennyj do restarta broker prodolzhaet
    resumed = []
    for sym, br in brokers.items():
        if br.state.get("active"):
            await br.start()
            resumed.append(sym)
    if resumed:
        await tg.send(
            "Bot avtomaticheski zapushchen posle restarta (avto-resume): "
            + ", ".join(resumed))

    await tg.run()


if __name__ == "__main__":
    asyncio.run(main())
