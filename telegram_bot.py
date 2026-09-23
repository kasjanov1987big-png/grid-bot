# -*- coding: utf-8 -*-
"""
Telegram-interfejs dlja upravlenija paper-botom so smartfona.
Versija 2.2: bystryj zapusk, Status s orderami, redaktiruemye Nastrojki,
polnyj bjekap (trades.csv + state.json) odnoj knopkoj.
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
        broker.notify = self._notify_admin
        self._register()

    def _register(self):
        self.dp.message(Command("start"))(self.cmd_start)
        self.dp.message(F.text == "Zapustit setku")(self.cmd_run)
        self.dp.message(F.text == "Ostanovit")(self.cmd_stop)
        self.dp.message(F.text == "Status")(self.cmd_status)
        self.dp.message(F.text == "Statistika")(self.cmd_stats)
        self.dp.message(F.text == "Logi")(self.cmd_logs)
        self.dp.message(F.text == "Nastrojki")(self.cmd_settings)
        self.dp.callback_query(F.data.startswith("set:"))(self.cb_settings)

    async def _notify_admin(self, text):
        try:
            await self.bot.send_message(self.admin_id, text)
        except Exception as e:
            logger.error("Notify error: %s", e)

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
        await msg.answer("Zapuskayu... Otchet o postroenii setki pridjet otdelno.")
        ok = await self.broker.start()
        if not ok:
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
            "Prodazh inventarja: <b>" + str(s.get("inv_sells", 0)) + "</b>\n"
            "Perestroek setki: <b>" + str(s.get("rebuilds", 0)) + "</b>\n"
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
        for path, cap in [
            (self.broker.trades_file, "trades.csv - zhurnal sdelok"),
            (self.broker.state_file, "state.json - polnoe sostojanie"),
        ]:
            try:
                await msg.answer_document(
                    types.FSInputFile(path), caption=cap)
            except Exception as e:
                await msg.answer("Ne udalos otpravit " + path + ": " + str(e))

    async def cmd_settings(self, msg):
        if not await self._is_admin(msg):
            return
        c = self.broker.config
        s = self.broker.state["settings"]
        step = s.get("step", c.STEP_PCT)
        quote = s.get("quote", c.QUOTE_PER_ORDER)
        levels = s.get("levels", c.LEVELS_PER_SIDE)
        poll = s.get("poll", c.POLL_SEC)
        slip = s.get("slippage", c.SLIPPAGE_PCT)
        rextra = s.get("rebuild_extra", 2)

        text = (
            "<b>Nastrojki</b> (primenjajutsja pri sledujushchem zapuske setki)\n\n"
            "Rezhim: <code>PAPER (bez klyuchej)</code>\n"
            "Para: <code>" + c.SYMBOL + "</code>\n"
            "Summa na order: <code>" + str(round(quote, 2)) + "</code> USDT\n"
            "Shag setki: <code>" + str(round(step * 100, 2)) + "%</code>\n"
            "Urovnej s kazhdo storony: <code>" + str(levels) + "</code>\n"
            "Proverka kazhdye: <code>" + str(poll) + "</code> sek\n"
            "Slippage: <code>" + str(round(slip * 100, 3)) + "%</code>\n"
            "Rebuild posle urovnej za krajem: <code>" + str(rextra) + "</code>\n"
            "Komissija: <code>" + str(round(c.FEE_PCT * 100, 2)) + "%</code>\n"
            "Limit prosadki dnja: <code>" + str(round(c.DD_LIMIT_PCT * 100, 1)) + "%</code>"
        )
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="Shag -0.2%", callback_data="set:step:-0.002"),
                    types.InlineKeyboardButton(text="Shag +0.2%", callback_data="set:step:+0.002"),
                ],
                [
                    types.InlineKeyboardButton(text="Summa -1$", callback_data="set:quote:-1.0"),
                    types.InlineKeyboardButton(text="Summa +1$", callback_data="set:quote:+1.0"),
                ],
                [
                    types.InlineKeyboardButton(text="Urovni -1", callback_data="set:levels:-1"),
                    types.InlineKeyboardButton(text="Urovni +1", callback_data="set:levels:+1"),
                ],
                [
                    types.InlineKeyboardButton(text="Interval -5sek", callback_data="set:poll:-5"),
                    types.InlineKeyboardButton(text="Interval +5sek", callback_data="set:poll:+5"),
                ],
                [
                    types.InlineKeyboardButton(text="Rebld -1", callback_data="set:rebuild_extra:-1"),
                    types.InlineKeyboardButton(text="Rebld +1", callback_data="set:rebuild_extra:+1"),
                ],
                [
                    types.InlineKeyboardButton(text="Slip -0.05%", callback_data="set:slippage:-0.0005"),
                    types.InlineKeyboardButton(text="Slip +0.05%", callback_data="set:slippage:+0.0005"),
                ],
            ]
        )
        await msg.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    async def cb_settings(self, cq: types.CallbackQuery):
        if cq.from_user.id != self.admin_id:
            await cq.answer("Dostup zapreshchen.", show_alert=True)
            return
        parts = cq.data.split(":")
        if len(parts) != 3:
            await cq.answer("Neizvestnaja komanda.")
            return
        key = parts[1]
        delta = float(parts[2])
        new_val = self.broker.update_setting(key, delta)
        await cq.answer("Sokhraneno: " + key + " = " + str(round(new_val, 4)))
        await self.cmd_settings(cq.message)

    async def run(self):
        logger.info("Telegram-bot zapushchen")
        await self.dp.start_polling(self.bot)
