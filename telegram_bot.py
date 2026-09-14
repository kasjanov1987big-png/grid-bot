# -*- coding: utf-8 -*-
"""
Telegram-interfejs dlja upravlenija paper-botom so smartfona.
Kod tolko na latinice - tak file ne lomaetsja pri peredache s telefona.
"""
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)


class TelegramController:
    def __init__(self, token, admin_id, broker):
        self.bot = Bot(token=token)
        self.dp = Dispatcher()
        self.admin_id = admin_id
        self.broker = broker
        self._register()

    def _register(self):
        self.dp.message(Command("start"))(self.cmd_start)
        self.dp.message(F.text == "Zapustit setku")(self.cmd_run)
        self.dp.message(F.text == "Ostanovit")(self.cmd_stop)
        self.dp.message(F.text == "Status")(self.cmd_status)
        self.dp.message(F.text == "Statistika")(self.cmd_stats)
        self.dp.message(F.text == "Logi")(self.cmd_logs)
        self.dp.message(F.text == "Nastrojki")(self.cmd_settings)

    async def _is_admin(self, msg):
        if msg.from_user.id != self.admin_id:
            await msg.answer("Dostup zapreshchen.")
            return False
        return True

    async def cmd_start(self, msg):
        if not await self._is_admin(msg):
            return
        kb = types.ReplyKeyboardMarkup(
            keyboard=[
                [
                    types.KeyboardButton(text="Zapustit setku"),
                    types.KeyboardButton(text="Ostanovit"),
                ],
                [
                    types.KeyboardButton(text="Status"),
                    types.KeyboardButton(text="Statistika"),
                ],
                [
                    types.KeyboardButton(text="Logi"),
                    types.KeyboardButton(text="Nastrojki"),
                ],
            ],
            resize_keyboard=True,
        )
        await msg.answer(
            "<b>PAPER grid-bot</b> (realnye ceny Bybit, virtualnye dengi).\n"
            "Upravlenie knopkami nizhe.",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )

    async def cmd_run(self, msg):
        if not await self._is_admin(msg):
            return
        if self.broker.running:
            await msg.answer("Bot uzhe rabotaet.")
            return
        await msg.answer("Stroju setku po tekushchej cene...")
        ok = await self.broker.start()
        if ok:
            await msg.answer("Setka zapushchena! Kazhdye "
                             + str(self.broker.config.POLL_SEC)
                             + " sek proverjaju rynok.")
        else:
            await msg.answer("Ne udalos zapustit.")

    async def cmd_stop(self, msg):
        if not await self._is_admin(msg):
            return
        if not self.broker.running:
            await msg.answer("Bot uzhe ostanovlen.")
            return
        ok = await self.broker.stop()
        if ok:
            await msg.answer("Bot ostanovlen. Sostojanie sokhraneno.")
        else:
            await msg.answer("Ne udalos ostanovit.")

    async def cmd_status(self, msg):
        if not await self._is_admin(msg):
            return
        await msg.answer(await self.broker.get_status_text(),
                         parse_mode=ParseMode.HTML)

    async def cmd_stats(self, msg):
        if not await self._is_admin(msg):
            return
        s = self.broker.state["stats"]
        text = (
            "<b>Polnaja statistika</b>\n\n"
            "Zavershennykh tsiklov: <b>" + str(s["cycles"]) + "</b>\n"
            "Vsego sdelok: <b>" + str(s["trades"]) + "</b>\n"
            "Summarnaja komissija: <b>" + str(round(s["fees_paid"], 4))
            + "</b> USDT\n"
            "Chistaja pribyl: <b>" + str(round(s["realized_pnl"], 4))
            + "</b> USDT\n"
            "Srednee za tsikl: <b>"
            + str(round(s["realized_pnl"] / max(s["cycles"], 1), 4))
            + "</b> USDT\n"
            "Otkrytykh pozitsij: <b>"
            + str(len(self.broker.state["open_buys"])) + "</b>"
        )
        await msg.answer(text, parse_mode=ParseMode.HTML)

    async def cmd_logs(self, msg):
        if not await self._is_admin(msg):
            return
        try:
            await msg.answer_document(
                types.FSInputFile(self.broker.trades_file),
                caption="trades.csv - zhurnal sdelok",
            )
        except Exception as e:
            await msg.answer("Ne udalos otpravit file: " + str(e))

    async def cmd_settings(self, msg):
        if not await self._is_admin(msg):
            return
        c = self.broker.config
        text = (
            "<b>Nastrojki</b>\n\n"
            "Rezhim: <code>PAPER (bez klyuchej)</code>\n"
            "Para: <code>" + c.SYMBOL + "</code>\n"
            "Summa na order: <code>" + str(c.QUOTE_PER_ORDER) + "</code> USDT\n"
            "Shag setki: <code>" + str(round(c.STEP_PCT * 100, 2)) + "%</code>\n"
            "Urovnej s kazhdo storony: <code>" + str(c.LEVELS_PER_SIDE) + "</code>\n"
            "Proverka kazhdye: <code>" + str(c.POLL_SEC) + "</code> sek\n"
            "Komissija: <code>" + str(round(c.FEE_PCT * 100, 2)) + "%</code>"
        )
        await msg.answer(text, parse_mode=ParseMode.HTML)

    async def run(self):
        logger.info("Telegram-bot zapushchen")
        await self.dp.start_polling(self.bot)
