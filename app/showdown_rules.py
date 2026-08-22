"""SHOWDOWN phase 2 — working out which showdown rule a table is using.

Phase 2 hides the showdown behind an opaque `table_rule` codename ("we are not
telling you what the rules are, or how many there are") and changes it every leg.
Betting, blinds, position and sizing are identical under every rule — only who
wins at showdown moves — so everything here is about one question: given our
number and the community number, how likely are we to take the pot?

Three facts from the statement make that learnable:

* `recent_hands` is a labelled training set. Every completed hand that reached
  showdown carries both seats' `shown_numbers`, the `community_number` and the
  `winners` — one labelled comparison per showdown.
* "the same codename always means the same ruleset, in every match, every attempt,
  and every later phase", so what we learn is keyed off the codename and kept.
* "the leg order and each leg's rule are identical on every retry", so a later
  attempt starts already knowing tables an earlier one paid to discover.

A rule is represented as a strength function `key(n, c)` — higher wins, equal
keys split. That single shape covers every one-sentence showdown rule we could
think of, and it is what lets a hypothesis set be scored by plain Bayes.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, ClassVar

DECK = 13


# ────────────────────────────── the hypothesis set ──────────────────────────────


@dataclass(frozen=True)
class Rule:
    name: str
    description: str
    key: Callable[[int, int], tuple]


def _rules() -> tuple[Rule, ...]:
    # NB: "odd numbers beat even numbers, higher within each group" is deliberately
    # absent — the statement says that exact rule is not in play, so it gets no
    # prior mass. The mirrored version is kept: only the one rule was excluded.
    spec: list[tuple[str, str, Callable[[int, int], tuple]]] = [
        ("standard", "a pair beats any non-pair, then higher wins",
         lambda n, c: (n == c, n)),
        ("pair_low", "a pair beats any non-pair, then LOWER wins",
         lambda n, c: (n == c, -n)),
        ("antipair_high", "a pair LOSES to any non-pair, then higher wins",
         lambda n, c: (n != c, n)),
        ("antipair_low", "a pair LOSES to any non-pair, then lower wins",
         lambda n, c: (n != c, -n)),
        ("high", "highest number wins, the community number is irrelevant",
         lambda n, c: (n,)),
        ("low", "lowest number wins, the community number is irrelevant",
         lambda n, c: (-n,)),
        ("near", "closest to the community number wins",
         lambda n, c: (-abs(n - c),)),
        ("near_high", "closest to the community number wins, higher breaks ties",
         lambda n, c: (-abs(n - c), n)),
        ("far", "furthest from the community number wins",
         lambda n, c: (abs(n - c),)),
        ("far_high", "furthest from the community number wins, higher breaks ties",
         lambda n, c: (abs(n - c), n)),
        ("wrap_up", "counting up from the community number, last one wins",
         lambda n, c: ((n - c) % DECK,)),
        ("wrap_down", "counting down from the community number, last one wins",
         lambda n, c: ((c - n) % DECK,)),
        ("sum_mod", "number plus community, modulo 13, highest wins",
         lambda n, c: ((n + c) % DECK,)),
        ("above_high", "beating the community number matters, then higher wins",
         lambda n, c: (n > c, n)),
        ("below_low", "coming under the community number matters, then lower wins",
         lambda n, c: (n < c, -n)),
        ("even_high", "even numbers beat odd, then higher wins",
         lambda n, c: (n % 2 == 0, n)),
        ("pair_near", "a pair beats any non-pair, then closest to the community",
         lambda n, c: (n == c, -abs(n - c))),
    ]
    # NB: a "banded deck" family used to live here, added because three tables
    # appeared to split a pot between two different numbers. Those splits turned
    # out to be all-in refunds (see `observe`), and with them discarded every
    # table is explained exactly by an unbanded rule. Removed rather than left
    # to dilute the posterior. If a genuinely banded table ever turns up it will
    # show different-number splits in SMALL pots, which is real evidence.
    # "One number beats everything." Amaranth showed a 7 beating an 8 twice, at two
    # different community numbers, and a 7 never lost — which no ordering by size
    # explains. Paired with banding (that table also split a 13 against a 12) it
    # accounts for all 27 of its showdowns. Every number gets a candidate so the
    # evidence picks the lucky one rather than us naming it.
    for lucky in range(1, DECK + 1):
        spec.append((
            f"lucky{lucky}",
            f"a {lucky} beats everything, then a pair, then higher wins",
            (lambda k: lambda n, c: (n == k, n == c, n))(lucky),
        ))
    return tuple(Rule(name, desc, key) for name, desc, key in spec)


def _signature(rule: Rule) -> tuple:
    """Who beats whom, over every (n, m, c). Two rules with the same signature
    are the same rule however differently they are written."""
    return tuple(
        (rule.key(n, c) > rule.key(m, c)) - (rule.key(n, c) < rule.key(m, c))
        for c in range(1, DECK + 1)
        for n in range(1, DECK + 1)
        for m in range(1, DECK + 1)
    )


def _distinct(rules: tuple[Rule, ...]) -> tuple[Rule, ...]:
    """Drop rules that are indistinguishable from one already in the set.

    Several natural phrasings collapse: "lowest wins" and "coming under the
    community matters, then lower" are the same rule, because if b < a < c then
    b is under the community too. Keeping both would split the posterior between
    identical hypotheses and halve our stated confidence for no reason.
    """
    seen: dict[tuple, str] = {}
    kept = []
    for rule in rules:
        sig = _signature(rule)
        if sig in seen:
            continue
        seen[sig] = rule.name
        kept.append(rule)
    return tuple(kept)


# The excluded example, kept only so we can prove it is not in the set.
EXCLUDED = Rule(
    "odd_high", "odd numbers beat even, then higher wins", lambda n, c: (n % 2 == 1, n)
)

RULES = tuple(r for r in _distinct(_rules()) if _signature(r) != _signature(EXCLUDED))
BY_NAME = {rule.name: rule for rule in RULES}

# Codenames we do not have to learn. Phase 1 announces `standard` and the guide
# spells that showdown out in full, so pinning it keeps phase 1 — still worth 300
# points — bit-for-bit unchanged instead of re-deriving it from scratch.
# Anything we become confident about in play should be added here and committed:
# GET /debug/showdown-rules dumps what has been learned so far.
KNOWN_RULES: dict[str, str] = {"standard": "standard"}

# The prior is NOT uniform. Of the four phase-2 tables we have played, three were
# best explained by the phase-1 rule (verdigris 100%, amaranth 92%, cinnabar 80%)
# and only obsidian clearly was not. A flat prior over thirty hypotheses throws
# that away and leaves us near a coin flip for the first dozen hands of every
# leg — which, over 40 hands, is most of it. So phase 2 starts from phase 1's
# answer and lets evidence move it, rather than starting from nothing.
PRIOR_STANDARD = 0.40


def showdown_winners(rule: Rule, numbers: dict[int, int], community: int) -> list[int]:
    """The seats that win this showdown under `rule`. Ties split."""
    keyed = {seat: rule.key(n, community) for seat, n in numbers.items()}
    best = max(keyed.values())
    return sorted(seat for seat, k in keyed.items() if k == best)


# ─────────────────────────────── learning from play ─────────────────────────────

# A single anomaly (an odd chip, a rule we have mis-modelled at the edges) should
# cost a hypothesis a lot of weight but never all of it.
CONSISTENT = 0.97
INCONSISTENT = 0.03


@dataclass
class Observation:
    numbers: dict[int, int]
    community: int
    winners: tuple[int, ...]


@dataclass
class RuleBelief:
    """Everything one codename has taught us, and the posterior it implies."""

    codename: str
    seen: dict[tuple, Observation] = field(default_factory=dict)
    _posterior: dict[str, float] | None = None

    _store: ClassVar["dict[str, RuleBelief]"] = {}
    _lock: ClassVar[threading.RLock] = threading.RLock()

    @property
    def count(self) -> int:
        return len(self.seen)

    @classmethod
    def for_codename(cls, codename: str) -> "RuleBelief":
        with cls._lock:
            belief = cls._store.get(codename)
            if belief is None:
                belief = cls(codename=codename)
                cls._store[codename] = belief
            return belief

    @classmethod
    def all(cls) -> "dict[str, RuleBelief]":
        return dict(cls._store)

    @classmethod
    def forget_all(cls) -> None:
        with cls._lock:
            cls._store.clear()

    def add(self, key: tuple, observation: Observation) -> bool:
        """Record one showdown. Returns True if it was new."""
        with self._lock:
            if key in self.seen:
                return False
            self.seen[key] = observation
            self._posterior = None  # recompute lazily
            return True

    def posterior(self) -> dict[str, float]:
        pinned = KNOWN_RULES.get(self.codename)
        if pinned in BY_NAME:
            return {name: (1.0 if name == pinned else 0.0) for name in BY_NAME}
        if self._posterior is None:
            self._posterior = self._compute()
        return self._posterior

    @staticmethod
    def _log_prior() -> dict[str, float]:
        import math

        names = [r.name for r in RULES] + [LEARNED]
        rest = (1.0 - PRIOR_STANDARD) / (len(names) - 1)
        return {
            name: math.log(PRIOR_STANDARD if name == "standard" else rest) for name in names
        }

    def _compute(self) -> dict[str, float]:
        """Two-fold cross-validated log-likelihood, in log space.

        Every hypothesis is scored on data it was not fitted on. For the fixed
        rules that changes nothing — they have no parameters — so this is a fair
        comparison that stops the fitted `learned_order` from winning simply by
        being flexible enough to memorise the observations.
        """
        import math

        keys = sorted(self.seen, key=repr)
        folds = ([], [])
        for i, key in enumerate(keys):
            folds[i % 2].append(self.seen[key])
        scores = dict(self._log_prior())
        if not keys:
            import math

            top = max(scores.values())
            w = {n: math.exp(v - top) for n, v in scores.items()}
            total = sum(w.values())
            return {n: x / total for n, x in w.items()}
        for f, held_out in enumerate(folds):
            trained_on = folds[1 - f]
            order = _fit_order(trained_on) if trained_on else None
            for obs in held_out:
                for rule in RULES:
                    agrees = tuple(showdown_winners(rule, obs.numbers, obs.community)) == obs.winners
                    scores[rule.name] += math.log(CONSISTENT if agrees else INCONSISTENT)
                if order is None:
                    scores[LEARNED] += math.log(0.5)  # nothing to fit on yet
                else:
                    agrees = _order_predicts(order, obs)
                    scores[LEARNED] += math.log(CONSISTENT if agrees else INCONSISTENT)

        top = max(scores.values())
        weights = {name: math.exp(score - top) for name, score in scores.items()}
        total = sum(weights.values())
        return {name: w / total for name, w in weights.items()}

    def order(self) -> dict[int, float]:
        """The fitted strength order, using every observation."""
        return _fit_order(list(self.seen.values()))


LEARNED = "learned_order"
LEARNED_DESC = "a strength order over the numbers, fitted from play (no community effect)"


def _fit_order(observations) -> dict[int, float]:
    """Laplace-smoothed win rate per number, ignoring the community number.

    A safety net for tables whose rule is not in the hypothesis set at all. It
    can only represent rules where a number's strength does not depend on the
    community number — but that covers a large family ("primes beat composites",
    "n mod 3", any fixed reordering of the deck) that no amount of hand-written
    hypotheses would reliably anticipate.
    """
    wins: dict[int, float] = {}
    games: dict[int, float] = {}
    for obs in observations:
        seats = sorted(obs.numbers)
        if len(seats) != 2:
            continue
        a, b = obs.numbers[seats[0]], obs.numbers[seats[1]]
        if a == b:
            continue
        if len(obs.winners) == 2:
            sa = sb = 0.5
        else:
            sa = 1.0 if obs.winners[0] == seats[0] else 0.0
            sb = 1.0 - sa
        wins[a] = wins.get(a, 0.0) + sa
        wins[b] = wins.get(b, 0.0) + sb
        games[a] = games.get(a, 0.0) + 1
        games[b] = games.get(b, 0.0) + 1
    return {
        n: (wins.get(n, 0.0) + 1.0) / (games.get(n, 0.0) + 2.0) for n in range(1, DECK + 1)
    }


def _order_predicts(scores: dict[int, float], obs: "Observation") -> bool:
    seats = sorted(obs.numbers)
    ka, kb = scores[obs.numbers[seats[0]]], scores[obs.numbers[seats[1]]]
    if abs(ka - kb) < 1e-9:
        predicted = (seats[0], seats[1])
    else:
        predicted = (seats[0],) if ka > kb else (seats[1],)
    return tuple(predicted) == obs.winners


SEED_PATH = Path(__file__).resolve().parent / "data" / "showdown_seed.json"


def load_seed(path=None) -> int:
    """Replay showdowns harvested from earlier attempts.

    A codename means the same ruleset in every match, attempt and later phase,
    so a showdown seen in any earlier attempt is still evidence about the same
    table. In-process memory does not survive a Render restart — and every
    deploy is a restart — so this file is the half of the memory that lasts.
    """
    path = Path(path) if path else SEED_PATH
    try:
        blob = json.loads(path.read_text())
    except (OSError, ValueError):
        return 0
    tables = blob.get("tables") if isinstance(blob, dict) else None
    if not isinstance(tables, dict):
        return 0
    added = 0
    for codename, rows in tables.items():
        if not isinstance(rows, list):
            continue
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            numbers = row.get("numbers")
            if not isinstance(numbers, dict):
                continue
            try:
                numbers = {int(k): int(v) for k, v in numbers.items()}
            except (TypeError, ValueError):
                continue
            added += observe(codename, match_id="seed", leg=None, hand_number=f"seed-{i}",
                             numbers=numbers, community=row.get("community"),
                             winners=row.get("winners"))
    return added


def observations_dump() -> dict:
    """Every showdown we hold, shaped like the seed file so an attempt's
    learning can be harvested and committed."""
    tables = {}
    for codename, belief in RuleBelief.all().items():
        rows = [{"numbers": {str(k): v for k, v in o.numbers.items()},
                 "community": o.community, "winners": list(o.winners)}
                for o in belief.seen.values()]
        if rows:
            tables[codename] = rows
    return {"tables": tables}


def forget_all() -> None:
    RuleBelief.forget_all()


# A pot at least this share of a starting stack means somebody was all in.
# Ordinary pots are single digits; the refunds we have seen were 127 to 405.
ALL_IN_POT_SHARE = 0.5


def _is_all_in_refund(seats, numbers, pot, starting_stack) -> bool:
    """Two winners holding DIFFERENT numbers, in a pot only an all-in explains.

    Plenty of rules tie two different numbers honestly — under "closest to the
    community" a 3 and a 7 both sit two away from a 5 — so the numbers alone
    prove nothing. What gives it away is the pot. When both players are all in,
    chips nobody could cover go back and the hand log lists both seats as
    winners; every one of these we have seen came from a pot of 127 to 405
    against a median of 8 for decided hands and 24 for genuine ties.

    Believing them cost us three tables: it is the only reason the deck ever
    looked like it was grouped into bands, and dropping them leaves every table
    explained exactly by an unbanded rule.
    """
    if len(seats) < 2 or len({numbers[s] for s in seats}) < 2:
        return False
    if pot is None or starting_stack is None:
        return False  # no pot to judge by (synthetic data) — take it at face value
    return pot >= ALL_IN_POT_SHARE * starting_stack


def observe(
    codename: str,
    match_id,
    leg,
    hand_number,
    numbers: dict[int, int],
    community: int,
    winners,
    pot=None,
    starting_stack=None,
) -> bool:
    """Record one completed showdown against a codename. Idempotent per hand."""
    if not isinstance(codename, str) or not codename:
        return False
    if not isinstance(numbers, dict) or len(numbers) < 2 or community is None:
        return False
    if not all(isinstance(n, int) and 1 <= n <= DECK for n in numbers.values()):
        return False
    if not isinstance(community, int) or not 1 <= community <= DECK:
        return False
    try:
        seats = tuple(sorted(int(s) for s in winners))
    except (TypeError, ValueError):
        return False
    if not seats or any(s not in numbers for s in seats):
        return False
    if _is_all_in_refund(seats, numbers, pot, starting_stack):
        return False
    belief = RuleBelief.for_codename(codename)
    key = (str(match_id), leg, hand_number, tuple(sorted(numbers.items())), community)
    return belief.add(key, Observation(dict(numbers), community, seats))


def posterior_for(codename: str) -> dict[str, float]:
    """Posterior over rules, and the fitted order this codename implies.

    ORDERS["current"] is set as a side effect so the `learned_order` hypothesis
    can be evaluated by the equity helpers below without threading the fit
    through every call site.
    """
    belief = RuleBelief.for_codename(codename)
    ORDERS["current"] = belief.order()
    return belief.posterior()


def learned_summary() -> dict:
    """What every codename we have met currently looks like. For /debug."""
    out = {}
    for codename, belief in RuleBelief.all().items():
        post = belief.posterior()
        best = max(post, key=post.get)
        out[codename] = {
            "showdowns_seen": belief.count,
            "best_guess": best,
            "confidence": round(post[best], 4),
            "means": LEARNED_DESC if best == LEARNED else BY_NAME[best].description,
            "pinned": codename in KNOWN_RULES,
            "runners_up": {
                name: round(p, 4)
                for name, p in sorted(post.items(), key=lambda kv: -kv[1])[1:4]
                if p > 0.01
            },
        }
    return out


# ─────────────────────────── equity under a belief ──────────────────────────────


ORDERS: dict[str, dict[int, float]] = {}


def _key_for(name: str, n: int, c: int):
    if name == LEARNED:
        return (round(ORDERS.get("current", {}).get(n, 0.5), 9),)
    return BY_NAME[name].key(n, c)


def _value(rule: Rule, n: int, m: int, c: int) -> float:
    """Our share of the pot holding `n` against `m`, community `c`."""
    ours, theirs = rule.key(n, c), rule.key(m, c)
    if ours > theirs:
        return 1.0
    if ours < theirs:
        return 0.0
    return 0.5


def rule_equity(
    belief: dict[str, float],
    n: int,
    c: int | None,
    weights: dict[int, float] | None = None,
) -> float:
    """Posterior-averaged chance of taking the pot.

    `weights` is the opponent's range over 1..13; None means uniform. With the
    belief spread across rules that disagree, this collapses toward a coin flip
    on its own — which is the right amount of caution while the table is unknown.
    """
    communities = range(1, DECK + 1) if c is None else (c,)
    total = 0.0
    for name, p in belief.items():
        if p <= 0.0 or (name != LEARNED and name not in BY_NAME):
            continue
        acc = 0.0
        for cc in communities:
            ours = _key_for(name, n, cc)
            for m in range(1, DECK + 1):
                w = 1.0 if weights is None else weights.get(m, 0.0)
                if w:
                    theirs = _key_for(name, m, cc)
                    acc += w * (1.0 if ours > theirs else (0.5 if ours == theirs else 0.0))
        total += p * acc / len(communities)
    if weights is not None:
        scale = sum(weights.values())
        return total / scale if scale else 0.5
    return total / DECK


def range_weights(belief: dict[str, float], c: int | None, sharpness: float) -> dict[int, float]:
    """The opponent's range, as strength rank under the rules we believe in.

    Betting says "my number is strong"; what *strong* means is whatever the table
    rule says. Ranking by `key` instead of by face value is what makes this
    transfer to a rule we have never seen — and under the standard rule it
    reproduces phase 1's "a big shove is usually the pair" without the idea of a
    pair appearing anywhere.
    """
    import math

    if sharpness <= 0:
        return {m: 1.0 / DECK for m in range(1, DECK + 1)}
    communities = range(1, DECK + 1) if c is None else (c,)
    weights = {m: 0.0 for m in range(1, DECK + 1)}
    for name, p in belief.items():
        if p <= 0.0 or (name != LEARNED and name not in BY_NAME):
            continue
        for cc in communities:
            order = sorted(range(1, DECK + 1), key=lambda m, nm=name, c2=cc: _key_for(nm, m, c2))
            for rank, m in enumerate(order):  # 0 = weakest
                weights[m] += p * math.exp(sharpness * rank / (DECK - 1))
    total = sum(weights.values())
    if total <= 0:
        return {m: 1.0 / DECK for m in range(1, DECK + 1)}
    return {m: w / total for m, w in weights.items()}


def unbeatable(belief: dict[str, float], n: int, c: int | None, floor: float = 0.995) -> bool:
    """True when, under everything we believe, no number beats ours.

    The generalisation of phase 1's "a pair cannot lose": worth knowing because a
    hand with no downside should ignore every stack-risk guard we own.
    """
    if c is None:
        return False
    weight = 0.0
    for name, p in belief.items():
        if p <= 0.0 or (name != LEARNED and name not in BY_NAME):
            continue
        ours = _key_for(name, n, c)
        if all(_key_for(name, m, c) <= ours for m in range(1, DECK + 1)):
            weight += p
    return weight >= floor


_SEEDED = load_seed()
