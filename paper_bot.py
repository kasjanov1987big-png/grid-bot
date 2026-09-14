# -*- coding: utf-8 -*-
"""
PAPER grid-bot.

Beret REALNYE ceny SOL/USDT s Bybit (publichnyj API, klyuchi ne nuzhny)
i torruet VIRTUALNYMI dengami.

1. Stroit setku urovnej vokrug tekushchej ceny (shag STEP_PCT).
2. Nizhe ceny - virtualnye Buy, vyshe - Sell.
3. Raz v POLL_SEC smotrit na rynok:
   - cena probla uroven Buy snizu  -> zaschityvaem pokupku, stavim Sell vyshe;
   - cena probla uroven Sell sverkhu -> zaschityvaem prodazhu, stavim Buy nizhe.
4. S kazhdo sdelki spisivaem komissiju 0.1% (kak na realnom Bybit),
   chtoby statistika byla chestnoj.
5. Vse pishit v trades.csv i derzhit v state.json.

Logika ispolnenija: limitnyj order schitaetsja ispolnennym, kogda rynochnaja
cena kosnulas ego urovnja - eto uproshchenie, dlja paper-testa dostatochno.
"""
import asyncio
import json
import csv
import os
import uuid
import logging
from datetime import datetime

from pybit.unified_trading import HTTP

logger = logging.getLogger(__name__)


class PaperBroker:
    def __init__(self, config):
        self.config = config
        self.base_coin = config.SYMBOL.replace("USDT", "")
        self.session = HTTP(testnet=False)
        self.state_file = config.STATE_FILE
        self.trades_file = config.TRADES_FILE
        self.state = self._load_state()
        self.running = False
        self._task = None
        self._last_price = None

    def _load_state(self):
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "active": False,
                "levels": [],
                "orders": {},
                "open_buys": [],
                "balances": {"USDT": 0.0, self.base_coin: 0.0},
                "start_equity": 0.0,
                "stats": {"cycles": 0, "trades": 0, "realized_pnl": 0.0,
                          "fees_paid": 0.0},
            }

    def _save_state(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def _init_csv(self):
        if not os.path.exists(self.trades_file):
            with open(self.trades_file, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(
                    ["time", "side", "symbol", "qty", "price", "fee", "cum_net_pnl"]
                )

    async def get_price(self):
        r = await asyncio.to_thread(
            self.session.get_tickers, category="spot", symbol=self.config.SYMBOL
        )
        price = float(r["result"]["list"][0]["lastPrice"])
        self._last_price = price
        return price

    def _place_virtual(self, idx, side, price, qty):
        self.state["orders"][str(idx)] = {
            "order_id": str(uuid.uuid4())[:8],
            "side": side,
            "price": round(price, 2),
            "qty": round(qty, 6),
        }
        logger.info("Virt. order %s %s @ %s (level %s)",
                    side, round(qty, 4), round(price, 2), idx)

    async def build_grid(self):
        price = await self.get_price()
        c = self.config
        levels = [round(price, 2)]
        for i in range(1, c.LEVELS_PER_SIDE + 1):
            levels.insert(0, round(price * (1 - c.STEP_PCT) ** i, 2))
            levels.append(round(price * (1 + c.STEP_PCT) ** i, 2))

        buys = [p for p in levels if p < price]
        sells = [p for p in levels if p > price]

        self.state["levels"] = levels
        self.state["orders"] = {}
        self.state["open_buys"] = []
        self.state["balances"] = {
            "USDT": round(c.QUOTE_PER_ORDER * len(buys) * 1.05, 2),
            self.base_coin: round(sum(c.QUOTE_PER_ORDER / p for p in sells) * 1.05, 6),
        }
        equity = self.state["balances"]["USDT"] + \
            self.state["balances"][self.base_coin] * price
        self.state["start_equity"] = round(equity, 2)

        for i, p in enumerate(levels):
            if p < price:
                self._place_virtual(i, "Buy", p, c.QUOTE_PER_ORDER / p)
            elif p > price:
                self._place_virtual(i, "Sell", p, c.QUOTE_PER_ORDER / p)

        self.state["active"] = True
        self._save_state()
        logger.info("Setka postroena: cena %s, urovnej %s, orderov %s, ekviti %s",
                    price, len(levels), len(self.state["orders"]), round(equity, 2))
        return levels

    def _execute_fill(self, idx, side, price, qty):
        fee = price * qty * self.config.FEE_PCT
        base = self.base_coin
        bal = self.state["balances"]
        st = self.state["stats"]
        st["trades"] += 1
        st["fees_paid"] += fee

        if side == "Buy":
            bal["USDT"] -= price * qty + fee
            bal[base] += qty
            self.state["open_buys"].append({"price": price, "qty": qty, "fee": fee})
            pnl = 0.0
        else:
            bal[base] -= qty
            bal["USDT"] += price * qty - fee
            if self.state["open_buys"]:
                b = self.state["open_buys"].pop(0)
                pnl = (price - b["price"]) * b["qty"] - b["fee"] - fee
                st["realized_pnl"] += pnl
                st["cycles"] += 1
                logger.info("TSIKL: kup. %s -> prod. %s | chistaja pribyl %s USDT",
                            round(b["price"], 2), price, round(pnl, 4))
            else:
                pnl = 0.0

        with open(self.trades_file, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                side, self.config.SYMBOL, round(qty, 6), price,
                round(fee, 5), round(st["realized_pnl"], 5),
            ])

        levels = self.state["levels"]
        if side == "Buy" and idx + 1 < len(levels):
            self._place_virtual(idx + 1, "Sell", levels[idx + 1], qty)
        elif side == "Sell" and idx - 1 >= 0:
            self._place_virtual(idx - 1, "Buy", levels[idx - 1], qty)

        del self.state["orders"][str(idx)]

    async def check_fills(self):
        price = await self.get_price()
        filled = []
        for idx_str, o in list(self.state["orders"].items()):
            if o["side"] == "Buy" and price <= o["price"]:
                filled.append((int(idx_str), o))
            elif o["side"] == "Sell" and price >= o["price"]:
                filled.append((int(idx_str), o))

        for idx, o in filled:
            logger.info("ISPOLNEN (paper) %s %s @ %s (ryn. %s)",
                        o["side"], o["qty"], o["price"], price)
            self._execute_fill(idx, o["side"], o["price"], o["qty"])

        if filled:
            self._save_state()

    async def loop(self):
        self._init_csv()
        await self.build_grid()
        while self.running:
            try:
                await self.check_fills()
                await asyncio.sleep(self.config.POLL_SEC)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Oshibka v tsikle: %s", e)
                await asyncio.sleep(30)
        self._save_state()

    async def start(self):
        if self.running:
            return False
        self.running = True
        self._task = asyncio.create_task(self.loop())
        return True

    async def stop(self):
        if not self.running:
            return False
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.state["active"] = False
        self._save_state()
        return True

    async def get_status_text(self):
        price = self._last_price or await self.get_price()
        b = self.state["balances"]
        s = self.state["stats"]
        equity = b["USDT"] + b[self.base_coin] * price
        lines = [
            "STATUS (PAPER)",
            "Rabotaet: " + ("DA" if self.running else "NET"),
            "Para: " + self.config.SYMBOL + " | TSena: " + str(round(price, 2)),
            "Balans: " + str(round(b["USDT"], 2)) + " USDT + " +
            str(round(b[self.base_coin], 4)) + " " + self.base_coin,
            "Ekviti: " + str(round(equity, 2)) +
            " USDT (start " + str(round(self.state["start_equity"], 2)) + ")",
            "Tsiklov: " + str(s["cycles"]) + " | Sdelok: " + str(s["trades"]),
            "Komissii: " + str(round(s["fees_paid"], 4)) + " USDT",
            "Chistaja pribyl: " + str(round(s["realized_pnl"], 4)) + " USDT",
            "Otkrytykh orderov: " + str(len(self.state["orders"])),
        ]
        return "\n".join(lines)
