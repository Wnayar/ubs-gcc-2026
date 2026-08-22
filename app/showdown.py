"""SHOWDOWN — the bot's brain, as a pure function of one /move request body.

Kept out of the router so it can be simulated offline (`tools/simulate.py`)
without HTTP. Nothing here touches global state: the guide warns that a /move
call is never retried, so a decision must be fast and side-effect-free.

The maths
---------
Each player holds one number from 1..13 drawn independently, and one shared
community number is drawn the same way. A number equal to the community number
is a *pair* and beats any non-pair; otherwise the higher number wins; equal
results split. Against an opponent holding a uniformly random number that gives
a closed form for our equity (win probability + half the split probability),
both verified by brute force in tests/test_showdown.py:

    pre-reveal   eq(n)    = (11n + 7.5) / 169
    post-reveal  eq(n, c) = 12.5/13                       when n == c
                          = (#{m < n, m != c} + 0.5) / 13 otherwise

Uniform is the right prior only until the opponent puts chips in. After that it
is actively dangerous: a 12 is 83% against a random number and a coin flip
against someone who has re-raised three times. `equity_vs_range` re-runs the
same count against just the top of the deck, and `_effective_equity` blends the
two — trusting the read, but not so far that a bluffer gets a free pass.

The other half of not going broke is `RAISE_RISK` / `CALL_RISK`: the equity we
demand scales with the share of our stack going in, because our read is least
reliable exactly when the opponent is happy to play for everything.
"""
from __future__ import annotations

import hashlib

DECK = 13
ACTIONS = ("fold", "check", "call", "bet", "raise")

# Equity needed to put chips in when nobody has bet yet. Above VALUE_BET we bet
# for value; THIN_BET is the smaller "charge them to see a showdown" bet.
VALUE_BET_EQ = 0.68
THIN_BET_EQ = 0.56
# Equity needed to raise a bet rather than just call it, and to fire a *second*
# raise in the same round — the spot that busts an over-eager bot.
RAISE_EQ = 0.72
RERAISE_EQ = 0.82
# Charged on top of raw pot odds before calling, scaled by how big the bet is
# relative to the pot.
CALL_MARGIN = 0.09
# Extra equity demanded per unit of our stack committed. The whole defence
# against a raising war: putting in half our stack costs half of this.
RAISE_RISK = 0.18
CALL_RISK = 0.20
# How narrow we read the opponent after each bet/raise they make this round:
# the lowest number we credit them with. Index = their raises this round.
RANGE_LADDER = (1, 4, 7, 9, 10)
# How far to trust that read. The rest stays uniform, which is what stops a
# bluffer from folding us off every decent number.
RANGE_TRUST = 0.85
# Post-reveal, "a high number" is the wrong read: the ONLY hand that beats a high
# card is the community number itself. So a big commitment is read mostly as the
# pair, rising from its 1/13 prior with the size and count of their raises.
PAIR_PRIOR = 1 / DECK
PAIR_GAIN = 0.18
PAIR_MAX = 0.55
# Pot fractions for our own bets, by strength.
SIZE_STRONG = 0.90  # a pair, or a 13 that missed
SIZE_VALUE = 0.62
SIZE_THIN = 0.38
SIZE_BLUFF = 0.45
# How often we fire a bluff at a pot nobody wants. Enough that our bets are not
# a tell; low enough that it does not become the losing half of the strategy.
BLUFF_RATE = 0.10
BLUFF_MAX_EQ = 0.34
# Phase 1 clears at a chip delta of +10. Once that is banked and the match is
# nearly over, marginal calls are worth less than the cushion they risk; if we
# are still short with the clock running out they are worth more.
TARGET_DELTA = 10
ENDGAME_HANDS = 12
PROTECT_TILT = 0.09
CHASE_TILT = -0.07


def _showdown_value(n: int, c: int | None, m: int) -> float:
    """Our share of the pot holding `n` against `m`, community `c`."""
    if c is None:
        # the community number is still to come, so average over it: it pairs
        # us 1/13 of the time, pairs them 1/13, and otherwise the higher number
        # takes it
        if n == m:
            return 0.5
        return 1 / DECK + ((DECK - 2) / DECK if n > m else 0.0)
    ours, theirs = n == c, m == c
    if ours != theirs:
        return 1.0 if ours else 0.0  # any pair beats any non-pair
    if n == m:
        return 0.5
    return 1.0 if n > m else 0.0


def equity(your_number: int, community_number: int | None = None) -> float:
    """Chance of taking the pot at showdown against one uniformly random number.

    Splits count as half a pot, so this is directly comparable to pot odds.
    """
    n = your_number
    if community_number is None:
        return (11 * n + 7.5) / 169
    c = community_number
    if n == c:
        return (DECK - 1 + 0.5) / DECK  # only an identical number stops us
    lower = (n - 1) - (1 if c < n else 0)  # numbers we beat, minus the pair card
    return (lower + 0.5) / DECK


def equity_vs_range(
    your_number: int,
    community_number: int | None,
    low: int,
    pair_weight: float | None = None,
) -> float:
    """Equity against an opponent holding `low`..13 rather than the whole deck.

    With `pair_weight` the range stops being flat: that much of it is the
    community number itself — the only hand that beats a high card — and the
    rest is spread over the other numbers we credit them with.
    """
    low = max(1, min(int(low), DECK))
    hands = range(low, DECK + 1)
    if pair_weight is None or community_number is None:
        return sum(_showdown_value(your_number, community_number, m) for m in hands) / len(hands)
    others = [m for m in hands if m != community_number]
    paired = _showdown_value(your_number, community_number, community_number)
    if not others:
        return paired
    rest = sum(_showdown_value(your_number, community_number, m) for m in others) / len(others)
    return pair_weight * paired + (1 - pair_weight) * rest


# ────────────────────────────── reading the state ──────────────────────────────
# "ignore any field you don't recognise" cuts both ways: nothing below assumes a
# field is present, well-typed, or in range.


def _int(value, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == value:  # not NaN
        return int(value)
    return default


def _number(value) -> int | None:
    """A dealt number, or None if it is missing or off the deck."""
    n = _int(value)
    return n if n is not None and 1 <= n <= DECK else None


def _me(state: dict) -> dict:
    """Our own entry in `players`, found by seat and falling back to the name."""
    players = state.get("players")
    if not isinstance(players, list):
        return {}
    seat = _int(state.get("your_seat"))
    for player in players:
        if isinstance(player, dict) and seat is not None and _int(player.get("seat")) == seat:
            return player
    for player in players:
        if isinstance(player, dict) and player.get("name") == "you":
            return player
    return {}


def _legal(state: dict) -> list[str]:
    raw = state.get("legal_actions")
    if not isinstance(raw, list):
        return []
    return [a for a in raw if a in ACTIONS]


def _aggression(state: dict) -> tuple[int, int]:
    """(their raises, our raises) in the current betting round.

    The forced bets "aren't actions and never appear there", so everything in
    the log is a voluntary statement about someone's number.
    """
    actions = state.get("current_hand_actions")
    if not isinstance(actions, list):
        return 0, 0
    seat = _int(state.get("your_seat"))
    theirs = ours = 0
    for entry in actions:
        if not isinstance(entry, dict) or entry.get("round") != state.get("round"):
            continue
        if entry.get("action") not in ("bet", "raise"):
            continue
        if seat is not None and _int(entry.get("seat")) == seat:
            ours += 1
        else:
            theirs += 1
    return theirs, ours


def _pair_weight(theirs: int, pot: int, to_call: int) -> float:
    """How much of the opponent's range is the community number itself."""
    if theirs <= 0:
        return PAIR_PRIOR
    size = min(to_call / max(pot - to_call, 1), 2.0) if to_call > 0 else 1.0
    return min(PAIR_MAX, PAIR_PRIOR + PAIR_GAIN * theirs * (0.5 + 0.5 * size))


def _effective_equity(state: dict, n: int, c: int | None, pot: int, to_call: int) -> float:
    """Equity against the range the opponent's betting implies, not vs random."""
    theirs, _ = _aggression(state)
    low = RANGE_LADDER[min(theirs, len(RANGE_LADDER) - 1)]
    if to_call > 0 and to_call > max(pot - to_call, 1):
        low += 1  # a bet bigger than the pot it was aimed at says more again
    honest = equity(n, c)
    if low <= 1 and theirs <= 0:
        return honest
    read = equity_vs_range(n, c, low, _pair_weight(theirs, pot, to_call))
    return RANGE_TRUST * read + (1 - RANGE_TRUST) * honest


def _coin(state: dict, salt: str) -> float:
    """A stable pseudo-random number in [0, 1) for this exact spot.

    Derived from the match and the action history rather than `random`, so the
    same situation always gets the same answer — reproducible in tests and in a
    replay — while the opponent sees no pattern. It also means a retried or
    duplicated /move cannot flip our story mid-hand.
    """
    actions = state.get("current_hand_actions")
    key = "|".join(
        str(x)
        for x in (
            state.get("match_id"),
            state.get("hand_number"),
            state.get("round"),
            len(actions) if isinstance(actions, list) else 0,
            salt,
        )
    )
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") / 2**64


def _tilt(state: dict) -> float:
    """Threshold shift for the run-in: + plays tighter, − takes more risk.

    `chip_delta` is frozen at the start of the hand, which is exactly the score
    we are judged on, so it is the right thing to steer by.
    """
    total = _int(state.get("total_hands"))
    hand = _int(state.get("hand_number"))
    if total is None or hand is None:
        return 0.0
    hands_left = total - hand
    if hands_left > ENDGAME_HANDS:
        return 0.0
    delta = _int(_me(state).get("chip_delta"))
    if delta is None:
        return 0.0
    # a cushion big enough that the blinds left to post cannot eat it
    if delta >= TARGET_DELTA + 2 * hands_left:
        return PROTECT_TILT
    if delta < TARGET_DELTA:
        return CHASE_TILT
    return 0.0


# ─────────────────────────────────── sizing ────────────────────────────────────


def _window(state: dict) -> tuple[int, int] | None:
    low, high = _int(state.get("min_raise_to")), _int(state.get("max_raise_to"))
    if low is None or high is None or low > high:
        return None  # both null means we cannot bet or raise at all
    return low, high


def _put_in(
    state: dict, action: str, total: float, eq: float, floor: float, risk_free: bool = False
) -> dict | None:
    """Bet/raise to `total`, but only if the equity covers the stack risk.

    `amount` is the total we will have put in *for this betting round*, and an
    out-of-range one "is not clamped for you — it counts as an illegal move".
    Shrinking to the minimum before giving up keeps us value-betting in spots
    where a big bet would be reckless but a small one is still profitable.
    """
    window = _window(state)
    if window is None:
        return None
    low, high = window
    mine = _int(_me(state).get("bet_this_round"), 0) or 0
    stack = max(_int(state.get("your_stack"), 0) or 0, 1)
    for target in (max(low, min(high, int(round(total)))), low):
        risk = 0.0 if risk_free else RAISE_RISK * (max(target - mine, 0) / stack)
        if eq >= floor + risk:
            return {"action": action, "amount": target}
    return None


def _cannot_lose(n: int, c: int | None) -> bool:
    """True when we hold the pair, which no hand beats.

    "Any pair beats any non-pair" and "identical results split the pot", so
    every opponent number either loses to us or ties: there is no distribution
    of their range under which putting chips in costs us any. That makes the
    stack-risk floor and the raising-war cap — both of which exist to stop us
    getting stacked — actively wrong here.
    """
    return c is not None and n == c


def _size_for(eq: float) -> float:
    if eq >= 0.88:
        return SIZE_STRONG
    if eq >= VALUE_BET_EQ:
        return SIZE_VALUE
    return SIZE_THIN


# ─────────────────────────────────── policy ────────────────────────────────────


def _passive(legal: list[str]) -> dict:
    """The cheapest legal way to stay out of trouble."""
    if "check" in legal:
        return {"action": "check"}
    if "fold" in legal:
        return {"action": "fold"}
    return {"action": legal[0]} if legal else {"action": "check"}


def _play(state: dict, legal: list[str]) -> dict:
    number = _number(state.get("your_number"))
    if number is None:
        return _passive(legal)  # no hand to reason about — never gamble blind

    community = _number(state.get("community_number"))
    pot = max(_int(state.get("pot"), 0) or 0, 0)
    to_call = max(_int(state.get("to_call"), 0) or 0, 0)
    stack = max(_int(state.get("your_stack"), 0) or 0, 1)
    eq = _effective_equity(state, number, community, pot, to_call)
    locked = _cannot_lose(number, community)
    tilt = _tilt(state)
    mine = _int(_me(state).get("bet_this_round"), 0) or 0
    _, our_raises = _aggression(state)

    if to_call > 0 and "call" in legal:
        # The opponent may bet more than we can cover: "you can still call for
        # everything you have and play for the part of the pot you matched;
        # chips you couldn't cover go back to them." So the most we can ever put
        # in — and lose — is our stack, however large `to_call` reads.
        risked = min(to_call, stack)
        odds = risked / (pot + risked) if pot + risked > 0 else 1.0
        # `pot` already includes the bet we are facing, so back it out to size
        # the bet against the pot it was aimed at
        pressure = min(risked / max(pot - risked, 1), 2.0)
        needed = odds + CALL_MARGIN * pressure + tilt + CALL_RISK * (risked / stack)
        if "raise" in legal:
            # a second raise in one round means the pot is getting away from us —
            # unless the hand cannot lose, in which case there is nothing to fear
            floor = RAISE_EQ + tilt if locked else (RERAISE_EQ if our_raises else RAISE_EQ) + tilt
            if eq >= floor:
                raised = _put_in(
                    state,
                    "raise",
                    mine + to_call + (pot + to_call) * _size_for(eq),
                    eq,
                    floor,
                    risk_free=locked,
                )
                if raised is not None:
                    return raised
        # folding a hand that cannot lose is never right at any price
        return {"action": "call"} if locked or eq >= needed else _passive(legal)

    if "bet" in legal:
        # value first, then the smaller "charge them to see a showdown" bet
        for floor, fraction in (
            (VALUE_BET_EQ + tilt, _size_for(eq)),
            (THIN_BET_EQ + tilt, SIZE_THIN),
        ):
            if eq >= floor:
                opened = _put_in(state, "bet", mine + pot * fraction, eq, floor, risk_free=locked)
                if opened is not None:
                    return opened
                break
        if eq <= BLUFF_MAX_EQ and _coin(state, "bluff") < BLUFF_RATE - tilt:
            # a bluff is priced by the pot, not by our equity, so it bypasses
            # the stack-risk floor — but only ever for a fraction of the pot
            window = _window(state)
            if window is not None:
                low, high = window
                target = max(low, min(high, int(round(mine + pot * SIZE_BLUFF))))
                if target - mine <= stack * 0.5:
                    return {"action": "bet", "amount": target}

    return _passive(legal)


def decide(state: dict) -> dict:
    """One /move request in, one reply out. Never raises, never returns an
    action outside `legal_actions` — the coordinator substitutes a check for
    anything it cannot use, and five substitutions in a row forfeit the match.
    """
    if not isinstance(state, dict):
        return {"action": "check"}
    legal = _legal(state)
    if not legal:
        return {"action": "check"}
    try:
        move = _play(state, legal)
    except Exception:
        return _passive(legal)
    if move.get("action") not in legal:  # belt and braces
        return _passive(legal)
    return move
