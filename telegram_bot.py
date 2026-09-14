# -*- coding: utf-8 -*-
"""
Telegram-интерфейс для управления paper-ботом со смартфона.
"""
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)


class TelegramController:
    def __init__(self, token: str, admin_id: int, broker):
        self.bot = Bot(token=token)
        self.dp = Dispatcher()
        self.admin_id = admin_id
        self.broker = broker
        self._register()

    def _register(self):
        self.dp.message(Command("start"))(self.cmd_start)
        self.dp.message(F.text == "🚀 Запустить сетку")(self.cmd_run)
        self.dp.message(F.text == "🛑 Остановить")(self.cmd_stop)
        self.dp.message(F.text == "📊 Статус")(self.cmd_status)
        self.dp.message(F.text == "📈 Статистика")(self.cmd_stats)
        self.dp.message(F.text == "📄 Логи")(self.cmd_logs)
        self.dp.message(F.text == "⚙️ Настройки")(self.cmd_settings)

    async def _is_admin(self, msg: types.Message) -> bool:
        if msg.from_user.id != self.admin_id:
            await msg.answer("⛔ Доступ запрещён.")
            return False
        return True

    async def cmd_start(self, msg: types.Message):
        if not await self._is_admin(msg):
            return
        kb = types.ReplyKeyboardMarkup(
            keyboard=[
                [
                    types.KeyboardButton(text="🚀 Запустить сетку"),
                    types.KeyboardButton(text="🛑 Остановить"),
                ],
                [
                    types.KeyboardButton(text="📊 Статус"),
                    types.KeyboardButton(text="📈 Статистика"),
                ],
                [
                    types.KeyboardButton(text="📄 Логи"),
                    types.KeyboardButton(text="⚙️ Настройки"),
                ],
            ],
            resize_keyboard=True,
        )
        await msg.answer(
            "👋 <b>PAPER grid-бот</b> (реальные цены Bybit, виртуальные деньги).
"
            "Управление кнопками ниже.",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )

    async def cmd_run(self, msg: types.Message):
        if not await self._is_admin(msg):
            return
        if self.broker.running:
            await msg.answer("⚠️ Бот уже работает.")
            return
        await msg.answer("⏳ Строю сетку по текущей цене...")
        ok = await self.broker.start()
        if ok:
            await msg.answer("✅ Сетка запущена! Каждые "
                             f"{self.broker.config.POLL_SEC} сек проверяю рынок.")
        else:
            await msg.answer("❌ Не удалось запустить.")

    async def cmd_stop(self, msg: types.Message):
        if not await self._is_admin(msg):
            return
        if not self.broker.running:
            await msg.answer("⚠️ Бот уже остановлен.")
            return
        ok = await self.broker.stop()
        if ok:
            await msg.answer("✅ Бот остановлен. Состояние сохранено.")
        else:
            await msg.answer("❌ Не удалось остановить.")

    async def cmd_status(self, msg: types.Message):
        if not await self._is_admin(msg):
            return
        await msg.answer(await self.broker.get_status_text(),
                         parse_mode=ParseMode.HTML)

    async def cmd_stats(self, msg: types.Message):
        if not await self._is_admin(msg):
            return
        s = self.broker.state["stats"]
        text = (
            f"📈 <b>Полная статистика</b>

"
            f"Завершённых циклов: <b>{s['cycles']}</b>
"
            f"Всего сделок: <b>{s['trades']}</b>
"
            f"Суммарная комиссия: <b>{s['fees_paid']:.4f}</b> USDT
"
            f"Чистая прибыль: <b>{s['realized_pnl']:.4f}</b> USDT
"
            f"Среднее за цикл: <b>{s['realized_pnl'] / max(s['cycles'], 1):.4f}</b> USDT
"
            f"Открытых позиций: <b>{len(self.broker.state['open_buys'])}</b>"
        )
        await msg.answer(text, parse_mode=ParseMode.HTML)

    async def cmd_logs(self, msg: types.Message):
        if not await self._is_admin(msg):
            return
        try:
            await msg.answer_document(
                types.FSInputFile(self.broker.trades_file),
                caption="📄 trades.csv — журнал сделок",
            )
        except Exception as e:
            await msg.answer(f"❌ Не удалось отправить файл: {e}")

    async def cmd_settings(self, msg: types.Message):
        if not await self._is_admin(msg):
            return
        c = self.broker.config
        text = (
            f"⚙️ <b>Настройки</b>

"
            f"Режим: <code>PAPER (без ключей)</code>
"
            f"Пара: <code>{c.SYMBOL}</code>
"
            f"Сумма на ордер: <code>{c.QUOTE_PER_ORDER}</code> USDT
"
            f"Шаг сетки: <code>{c.STEP_PCT * 100:.2f}%</code>
"
            f"Уровней с каждой стороны: <code>{c.LEVELS_PER_SIDE}</code>
"
            f"Проверка каждые: <code>{c.POLL_SEC}</code> сек
"
            f"Комиссия: <code>{c.FEE_PCT * 100:.2f}%</code>"
        )
        await msg.answer(text, parse_mode=ParseMode.HTML)

    async def run(self):
        logger.info("Telegram-бот запущен")
        await self.dp.start_polling(self.bot)
