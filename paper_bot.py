# -*- coding: utf-8 -*-
"""
PAPER grid-bot. Versija 3.1.

Izmenenija vs 2.2:
- V3.1: bank perezhivajet zapuski. Balansy initsializirujutsja odin raz
  ot START_BALANCE i bolshe ne sbrosyvajutsja pri build_grid.
  Migracija: starye sostojanija (do bank_initialized) schitajutsja
  proinitsializirovannymi - nakoplennyj bank ne terjaetsja.
- A1: prodazhi startovogo inventarja schitajutsja po sebestoimosti (inv_cost);
- A2: tsikly parnye po urovnjam (buy idx -> sell idx+1), fallback - inventar;
- A3: slippage pri ispolnenii (nastrojka, default 0.05%);
- A4: watchdog - uvedomlenie pri 5 oshibkakh podrjad i pri vosstanovlenii;
- B1: dnevnoj limit prosadki - ostanovka + uvedomlenie;
- B2: ezhednevnyj dajdzhest v Telegram.
"""
import asyncio
import json
import csv
import os
import time
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
        self.state.setdefault("settings", {})
        self.running = False
        self._task = None
        self._last_price = None
        self._started_at = None
        self.notify = None
        self._consec_errors = 0
        self._error_alerted = False

    # ---------- nastrojki ----------

    def _eff(self, key, default):
        return self.state["settings"].get(key, default)

    def eff_step(self):
        return float(self._eff("step", self.config.STEP_PCT))

    def eff_quote(self):
        return float(self._eff("quote", self.config.QUOTE_PER_ORDER))

    def eff_levels(self):
        return int(self._eff("levels", self.config.LEVELS_PER_SIDE))

    def eff_poll(self):
        return int(self._eff("poll", self.config.POLL_SEC))

    def eff_slippage(self):
        return float(self._eff("slippage", self.config.SLIPPAGE_PCT))

    def update_setting(self, key, delta):
        cur = self._eff(key, {
            "step": self.config.STEP_PCT,
            "quote": self.config.QUOTE_PER_ORDER,
            "levels": self.config.LEVELS_PER_SIDE,
            "poll": self.config.POLL_SEC,
            "slippage": self.config.SLIPPAGE_PCT,
            "rebuild_extra": 2,
        }[key])
        new = cur + delta
        if key == "step":
            new = max(0.002, min(0.05, new))
        elif key == "quote":
            new = max(1.0, min(500.0, new))
        elif key == "levels":
            new = int(max(1, min(20, new)))
        elif key == "poll":
            new = int(max(3, min(300, new)))
        elif key == "rebuild_extra":
            new = int(max(1, min(10, new)))
        elif key == "slippage":
            new = max(0.0, min(0.005, new))
        self.state["settings"][key] = new
        self._save_state()
        return new

    # ---------- sostojanie ----------

    def _load_state(self):
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            st = {
                "active": False,
                "levels": [],
                "orders": {},
                "open_buys": [],
                "balances": {"USDT": 0.0, self.base_coin: 0.0},
                "start_equity": 0.0,
                "inv_cost": 0.0,
                "day": None,
                "day_start_equity": 0.0,
                "day_start_realized": 0.0,
                "day_trades": 0,
                "day_cycles": 0,
                "down_alerted": False,
                "stats": {"cycles": 0, "trades": 0, "realized_pnl": 0.0,
                          "fees_paid": 0.0, "inv_sells": 0, "rebuilds": 0},
            }
        # V3.1: starye sostojanija (do bank_initialized) schitaem
        # proinitsializirovannymi - chtoby ne sbrosit nakoplennyj bank
        if "bank_initialized" not in st:
            st["bank_initialized"] = bool(st.get("start_equity"))
        return st

    def _save_state(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def _init_csv(self):
        if not os.path.exists(self.trades_file):
            with open(self.trades_file, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(
                    ["time", "side", "symbol", "qty", "price", "fee", "cum_net_pnl"]
                )

    def _init_day(self, equity):
        self.state["day"] = datetime.now().strftime("%Y-%m-%d")
        self.state["day_start_equity"] = round(equity, 2)
        self.state["day_start_realized"] = self.state["stats"]["realized_pnl"]
        self.state["day_trades"] = 0
        self.state["day_cycles"] = 0

    def _init_bank(self, price, levels):
        """V3.1: odin raz delit START_BALANCE mezhdu USDT i bazoj monetoj."""
        n_buy = sum(1 for p in levels if p < price)
        n_sell = sum(1 for p in levels if p > price)
        total = n_buy + n_sell
        if total == 0:
            n_buy = n_sell = 1
            total = 2
        usdt_part = self.config.START_BALANCE * n_buy / total
        base_part = self.config.START_BALANCE - usdt_part
        self.state["balances"] = {
            "USDT": round(usdt_part, 2),
            self.base_coin: round(base_part / price, 6),
        }

    async def get_price(self):
        r = await asyncio.to_thread(
            self.session.get_tickers, category="spot", symbol=self.config.SYMBOL
        )
        price = float(r["result"]["list"][0]["lastPrice"])
        self._last_price = price
        return price

    # ---------- setka ----------

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
        step = self.eff_step()
        quote = self.eff_quote()
        n = self.eff_levels()

        levels = [round(price, 2)]
        for i in range(1, n + 1):
            levels.insert(0, round(price * (1 - step) ** i, 2))
            levels.append(round(price * (1 + step) ** i, 2))

        self.state["levels"] = levels
        self.state["orders"] = {}
        self.state["open_buys"] = []
        self.state["inv_cost"] = price   # A1: sebestoimost inventarja

        # V3.1: bank perezhivajet zapuski - initsializiruem tolko odin raz
        if not self.state.get("bank_initialized"):
            self._init_bank(price, levels)
            self.state["bank_initialized"] = True

        b = self.state["balances"]
        equity = b["USDT"] + b[self.base_coin] * price
        # start_equity fiksiruetsja odin raz - Itog PnL otnositsja k deposity
        if not self.state.get("start_equity"):
            self.state["start_equity"] = round(equity, 2)
        self._init_day(equity)

        for i, p in enumerate(levels):
            if p < price:
                self._place_virtual(i, "Buy", p, quote / p)
            elif p > price:
                self._place_virtual(i, "Sell", p, quote / p)

        self.state["active"] = True
        self._save_state()
        logger.info("Setka postroena: cena %s, urovnej %s, orderov %s, ekviti %s",
                    price, len(levels), len(self.state["orders"]), round(equity, 2))
        return levels

    # ---------- proboj setki ----------

    def _grid_breached(self, price):
        levels = self.state["levels"]
        if not levels:
            return None
        step = self.eff_step()
        extra = int(self._eff("rebuild_extra", 2))
        if price > levels[-1] * (1 + step) ** extra:
            return "up"
        if price < levels[0] * (1 - step) ** extra:
            return "down"
        return None

    async def rebuild_grid(self, price):
        bal = self.state["balances"]
        st = self.state["stats"]
        step = self.eff_step()
        quote = self.eff_quote()
        n = self.eff_levels()
        base = self.base_coin

        for b in self.state["open_buys"]:
            pnl = (price - b["price"]) * b["qty"] - b["fee"]
            st["realized_pnl"] += pnl
        self.state["open_buys"] = []
        st["rebuilds"] = st.get("rebuilds", 0) + 1
        if bal[base] > 0:
            self.state["inv_cost"] = price   # novaja sebestoimost inventarja

        levels = [round(price, 2)]
        for i in range(1, n + 1):
            levels.insert(0, round(price * (1 - step) ** i, 2))
            levels.append(round(price * (1 + step) ** i, 2))

        self.state["levels"] = levels
        self.state["orders"] = {}
        self.state["down_alerted"] = False

        usdt_free = bal["USDT"]
        base_free = bal[base]
        fee_k = 1 + self.config.FEE_PCT

        for i, p in enumerate(levels):
            if p < price:
                q = min(quote, usdt_free / fee_k)
                if q >= 1.0:
                    self._place_virtual(i, "Buy", p, q / p)
                    usdt_free -= q * fee_k
            elif p > price:
                q_qty = min(quote / p, base_free)
                if q_qty * p >= 1.0:
                    self._place_virtual(i, "Sell", p, q_qty)
                    base_free -= q_qty

        self._save_state()
        logger.info("Setka perestroena: cena %s, orderov %s, rebuild #%s",
                    price, len(self.state["orders"]), st["rebuilds"])
        if self.notify:
            try:
                await self.notify(
                    "Setka perestroena ot ceny " + str(round(price, 2)) +
                    "\nBuy " + str(self._count("Buy")) + " / Sell " +
                    str(self._count("Sell")) + " | Rebuild #" +
                    str(st["rebuilds"])
                )
            except Exception as e:
                logger.error("Notify error: %s", e)

    # ---------- ispolnenija ----------

    def _can_fill(self, side, price, qty):
        bal = self.state["balances"]
        fee = price * qty * self.config.FEE_PCT
        if side == "Buy":
            return bal["USDT"] >= price * qty + fee
        return bal[self.base_coin] >= qty

    def _execute_fill(self, idx, side, price, qty):
        fee = price * qty * self.config.FEE_PCT
        base = self.base_coin
        bal = self.state["balances"]
        st = self.state["stats"]
        st["trades"] += 1
        st["fees_paid"] += fee
        self.state["day_trades"] = self.state.get("day_trades", 0) + 1

        if side == "Buy":
            bal["USDT"] -= price * qty + fee
            bal[base] += qty
            self.state["open_buys"].append(
                {"price": price, "qty": qty, "fee": fee, "idx": idx})
            pnl = 0.0
        else:
            bal[base] -= qty
            bal["USDT"] += price * qty - fee
            paired = None
            for i, b in enumerate(self.state["open_buys"]):
                if b.get("idx") == idx - 1:
                    paired = self.state["open_buys"].pop(i)
                    break
            if paired is not None:
                b = paired
                pnl = (price - b["price"]) * b["qty"] - b["fee"] - fee
                st["realized_pnl"] += pnl
                st["cycles"] += 1
                self.state["day_cycles"] = \
                    self.state.get("day_cycles", 0) + 1
                logger.info(
                    "TSIKL: kup. %s -> prod. %s | chistaja pribyl %s USDT",
                    round(b["price"], 2), price, round(pnl, 4))
            else:
                cost = self.state.get("inv_cost") or price
                pnl = (price - cost) * qty - fee
                st["realized_pnl"] += pnl
                st["inv_sells"] = st.get("inv_sells", 0) + 1
                logger.info(
                    "PRODAZHA INVENTARJA: sebest. %s -> prod. %s | pribyl %s",
                    round(cost, 2), price, round(pnl, 4))

        with open(self.trades_file, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                side, self.config.SYMBOL, round(qty, 6), round(price, 4),
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
        slip = self.eff_slippage()
        filled = []
        for idx_str, o in list(self.state["orders"].items()):
            fp = None
            if o["side"] == "Buy" and price <= o["price"]:
                fp = o["price"] * (1 + slip)
            elif o["side"] == "Sell" and price >= o["price"]:
                fp = o["price"] * (1 - slip)
            if fp is None:
                continue
            if not self._can_fill(o["side"], fp, o["qty"]):
                continue
            filled.append((int(idx_str), o, fp))

        for idx, o, fp in filled:
            logger.info("ISPOLNEN (paper) %s %s @ %s (uroven %s, ryn. %s)",
                        o["side"], o["qty"], round(fp, 4), o["price"], price)
            self._execute_fill(idx, o["side"], fp, o["qty"])

        if filled:
            self._save_state()

    # ---------- dnevnoj dajdzhest i limit prosadki ----------

    async def _daily_tick(self, price):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.state.get("day") == today:
            return
        b = self.state["balances"]
        equity = b["USDT"] + b[self.base_coin] * price
        if self.state.get("day"):
            s = self.state["stats"]
            day_pnl = s["realized_pnl"] - \
                self.state.get("day_start_realized", 0.0)
            eq_change = equity - \
                self.state.get("day_start_equity", equity)
            if self.notify:
                try:
                    await self.notify(
                        "DAJDJEST ZA " + self.state["day"] + "\n"
                        "Sdelok: " + str(self.state.get("day_trades", 0)) +
                        " | Tsiklov: " +
                        str(self.state.get("day_cycles", 0)) + "\n"
                        "Realiz. pribyl za den: " +
                        str(round(day_pnl, 4)) + " USDT\n"
                        "Ekviti: " + str(round(equity, 2)) +
                        " USDT (izmenenie za den: " +
                        str(round(eq_change, 2)) + ")"
                    )
                except Exception as e:
                    logger.error("Notify error: %s", e)
        self._init_day(equity)
        self._save_state()

    async def _drawdown_check(self, price):
        limit = float(self._eff("dd_limit", self.config.DD_LIMIT_PCT))
        b = self.state["balances"]
        equity = b["USDT"] + b[self.base_coin] * price
        start = self.state.get("day_start_equity", 0.0)
        if start > 0 and equity < start * (1 - limit):
            self.running = False
            self.state["active"] = False
            self._save_state()
            logger.warning("Dnevnoj limit prosadki: ekviti %s (start %s)",
                           round(equity, 2), round(start, 2))
            if self.notify:
                try:
                    await self.notify(
                        "STOP: dnevnoj limit prosadki dostignut.\n"
                        "Ekviti: " + str(round(equity, 2)) + " USDT (limit -"
                        + str(round(limit * 100, 1)) + "% ot " +
                        str(round(start, 2)) + ")\n"
                        "Bot ostanovlen. Dlja prodolzhenija - Zapustit setku."
                    )
                except Exception as e:
                    logger.error("Notify error: %s", e)

    # ---------- glavnyj tsikl ----------

    async def loop(self):
        self._init_csv()
        await self.build_grid()
        while self.running:
            try:
                await self.check_fills()
                price = self._last_price
                if price:
                    await self._daily_tick(price)
                    if not self.running:
                        break
                    await self._drawdown_check(price)
                    if not self.running:
                        break
                    breach = self._grid_breached(price)
                    if breach == "up":
                        logger.info("Setka probita vverkh - rebuild")
                        await self.rebuild_grid(price)
                    elif breach == "down":
                        if not self.state.get("down_alerted"):
                            self.state["down_alerted"] = True
                            self._save_state()
                            logger.warning("Setka probita vniz - derzhu")
                            if self.notify:
                                try:
                                    await self.notify(
                                        "VNIMANIE: TSena probila setku VNIZ "
                                        "(" + str(round(price, 2)) + "). "
                                        "Derzhu nakoplennyj SOL, zhdu "
                                        "vozvrata. Rebuild ne delaju."
                                    )
                                except Exception as e:
                                    logger.error("Notify error: %s", e)
                    else:
                        if self.state.get("down_alerted"):
                            self.state["down_alerted"] = False
                            self._save_state()
                self._consec_errors = 0
                if self._error_alerted:
                    self._error_alerted = False
                    if self.notify:
                        try:
                            await self.notify(
                                "Bot vosstanovlen. Oshibki prekratilis.")
                        except Exception as e:
                            logger.error("Notify error: %s", e)
                await asyncio.sleep(self.eff_poll())
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consec_errors += 1
                logger.error("Oshibka v tsikle (%s podrjad): %s",
                             self._consec_errors, e)
                if self._consec_errors >= 5 and \
                        not self._error_alerted and self.notify:
                    self._error_alerted = True
                    try:
                        await self.notify(
                            "VNIMANIE: 5 oshibok podrjad. "
                            "Prover Bybit/Railway."
                        )
                    except Exception as ne:
                        logger.error("Notify error: %s", ne)
                await asyncio.sleep(30)
        self._save_state()

    async def start(self):
        if self.running:
            return False
        self.running = True
        self._started_at = time.time()
        self._consec_errors = 0
        self._error_alerted = False
        self._task = asyncio.create_task(self.loop())
        return True

    async def stop(self):
        if not self.running:
            return False
        self.running = False
        self._started_at = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.state["active"] = False
        self._save_state()
        return True

    # ---------- status ----------

    def _uptime_text(self):
        if not self._started_at:
            return "-"
        sec = int(time.time() - self._started_at)
        h, sec = divmod(sec, 3600)
        m, sec = divmod(sec, 60)
        if h:
            return str(h) + "ch " + str(m) + "min"
        if m:
            return str(m) + "min " + str(sec) + "sek"
        return str(sec) + "sek"

    def _count(self, side):
        return sum(1 for o in self.state["orders"].values()
                   if o["side"] == side)

    def _nearest_orders(self, limit=3):
        if self._last_price is None or not self.state["orders"]:
            return []
        items = sorted(
            self.state["orders"].values(),
            key=lambda o: abs(o["price"] - self._last_price),
        )[:limit]
        return [o["side"] + "@" + str(o["price"]) for o in items]

    async def get_status_text(self):
        price = self._last_price or await self.get_price()
        b = self.state["balances"]
        s = self.state["stats"]
        equity = b["USDT"] + b[self.base_coin] * price
        pnl_total = equity - self.state["start_equity"]
        lines = [
            "STATUS (PAPER)",
            "Rabotaet: " + ("DA" if self.running else "NET") +
            " | Uptime: " + self._uptime_text(),
            "Para: " + self.config.SYMBOL + " | TSena: " + str(round(price, 2)),
            "Balans: " + str(round(b["USDT"], 2)) + " USDT + " +
            str(round(b[self.base_coin], 4)) + " " + self.base_coin,
            "Ekviti: " + str(round(equity, 2)) +
            " USDT (start " + str(round(self.state["start_equity"], 2)) + ")",
            "Itog PnL: " + str(round(pnl_total, 4)) + " USDT",
            "Dnes: sdelok " + str(self.state.get("day_trades", 0)) +
            " | tsiklov " + str(self.state.get("day_cycles", 0)),
            "Vsego tsiklov: " + str(s["cycles"]) +
            " | sdelok: " + str(s["trades"]),
            "Komissii: " + str(round(s["fees_paid"], 4)) + " USDT",
            "Realiz. pribyl: " + str(round(s["realized_pnl"], 4)) +
            " USDT (iz nikh inventar: " + str(s.get("inv_sells", 0)) + " prod.)",
            "Orderov: " + str(self._count("Buy")) + " Buy / " +
            str(self._count("Sell")) + " Sell",
            "Perestroek setki: " + str(s.get("rebuilds", 0)),
        ]
        near = self._nearest_orders()
        if near:
            lines.append("Blizhajshie ordera: " + ", ".join(near))
        return "\n".join(lines)
