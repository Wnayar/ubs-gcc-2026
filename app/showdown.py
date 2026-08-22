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
    rule_equity_ranges,
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
# How hard the calibrated call cushion compresses as the table fills up. The
# cushion (CALL_MARGIN, CALL_RISK, tilt) is measured on the heads-up equity
# axis, where an average hand is 0.5; six-handed an average hand is worth 1/6 of
# the pot, so an uncompressed CALL_RISK of 0.55 dwarfs the equity it is charged
# against and folds everything. `share ** FIELD_MARGIN` scales it: 0 keeps the
# full heads-up cushion, 1 scales it exactly with the axis. Identity at one
# opponent either way, so phases 1 and 2 cannot be affected. Swept in
# tools/simulate3.py.
FIELD_MARGIN = 1.0
# Phase 2 scores +25 a leg over 40 hands; phase 1 scored +10 over 100. We cannot
# read the target off the wire, so it keys off whether we are in a multi-leg
# attempt at all.
LEG_TARGET_DELTA = 25
# Pot fractions for our own bets, by strength.
#
# Sized up deliberately. Across every graded match we win 60-75% of showdowns —
# hand selection is not the problem — but the pots we WIN average 10 to 16 chips
# while the pots we LOSE average 22 to 33. We were winning small and losing big,
# which loses money even at a 60% win rate. The opponent folds only 15-22% of the
# time, so they are a caller: against a caller the answer to "they keep paying"
# is to charge more, not to bet less often.
SIZE_STRONG = 1.15  # overbet — a hand that is way ahead should build the pot
SIZE_VALUE = 0.85
SIZE_THIN = 0.45
SIZE_BLUFF = 0.45
# How often we fire a bluff at a pot nobody wants. Enough that our bets are not
# a tell; low enough that it does not become the losing half of the strategy.
BLUFF_RATE = 0.10
BLUFF_MAX_EQ = 0.34
# Phase 1 clears at a chip delta of +10. Once that is banked and the match is
# nearly over, marginal calls are worth less than the cushion they risk; if we
# are still short with the clock running out they are worth more.
TARGET_DELTA = 10
# Phase 3 seats six and scores "chip delta >= +10 AND strictly highest at the
# table". The +10 is the easy half — topping five opponents is the binding one.
PHASE3_TARGET_DELTA = 10
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


def _raises_by_seat(state: dict) -> tuple[dict, int]:
    """(how often each opponent seat bet or raised this round, how often we did).

    The forced bets "aren't actions and never appear there", so everything in
    the log is a voluntary statement about someone's number. Six-handed it
    matters *which* seat made it: five limpers are not five raisers.
    """
    actions = state.get("current_hand_actions")
    if not isinstance(actions, list):
        return {}, 0
    seat = _int(state.get("your_seat"))
    theirs: dict = {}
    ours = 0
    for entry in actions:
        if not isinstance(entry, dict) or entry.get("round") != state.get("round"):
            continue
        if entry.get("action") not in ("bet", "raise"):
            continue
        who = _int(entry.get("seat"))
        if seat is not None and who == seat:
            ours += 1
        else:
            theirs[who] = theirs.get(who, 0) + 1
    return theirs, ours


def _aggression(state: dict) -> tuple[int, int]:
    """(their raises, our raises) in the current betting round, across the table."""
    theirs, ours = _raises_by_seat(state)
    return sum(theirs.values()), ours


# ───────────────────────────── reading the table ───────────────────────────────


def _seated(state: dict) -> list[dict]:
    """Every seat at the table, folded and busted included. `players` "is a list
    in seat order ... Read it as a list rather than assuming a fixed shape"."""
    players = state.get("players")
    if not isinstance(players, list):
        return []
    return [p for p in players if isinstance(p, dict)]


def _is_us(state: dict, player: dict) -> bool:
    """Seat numbers decide it whenever both sides have one; the name is only a
    fallback for a seating we cannot read."""
    seat = _int(state.get("your_seat"))
    mine = _int(player.get("seat"))
    if seat is not None and mine is not None:
        return mine == seat
    return player.get("name") == "you"


def live_opponents(state: dict) -> int:
    """How many seats are still in this hand, not counting us.

    "Folded players stay in `players` with `folded: true` — the list is the
    table's seating, not the list of live opponents. Filter on `folded` /
    `busted` yourself." An all-in seat is still live: it is out of chips for
    this hand but it is still going to the showdown.
    """
    return sum(
        1
        for p in _seated(state)
        if not p.get("folded") and not p.get("busted") and not _is_us(state, p)
    )


def live_seats(state: dict) -> list[int]:
    """The seat numbers still in the hand, us included, in seat order."""
    seats = []
    for p in _seated(state):
        if p.get("folded") or p.get("busted"):
            continue
        seat = _int(p.get("seat"))
        if seat is not None:
            seats.append(seat)
    return sorted(seats)


# ──────────────────────────── position at the table ────────────────────────────
# Nothing about position changes six-handed, "there are just more seats". We read
# the order but do not yet vary the thresholds by it — see notes.md, assumption 7.


def _from_button(button, seats: list[int]) -> list[int]:
    """`seats` rotated so the button is first."""
    if not seats:
        return []
    if button in seats:
        index = seats.index(button)
    else:  # the button is sitting on a busted seat: it moves to the next live one
        later = [s for s in seats if s > button]
        index = seats.index(later[0]) if later else 0
    return seats[index:] + seats[:index]


def forced_bet_seats(button: int, seats: list[int]) -> tuple:
    """(the seat paying 1, the seat paying 2) among the seats still in the match.

    "Forced bets start just past the button: seat 1 pays 1, seat 2 pays 2. The
    button pays nothing, which is why it's the cheapest seat."

    Two seats is the guide's heads-up table, where that same sentence wraps
    round onto the button itself: "the button pays the smaller forced bet (1)".
    """
    order = _from_button(button, seats)
    if len(order) < 2:
        return (None, None)
    if len(order) == 2:
        return (order[0], order[1])
    return (order[1], order[2])


def acting_order(button: int, seats: list[int], round_name: str) -> list[int]:
    """Who acts, in order, in this betting round.

    "Before the reveal, the order opens just past the seat that paid 2, so that
    seat acts last. After the reveal, the order opens just past the button, so
    the button acts last — with the most information."

    The two rounds are deliberately not the same order, heads-up or six-handed.
    """
    order = _from_button(button, seats)
    if len(order) < 2:
        return order
    if round_name == "pre_reveal":
        paid_two = 1 if len(order) == 2 else 2
        opens = (paid_two + 1) % len(order)
    else:
        opens = 1
    return order[opens:] + order[:opens]


def _codename(state: dict) -> str:
    rule = state.get("table_rule")
    return rule if isinstance(rule, str) and rule else "standard"


def _sharpness(raises: int, pot: int, to_call: int) -> float:
    """How hard one seat's betting says "my number is strong"."""
    if raises <= 0:
        return 0.0
    size = min(to_call / max(pot - to_call, 1), 2.0) if to_call > 0 else 1.0
    return SHARPNESS_PER_RAISE * raises * (0.5 + 0.5 * size)


def field_share(live: int) -> float:
    """What an average number is worth against `live` opponents, on the
    heads-up equity axis.

    Every threshold in this file — VALUE_BET_EQ, RAISE_EQ, CALL_MARGIN,
    CALL_RISK — was calibrated one-on-one, where 0.5 is an average hand. Six
    handed an average number is worth 1/6 of the pot, so feeding raw multiway
    equity into a 0.68 threshold would mean never betting again. Dividing an
    equity by this puts it back on the axis those numbers were written for;
    multiplying a margin by it compresses the margin the same way.

    One opponent gives exactly 1.0, so heads-up nothing moves at all.
    """
    return 1.0 if live <= 1 else 2.0 / (live + 1)


def bluff_rate(live: int) -> float:
    """A bluff has to get through *every* live opponent, so its chance of
    working falls off geometrically as the table fills up."""
    return BLUFF_RATE * (0.5 ** max(live - 1, 0))


def _opponent_ranges(state: dict, belief: dict, c: int | None, pot: int,
                     to_call: int, live: int) -> list:
    """One range per live opponent: sharpened for the seats that have bet or
    raised this round, uniform for the seats that are merely still in.

    Phase 2 pointed a single sharpened range at "the opponent". Six-handed that
    is wrong in both directions: five limpers are not five raisers, and one shove
    in front of four folds is not a table full of strength.
    """
    raises, _ = _raises_by_seat(state)
    if not raises:
        return [None] * live
    ours = _int(state.get("your_seat"))
    seats = [s for s in live_seats(state) if s != ours]
    if not seats:
        # we cannot line the log up with the seating; credit as many opponents
        # with the aggregate read as there were aggressors
        sharp = range_weights(belief, c, _sharpness(sum(raises.values()), pot, to_call))
        return [sharp] * min(len(raises), live) + [None] * max(live - len(raises), 0)
    lanes: list = []
    cache: dict[int, dict] = {}
    for i in range(live):
        count = raises.get(seats[i], 0) if i < len(seats) else 0
        if count <= 0:
            lanes.append(None)
            continue
        if count not in cache:
            cache[count] = range_weights(belief, c, _sharpness(count, pot, to_call))
        lanes.append(cache[count])
    return lanes


def _equities(state: dict, n: int, c: int | None, pot: int,
              to_call: int) -> tuple[float, float]:
    """(our share of the pot, that share on the heads-up axis).

    The first is what a *call* is priced against, because `to_call / (pot +
    to_call)` is already the correct multiway comparison. The second is what a
    *bet or raise* is judged on, because every one of those thresholds was
    calibrated against a single opponent.

    Both halves stay rule-relative: with the belief spread across rules that
    disagree the number collapses toward a coin flip on its own, which is the
    right caution while the table is still unknown.
    """
    belief = posterior_for(_codename(state))
    live = live_opponents(state)
    honest = rule_equity_ranges(belief, n, c, [None] * live)
    lanes = _opponent_ranges(state, belief, c, pot, to_call, live)
    if any(lane is not None for lane in lanes):
        read = rule_equity_ranges(belief, n, c, lanes)
        eq = RANGE_TRUST * read + (1 - RANGE_TRUST) * honest
    else:
        eq = honest
    return eq, min(1.0, eq / field_share(live))


def table_equity(state: dict) -> float:
    """Our share of the pot as the bot currently reads it, for tests and replays."""
    n = _number(state.get("your_number"))
    if n is None:
        return 0.0
    return _equities(
        state,
        n,
        _number(state.get("community_number")),
        max(_int(state.get("pot"), 0) or 0, 0),
        max(_int(state.get("to_call"), 0) or 0, 0),
    )[0]


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


def objective(state: dict) -> tuple[int, bool]:
    """(the chip delta this leg needs, whether we also have to top the table).

    Phase 3 seats six: "chip delta >= +10 *and* top the table -> 150 points ...
    beating four of the five is worth nothing". Phase 2 seats two and wants +25
    a leg; phase 1 is a single match and wants +10.

    Read off the SEATING, not off who is still alive — busting the table down to
    two players does not turn a phase 3 leg back into a phase 2 one.
    """
    if len(_seated(state)) >= 3:
        return PHASE3_TARGET_DELTA, True
    if _int(state.get("leg_number")) is not None:
        return LEG_TARGET_DELTA, False
    return TARGET_DELTA, False


def _best_rival(state: dict) -> int | None:
    """The highest chip delta at the table that is not ours.

    Busted seats included: they are still seats, and "top the table" means
    strictly above every one of them.
    """
    best = None
    for player in _seated(state):
        if _is_us(state, player):
            continue
        delta = _int(player.get("chip_delta"))
        if delta is not None and (best is None or delta > best):
            best = delta
    return best


def endgame_tilt(state: dict) -> float:
    """Threshold shift for the run-in: + plays tighter, − takes more risk.

    `chip_delta` is frozen at the start of the hand, which is exactly the score
    we are judged on, so it is the right thing to steer by.

    Phase 3 changes what "ahead" means. The leg is a race — "you must finish the
    leg with strictly highest chip delta at the table", "ties don't count" — so
    a comfortable second place scores the same zero as busting, and there is
    nothing to protect until we are actually in front.
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
    target, must_top = objective(state)
    cushion = 2 * hands_left  # big enough that the blinds left to post cannot eat it
    banked = delta >= target + cushion
    if must_top:
        rival = _best_rival(state)
        if rival is not None:
            # level with the leader is still losing, and leading on a delta
            # under the target still does not clear the leg
            if delta <= rival or delta < target:
                return CHASE_TILT
            return PROTECT_TILT if banked and delta - rival > cushion else 0.0
    if banked:
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
    # `eq` is our real share of the pot; `strength` is that share put back on the
    # one-on-one axis every threshold below was calibrated against
    eq, strength = _equities(state, number, community, pot, to_call)
    locked = _cannot_lose(state, number, community)
    tilt = endgame_tilt(state)
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
        # Pot odds against our real share of the pot is already the correct
        # multiway comparison. The cushion on top is not: see FIELD_MARGIN.
        cushion = CALL_MARGIN * pressure + tilt + CALL_RISK * (risked / stack)
        needed = odds + cushion * (field_share(live) ** FIELD_MARGIN)
        if "raise" in legal:
            # a second raise in one round means the pot is getting away from us —
            # unless the hand cannot lose, in which case there is nothing to fear
            floor = RAISE_EQ + tilt if locked else (RERAISE_EQ if our_raises else RAISE_EQ) + tilt
            if strength >= floor:
                raised = _put_in(
                    state,
                    "raise",
                    mine + to_call + (pot + to_call) * _size_for(strength),
                    strength,
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
            (VALUE_BET_EQ + tilt, _size_for(strength)),
            (THIN_BET_EQ + tilt, SIZE_THIN),
        ):
            if strength >= floor:
                opened = _put_in(
                    state, "bet", mine + pot * fraction, strength, floor, risk_free=locked
                )
                if opened is not None:
                    return opened
                break
        if strength <= BLUFF_MAX_EQ and _coin(state, "bluff") < bluff_rate(live) - tilt:
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
