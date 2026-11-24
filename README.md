[![Pump.fun Paper Sprint](https://make.fun/badge/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b.svg)](https://make.fun/bounty/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b)
[![Rank](https://make.fun/badge/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b/monicazhy949/makefun-pump-any-01/rank.svg)](https://make.fun/bounty/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b)
[![Reward](https://make.fun/badge/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b/monicazhy949/makefun-pump-any-01/reward.svg)](https://make.fun/bounty/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b)

# Pump Paper Sprint Momentum Bot

Paper trading bot for the [Pump.fun Paper Sprint: Any Bot Can Win](https://make.fun/bounty/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b) competition. It trades 10 SOL of paper money on a replay of recorded pump.fun bonding-curve activity (protocol `agent-fun/replay/v2`). Nothing is traded for real.

## Strategy

Small-stake early momentum with hard exits — "buy the launch, sell the move, never marry a coin":

- **Buy:** a coin becomes a candidate on its `CreateEvent`. On the first batch where the harness size cap allows at least 0.005 SOL *and* the price is at least 2.5x its creation price, buy `min(0.05 SOL, cap)` when a position slot is free and free cash covers the buy plus tx fees. Only proven runners are bought, never the launch itself. At most 5 open positions, flat 0.05 SOL sizing, so no single coin dominates the book.
- **Filters:** never chase a launch that already ran above 4x its creation price, and never buy one that already dumped below 0.5x of it. A coin whose curve completes first is dropped.
- **Sell (whole position):** take profit at +25%, stop loss at −15%, and a trailing stop that arms at +10% and sells 15% below the best price seen since entry. A position still held after 7,200 slots (~25 minutes of chain time) is sold whatever it did: most coins go quiet minutes after launch, and a dead coin must not occupy one of the 5 slots forever. The replay closes completed curves and flattens the rest at the end.
- **Turnover:** exits free slots for fresh launches, which is how the 20-coin round-trip bar (≥ 0.01 SOL each) is met.
- **Determinism:** no clock, no environment, no randomness; candidate order follows the batch's own event/mark order. Two runs produce identical action logs.

## Layout

- `main.py` — the entrypoint (Python 3.13, standard library only).
- `vendor/makefun_bot.py` — the kit's Python SDK shim, byte-identical copy of `sdk/python/makefun_bot.py`.

## Run

```sh
PYTHONHASHSEED=0 python3 -P -s main.py
```

The bot reads `hello` / `batch` / `done` JSON lines on stdin and writes one `reply` per batch on stdout; diagnostics go to stderr.

## License

MIT — see [LICENSE](LICENSE).
