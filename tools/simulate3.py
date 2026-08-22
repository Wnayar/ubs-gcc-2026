#!/usr/bin/env python3
"""Offline six-seat SHOWDOWN table, for phase 3.

`tools/simulate.py` is heads-up to its bones — two stacks, `1 - seat`, no side
pots — and phase 3's whole point is that none of that holds any more. Rather than
bend it out of shape and risk the phase 1/2 tuning it still carries, this is a
separate N-seat engine following docs/phases/showdown/phase-3/statement.pdf:

* six seats, 200 chips each, blinds 1/2;
* forced bets start just past the button (the button pays nothing), the
  pre-reveal order opens just past the seat that paid 2 and the post-reveal
  order just past the button;
* the button moves one seat along every hand, skipping busted seats;
* bust at 0 chips and you are out of the match while the others play on; the
  match ends early only when one player has all the chips;
* proper side pots, because six stacks of different sizes is the normal case.

    python3 tools/simulate3.py                 # 4 legs x 60 hands, scored
    python3 tools/simulate3.py --attempts 200
    python3 tools/simulate3.py --sweep FIELD_TIGHTEN
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import showdown  # noqa: E402
from app.showdown import acting_order, decide, forced_bet_seats  # noqa: E402
from app.showdown_rules import BY_NAME, Rule, forget_all  # noqa: E402
from tools.simulate import EXOTIC  # noqa: E402

DECK = 13
SMALL_BLIND, BIG_BLIND = 1, 2
STARTING_STACK = 200

TABLE: dict = {"rule": BY_NAME["standard"], "codename": "standard"}


# ────────────────────────────────── one hand ───────────────────────────────────


class Hand:
    def __init__(self, table, button: int, rng: random.Random):
        self.table = table
        self.button = button
        self.rng = rng
        self.seats = list(table.alive())  # seats still in the match, in seat order
        self.numbers = {s: rng.randint(1, DECK) for s in self.seats}
        self.community = rng.randint(1, DECK)
        self.contributed = {s: 0 for s in self.seats}
        self.bet_this_round = {s: 0 for s in self.seats}
        self.folded = {s: False for s in self.seats}
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
        return sum(self.contributed.values())

    def to_call(self, seat: int) -> int:
        """Raw chips owed, NOT capped at the seat's stack — the live coordinator
        sends the full amount owed even when it exceeds the stack."""
        return max(self.bet_this_round.values()) - self.bet_this_round[seat]

    def all_in(self, seat: int) -> bool:
        return self.stack(seat) == 0

    def live(self) -> list[int]:
        return [s for s in self.seats if not self.folded[s]]

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
            # the full seating, folded and busted seats included, in seat order
            "players": [
                {
                    "seat": s,
                    "name": "you" if s == seat else self.table.names[s],
                    "folded": self.folded.get(s, True),
                    "chip_delta": self.table.stacks[s] - STARTING_STACK,
                    "bet_this_round": self.bet_this_round.get(s, 0),
                    "stack": self.stack(s) if s in self.seats else 0,
                    "all_in": self.all_in(s) if s in self.seats else False,
                    "busted": s not in self.seats,
                }
                for s in range(self.table.size)
            ],
            "current_hand_actions": list(self.actions),
            "recent_hands": self.table.recent_hands[-20:],
        }

    # -- betting ---------------------------------------------------------------

    def _round_over(self, order, acted) -> bool:
        live = [s for s in order if not self.folded[s]]
        if len(live) < 2:
            return True
        return not [
            s for s in live
            if not self.all_in(s) and (self.to_call(s) > 0 or s not in acted)
        ]

    def betting_round(self, order: list[int]) -> None:
        """No-limit multiway: action cycles until everyone live has matched the
        high bet and acted since the last raise."""
        last_raise = BIG_BLIND
        acted: set[int] = set()
        pos = 0
        for _ in range(400):  # guard against a pathological loop
            if self._round_over(order, acted):
                return
            seat = order[pos % len(order)]
            pos += 1
            if self.folded[seat] or self.all_in(seat):
                continue
            owed = self.to_call(seat)
            if owed == 0 and seat in acted:
                continue

            high = max(self.bet_this_round.values())
            others_can_act = any(
                s != seat and not self.folded[s] and not self.all_in(s) for s in order
            )
            if owed > 0:
                legal, opener = ["fold", "call"], "raise"
            else:
                legal, opener = ["check"], "bet"
            min_raise_to = max_raise_to = None
            if self.stack(seat) > owed and others_can_act:
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
                    acted = set()  # a raise reopens the action for everyone
                self.actions.append({"round": self.round, "seat": seat, "action": action,
                                     "amount": self.bet_this_round[seat]})
            acted.add(seat)

    # -- resolution ------------------------------------------------------------

    def _side_pots(self) -> list[tuple[int, list[int]]]:
        """(chips, seats eligible to win them), smallest layer first.

        Six stacks of different sizes means a short all-in can only win the part
        of the pot it covered; the rest is contested by whoever put in more.
        """
        live = self.live()
        levels = sorted({c for c in self.contributed.values() if c > 0})
        pots, previous = [], 0
        for level in levels:
            chips = sum(
                min(c, level) - min(c, previous) for c in self.contributed.values()
            )
            eligible = [s for s in live if self.contributed[s] >= level]
            if chips > 0:
                pots.append((chips, eligible))
            previous = level
        return pots

    def _best(self, seats: list[int]) -> list[int]:
        key = TABLE["rule"].key
        keyed = {s: key(self.numbers[s], self.community) for s in seats}
        top = max(keyed.values())
        return sorted(s for s, k in keyed.items() if k == top)

    def play(self) -> None:
        pays_one, pays_two = forced_bet_seats(self.button, self.seats)
        if pays_one is None:
            return
        self.put_in(pays_one, SMALL_BLIND)
        self.put_in(pays_two, BIG_BLIND)

        self.betting_round(acting_order(self.button, self.seats, "pre_reveal"))

        showdown_reached = len(self.live()) > 1
        if showdown_reached:
            self.round = "post_reveal"
            self.bet_this_round = {s: 0 for s in self.seats}
            if sum(1 for s in self.live() if not self.all_in(s)) > 1:
                self.betting_round(acting_order(self.button, self.seats, "post_reveal"))
            showdown_reached = len(self.live()) > 1

        for seat in self.seats:
            self.table.stacks[seat] -= self.contributed[seat]

        winners: list[int] = []
        if not showdown_reached:
            taker = self.live()[0]
            self.table.stacks[taker] += self.pot
            winners, shown, community = [taker], {}, None
        else:
            won = {}
            for chips, eligible in self._side_pots():
                if not eligible:  # everyone at this level folded: give it back
                    for seat in self.seats:
                        if self.contributed[seat] >= chips:
                            self.table.stacks[seat] += chips
                            break
                    continue
                best = self._best(eligible)
                share = chips // len(best)
                for seat in best:
                    self.table.stacks[seat] += share
                    won[seat] = won.get(seat, 0) + share
                self.table.stacks[best[0]] += chips - share * len(best)
            winners = sorted(won)
            shown = {str(s): self.numbers[s] for s in self.live()}
            community = self.community

        self.table.recent_hands.append({
            "hand_number": self.table.hand_number,
            "community_number": community,
            "winners": winners,
            "pot": self.pot,
            "shown_numbers": shown,
            "actions": list(self.actions),
        })


class Table:
    def __init__(self, bots, names, total_hands, seed, leg_number=None, total_legs=None):
        self.bots = bots
        self.names = names
        self.size = len(bots)
        self.leg_number = leg_number
        self.total_legs = total_legs
        self.total_hands = total_hands
        self.stacks = [STARTING_STACK] * self.size
        self.recent_hands: list[dict] = []
        self.hand_number = 0
        self.match_id = f"sim3-seed{seed}"

    def alive(self) -> list[int]:
        return [s for s in range(self.size) if self.stacks[s] > 0]

    def play(self, rng) -> list[int]:
        button = -1  # so hand 1 puts the button on the lowest live seat
        for hand in range(1, self.total_hands + 1):
            alive = self.alive()
            if len(alive) < 2:
                break  # "the match only ends early if just one player still has chips"
            self.hand_number = hand
            # the button moves one seat along every hand, skipping busted seats
            later = [s for s in alive if s > button]
            button = later[0] if later else alive[0]
            Hand(self, button=button, rng=rng).play()
        return [s - STARTING_STACK for s in self.stacks]


# ───────────────────────── the five house opponents ────────────────────────────
# "It's the same five every leg, and they play very differently from one another."
# They know the table rule — a house bot presumably knows the game it deals — and
# they reason multiway, so beating them is not a matter of out-reading the rule.


def true_equity(state) -> float:
    """The seat's real share of the pot under the ACTUAL rule, multiway."""
    rule, n, c = TABLE["rule"], state["your_number"], state.get("community_number")
    live = sum(
        1 for p in state["players"]
        if not p["folded"] and not p["busted"] and p["name"] != "you"
    )
    communities = list(range(1, DECK + 1)) if c is None else [c]
    total = 0.0
    for cc in communities:
        ours = rule.key(n, cc)
        lose = tie = 0.0
        for m in range(1, DECK + 1):
            theirs = rule.key(m, cc)
            if theirs < ours:
                lose += 1 / DECK
            elif theirs == ours:
                tie += 1 / DECK
        poly = [1.0]
        for _ in range(max(live, 1)):
            nxt = [0.0] * (len(poly) + 1)
            for j, v in enumerate(poly):
                nxt[j] += v * lose
                nxt[j + 1] += v * tie
            poly = nxt
        total += sum(v / (j + 1) for j, v in enumerate(poly))
    return total / len(communities)


def _sized(state, fraction):
    lo, hi = state["min_raise_to"], state["max_raise_to"]
    return min(hi, max(lo, int((state["pot"] + state["to_call"]) * fraction)))


def bot_station(state):
    """Never folds, never raises. Punishes bluffing, pays off value bets."""
    legal = state["legal_actions"]
    return {"action": "call"} if "call" in legal else {"action": "check"}


def bot_rock(state):
    """Only plays strong numbers, and knows a strong number is rarer six-handed."""
    legal, eq = state["legal_actions"], true_equity(state)
    fair = 1.0 / (1 + max(_live(state), 1))
    if eq >= 2.2 * fair and state["min_raise_to"] is not None:
        if "raise" in legal:
            return {"action": "raise", "amount": _sized(state, 0.8)}
        if "bet" in legal:
            return {"action": "bet", "amount": _sized(state, 0.7)}
    if state["to_call"] > 0:
        odds = state["to_call"] / (state["pot"] + state["to_call"])
        return {"action": "call"} if eq >= odds * 1.3 else {"action": "fold"}
    return {"action": "check"} if "check" in legal else {"action": "fold"}


def bot_sane(state):
    """Straightforward equity against pot odds — the likely house bot."""
    legal, eq = state["legal_actions"], true_equity(state)
    fair = 1.0 / (1 + max(_live(state), 1))
    to_call, pot = state["to_call"], state["pot"]
    if to_call > 0:
        odds = to_call / (pot + to_call)
        if eq >= 2.6 * fair and "raise" in legal:
            return {"action": "raise", "amount": _sized(state, 0.7)}
        return {"action": "call"} if eq >= odds else {"action": "fold"}
    if eq >= 1.9 * fair and "bet" in legal:
        return {"action": "bet", "amount": _sized(state, 0.6)}
    return {"action": "check"} if "check" in legal else {"action": "fold"}


def make_maniac(rng):
    """Bets huge and often. Six-handed this is far more punishing than it looks:
    somebody always has something."""
    def bot(state):
        legal = state["legal_actions"]
        if rng.random() < 0.5 and state["min_raise_to"] is not None:
            amount = _sized(state, rng.uniform(0.7, 1.8))
            if "raise" in legal:
                return {"action": "raise", "amount": amount}
            if "bet" in legal:
                return {"action": "bet", "amount": amount}
        if "check" in legal:
            return {"action": "check"}
        return {"action": "call"} if rng.random() < 0.65 else {"action": "fold"}
    return bot


def make_gaston(rng):
    """Reconstructed from the live phase 1 opponent: jams anything unbeatable,
    re-raises big, and bluff-shoves often enough that folding to him is not free."""
    def bot(state):
        legal, eq = state["legal_actions"], true_equity(state)
        n, c = state["your_number"], state.get("community_number")
        rule = TABLE["rule"]
        locked = c is not None and all(
            rule.key(m, c) <= rule.key(n, c) for m in range(1, DECK + 1)
        )
        big = rng.random() < 0.22
        if state["min_raise_to"] is not None and (locked or eq >= 0.55 or big):
            amount = _sized(state, 2.5 if (locked or big) else 1.0)
            if "raise" in legal:
                return {"action": "raise", "amount": amount}
            if "bet" in legal:
                return {"action": "bet", "amount": amount}
        if state["to_call"] > 0:
            odds = state["to_call"] / (state["pot"] + state["to_call"])
            return {"action": "call"} if eq >= odds else {"action": "fold"}
        if "bet" in legal and eq >= 1.8 / (1 + max(_live(state), 1)):
            return {"action": "bet", "amount": _sized(state, 0.6)}
        return {"action": "check"} if "check" in legal else {"action": "fold"}
    return bot


def _live(state) -> int:
    """Opponents still in the hand from this seat's point of view."""
    return sum(
        1 for p in state["players"]
        if not p["folded"] and not p["busted"] and p["name"] != "you"
    )


def house(rng) -> tuple[list, list[str]]:
    """Dana, Miles, Theo, Rhea and Bram — five archetypes that play very
    differently from one another, as the statement promises."""
    return (
        [bot_station, bot_rock, bot_sane, make_maniac(rng), make_gaston(rng)],
        ["Dana", "Miles", "Theo", "Rhea", "Bram"],
    )


# ────────────────────────────────── running ────────────────────────────────────


def play_leg(rule, codename, seed, leg_number, total_legs, hands, our_seat):
    TABLE["rule"], TABLE["codename"] = rule, codename
    rng = random.Random(seed)
    bots, names = house(rng)
    bots.insert(our_seat, decide)
    names.insert(our_seat, "you")
    table = Table(bots, names, hands, seed, leg_number, total_legs)
    return table.play(rng), our_seat


def attempt(rules, seed, hands=60):
    """Four legs back to back. Returns (our delta, best rival delta) per leg."""
    out = []
    for i, rule in enumerate(rules, start=1):
        # rotate our seat so a lucky seat cannot flatter the result
        deltas, seat = play_leg(rule, f"codename-{rule.name}", seed * 10 + i,
                                i, len(rules), hands, our_seat=(seed + i) % 6)
        ours = deltas[seat]
        rivals = max(d for s, d in enumerate(deltas) if s != seat)
        out.append((ours, rivals))
    return out


def score(legs) -> int:
    """"chip delta >= +10 and top the table -> 150 points" a leg."""
    return sum(150 for ours, rivals in legs if ours >= 10 and ours > rivals)


def report(attempts, rule_names, hands=60):
    rules = [BY_NAME.get(n) or next(r for r in EXOTIC if r.name == n) for n in rule_names]
    print(f"legs = {', '.join(rule_names)}   ({attempts} attempts x {hands} hands)\n")
    print(f"  {'':8} {'leg1':>7} {'leg2':>7} {'leg3':>7} {'leg4':>7} {'points':>8} {'bust':>6}")
    for label in ("cold", "warm"):
        topped = [0] * len(rules)
        points, deltas, busts = [], [], 0
        for a in range(attempts):
            forget_all()
            if label == "warm":
                attempt(rules, seed=9000 + a, hands=hands)
            legs = attempt(rules, seed=a, hands=hands)
            for i, (ours, rivals) in enumerate(legs):
                if ours >= 10 and ours > rivals:
                    topped[i] += 1
                deltas.append(ours)
                busts += ours <= -STARTING_STACK
            points.append(score(legs))
        rates = "".join(f"{c / attempts:>7.0%}" for c in topped)
        print(f"  {label:<8}{rates} {statistics.mean(points):>8.0f} "
              f"{busts / (attempts * len(rules)):>6.1%}")
    print(f"\n  mean chip delta {statistics.mean(deltas):+.1f}, "
          f"median {statistics.median(deltas):+.0f}")


def sweep(knob, values, attempts, rule_names, hands=60):
    rules = [BY_NAME.get(n) or next(r for r in EXOTIC if r.name == n) for n in rule_names]
    original = getattr(showdown, knob)
    print(f"{knob}  (current {original})")
    for value in values:
        setattr(showdown, knob, value)
        points, tops = [], 0
        for a in range(attempts):
            forget_all()
            legs = attempt(rules, seed=a, hands=hands)
            points.append(score(legs))
            tops += sum(1 for o, r in legs if o >= 10 and o > r)
        print(f"  {value:<8} points={statistics.mean(points):>6.0f}  "
              f"legs topped={tops / (attempts * len(rules)):>5.0%}")
    setattr(showdown, knob, original)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=60)
    parser.add_argument("--hands", type=int, default=60)
    parser.add_argument("--legs", default="standard,near,antipair_low,x_mod3")
    parser.add_argument("--sweep")
    parser.add_argument("--values", default="")
    args = parser.parse_args()
    names = args.legs.split(",")
    if args.sweep:
        vals = [float(v) for v in args.values.split(",")] if args.values else [0.0, 0.5, 1.0]
        sweep(args.sweep, vals, args.attempts, names, args.hands)
    else:
        report(args.attempts, names, args.hands)
