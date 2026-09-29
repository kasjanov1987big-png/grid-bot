# -*- coding: utf-8 -*-
"""
Telegram-interfejs dlja upravlenija paper-botom so smartfona.
Versija 3.9: multisymbol, winrate, filtr trenda (vykl po umolch.) - neskolko PaperBroker, knopka "Para"
perekljuchaet aktivnuju paru. Uvedomlenija s prefiksom pary pri
multisymbol. Kod tolko na latinice.
"""
import logging
import os
import csv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)


class TelegramController:
    def __init__(self, token, admin_id, brokers):
        # brokers: dict {SYMBOL: PaperBroker} (ili odin broker - oborachivaem)
        if not isinstance(brokers, dict):
            brokers = {brokers.config.SYMBOL: brokers}
        self.bot = Bot(token=token)
        self.dp = Dispatcher()
        self.admin_id = admin_id
        self.brokers = brokers
        self.symbols = list(brokers.keys())
        self.cur = self.symbols[0]
        self.broker = brokers[self.cur]
        multi = len(self.symbols) > 1
        for sym, br in brokers.items():
            br.notify = self._make_notifier(sym, multi)
            br.notify_file = self._make_file_sender(sym, multi)
        self._register()

    def _make_notifier(self, sym, multi):
        async def _n(text):
            await self._notify_admin(("[" + sym + "] " if multi else "") + text)
        return _n

    def _make_file_sender(self, sym, multi):
        async def _f(path, caption=""):
            await self._send_document(
                path, (("[" + sym + "] " if multi else "") + caption))
        return _f

    def _register(self):
        self.dp.message(Command("start"))(self.cmd_start)
        self.dp.message(F.text == "Zapustit setku")(self.cmd_run)
        self.dp.message(F.text == "Ostanovit")(self.cmd_stop)
        self.dp.message(F.text == "Status")(self.cmd_status)
        self.dp.message(F.text == "Statistika")(self.cmd_stats)
        self.dp.message(F.text == "Logi")(self.cmd_logs)
        self.dp.message(F.text == "Nastrojki")(self.cmd_settings)
        self.dp.message(F.text == "Grafik")(self.cmd_graph)
        self.dp.message(F.text == "Para")(self.cmd_para)
        self.dp.callback_query(F.data.startswith("set:"))(self.cb_settings)

    async def _notify_admin(self, text):
        try:
            await self.bot.send_message(self.admin_id, text)
        except Exception as e:
            logger.error("Notify error: %s", e)

    async def _send_document(self, path, caption=""):
        try:
            await self.bot.send_document(
                self.admin_id, types.FSInputFile(path), caption=caption)
        except Exception as e:
            logger.error("Send file error: %s", e)

    async def send(self, text):
        """Otpravka soobshchenija adminu izvne (napr., iz main.py)."""
        await self._notify_admin(text)

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
                [
                    types.KeyboardButton(text="Grafik"),
                    types.KeyboardButton(text="Para"),
                ],
            ],
            resize_keyboard=True,
        )
        await msg.answer(
            "<b>PAPER grid-bot</b> (realnye ceny Bybit, virtualnye dengi).\n"
            "Aktivnaja para: <b>" + self.cur + "</b>. "
            "Knopka 'Para' - perekljuchenie. Upravlenie knopkami nizhe.",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )

    async def cmd_para(self, msg):
        if not await self._is_admin(msg):
            return
        i = self.symbols.index(self.cur)
        self.cur = self.symbols[(i + 1) % len(self.symbols)]
        self.broker = self.brokers[self.cur]
        await msg.answer(
            "Aktivnaja para: " + self.cur + "\n"
            "Vse knopki (Status, Grafik, Nastrojki...) teper rabotajut s nej.")

    async def cmd_run(self, msg):
        if not await self._is_admin(msg):
            return
        if self.broker.running:
            await msg.answer("Bot uzhe rabotaet (" + self.cur + ").")
            return
        await msg.answer("Zapuskayu (" + self.cur + ")... "
                         "Otchet o postroenii setki pridjet otdelno.")
        ok = await self.broker.start()
        if not ok:
            await msg.answer("Ne udalos zapustit.")

    async def cmd_stop(self, msg):
        if not await self._is_admin(msg):
            return
        if not self.broker.running:
            await msg.answer("Bot uzhe ostanovlen (" + self.cur + ").")
            return
        ok = await self.broker.stop()
        if ok:
            await msg.answer("Bot ostanovlen (" + self.cur +
                             "). Sostojanie sokhraneno.")
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
            "<b>Polnaja statistika</b> (" + self.cur + ")\n\n"
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
            "Winrate: <b>"
            + str(round(100 * s.get("cycles_win", 0)
                        / max(s["cycles"], 1), 1))
            + "%</b> (" + str(s.get("cycles_win", 0)) + " win / "
            + str(s.get("cycles_loss", 0)) + " loss)\n"
            "Luchshij tsikl: <b>+"
            + str(round(s.get("best_cycle", 0.0), 4))
            + "</b> USDT | Khudshij: <b>"
            + str(round(s.get("worst_cycle", 0.0), 4))
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

    async def cmd_graph(self, msg):
        if not await self._is_admin(msg):
            return
        path = self.broker.config.EQUITY_FILE
        if not os.path.exists(path):
            await msg.answer(
                "Net dannykh dlja grafika (" + self.cur + "). "
                "Pojavjatsja cherez ~1 chas posle zapuska bota.")
            return
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            times, equities, realized = [], [], []
            with open(path, "r", encoding="utf-8") as f:
                for row in csv.reader(f):
                    if row and row[0] != "time":
                        times.append(row[0])
                        equities.append(float(row[2]))
                        realized.append(float(row[3]))
            if len(times) < 2:
                await msg.answer(
                    "Slishkom malo tochek dlja grafika: podozhdi "
                    "neskolko chasov.")
                return
            fig, ax = plt.subplots(figsize=(8, 4.5))
            ax.plot(times, equities, marker="o", color="tab:blue",
                    label="Equity (USDT)")
            ax.set_ylabel("Equity, USDT", color="tab:blue")
            ax.tick_params(axis="y", labelcolor="tab:blue")
            ax2 = ax.twinx()
            ax2.plot(times, realized, marker=".", color="tab:orange",
                     label="Realiz. pribyl")
            ax2.set_ylabel("Realiz. pribyl, USDT", color="tab:orange")
            ax2.tick_params(axis="y", labelcolor="tab:orange")
            lo, hi = min(equities), max(equities)
            pad = max((hi - lo) * 0.2, 0.5)
            ax.set_ylim(lo - pad, hi + pad)
            lo2, hi2 = min(realized), max(realized)
            pad2 = max((hi2 - lo2) * 0.2, 0.1)
            ax2.set_ylim(lo2 - pad2, hi2 + pad2)
            ax.set_title("Grid-bot: " + self.cur)
            ax.grid(True, alpha=0.3)
            lines = ax.get_lines() + ax2.get_lines()
            ax.legend(lines, [l.get_label() for l in lines], loc="best")
            step = max(1, len(times) // 8)
            ax.set_xticks(range(0, len(times), step))
            ax.set_xticklabels(
                [times[i] for i in range(0, len(times), step)],
                rotation=45, fontsize=7)
            fig.tight_layout()
            png = os.path.join(os.path.dirname(path), "equity_graph.png")
            fig.savefig(png, dpi=110)
            plt.close(fig)
            await msg.answer_photo(
                types.FSInputFile(png),
                caption=self.cur + " | Ekviti: " + str(round(equities[-1], 2))
                + " USDT | tochek: " + str(len(times)))
        except Exception as e:
            await msg.answer("Ne udalos postroit grafik: " + str(e))

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
            "<b>Nastrojki</b> (" + self.cur + ") - primenjajutsja pri "
            "sledujushchem zapuske setki\n\n"
            "Rezhim: <code>PAPER (bez klyuchej)</code>\n"
            "Summa na order: <code>" + str(round(quote, 2)) + "</code> USDT\n"
            "Shag setki: <code>" + str(round(step * 100, 2)) + "%</code>\n"
            "Urovnej s kazhdo storony: <code>" + str(levels) + "</code>\n"
            "Proverka kazhdye: <code>" + str(poll) + "</code> sek\n"
            "Slippage: <code>" + str(round(slip * 100, 3)) + "%</code>\n"
            "Filtr trenda: <code>" + ("VKL" if self.broker.state["settings"].get("filter_on", 0) else "VYKL") + "</code> "
            "(porog <code>" + str(round(abs(self.broker.state["settings"].get("trend_thresh", 0.02)) * 100, 1)) + "%</code> za 6ch)\n"
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
                [
                    types.InlineKeyboardButton(text="Filtr trenda VKL/VYKL", callback_data="set:filter_on:0"),
                ],
                [
                    types.InlineKeyboardButton(text="Porog -0.5%", callback_data="set:trend_thresh:-0.005"),
                    types.InlineKeyboardButton(text="Porog +0.5%", callback_data="set:trend_thresh:+0.005"),
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
        await cq.answer("Sokhraneno (" + self.cur + "): " + key + " = "
                        + str(round(new_val, 4)))
        await self.cmd_settings(cq.message)

    async def run(self):
        logger.info("Telegram-bot zapushchen. Pary: %s", ", ".join(self.symbols))
        await self.dp.start_polling(self.bot)
