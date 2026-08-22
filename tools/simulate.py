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
            "table_rule": "standard",
            "small_blind": SMALL_BLIND,
            "big_blind": BIG_BLIND,
            "starting_stack": STARTING_STACK,
            "your_stack": self.stack(seat),
            "hand_number": self.table.hand_number,
            "total_hands": self.table.total_hands,
            "round": self.round,
            "your_number": self.numbers[seat],
            "community_number": self.community if self.round == "post_reveal" else None,
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
        pair_a, pair_b = self.numbers[a] == self.community, self.numbers[b] == self.community
        if pair_a != pair_b:
            return 1 if pair_a else -1
        return (self.numbers[a] > self.numbers[b]) - (self.numbers[a] < self.numbers[b])

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
    def __init__(self, bots, names, total_hands, seed):
        self.bots = bots
        self.names = names
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


def _eq(state) -> float:
    return equity(state["your_number"], state.get("community_number"))


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
        pair = c is not None and n == c
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=int, default=1000)
    parser.add_argument("--hands", type=int, default=100)
    parser.add_argument("--sweep", action="store_true")
    args = parser.parse_args()
    if args.sweep:
        sweep(max(args.matches // 4, 150), args.hands)
    else:
        report(args.matches, args.hands)
