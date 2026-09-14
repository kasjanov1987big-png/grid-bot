# -*- coding: utf-8 -*-
"""
PAPER grid-бот.

Берёт РЕАЛЬНЫЕ цены SOL/USDT с Bybit (публичный API, ключи не нужны)
и торгует ВИРТУАЛЬНЫМИ деньгами:

1. Строит сетку уровней вокруг текущей цены (шаг STEP_PCT).
2. Ниже цены — виртуальные Buy, выше — Sell.
3. Раз в POLL_SEC смотрит на рынок:
   - цена пробила уровень Buy снизу  -> засчитываем покупку, ставим Sell выше;
   - цена пробила уровень Sell сверху -> засчитываем продажу, ставим Buy ниже.
4. С каждой сделки списываем комиссию 0.1% (как на реальном Bybit),
   чтобы статистика была честной.
5. Всё пишет в trades.csv и держит в state.json.

Логика исполнения: лимитный ордер считается исполненным, когда рыночная
цена коснулась его уровня — это упрощение, для paper-теста его достаточно.
"""
import asyncio
import json
import csv
import os
import uuid
import logging
from datetime import datetime

from pybit.unified_trading import HTTP  # используем ТОЛЬКО для публичных цен

logger = logging.getLogger(__name__)


class PaperBroker:
    def __init__(self, config):
        self.config = config
        self.base_coin = config.SYMBOL.replace("USDT", "")
        # публичный доступ: без api_key — только чтение рынка
        self.session = HTTP(testnet=False)
        self.state_file = config.STATE_FILE
        self.trades_file = config.TRADES_FILE
        self.state = self._load_state()
        self.running = False
        self._task = None
        self._last_price = None

    # ---------- persistence ----------
    def _load_state(self) -> dict:
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "active": False,
                "levels": [],
                "orders": {},     # str(level_idx) -> {order_id, side, price, qty}
                "open_buys": [],  # FIFO {price, qty, fee}
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

    # ---------- рынок ----------
    async def get_price(self) -> float:
        r = await asyncio.to_thread(
            self.session.get_tickers, category="spot", symbol=self.config.SYMBOL
        )
        price = float(r["result"]["list"][0]["lastPrice"])
        self._last_price = price
        return price

    # ---------- виртуальные ордера ----------
    def _place_virtual(self, idx: int, side: str, price: float, qty: float):
        self.state["orders"][str(idx)] = {
            "order_id": str(uuid.uuid4())[:8],
            "side": side,
            "price": round(price, 2),
            "qty": round(qty, 6),
        }
        logger.info(f"Вирт. ордер {side} {round(qty,4)} @ {round(price,2)} (уровень {idx})")

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
        # бумажные балансы: под все уровни сетки + запас 5% на комиссии
        self.state["balances"] = {
            "USDT": round(c.QUOTE_PER_ORDER * len(buys) * 1.05, 2),
            self.base_coin: round(sum(c.QUOTE_PER_ORDER / p for p in sells) * 1.05, 6),
        }
        equity = self.state["balances"]["USDT"] +             self.state["balances"][self.base_coin] * price
        self.state["start_equity"] = round(equity, 2)

        for i, p in enumerate(levels):
            if p < price:
                self._place_virtual(i, "Buy", p, c.QUOTE_PER_ORDER / p)
            elif p > price:
                self._place_virtual(i, "Sell", p, c.QUOTE_PER_ORDER / p)

        self.state["active"] = True
        self._save_state()
        logger.info(f"Сетка построена: цена {price}, уровней {len(levels)}, "
                    f"ордеров {len(self.state['orders'])}, эквити {equity:.2f}")
        return levels

    # ---------- исполнение ----------
    def _execute_fill(self, idx: int, side: str, price: float, qty: float):
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
                logger.info(
                    f"ЦИКЛ: куплено {b['price']:.2f} -> продано {price:.2f} | "
                    f"чистая прибыль {pnl:.4f} USDT"
                )
            else:
                pnl = 0.0

        with open(self.trades_file, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                side, self.config.SYMBOL, round(qty, 6), price,
                f"{fee:.5f}", f"{st['realized_pnl']:.5f}",
            ])

        # встречный ордер на соседнем уровне, ТЕМ ЖЕ объёмом
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
            logger.info(f"ИСПОЛНЕН (paper) {o['side']} {o['qty']} @ {o['price']} "
                        f"(рыночная {price})")
            self._execute_fill(idx, o["side"], o["price"], o["qty"])

        if filled:
            self._save_state()

    # ---------- жизненный цикл ----------
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
                logger.error(f"Ошибка в цикле: {e}")
                await asyncio.sleep(30)
        self._save_state()

    async def start(self) -> bool:
        if self.running:
            return False
        self.running = True
        self._task = asyncio.create_task(self.loop())
        return True

    async def stop(self) -> bool:
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

    # ---------- отчёты ----------
    async def get_status_text(self) -> str:
        price = self._last_price or await self.get_price()
        b = self.state["balances"]
        s = self.state["stats"]
        equity = b["USDT"] + b[self.base_coin] * price
        return (
            f"📊 <b>Статус (PAPER)</b>
"
            f"Работает: {'✅ Да' if self.running else '❌ Нет'}
"
            f"Пара: {self.config.SYMBOL} | Цена: {price:.2f}
"
            f"Баланс: {b['USDT']:.2f} USDT + {b[self.base_coin]:.4f} {self.base_coin}
"
            f"Эквити: {equity:.2f} USDT (старт {self.state['start_equity']:.2f})
"
            f"Циклов: {s['cycles']} | Сделок: {s['trades']}
"
            f"Комиссии: {s['fees_paid']:.4f} USDT
"
            f"Чистая прибыль: {s['realized_pnl']:.4f} USDT
"
            f"Открытых ордеров: {len(self.state['orders'])}"
        )
