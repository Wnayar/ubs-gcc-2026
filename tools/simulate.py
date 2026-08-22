#!/usr/bin/env python3
"""Offline SHOWDOWN table, for tuning app/showdown.py without burning attempts.

The coordinator only tells us our score, so the only way to know whether a
threshold change is an improvement is to play a few thousand matches against
bots we control. This engine follows docs/phases/showdown/guide.pdf: blinds 1/2,
200 chips, numbers 1..13, a pair beats any non-pair, standard no-limit raise
sizing, button alternates every hand.

    python3 tools/simulate.py                  # our bot vs every opponent
    python3 tools/simulate.py --matches 2000
    python3 tools/simulate.py --sweep          # threshold sensitivity
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import showdown  # noqa: E402
from app.showdown import decide, equity  # noqa: E402
from app.showdown_rules import BY_NAME, Rule, forget_all, rule_equity  # noqa: E402

# The leg's true rule. The engine sets it; the opponent bots read it, because a
# house bot presumably knows the table it deals. Our own bot only ever sees the
# codename.
TABLE: dict = {"rule": BY_NAME["standard"], "codename": "standard"}


def _is_prime(n):
    return n in (2, 3, 5, 7, 11, 13)


# Rules deliberately OUTSIDE app.showdown_rules.RULES, to measure what happens
# when the real table is something we never hypothesised.
EXOTIC = (
    Rule("x_mod3", "n mod 3, then higher", lambda n, c: (n % 3, n)),
    Rule("x_prime", "primes beat composites, then higher", lambda n, c: (_is_prime(n), n)),
    Rule("x_cycdist", "cyclic distance to the community", 
         lambda n, c: (-min(abs(n - c), DECK - abs(n - c)),)),
    Rule("x_sumpar", "parity of n+c, then higher", lambda n, c: ((n + c) % 2, n)),
)

DECK = 13
SMALL_BLIND, BIG_BLIND = 1, 2
STARTING_STACK = 200


# ────────────────────────────────── the table ──────────────────────────────────


class Hand:
    """One hand: blinds, deal, two betting rounds, showdown."""

    def __init__(self, table, button: int, rng: random.Random):
        self.table = table
        self.button = button
        self.rng = rng
        self.numbers = [rng.randint(1, DECK), rng.randint(1, DECK)]
        self.community = rng.randint(1, DECK)
        self.contributed = [0, 0]
        self.bet_this_round = [0, 0]
        self.folded = [False, False]
        self.actions: list[dict] = []
        self.round = "pre_reveal"

    # -- chips -----------------------------------------------------------------

    def stack(self, seat: int) -> int:
        return self.table.stacks[seat] - self.contributed[seat]

    def put_in(self, seat: int, chips: int) -> None:
        chips = max(0, min(chips, self.stack(seat)))
        self.contributed[seat] += chips
        self.bet_this_round[seat] += chips

    @property
    def pot(self) -> int:
        return sum(self.contributed)

    def to_call(self, seat: int) -> int:
        """Raw chips owed — NOT capped at our stack.

        The live coordinator sends the full amount owed even when it exceeds
        the stack (observed: your_stack 24, to_call 202). Capping it here is
        what let a bug through that folded pairs for their whole stack.
        """
        return max(self.bet_this_round) - self.bet_this_round[seat]

    def all_in(self, seat: int) -> bool:
        return self.stack(seat) == 0

    # -- the request we hand a bot --------------------------------------------

    def state_for(self, seat: int, min_raise_to, max_raise_to, legal) -> dict:
        other = 1 - seat
        return {
            "protocol_version": 2,
            "match_id": self.table.match_id,
            "phase": 1,
            "table_rule": TABLE["codename"],
            "small_blind": SMALL_BLIND,
            "big_blind": BIG_BLIND,
            "starting_stack": STARTING_STACK,
            "your_stack": self.stack(seat),
            "hand_number": self.table.hand_number,
            "total_hands": self.table.total_hands,
            "round": self.round,
            "your_number": self.numbers[seat],
            "community_number": self.community if self.round == "post_reveal" else None,
            "leg_number": self.table.leg_number,
            "total_legs": self.table.total_legs,
            "your_seat": seat,
            "button_seat": self.button,
            "pot": self.pot,
            "to_call": self.to_call(seat),
            "min_raise_to": min_raise_to,
            "max_raise_to": max_raise_to,
            "legal_actions": legal,
            "players": [
                {
                    "seat": s,
                    "name": "you" if s == seat else self.table.names[s],
                    "folded": self.folded[s],
                    "chip_delta": self.table.stacks[s] - STARTING_STACK,
                    "bet_this_round": self.bet_this_round[s],
                    "stack": self.stack(s),
                    "all_in": self.all_in(s),
                    "busted": False,
                }
                for s in (seat, other)
                if True
            ],
            "current_hand_actions": list(self.actions),
            "recent_hands": self.table.recent_hands[-20:],
        }

    # -- betting ---------------------------------------------------------------

    def betting_round(self, first: int) -> None:
        """Standard no-limit round: min raise is the size of the last raise."""
        last_raise = BIG_BLIND if self.round == "pre_reveal" else BIG_BLIND
        seat = first
        acted = {0: False, 1: False}
        while True:
            other = 1 - seat
            if self.folded[0] or self.folded[1]:
                return
            if self.all_in(seat) or self.all_in(other):
                # nobody left to act meaningfully once someone is all-in and
                # the bets are square
                if self.to_call(seat) == 0:
                    return
            if self.all_in(seat):
                return
            owed = self.to_call(seat)
            if acted[seat] and owed == 0:
                return

            high = max(self.bet_this_round)
            room = self.stack(seat) > owed
            if owed > 0:
                legal = ["fold", "call"]
                opener = "raise"
            else:
                legal = ["check"]
                opener = "bet"
            min_raise_to = max_raise_to = None
            if room and not self.all_in(other):
                legal.append(opener)
                max_raise_to = self.bet_this_round[seat] + self.stack(seat)
                min_raise_to = min(high + last_raise, max_raise_to)

            state = self.state_for(seat, min_raise_to, max_raise_to, legal)
            reply = self.table.bots[seat](state)
            action = reply.get("action")
            if action not in legal:
                action = "check" if "check" in legal else "fold"

            if action == "fold":
                self.folded[seat] = True
                self.actions.append({"round": self.round, "seat": seat, "action": "fold"})
                return
            if action == "check":
                self.actions.append({"round": self.round, "seat": seat, "action": "check"})
            elif action == "call":
                self.put_in(seat, min(owed, self.stack(seat)))
                self.actions.append(
                    {
                        "round": self.round,
                        "seat": seat,
                        "action": "call",
                        "amount": self.bet_this_round[seat],
                    }
                )
            else:  # bet / raise
                target = reply.get("amount")
                if not isinstance(target, int) or not (min_raise_to <= target <= max_raise_to):
                    target = min_raise_to
                raise_size = target - high
                self.put_in(seat, target - self.bet_this_round[seat])
                if raise_size > 0:
                    last_raise = max(last_raise, raise_size)
                    acted = {0: False, 1: False}
                self.actions.append(
                    {
                        "round": self.round,
                        "seat": seat,
                        "action": action,
                        "amount": self.bet_this_round[seat],
                    }
                )
            acted[seat] = True
            seat = other

    # -- resolution ------------------------------------------------------------

    def beats(self, a: int, b: int) -> int:
        rule = TABLE["rule"]
        ka = rule.key(self.numbers[a], self.community)
        kb = rule.key(self.numbers[b], self.community)
        return (ka > kb) - (ka < kb)

    def play(self) -> None:
        sb, bb = self.button, 1 - self.button
        self.put_in(sb, SMALL_BLIND)
        self.put_in(bb, BIG_BLIND)
        self.betting_round(first=self.button)

        went_to_showdown = not any(self.folded)
        if went_to_showdown:
            self.round = "post_reveal"
            self.bet_this_round = [0, 0]
            if not (self.all_in(0) or self.all_in(1)):
                self.betting_round(first=1 - self.button)

        # chips nobody could cover go back to whoever over-committed
        matched = min(self.contributed)
        for seat in (0, 1):
            refund = self.contributed[seat] - matched
            if refund:
                self.contributed[seat] -= refund
        pot = sum(self.contributed)

        if self.folded[0] or self.folded[1]:
            winners = [0 if self.folded[1] else 1]
            shown = {}
            community = None
        else:
            cmp = self.beats(0, 1)
            winners = [0] if cmp > 0 else [1] if cmp < 0 else [0, 1]
            shown = {"0": self.numbers[0], "1": self.numbers[1]}
            community = self.community

        for seat in (0, 1):
            self.table.stacks[seat] -= self.contributed[seat]
        share = pot // len(winners)
        for seat in winners:
            self.table.stacks[seat] += share
        self.table.stacks[winners[0]] += pot - share * len(winners)  # odd chip

        self.table.recent_hands.append(
            {
                "hand_number": self.table.hand_number,
                "community_number": community,
                "winners": winners,
                "pot": pot,
                "shown_numbers": shown,
                "actions": list(self.actions),
            }
        )


class Table:
    def __init__(self, bots, names, total_hands, seed, leg_number=None, total_legs=None):
        self.bots = bots
        self.names = names
        self.leg_number = leg_number
        self.total_legs = total_legs
        self.total_hands = total_hands
        self.stacks = [STARTING_STACK, STARTING_STACK]
        self.recent_hands: list[dict] = []
        self.hand_number = 0
        self.match_id = f"sim-seed{seed}"

    def play(self, rng) -> list[int]:
        for hand in range(1, self.total_hands + 1):
            if min(self.stacks) <= 0:
                break  # busted: out for the rest of the match
            self.hand_number = hand
            Hand(self, button=(hand - 1) % 2, rng=rng).play()
        return [s - STARTING_STACK for s in self.stacks]


# ───────────────────────────────── opponents ──────────────────────────────────


def _live_count(state) -> int:
    """How many opponents can still take this pot, from the wire."""
    players = state.get("players")
    if not isinstance(players, list):
        return 1
    return max(
        1,
        sum(
            1
            for p in players
            if isinstance(p, dict)
            and p.get("name") != "you"
            and not p.get("folded")
            and not p.get("busted")
        ),
    )


def _eq(state) -> float:
    """Opponent-side equity, computed under the table's ACTUAL rule.

    The house bots know their own table, and phase 3 says "every opponent here
    plays the rule correctly". They also price against the whole field: a house
    bot that valued its number heads-up while five players were live would be a
    strawman, and beating a strawman tells us nothing.
    """
    return _share_vs_field(
        TABLE["rule"], state["your_number"], state.get("community_number"),
        _live_count(state),
    )


def _share_vs_field(rule, n, c, k: int) -> float:
    """Expected share of the pot holding `n` against `k` uniform opponents.

    The same dynamic program as app.showdown_rules.rule_equity_multiway, written
    out here so it also works for the EXOTIC rules, which are deliberately not in
    the app's hypothesis set.
    """
    cs = range(1, DECK + 1) if c is None else (c,)
    total = 0.0
    for cc in cs:
        ours = rule.key(n, cc)
        below = tied = 0.0
        for m in range(1, DECK + 1):
            theirs = rule.key(m, cc)
            if theirs < ours:
                below += 1.0
            elif theirs == ours:
                tied += 1.0
        below /= DECK
        tied /= DECK
        dist = [1.0] + [0.0] * k
        for _ in range(k):
            nxt = [0.0] * (k + 1)
            for j in range(k):
                w = dist[j]
                if w:
                    nxt[j] += w * below
                    nxt[j + 1] += w * tied
            dist = nxt
        total += sum(w / (1 + j) for j, w in enumerate(dist) if w)
    return total / len(cs)


def _eq_exotic(state) -> float:
    return _eq(state)


def bot_station(state):
    """Never folds, never raises. Punishes bluffing, pays off value bets."""
    legal = state["legal_actions"]
    return {"action": "call"} if "call" in legal else {"action": "check"}


def bot_rock(state):
    """Plays only strong numbers, folds everything else."""
    legal, eq = state["legal_actions"], _eq(state)
    if eq >= 0.70 and "raise" in legal:
        return {"action": "raise", "amount": state["min_raise_to"]}
    if eq >= 0.70 and "bet" in legal:
        return {"action": "bet", "amount": min(state["max_raise_to"], state["min_raise_to"] + 4)}
    if eq >= 0.55 and "call" in legal:
        return {"action": "call"}
    return {"action": "check"} if "check" in legal else {"action": "fold"}


def make_maniac(rng):
    def bot(state):
        legal = state["legal_actions"]
        if rng.random() < 0.55 and state["min_raise_to"] is not None:
            lo, hi = state["min_raise_to"], state["max_raise_to"]
            amount = min(hi, max(lo, int(state["pot"] * rng.uniform(0.7, 1.6))))
            if "raise" in legal:
                return {"action": "raise", "amount": amount}
            if "bet" in legal:
                return {"action": "bet", "amount": amount}
        if "check" in legal:
            return {"action": "check"}
        return {"action": "call"} if rng.random() < 0.7 else {"action": "fold"}

    return bot


def bot_sane(state):
    """Straightforward equity + pot odds, no bluffs — the likely house bot."""
    legal, eq = state["legal_actions"], _eq(state)
    pot, to_call = state["pot"], state["to_call"]
    if to_call > 0:
        odds = to_call / (pot + to_call)
        if eq >= 0.78 and "raise" in legal:
            lo, hi = state["min_raise_to"], state["max_raise_to"]
            return {"action": "raise", "amount": min(hi, max(lo, int(pot * 0.7)))}
        return {"action": "call"} if eq >= odds else {"action": "fold"}
    if eq >= 0.62 and "bet" in legal:
        lo, hi = state["min_raise_to"], state["max_raise_to"]
        return {"action": "bet", "amount": min(hi, max(lo, int(pot * 0.6)))}
    return {"action": "check"} if "check" in legal else {"action": "fold"}


def make_gaston(rng):
    """Reconstructed from the live phase-1 opponent (see the debug log).

    Jams a pair hard post-reveal and re-raises big over our raises, with enough
    bluff-shoving that folding every high card to him is not free either.
    """

    def bot(state):
        legal, eq = state["legal_actions"], _eq(state)
        pot, to_call = state["pot"], state["to_call"]
        n, c = state["your_number"], state.get("community_number")
        rule = TABLE["rule"]
        pair = c is not None and all(
            rule.key(m, c) <= rule.key(n, c) for m in range(1, DECK + 1)
        )
        lo, hi = state["min_raise_to"], state["max_raise_to"]
        big = rng.random() < 0.30  # bluff-shove frequency
        if lo is not None and (pair or eq >= 0.80 or big):
            size = 3.0 if (pair or big) else 1.0
            amount = min(hi, max(lo, int((pot + to_call) * size)))
            if "raise" in legal:
                return {"action": "raise", "amount": amount}
            if "bet" in legal:
                return {"action": "bet", "amount": amount}
        if to_call > 0:
            odds = to_call / (pot + to_call)
            return {"action": "call"} if eq >= odds else {"action": "fold"}
        if "bet" in legal and eq >= 0.60 and lo is not None:
            return {"action": "bet", "amount": min(hi, max(lo, int(pot * 0.6)))}
        return {"action": "check"} if "check" in legal else {"action": "fold"}

    return bot


def make_random(rng):
    def bot(state):
        legal = state["legal_actions"]
        action = rng.choice(legal)
        if action in ("bet", "raise"):
            lo, hi = state["min_raise_to"], state["max_raise_to"]
            return {"action": action, "amount": rng.randint(lo, hi)}
        return {"action": action}

    return bot


def opponents(rng):
    return {
        "station": bot_station,
        "rock": bot_rock,
        "maniac": make_maniac(rng),
        "sane": bot_sane,
        "gaston": make_gaston(rng),
        "random": make_random(rng),
    }


# ────────────────────────────────── running ───────────────────────────────────


def run(name, opponent, matches, hands, seed0=0):
    deltas = []
    for i in range(matches):
        rng = random.Random(seed0 + i)
        # alternate seats so position/blind order cannot flatter us
        us, them = (decide, opponent) if i % 2 == 0 else (opponent, decide)
        names = ["you", name] if i % 2 == 0 else [name, "you"]
        table = Table([us, them], names, hands, seed0 + i)
        result = table.play(rng)
        deltas.append(result[0] if i % 2 == 0 else result[1])
    cleared = sum(d >= 10 for d in deltas) / len(deltas)
    busted = sum(d <= -STARTING_STACK for d in deltas) / len(deltas)
    return {
        "mean": statistics.mean(deltas),
        "median": statistics.median(deltas),
        "clear_rate": cleared,
        "bust_rate": busted,
    }


def report(matches, hands):
    rng = random.Random(7)
    print(f"{matches} matches x {hands} hands, seats alternated\n")
    print(f"{'opponent':<10} {'mean Δ':>8} {'median':>8} {'P(Δ>=+10)':>10} {'P(bust)':>8}")
    print("-" * 48)
    overall = []
    for name, bot in opponents(rng).items():
        r = run(name, bot, matches, hands)
        overall.append(r["clear_rate"])
        print(
            f"{name:<10} {r['mean']:>8.1f} {r['median']:>8.0f} "
            f"{r['clear_rate']:>9.0%} {r['bust_rate']:>8.1%}"
        )
    print("-" * 48)
    print(f"{'worst case':<10} {'':>8} {'':>8} {min(overall):>9.0%}")


def sweep(matches, hands):
    """One knob at a time, worst-case clear rate across all opponents."""
    knobs = {
        "RAISE_EQ": [0.66, 0.70, 0.72, 0.76, 0.82],
        "CALL_MARGIN": [0.0, 0.03, 0.055, 0.09, 0.14],
        "BLUFF_RATE": [0.0, 0.10, 0.18, 0.28, 0.40],
        "RAISE_RISK": [0.0, 0.18, 0.34, 0.50, 0.70],
        "CALL_RISK": [0.0, 0.12, 0.20, 0.32, 0.45],
        "RANGE_TRUST": [0.4, 0.6, 0.75, 0.9, 1.0],
        "RERAISE_EQ": [0.78, 0.82, 0.86, 0.90],
        "PAIR_GAIN": [0.0, 0.10, 0.18, 0.28, 0.40],
        "PAIR_MAX": [0.25, 0.40, 0.55, 0.70, 0.85],
        "RANGE_TRUST": [0.6, 0.75, 0.85, 0.95],
        "CALL_RISK": [0.08, 0.14, 0.20, 0.30],
        "RAISE_RISK": [0.08, 0.18, 0.30, 0.45],
    }
    for knob, values in knobs.items():
        original = getattr(showdown, knob)
        print(f"\n{knob}  (current {original})")
        for value in values:
            setattr(showdown, knob, value)
            rng = random.Random(7)
            results = {n: run(n, b, matches, hands) for n, b in opponents(rng).items()}
            worst = min(r["clear_rate"] for r in results.values())
            mean = statistics.mean(r["mean"] for r in results.values())
            detail = " ".join(f"{n[:4]}={r['mean']:+.0f}" for n, r in results.items())
            print(f"  {value:<6} worst P(clear)={worst:>4.0%}  mean Δ={mean:+6.1f}   {detail}")
        setattr(showdown, knob, original)


# ───────────────────────────── phase 2: hidden tables ───────────────────────────


def play_leg(bots, names, rule, codename, hands, seed, leg_number, total_legs):
    """One leg: fresh stacks, its own table rule, its own recent_hands."""
    TABLE["rule"], TABLE["codename"] = rule, codename
    table = Table(bots, names, hands, seed, leg_number, total_legs)
    return table.play(random.Random(seed))


def phase2_attempt(opponent, name, rules, seed, hands=40):
    """Four legs back to back. Returns each leg's chip delta for us."""
    deltas = []
    for i, rule in enumerate(rules, start=1):
        us, them = (decide, opponent) if i % 2 == 0 else (opponent, decide)
        names = ["you", name] if i % 2 == 0 else [name, "you"]
        out = play_leg(
            [us, them], names, rule, f"codename-{rule.name}", hands,
            seed * 10 + i, i, len(rules),
        )
        deltas.append(out[0] if i % 2 == 0 else out[1])
    return deltas


def phase2_report(attempts, opponent_name, rule_names, hands=40):
    """Cold = a fresh process meeting these tables for the first time.
    Warm  = a later retry, where an earlier attempt already taught us the rules
            (the statement guarantees the leg order and rules never change)."""
    rules = [BY_NAME.get(n) or next(r for r in EXOTIC if r.name == n) for n in rule_names]
    rng = random.Random(7)
    opponent = opponents(rng)[opponent_name]
    print(f"\nvs {opponent_name}: legs = {', '.join(rule_names)}   ({attempts} attempts)")
    print(f"  {'':14} {'leg1':>6} {'leg2':>6} {'leg3':>6} {'leg4':>6} {'points':>8}")
    for label in ("cold", "warm"):
        cleared = [0] * len(rules)
        points = []
        for a in range(attempts):
            forget_all()
            if label == "warm":
                phase2_attempt(opponent, opponent_name, rules, seed=9000 + a, hands=hands)
            deltas = phase2_attempt(opponent, opponent_name, rules, seed=a, hands=hands)
            got = 0
            for i, d in enumerate(deltas):
                if d >= 25:
                    cleared[i] += 1
                    got += 100
            points.append(got)
        rates = "".join(f"{c / attempts:>6.0%}" for c in cleared)
        print(f"  {label:<14}{rates} {statistics.mean(points):>8.0f}")


# ─────────────────────── phase 3: six seats, side pots ──────────────────────────
#
# The heads-up engine above cannot be stretched to six: forced bets move from
# "the two of you" to "the two seats past the button", the acting order opens in
# two different places depending on the round, busted seats have to be skipped by
# both the button and the deal, and an all-in has to build side pots instead of
# refunding the difference. So phase 3 gets its own table, following the phase-3
# statement's position diagram exactly.

SEATS = 6


class CrowdedHand:
    """One six-seat hand: blinds, deal, two betting rounds, layered showdown."""

    def __init__(self, table, button: int, rng: random.Random):
        self.table = table
        self.rng = rng
        self.seats = [s for s in range(table.seats) if table.stacks[s] > 0]
        self.button = button
        self.numbers = {s: rng.randint(1, DECK) for s in self.seats}
        self.community = rng.randint(1, DECK)
        self.contributed = {s: 0 for s in self.seats}
        self.bet_this_round = {s: 0 for s in self.seats}
        self.folded = {s: False for s in self.seats}
        self.actions: list[dict] = []
        self.round = "pre_reveal"

    # -- seating ---------------------------------------------------------------

    def after(self, seat: int, steps: int = 1) -> int:
        """`steps` live seats clockwise of `seat` — busted seats do not exist."""
        i = self.seats.index(seat)
        return self.seats[(i + steps) % len(self.seats)]

    def contenders(self) -> list[int]:
        return [s for s in self.seats if not self.folded[s]]

    def stack(self, seat: int) -> int:
        return self.table.stacks[seat] - self.contributed[seat]

    def all_in(self, seat: int) -> bool:
        return self.stack(seat) == 0

    def put_in(self, seat: int, chips: int) -> None:
        chips = max(0, min(chips, self.stack(seat)))
        self.contributed[seat] += chips
        self.bet_this_round[seat] += chips

    @property
    def pot(self) -> int:
        return sum(self.contributed.values())

    def to_call(self, seat: int) -> int:
        return max(self.bet_this_round.values()) - self.bet_this_round[seat]

    # -- the request we hand a bot --------------------------------------------

    def state_for(self, seat, min_raise_to, max_raise_to, legal) -> dict:
        return {
            "protocol_version": 2,
            "match_id": self.table.match_id,
            "phase": 3,
            "table_rule": TABLE["codename"],
            "small_blind": SMALL_BLIND,
            "big_blind": BIG_BLIND,
            "starting_stack": STARTING_STACK,
            "your_stack": self.stack(seat),
            "hand_number": self.table.hand_number,
            "total_hands": self.table.total_hands,
            "round": self.round,
            "your_number": self.numbers[seat],
            "community_number": self.community if self.round == "post_reveal" else None,
            "leg_number": self.table.leg_number,
            "total_legs": self.table.total_legs,
            "your_seat": seat,
            "button_seat": self.button,
            "pot": self.pot,
            "to_call": self.to_call(seat),
            "min_raise_to": min_raise_to,
            "max_raise_to": max_raise_to,
            "legal_actions": legal,
            "players": [
                {
                    "seat": s,
                    "name": "you" if s == seat else self.table.names[s],
                    "folded": bool(self.folded.get(s)),
                    "chip_delta": self.table.stacks[s] - STARTING_STACK,
                    "bet_this_round": self.bet_this_round.get(s, 0),
                    "stack": self.stack(s) if s in self.seats else 0,
                    "all_in": s in self.seats and self.all_in(s),
                    "busted": s not in self.seats,
                }
                for s in range(self.table.seats)
            ],
            "current_hand_actions": list(self.actions),
            "recent_hands": self.table.recent_hands[-20:],
        }

    # -- betting ---------------------------------------------------------------

    def betting_round(self, first: int) -> None:
        last_raise = BIG_BLIND
        acted = {s: False for s in self.seats}
        seat = first
        while True:
            if len(self.contenders()) <= 1:
                return
            can_act = [s for s in self.contenders() if not self.all_in(s)]
            if not can_act:
                return
            if all(acted[s] and self.to_call(s) == 0 for s in can_act):
                return
            if self.folded[seat] or self.all_in(seat) or (acted[seat] and self.to_call(seat) == 0):
                seat = self.after(seat)
                continue

            owed = self.to_call(seat)
            high = max(self.bet_this_round.values())
            if owed > 0:
                legal, opener = ["fold", "call"], "raise"
            else:
                legal, opener = ["check"], "bet"
            min_raise_to = max_raise_to = None
            # someone has to be left who could still respond to a raise
            respondable = [s for s in self.contenders() if s != seat and not self.all_in(s)]
            if self.stack(seat) > owed and respondable:
                legal.append(opener)
                max_raise_to = self.bet_this_round[seat] + self.stack(seat)
                min_raise_to = min(high + last_raise, max_raise_to)

            reply = self.table.bots[seat](self.state_for(seat, min_raise_to, max_raise_to, legal))
            action = reply.get("action")
            if action not in legal:
                action = "check" if "check" in legal else "fold"

            if action == "fold":
                self.folded[seat] = True
                self.actions.append({"round": self.round, "seat": seat, "action": "fold"})
            elif action == "check":
                self.actions.append({"round": self.round, "seat": seat, "action": "check"})
            elif action == "call":
                self.put_in(seat, min(owed, self.stack(seat)))
                self.actions.append({"round": self.round, "seat": seat, "action": "call",
                                     "amount": self.bet_this_round[seat]})
            else:
                target = reply.get("amount")
                if not isinstance(target, int) or not (min_raise_to <= target <= max_raise_to):
                    target = min_raise_to
                size = target - high
                self.put_in(seat, target - self.bet_this_round[seat])
                if size > 0:
                    last_raise = max(last_raise, size)
                    acted = {s: False for s in self.seats}  # the round reopens
                self.actions.append({"round": self.round, "seat": seat, "action": action,
                                     "amount": self.bet_this_round[seat]})
            acted[seat] = True
            seat = self.after(seat)

    # -- resolution ------------------------------------------------------------

    def best_of(self, seats: list[int]) -> list[int]:
        rule = TABLE["rule"]
        keyed = {s: rule.key(self.numbers[s], self.community) for s in seats}
        best = max(keyed.values())
        return [s for s in seats if keyed[s] == best]

    def payout(self) -> dict[int, int]:
        """Split the pot into main and side pots and award each one.

        Everyone contests the main pot; a seat that could only cover part of the
        betting is simply not eligible for the layers above what it paid in.
        """
        won = {s: 0 for s in self.seats}
        live = self.contenders()
        if len(live) == 1:
            won[live[0]] = self.pot
            return won
        levels = sorted({self.contributed[s] for s in self.seats if self.contributed[s] > 0})
        floor = 0
        for level in levels:
            chips = sum(min(self.contributed[s], level) - floor
                        for s in self.seats if self.contributed[s] > floor)
            eligible = [s for s in live if self.contributed[s] >= level]
            if chips <= 0:
                floor = level
                continue
            if not eligible:  # everyone eligible for this layer folded
                eligible = live
            winners = self.best_of(eligible)
            share, odd = divmod(chips, len(winners))
            for s in winners:
                won[s] += share
            won[winners[0]] += odd
            floor = level
        return won

    def play(self) -> None:
        # "Forced bets start just past the button: seat 1 pays 1, seat 2 pays 2."
        small, big = self.after(self.button), self.after(self.button, 2)
        if len(self.seats) == 2:  # heads-up rump: the button pays the small blind
            small, big = self.button, self.after(self.button)
        self.put_in(small, SMALL_BLIND)
        self.put_in(big, BIG_BLIND)

        # "the order opens just past the seat that paid 2, so that seat acts last"
        self.betting_round(first=self.after(big))

        if len(self.contenders()) > 1:
            self.round = "post_reveal"
            self.bet_this_round = {s: 0 for s in self.seats}
            if sum(1 for s in self.contenders() if not self.all_in(s)) > 1:
                # "the order opens just past the button, so the button acts last"
                self.betting_round(first=self.after(self.button))

        won = self.payout()
        for s in self.seats:
            self.table.stacks[s] += won[s] - self.contributed[s]

        live = self.contenders()
        showdown = len(live) > 1
        self.table.recent_hands.append({
            "hand_number": self.table.hand_number,
            "community_number": self.community if showdown else None,
            "winners": sorted(s for s in self.seats if won[s] > self.contributed[s]),
            "pot": self.pot,
            "shown_numbers": {str(s): self.numbers[s] for s in live} if showdown else {},
            "actions": list(self.actions),
        })


class CrowdedTable:
    def __init__(self, bots, names, total_hands, seed, leg_number, total_legs, seats=SEATS):
        self.bots = bots
        self.names = names
        self.seats = seats
        self.leg_number = leg_number
        self.total_legs = total_legs
        self.total_hands = total_hands
        self.stacks = [STARTING_STACK] * seats
        self.recent_hands: list[dict] = []
        self.hand_number = 0
        self.match_id = f"sim6-seed{seed}"

    def play(self, rng) -> list[int]:
        button = 0
        for hand in range(1, self.total_hands + 1):
            live = [s for s in range(self.seats) if self.stacks[s] > 0]
            if len(live) <= 1:
                break  # "the match only ends early if just one player still has chips"
            self.hand_number = hand
            while button not in live:  # the button skips anyone who has busted
                button = (button + 1) % self.seats
            CrowdedHand(self, button, rng).play()
            button = (button + 1) % self.seats
        return [s - STARTING_STACK for s in self.stacks]


def phase3_leg(seat_of_ours, rule, codename, hands, seed, leg_number, total_legs):
    """One six-seat leg. Returns every seat's chip delta, and which seat is ours."""
    TABLE["rule"], TABLE["codename"] = rule, codename
    rng = random.Random(seed)
    house = opponents(random.Random(seed + 1))
    others = ["station", "rock", "maniac", "sane", "gaston"]
    bots, names = [], []
    pool = iter(others)
    for s in range(SEATS):
        if s == seat_of_ours:
            bots.append(decide)
            names.append("you")
        else:
            who = next(pool)
            bots.append(house[who])
            names.append(who)
    table = CrowdedTable(bots, names, hands, seed, leg_number, total_legs)
    return table.play(rng)


def phase3_attempt(rules, seed, hands=60):
    """Four legs back to back, our seat rotated so position cannot flatter us."""
    out = []
    for i, rule in enumerate(rules, start=1):
        ours = (i - 1) % SEATS
        deltas = phase3_leg(ours, rule, f"codename-{rule.name}", hands,
                            seed * 10 + i, i, len(rules))
        out.append((deltas[ours], max(d for s, d in enumerate(deltas) if s != ours)))
    return out


def phase3_report(attempts, rule_names, hands=60):
    """Scored the way the statement scores it: +10 AND strictly top the table."""
    rules = [BY_NAME.get(n) or next(r for r in EXOTIC if r.name == n) for n in rule_names]
    print(f"\nsix seats, {hands} hands x {len(rules)} legs: {', '.join(rule_names)}"
          f"   ({attempts} attempts)")
    print(f"  {'':14} {'leg1':>6} {'leg2':>6} {'leg3':>6} {'leg4':>6} {'points':>8} {'mean Δ':>8}")
    for label in ("cold", "warm"):
        cleared = [0] * len(rules)
        points, deltas = [], []
        for a in range(attempts):
            forget_all()
            if label == "warm":
                phase3_attempt(rules, seed=9000 + a, hands=hands)
            got = 0
            for i, (ours, best_other) in enumerate(phase3_attempt(rules, seed=a, hands=hands)):
                deltas.append(ours)
                if ours >= 10 and ours > best_other:
                    cleared[i] += 1
                    got += 150
            points.append(got)
        rates = "".join(f"{c / attempts:>6.0%}" for c in cleared)
        print(f"  {label:<14}{rates} {statistics.mean(points):>8.0f} "
              f"{statistics.mean(deltas):>8.1f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=int, default=1000)
    parser.add_argument("--hands", type=int, default=100)
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--phase2", action="store_true")
    parser.add_argument("--phase3", action="store_true")
    parser.add_argument("--legs", default="low,near,wrap_up,antipair_high")
    args = parser.parse_args()
    if args.phase3:
        phase3_report(max(args.matches // 25, 20), args.legs.split(","))
    elif args.sweep:
        sweep(max(args.matches // 4, 150), args.hands)
    elif args.phase2:
        names = args.legs.split(",")
        for who in ("sane", "gaston", "rock"):
            phase2_report(max(args.matches // 10, 40), who, names)
    else:
        report(args.matches, args.hands)
