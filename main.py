# -*- coding: utf-8 -*-
"""
Tochka vkhoda: paper grid-bot + Telegram-upravlenie.
Versija 3.
- Avto-resume: esli pri restarte (Railway redeploy/reboot) v state.json
  stojalo active=true, bot sam prodolzhaet rabotu bez knopki v Telegram.
"""
import asyncio
import logging
import os
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


async def main():
    if not validate():
        return

    broker = PaperBroker(config)
    tg = TelegramController(config.TELEGRAM_TOKEN, config.ADMIN_ID, broker)

    # Avto-resume: byl zapushchen do restarta - vozobnovljaem bez knopki
    if broker.state.get("active"):
        await broker.start()
        await tg.send(
            "Bot avtomaticheski zapushchen posle restarta (avto-resume)."
        )

    await tg.run()


if __name__ == "__main__":
    asyncio.run(main())
