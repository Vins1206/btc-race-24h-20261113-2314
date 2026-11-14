# btc-race-24h-20261113-2314 — cbBTC momentum bot

Paper-trading bot for Coinbase Wrapped BTC (cbBTC) on the
agent-fun/bars-replay/v1 harness: it reads one 1-minute bar per batch
(hello, then batch after batch) and answers with orders that fill at the
next bar's open. Long only, one position, $1,000 paper capital.

## Strategy

Selective momentum with an EMA turn check and a volatility filter.
An entry needs all of these on the same bar close:

- Context: trailing 360-bar return is a deep pullback (<= -1.5%) or a
  strong uptrend (>= +2.0% plus a 240-bar breakout).
- Momentum: +0.5% over the last 30 bars (pullback) or +0.8% over the
  last 60 bars (trend).
- EMA: close above EMA(12), EMA(12) rising over 10 bars; trend entries
  also need EMA(12) above EMA(48).
- Volatility filter: stdev of the last 20 one-bar returns <= 0.15%.

Exits: take profit +1.2%, stop loss -0.5%, or 480 bars held. Position
size is 75% of cash, slippage is capped at 100 bps per order, and a
240-bar cooldown after each exit keeps trade frequency (and fees) low.

## Run

Python 3.13, standard library only. The protocol shim is vendored
byte-for-byte from the competition kit at `vendor/makefun_bars.py`;
`main.py` holds the strategy and is fully deterministic.
