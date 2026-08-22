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

from app.showdown_rules import (
    observe,
    posterior_for,
    range_weights,
    rule_equity,
    rule_equity_multiway,
    unbeatable,
)

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
# Measured over every graded match: hands where we voluntarily committed 60% or
# more of our stack went 2-16, an 11% win rate, for -484 chips, while the other
# 319 hands together were +47. We are not unlucky in those spots, we are getting
# it in badly — the opponent's big bets are far stronger than the range model
# credits. These prices are deliberately steep: the term is `RISK x (chips in /
# stack)`, so it is negligible on an ordinary call and heavy on one that plays
# for a stack. A hand that genuinely cannot lose is exempt via `risk_free`.
RAISE_RISK = 0.40
CALL_RISK = 0.55
# How sharply each bet/raise of theirs concentrates their range onto the numbers
# that are strong *under the rule this table is using*. Replaces phase 1's
# "they hold a high number" ladder, which only made sense under the standard rule.
SHARPNESS_PER_RAISE = 2.2
# How far to trust that read. The rest stays uniform, which is what stops a
# bluffer from folding us off every decent number.
RANGE_TRUST = 0.85
# Phase 2 scores +25 a leg over 40 hands; phase 1 scored +10 over 100. We cannot
# read the target off the wire, so it keys off whether we are in a multi-leg
# attempt at all.
LEG_TARGET_DELTA = 25
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

# ── phase 3: six seats ────────────────────────────────────────────────────────
# Every threshold above is equity against ONE opponent, where a fair share of the
# pot is a half. Against k opponents a fair share is 1/(k+1), so the thresholds
# are rescaled rather than re-tuned: each keeps the multiple of a fair share it
# always meant. At k == 1 the factor is exactly 1.0, which is what leaves phases
# 1 and 2 — 700 points the grader may re-run — running the same arithmetic.
# On top of that each extra live opponent adds FIELD_TAX to the multiple we
# demand, because a bet has to get through all of them and the hands that call
# it are the ones that beat us.
FIELD_TAX = 0.03
# A bluff needs *everyone* to fold, which gets geometrically less likely as the
# field grows, so the bluff rate decays per extra opponent rather than staying
# at the heads-up figure.
MULTIWAY_BLUFF_DECAY = 0.55
# Phase 3 clears on "chip delta >= +10 AND strictly the highest at the table".
# Being second scores exactly what being last scores, which is what makes a
# losing position the one where variance is free.
PHASE3_TARGET_DELTA = 10
PHASE3_ENDGAME_HANDS = 18
PHASE3_CHASE_TILT = -0.16
# Roughly what an ordinary run of hands is worth, used to judge whether a
# shortfall is one we can play our way out of or one that needs gambling.
CHASE_REACH_PER_HAND = 4


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


def live_opponents(state: dict) -> list[dict]:
    """The seats that can still take this pot.

    "Folded players stay in `players` with `folded: true` — the list is the
    table's seating, not the list of live opponents. Filter on `folded`/`busted`
    yourself." A busted seat is out of the match entirely: no cards, no forced
    bets, no button.
    """
    players = state.get("players")
    if not isinstance(players, list):
        return []
    me = _me(state)
    seat = _int(state.get("your_seat"))
    live = []
    for player in players:
        if not isinstance(player, dict):
            continue
        if player is me or player.get("name") == "you":
            continue
        if seat is not None and _int(player.get("seat")) == seat:
            continue
        if player.get("folded") or player.get("busted"):
            continue
        live.append(player)
    return live


def _table_size(state: dict) -> int:
    """Seats at this table, folded and busted included — it is the seating."""
    players = state.get("players")
    if not isinstance(players, list):
        return 0
    return sum(1 for player in players if isinstance(player, dict))


def _field_scale(opponents: int) -> float:
    """A fair share of the pot against `opponents`, relative to heads-up.

    Exactly 1.0 for one opponent, which is what makes the phase-1/2 thresholds
    survive the rescaling untouched.
    """
    return 2.0 / (opponents + 1)


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


def _codename(state: dict) -> str:
    rule = state.get("table_rule")
    return rule if isinstance(rule, str) and rule else "standard"


def _sharpness(state: dict, pot: int, to_call: int) -> float:
    """How hard the opponent's betting says "my number is strong"."""
    theirs, _ = _aggression(state)
    if theirs <= 0:
        return 0.0
    size = min(to_call / max(pot - to_call, 1), 2.0) if to_call > 0 else 1.0
    return SHARPNESS_PER_RAISE * theirs * (0.5 + 0.5 * size)


def _effective_equity(state: dict, n: int, c: int | None, pot: int, to_call: int) -> float:
    """Equity under what we believe this table's rule is, against the range the
    opponent's betting implies.

    Both halves are rule-relative: with the belief spread across rules that
    disagree the number collapses toward a coin flip on its own, which is the
    right caution while the table is still unknown.
    """
    belief = posterior_for(_codename(state))
    honest = rule_equity(belief, n, c)
    sharpness = _sharpness(state, pot, to_call)
    if sharpness <= 0:
        return honest
    read = rule_equity(belief, n, c, range_weights(belief, c, sharpness))
    return RANGE_TRUST * read + (1 - RANGE_TRUST) * honest


def _seat_sharpness(state: dict, seat: int | None, pot: int, to_call: int) -> float:
    """How hard THIS seat's betting says its number is strong.

    Phase 2 pooled every opponent's aggression, which is the same thing when
    there is only one of them and badly wrong when there are five: a seat that
    has raised twice and a seat that has called once are not the same threat,
    and averaging them is throwing the read away.
    """
    if seat is None:
        return 0.0
    actions = state.get("current_hand_actions")
    if not isinstance(actions, list):
        return 0.0
    raises = 0
    for entry in actions:
        if not isinstance(entry, dict) or entry.get("round") != state.get("round"):
            continue
        if entry.get("action") in ("bet", "raise") and _int(entry.get("seat")) == seat:
            raises += 1
    if raises <= 0:
        return 0.0
    size = min(to_call / max(pot - to_call, 1), 2.0) if to_call > 0 else 1.0
    return SHARPNESS_PER_RAISE * raises * (0.5 + 0.5 * size)


def _field_equity(
    state: dict, n: int, c: int | None, live: list[dict], pot: int, to_call: int
) -> float:
    """Our share of the pot against everyone still in the hand.

    "A bet now has to get through everyone still in the hand, not just one
    player. The same number is worth less than it is one-on-one" — so this is
    the probability of beating them ALL, not of beating a representative one.
    """
    belief = posterior_for(_codename(state))
    honest = rule_equity_multiway(belief, n, c, [None] * len(live))
    ranges: list[dict[int, float] | None] = []
    reading = False
    for opponent in live:
        sharpness = _seat_sharpness(state, _int(opponent.get("seat")), pot, to_call)
        if sharpness > 0:
            reading = True
            ranges.append(range_weights(belief, c, sharpness))
        else:
            ranges.append(None)
    if not reading:
        return honest
    read = rule_equity_multiway(belief, n, c, ranges)
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


def _best_other_delta(state: dict) -> int | None:
    """The best chip delta at the table that is not ours — the seat to beat.

    Busted seats count. One frozen at −200 is still a seat we are ahead of, and
    a leg is scored on the final standings, not on who is still playing.
    """
    players = state.get("players")
    if not isinstance(players, list):
        return None
    me = _me(state)
    seat = _int(state.get("your_seat"))
    best = None
    for player in players:
        if not isinstance(player, dict):
            continue
        if player is me or player.get("name") == "you":
            continue
        if seat is not None and _int(player.get("seat")) == seat:
            continue
        delta = _int(player.get("chip_delta"))
        if delta is None:
            continue
        best = delta if best is None else max(best, delta)
    return best


def _crowded_tilt(state: dict, hands_left: int) -> float:
    """The run-in at a six-seat table, where clearing is a relative target.

    "You must finish the leg with strictly the highest chip delta at the table —
    beating four of the five is worth nothing." Second place and last place score
    the same, so once the leg is nearly over and somebody is ahead of us, the
    downside of variance is nil and the upside is the only 150 points on offer.

    Both halves of the clearing condition — at least +10, and strictly ahead —
    collapse into one number: the chips we still need. Chasing a shortfall we
    could play our way into is just spew, so the chase scales with how big that
    shortfall is against what the hands left could ordinarily produce.
    """
    if hands_left > PHASE3_ENDGAME_HANDS:
        return 0.0  # the standings are not settled yet; play the hand, not the board
    delta = _int(_me(state).get("chip_delta"))
    best_other = _best_other_delta(state)
    if delta is None or best_other is None:
        return 0.0
    need = max(best_other + 1 - delta, PHASE3_TARGET_DELTA - delta)
    if need > 0:
        reachable = max(CHASE_REACH_PER_HAND * hands_left, 1)
        return PHASE3_CHASE_TILT * min(1.0, need / reachable)
    if delta - best_other > 2 * hands_left:
        return PROTECT_TILT  # a lead the blinds cannot eat is worth protecting
    return 0.0


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
    if _table_size(state) >= 3:
        return _crowded_tilt(state, hands_left)
    if hands_left > ENDGAME_HANDS:
        return 0.0
    delta = _int(_me(state).get("chip_delta"))
    if delta is None:
        return 0.0
    target = LEG_TARGET_DELTA if _int(state.get("leg_number")) is not None else TARGET_DELTA
    # a cushion big enough that the blinds left to post cannot eat it
    if delta >= target + 2 * hands_left:
        return PROTECT_TILT
    if delta < target:
        return CHASE_TILT
    return 0.0


# ─────────────────────────────────── sizing ────────────────────────────────────


def _window(state: dict) -> tuple[int, int] | None:
    low, high = _int(state.get("min_raise_to")), _int(state.get("max_raise_to"))
    if low is None or high is None or low > high:
        return None  # both null means we cannot bet or raise at all
    return low, high


def _put_in(
    state: dict,
    action: str,
    total: float,
    eq: float,
    floor: float,
    risk_free: bool = False,
    scale: float = 1.0,
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
        risk = 0.0 if risk_free else RAISE_RISK * scale * (max(target - mine, 0) / stack)
        if eq >= floor + risk:
            return {"action": action, "amount": target}
    return None


def _cannot_lose(state: dict, n: int, c: int | None) -> bool:
    """True when, under every rule we still believe in, no number beats ours.

    Under the standard rule that is exactly "we hold the pair" — any pair beats
    any non-pair and identical results split, so every opponent number either
    loses to us or ties. A hand with no downside should ignore the stack-risk
    floor and the raising-war cap, both of which exist only to stop us getting
    stacked. Phase 2 generalises it: what is unbeatable depends on the table.
    """
    name = _codename(state)
    return unbeatable(posterior_for(name), n, c, codename=name)


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
    live = live_opponents(state)
    # Two or more opponents is a different game and takes the phase-3 maths. One
    # or none is heads-up — which is phase 1 and phase 2, and also a six-seat hand
    # that has folded down to a duel, where the heads-up reasoning is simply
    # correct again. Below, `scale` and `tax` are both exactly 1.0 on that path,
    # so it runs the arithmetic those phases were tuned on, unchanged.
    crowded = len(live) >= 2
    scale = _field_scale(len(live)) if crowded else 1.0
    tax = 1.0 + FIELD_TAX * (len(live) - 1) if crowded else 1.0
    if crowded:
        eq = _field_equity(state, number, community, live, pot, to_call)
    else:
        eq = _effective_equity(state, number, community, pot, to_call)
    locked = _cannot_lose(state, number, community)
    tilt = _tilt(state) * scale
    mine = _int(_me(state).get("bet_this_round"), 0) or 0
    _, our_raises = _aggression(state)
    # equity read back on the heads-up scale, so bet sizing keeps meaning what it
    # meant: "how strong is this, for a hand that has to beat this many people?"
    strength = eq / scale

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
        needed = (
            odds + CALL_MARGIN * scale * pressure + tilt + CALL_RISK * scale * (risked / stack)
        )
        if "raise" in legal:
            # a second raise in one round means the pot is getting away from us —
            # unless the hand cannot lose, in which case there is nothing to fear
            base = RAISE_EQ if locked else (RERAISE_EQ if our_raises else RAISE_EQ)
            floor = base * scale * tax + tilt
            if eq >= floor:
                raised = _put_in(
                    state,
                    "raise",
                    mine + to_call + (pot + to_call) * _size_for(strength),
                    eq,
                    floor,
                    risk_free=locked,
                    scale=scale,
                )
                if raised is not None:
                    return raised
        # folding a hand that cannot lose is never right at any price
        return {"action": "call"} if locked or eq >= needed else _passive(legal)

    if "bet" in legal:
        # value first, then the smaller "charge them to see a showdown" bet
        for floor, fraction in (
            (VALUE_BET_EQ * scale * tax + tilt, _size_for(strength)),
            (THIN_BET_EQ * scale * tax + tilt, SIZE_THIN),
        ):
            if eq >= floor:
                opened = _put_in(
                    state, "bet", mine + pot * fraction, eq, floor,
                    risk_free=locked, scale=scale,
                )
                if opened is not None:
                    return opened
                break
        # a bluff has to get through every live opponent, so it gets rarer fast
        bluff_rate = BLUFF_RATE * MULTIWAY_BLUFF_DECAY ** max(len(live) - 1, 0)
        if eq <= BLUFF_MAX_EQ * scale and _coin(state, "bluff") < bluff_rate - tilt:
            # a bluff is priced by the pot, not by our equity, so it bypasses
            # the stack-risk floor — but only ever for a fraction of the pot
            window = _window(state)
            if window is not None:
                low, high = window
                target = max(low, min(high, int(round(mine + pot * SIZE_BLUFF))))
                if target - mine <= stack * 0.5:
                    return {"action": "bet", "amount": target}

    return _passive(legal)


def _learn(state: dict) -> None:
    """Fold every completed showdown in `recent_hands` into what we know about
    this codename. Hands won by a fold show nothing and teach nothing.
    """
    hands = state.get("recent_hands")
    if not isinstance(hands, list):
        return
    codename = _codename(state)
    match_id, leg = state.get("match_id"), _int(state.get("leg_number"))
    for entry in hands:
        if not isinstance(entry, dict):
            continue
        shown = entry.get("shown_numbers")
        if not isinstance(shown, dict) or len(shown) < 2:
            continue
        numbers = {}
        for seat, value in shown.items():
            try:
                numbers[int(seat)] = int(value)
            except (TypeError, ValueError):
                numbers = {}
                break
        if len(numbers) < 2:
            continue
        observe(
            codename,
            match_id=match_id,
            leg=leg,
            hand_number=_int(entry.get("hand_number")),
            numbers=numbers,
            community=_int(entry.get("community_number")),
            winners=entry.get("winners"),
        )


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
        _learn(state)
    except Exception:
        pass  # never let a malformed history cost us the hand
    try:
        move = _play(state, legal)
    except Exception:
        return _passive(legal)
    if move.get("action") not in legal:  # belt and braces
        return _passive(legal)
    return move
