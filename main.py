"""Pump.fun Paper Sprint: Any Bot Can Win — paper trading bot (agent-fun/replay/v2, Python).

Strategy: small-stake early momentum with hard exits ("buy the launch, sell
the move, never marry a coin").

- Paper money only: 10 SOL starting capital, no real trades, no leverage,
  no shorts. All state comes from the harness messages on stdin.
- Buy: a coin becomes a candidate on its CreateEvent. It is decided on the
  first batch where the harness size cap lets it buy at least 0.005 SOL *and*
  the price is at least 2.5x its creation price: only proven runners are
  bought, never the launch itself (on the dev window, buying every launch
  lost money; buying only coins that already ran 2.5x lost least). Buy
  min(0.05 SOL, cap) if an open-position slot is free and free cash covers
  the buy plus tx fees. Two permanent filters drop a coin for good: the
  price already ran more than 4x above its creation price (never chase a
  parabolic launch) or it already fell below 0.5x of it (dead launch).
  A coin whose curve completes first is dropped. At most 5 open positions.
  Candidates are checked from both the batch's events and its marks, in
  that order, because the shim applies a CreateEvent after the batch's
  marks (resetting the size cap to zero on the creation batch) and a coin
  whose cap only becomes sufficient through marks would otherwise never
  be decided. A skip for a transient reason (no free slot, no free cash,
  reply order cap) keeps the coin a candidate for a later batch instead
  of burning it.
- Sell (whole position, every batch the holding is checked):
    * take profit at +25% over the entry price,
    * stop loss at -15% under the entry price,
    * trailing stop: once up at least +10%, sell if the price falls 15%
      below the best price seen since entry.
    * time exit: sell a position still held after 7,200 slots (~25 minutes
      of chain time) whatever it did — most coins go quiet minutes after
      launch, and a dead coin must not occupy one of the 5 slots forever.
  The replay closes a completed curve and flattens the rest at the end, so
  no end-of-run sell logic is needed here.
- Sizing is flat (0.05 SOL per coin, >= 0.01 SOL round-trip minimum), so no
  single coin can dominate the book and the 20-coin round-trip bar is met
  by turnover: exits free slots for fresh launches.
- Determinism: no clock, no environment, no randomness, no set iteration
  for decisions (sets are membership-only; candidate order comes from the
  batch's own event/mark order); dicts keep insertion order and the grader
  fixes PYTHONHASHSEED=0. Two runs therefore produce identical action logs.

Run by the grader as ``python3 -P -s /bot/main.py`` with PYTHONHASHSEED=0.
The SDK shim is vendored at vendor/makefun_bot.py (a byte-identical copy of
sdk/python/makefun_bot.py from the kit).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bot  # noqa: E402  (after the sys.path line: -P leaves the script directory off sys.path)

LAMPORTS_PER_SOL = makefun_bot.LAMPORTS_PER_SOL

STAKE_LAMPORTS = LAMPORTS_PER_SOL // 20          # 0.05 SOL per coin
MIN_BUY_LAMPORTS = LAMPORTS_PER_SOL // 200       # 0.005 SOL minimum meaningful buy
MAX_SLIPPAGE_BPS = 1000                          # 10% slippage cap on every order
MAX_CHASE_MULT = 4.0                             # never buy above 4x the creation price
MIN_DIP_MULT = 0.5                               # never buy below 0.5x the creation price
MIN_ENTRY_MULT = 2.5                             # buy only once the price is at least 2.5x creation: proven runners only, never the launch itself
TAKE_PROFIT = 0.25                               # sell at +25%
STOP_LOSS = -0.15                                # sell at -15%
TRAIL_TRIGGER = 0.10                             # trailing stop arms at +10%
TRAIL_DROP = 0.15                                # sell 15% below the peak since entry
MAX_HOLD_SLOTS = 7200                            # time exit: sell after ~25 min of chain time

# Coins created and not yet decided (membership only, never iterated).
candidates = set()
# Creation price (lamports per token) per candidate mint.
creation_price = {}
# Best price seen since entry, per held mint.
peak_price = {}
# Slot a held mint first appeared in the account, per held mint.
held_since = {}


def price_of(curve):
    """Current bonding-curve price in lamports per token, or None if unknown."""
    if curve is None:
        return None
    if curve.virtual_token_reserves <= 0 or curve.virtual_quote_reserves <= 0:
        return None
    return curve.virtual_quote_reserves / curve.virtual_token_reserves


def entry_price_of(holding):
    """Average entry price in lamports per token, or None if unknown."""
    if holding is None or holding.token_amount <= 0 or holding.cost_lamports <= 0:
        return None
    return holding.cost_lamports / holding.token_amount


def on_batch(state, batch):
    caps = state.hello["caps"]
    tx = state.tx_fee_lamports()
    free = state.free_cash_lamports()
    slots = caps["max_open_positions"] - state.committed_position_count()
    orders = []

    # Record creation prices for new coins.
    for e in batch["events"]:
        if e["event"] == "CreateEvent":
            candidates.add(e["mint"])
            curve = state.curves.get(e["mint"])
            p = price_of(curve)
            if p is not None:
                creation_price[e["mint"]] = p

    # Exits first: selling frees a slot a buy in the same batch can reuse
    # only in a later batch (committed count counts pending buys), so exits
    # are decided before buys but do not free slots within this batch.
    for mint in list(held_since):
        if mint not in state.positions:
            held_since.pop(mint, None)
            peak_price.pop(mint, None)
    for mint, holding in list(state.positions.items()):
        if mint not in held_since:
            held_since[mint] = state.slot
        curve = state.curves.get(mint)
        if curve is None or curve.complete:
            peak_price.pop(mint, None)
            continue
        now = price_of(curve)
        entry = entry_price_of(holding)
        if now is None or entry is None:
            continue
        peak = peak_price.get(mint)
        if peak is None or now > peak:
            peak = now
            peak_price[mint] = peak
        ret = now / entry - 1.0
        peak_ret = peak / entry - 1.0
        age = state.slot - held_since[mint]
        should_sell = (
            ret >= TAKE_PROFIT
            or ret <= STOP_LOSS
            or (peak_ret >= TRAIL_TRIGGER and now <= peak * (1.0 - TRAIL_DROP))
            or age >= MAX_HOLD_SLOTS
        )
        if not should_sell:
            continue
        if len(orders) >= caps["max_orders_per_batch"]:
            break
        orders.append(
            {
                "side": "sell",
                "mint": mint,
                "token_amount": holding.token_amount,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }
        )
        peak_price.pop(mint, None)

    # Entries: decide each candidate at most once per batch, in batch order
    # (event mints first, then mark mints not already seen in the events).
    # Returns True when the mint was decided (bought or permanently dropped).
    def decide(mint):
        nonlocal free, slots
        if mint not in candidates:
            return True
        curve = state.curves.get(mint)
        if curve is None or curve.complete:
            candidates.discard(mint)
            creation_price.pop(mint, None)
            return True
        cap = state.max_buy_lamports(mint)
        if cap < MIN_BUY_LAMPORTS:
            return False  # not decidable yet: keep waiting
        created = creation_price.get(mint)
        now = price_of(curve)
        if created is not None and now is not None:
            if now > created * MAX_CHASE_MULT:
                candidates.discard(mint)
                creation_price.pop(mint, None)
                return True  # already ran away: never chase it
            if now < created * MIN_DIP_MULT:
                candidates.discard(mint)
                creation_price.pop(mint, None)
                return True  # already dumped: dead launch
            if now < created * MIN_ENTRY_MULT:
                return False  # no buy pressure yet: keep waiting for strength
        amount = min(cap, STAKE_LAMPORTS)
        if len(orders) >= caps["max_orders_per_batch"] or slots <= 0:
            return False  # transient: retry on a later batch
        if free < amount + tx:
            return False  # transient: retry on a later batch
        candidates.discard(mint)
        creation_price.pop(mint, None)
        orders.append(
            {
                "side": "buy",
                "mint": mint,
                "quote_lamports": amount,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }
        )
        free -= amount + tx
        slots -= 1
        return True

    seen = set()
    for e in batch["events"]:
        seen.add(e["mint"])
        decide(e["mint"])
    for m in batch["marks"]:
        if m["mint"] not in seen:
            seen.add(m["mint"])
            decide(m["mint"])
    return orders


def on_done(state, done):
    sys.stderr.write(
        "done: batches answered, cash=%d lamports, open positions=%d\n"
        % (state.cash, len(state.positions))
    )


if __name__ == "__main__":
    makefun_bot.run(on_batch, on_done=on_done)
