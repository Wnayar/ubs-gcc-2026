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
    # Banded rules: the deck grouped into equal-strength bands, higher band wins.
    # Not speculation — cinnabar split a pot between a 12 and a 13, and no
    # ordering by face value can tie two different numbers, so at least one real
    # table groups the deck. The specific banding is left to the evidence.
    for width in (2, 3, 4):
        for offset in (0, 1):
            spec.append((
                f"band{width}_{offset}",
                f"numbers grouped into bands of {width}, higher band wins, same band splits",
                (lambda w, o: lambda n, c: ((n + o) // w,))(width, offset),
            ))
            spec.append((
                f"pair_band{width}_{offset}",
                f"a pair beats any non-pair, then bands of {width}, same band splits",
                (lambda w, o: lambda n, c: (n == c, (n + o) // w))(width, offset),
            ))
            spec.append((
                f"band{width}_{offset}_low",
                f"numbers grouped into bands of {width}, LOWER band wins",
                (lambda w, o: lambda n, c: (-((n + o) // w),))(width, offset),
            ))
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
        spec.append((
            f"lucky{lucky}_band2",
            f"a {lucky} beats everything, then a pair, then bands of two",
            (lambda k: lambda n, c: (n == k, n == c, n // 2))(lucky),
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


def agrees_with(rule: Rule, observation: "Observation") -> bool:
    """Is this rule consistent with how that showdown actually paid out?

    Two players: the predicted winners must be exactly the reported winners.
    That is phase 2's test, and it stays untouched — every one of the seeded
    observations is two-player, and phase 2 learned the hard way what happens
    when this is loosened (a filter on odd two-winner hands removed exactly the
    evidence that discriminated between rules, and the false confidence that
    produced cost a leg).

    Phase 3 seats six. Once three or more players reach a showdown, two winners
    with *different* numbers is ordinary rather than odd: with all-ins there are
    side pots, and the seat that takes one need not have the best number at the
    table. What holds under every rule is that the best key wins the MAIN pot,
    because everybody contests it. So the predicted winners must appear among
    the reported ones — extra names are explained by side pots, while a
    predicted winner who did not win at all is still a real contradiction.
    """
    predicted = showdown_winners(rule, observation.numbers, observation.community)
    if len(observation.numbers) <= 2:
        return tuple(predicted) == observation.winners
    return set(predicted) <= set(observation.winners)


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
                    agrees = agrees_with(rule, obs)
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
        if len(seats) == 2:
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
            continue
        if len(seats) < 2:
            continue
        # A crowded showdown is a whole round-robin: every winner beat every
        # seat that did not win. Side-pot winners make that slightly generous —
        # one of them only beat the seats in their own pot — which is another
        # reason this stays the low-weight fallback rather than the main model.
        winners = set(obs.winners)
        losers = [s for s in seats if s not in winners]
        for w in winners:
            for loser in losers:
                a, b = obs.numbers[w], obs.numbers[loser]
                if a == b:
                    continue
                wins[a] = wins.get(a, 0.0) + 1.0
                games[a] = games.get(a, 0.0) + 1
                games[b] = games.get(b, 0.0) + 1
    return {
        n: (wins.get(n, 0.0) + 1.0) / (games.get(n, 0.0) + 2.0) for n in range(1, DECK + 1)
    }


def _order_predicts(scores: dict[int, float], obs: "Observation") -> bool:
    seats = sorted(obs.numbers)
    keyed = {seat: scores[obs.numbers[seat]] for seat in seats}
    best = max(keyed.values())
    predicted = tuple(seat for seat in seats if abs(keyed[seat] - best) < 1e-9)
    if len(seats) <= 2:
        return predicted == obs.winners
    return set(predicted) <= set(obs.winners)  # side pots, as in agrees_with


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


def observe(
    codename: str,
    match_id,
    leg,
    hand_number,
    numbers: dict[int, int],
    community: int,
    winners,
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


_KEY_VECTORS: dict[tuple[str, int], tuple] = {}


def _key_vector(name: str, c: int) -> tuple:
    """Every number's key under one rule at one community number, 1..13.

    Phase 3 asks for this hundreds of times per decision — 58 hypotheses by 13
    possible community numbers by five opponents — and the keys of a fixed rule
    never change, so they are worth computing once. `learned_order` is refitted
    as evidence arrives and is deliberately not cached.
    """
    if name == LEARNED:
        order = ORDERS.get("current", {})
        return tuple((round(order.get(n, 0.5), 9),) for n in range(1, DECK + 1))
    vector = _KEY_VECTORS.get((name, c))
    if vector is None:
        key = BY_NAME[name].key
        vector = tuple(key(n, c) for n in range(1, DECK + 1))
        _KEY_VECTORS[(name, c)] = vector
    return vector


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


# Hypotheses this far out of the running cannot move a decision, and skipping
# them is what keeps a six-way pre-reveal call inside the time budget.
NEGLIGIBLE = 1e-4


def rule_equity_multiway(
    belief: dict[str, float],
    n: int,
    c: int | None,
    ranges: "list[dict[int, float] | None]",
) -> float:
    """Posterior-averaged share of the pot against several opponents at once.

    Phase 3 seats six: "a bet now has to get through everyone still in the hand,
    not just one player", so our number has to beat *all* of them. One entry in
    `ranges` per live opponent, each a distribution over 1..13 (None for the
    whole deck) — they are kept separate because a seat that has raised twice
    and a seat that has just called are not the same threat, and averaging them
    away is most of the read.

    Opponents draw independently, so for one rule and one community number the
    exact answer is a small dynamic program. Walking the opponents while
    tracking P(nobody has beaten us yet, `j` of them tied) gives

        share = sum_j P(j) / (1 + j)

    which prices a three-way tie at a third of the pot rather than at nothing —
    it matters here because several candidate rules (`near`, the banded ones)
    tie numbers far more often than the standard rule does.
    """
    k = len(ranges)
    if k == 0:
        return 1.0  # everyone folded; the pot is already ours
    communities = range(1, DECK + 1) if c is None else (c,)
    total = 0.0
    mass = 0.0
    for name, p in belief.items():
        if p <= NEGLIGIBLE or (name != LEARNED and name not in BY_NAME):
            continue
        mass += p
        acc = 0.0
        for cc in communities:
            keys = _key_vector(name, cc)
            ours = keys[n - 1]
            distribution = [1.0] + [0.0] * k
            for weights in ranges:
                below = tied = 0.0
                if weights is None:
                    for key in keys:
                        if key < ours:
                            below += 1.0
                        elif key == ours:
                            tied += 1.0
                    below /= DECK
                    tied /= DECK
                else:
                    scale = 0.0
                    for m, key in enumerate(keys, start=1):
                        w = weights.get(m, 0.0)
                        if not w:
                            continue
                        scale += w
                        if key < ours:
                            below += w
                        elif key == ours:
                            tied += w
                    if scale > 0:
                        below /= scale
                        tied /= scale
                    else:  # an empty range says nothing; fall back on the deck
                        below = sum(1 for key in keys if key < ours) / DECK
                        tied = sum(1 for key in keys if key == ours) / DECK
                nxt = [0.0] * (k + 1)
                for j in range(k):
                    weight = distribution[j]
                    if weight:
                        nxt[j] += weight * below
                        nxt[j + 1] += weight * tied
                distribution = nxt
            acc += sum(w / (1 + j) for j, w in enumerate(distribution) if w)
        total += p * acc / len(communities)
    if mass <= 0:
        return 1.0 / (k + 1)  # believing nothing, expect a fair share
    return total / mass


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


def contradicted_as_unbeatable(codename: str, n: int, community: int) -> bool:
    """Have we actually SEEN this number fail to win a showdown outright?

    `unbeatable` waives every stack-risk guard we own, so it must not rest on a
    rule the evidence already argues with. Amaranth cost us a leg exactly this
    way: two hands said a 7 beat an 8, "a 7 beats everything" reached ~100% of
    the posterior between two near-identical variants, and the bot shoved its
    whole 211-chip stack — into a hand the log then reported as NOT an outright
    win for the 7. One direct counter-example outranks any amount of posterior.
    """
    for obs in RuleBelief.for_codename(codename).seen.values():
        if obs.community != community:
            continue  # a number's strength depends on the community number
        holders = [s for s, v in obs.numbers.items() if v == n]
        if not holders:
            continue
        if len({v for v in obs.numbers.values()}) == 1:
            continue  # everyone holds n; tying with a copy of yourself proves nothing
        if set(obs.winners) != set(holders):
            return True
    return False


def unbeatable(
    belief: dict[str, float],
    n: int,
    c: int | None,
    floor: float = 0.995,
    codename: str | None = None,
) -> bool:
    """True when, under everything we believe, no number beats ours.

    The generalisation of phase 1's "a pair cannot lose": worth knowing because a
    hand with no downside should ignore every stack-risk guard we own.
    """
    if c is None:
        return False
    if codename is not None and contradicted_as_unbeatable(codename, n, c):
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
