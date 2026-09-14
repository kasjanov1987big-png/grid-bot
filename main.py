# -*- coding: utf-8 -*-
"""
Точка входа: paper grid-бот + Telegram-управление.
"""
import asyncio
import logging
import sys

import config
from paper_bot import PaperBroker
from telegram_bot import TelegramController

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
    if "ВСТАВЬ" in config.TELEGRAM_TOKEN:
        errors.append("TELEGRAM_TOKEN не заполнен")
    if config.ADMIN_ID == 0:
        errors.append("ADMIN_ID не заполнен (узнай у @userinfobot)")
    if errors:
        print("❌ ОШИБКА ЗАПУСКА:")
        for e in errors:
            print(f"   • {e}")
        print("\nЗаполни переменные окружения в Railway.")
        return False
    return True


async def main():
    if not validate():
        return

    broker = PaperBroker(config)
    tg = TelegramController(config.TELEGRAM_TOKEN, config.ADMIN_ID, broker)
    await tg.run()


if __name__ == "__main__":
    asyncio.run(main())
