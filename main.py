"""cbBTC paper-trading bot for agent-fun/bars-replay/v1 (bars-replay).

Strategy: selective momentum, long only, one position, stdlib only.
The bot speaks the hello / batch / orders protocol through the vendored
makefun_bars shim: every batch carries one 1-minute bar, and each reply
carries the orders decided on that bar (they fill at the next bar open).

Entry needs every filter to agree, so the bot trades rarely and fees
stay a small part of PnL (a full round trip costs about 26 bps):
  - context: the trailing 360-bar return is either a deep pullback
    (<= -1.5%) or a strong uptrend (>= +2.0% with a 240-bar breakout);
  - momentum: the last 30 bars gained >= +0.5% (pullback mode) or the
    last 60 bars gained >= +0.8% (trend mode);
  - EMA turn: the close is above EMA(12) and EMA(12) is rising versus
    10 bars ago (trend mode also needs EMA(12) above EMA(48));
  - volatility filter: the stdev of the last 20 one-bar returns is at
    most 0.15%, so chaotic minutes never trigger an entry.
Exit: take profit at +1.2% over the fill bar open, stop loss at -0.5%,
or a time stop after 480 bars in the position, whichever comes first.
Sizing is 75% of cash per entry, a 240-bar cooldown follows every exit,
and orders cap slippage at 100 bps from the latest close. Everything is
a deterministic function of the bars: no clock, no randomness, no I/O.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
FAST_SPAN = 12
SLOW_SPAN = 48
HISTORY = 360
MOM_FAST = 30
MOM_SLOW = 60
BREAKOUT = 240
VOL_SPAN = 20
DIP = -0.015
TREND = 0.020
MOM_DIP = 0.005
MOM_TREND = 0.008
VOL_MAX = 0.0015
ALLOC_PCT = 75
TAKE_PROFIT = 0.012
STOP_LOSS = -0.005
MAX_HOLD = 480
COOLDOWN = 240
MAX_SLIPPAGE_BPS = 100

closes = []
ema_fast = None
ema_slow = None
ema_fast_hist = []
entry_ref = None
entry_seq = -1
exit_seq = -10 ** 9
was_held = False


def _step_ema(value, close, span):
    if value is None:
        return close
    k = 2.0 / (span + 1)
    return value + (close - value) * k


def _should_exit(ret, held_bars):
    """Exit on the first of take profit, stop loss or the time stop."""
    return ret >= TAKE_PROFIT or ret <= STOP_LOSS or held_bars >= MAX_HOLD


def _volatility():
    if len(closes) <= VOL_SPAN:
        return None
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(len(closes) - VOL_SPAN, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return var ** 0.5


def on_batch(state, batch):
    global ema_fast, ema_slow, entry_ref, entry_seq, exit_seq, was_held
    bar = None
    for b in batch["bars"]:
        if b["symbol"] == SYMBOL:
            bar = b
    if bar is None:
        return []
    close = int(bar["c"])
    closes.append(close)
    ema_fast = _step_ema(ema_fast, close, FAST_SPAN)
    ema_slow = _step_ema(ema_slow, close, SLOW_SPAN)
    ema_fast_hist.append(ema_fast)
    held = state.positions.get(SYMBOL)
    if held is not None and held.qty <= 0:
        held = None  # a zero-quantity holding is flat, never sellable
    if held is not None and not was_held:
        # The position appeared with this batch: its fill was priced at
        # this bar's open, which anchors take profit and stop loss.
        entry_ref = int(bar["o"])
        entry_seq = state.seq
    if held is None and was_held:
        exit_seq = state.seq
        entry_ref = None
    was_held = held is not None
    if state.warming_up:
        return []
    if held is not None:
        ret = close / entry_ref - 1.0 if entry_ref else 0.0
        held_bars = state.seq - entry_seq
        if _should_exit(ret, held_bars):
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []
    if len(closes) <= HISTORY or state.seq - exit_seq < COOLDOWN:
        return []
    vol = _volatility()
    if vol is None or vol > VOL_MAX:
        return []
    ret_long = closes[-1] / closes[-1 - HISTORY] - 1.0
    ret_fast = closes[-1] / closes[-1 - MOM_FAST] - 1.0
    ret_slow = closes[-1] / closes[-1 - MOM_SLOW] - 1.0
    ema_rising = ema_fast_hist[-1] > ema_fast_hist[-11]
    above_ema = closes[-1] > ema_fast
    pullback = (ret_long <= DIP and ret_fast >= MOM_DIP
                and above_ema and ema_rising)
    breakout = (ret_long >= TREND and ret_slow >= MOM_TREND
                and closes[-1] >= max(closes[-1 - BREAKOUT:-1])
                and ema_fast > ema_slow and above_ema)
    if not (pullback or breakout):
        return []
    notional = state.cash * ALLOC_PCT // 100
    min_notional = int(state.hello["fees"]["min_notional_quote_units"])
    if notional < min_notional:
        return []
    return [{"side": "buy", "symbol": SYMBOL,
             "notional_quote_units": notional,
             "max_slippage_bps": MAX_SLIPPAGE_BPS}]


makefun_bars.run(on_batch)
