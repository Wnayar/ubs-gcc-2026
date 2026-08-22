# SHOWDOWN — Phase 3: A Crowded Table

- **PDFs:** `statement.pdf` in this folder; shared rules in `../guide.pdf`; phase 2's
  table rules and legs in `../phase-2/notes.md` — **both still in force.** The phase 3
  page says so explicitly: "The full game rules and protocol are on the SHOWDOWN guide;
  the phase 2 guide covers table rules and legs. This page covers what phase 3 adds:
  six-seat tables and multiway play."
- **Endpoints required:** `POST /move` — the same endpoint for the third time, no new route
- **Submitted to controller:** no
- **Score:** —

## What phase 3 adds

Two things, on top of the guide *and* all of phase 2. Table rules, codenames, legs and
the leg-order-is-fixed guarantee are unchanged.

### 1. More than one opponent

> A bet now has to get through everyone still in the hand, not just one player. The same
> number is worth less than it is one-on-one: the more players still live, the likelier
> one of them holds something.
>
> Folded players stay in `players` with `folded: true` — the list is the table's seating,
> not the list of live opponents. Filter on `folded` / `busted` yourself.
>
> Busting also changes. Hit 0 chips and you're out for the rest of that match — no cards,
> no forced bets, no button — while the others play on. The match only ends early if just
> one player still has chips.

### 2. Position at a six-seat table

> Nothing about position changes, there are just more seats. The button still decides who
> pays which forced bet and who acts when, and still moves one seat along every hand —
> now skipping anyone who has busted.

The statement's table, verbatim:

```
                 seat 0   seat 1   seat 2   seat 3   seat 4   seat 5
                 [BUTTON]

 forced bet         –        1        2        –        –        –

 acts pre_reveal    4th      5th      6th      1st      2nd      3rd
                                      (last)   (first)

 acts post_reveal   6th      1st      2nd      3rd      4th      5th
                    (last)   (first)
```

> - **Forced bets** start just past the button: seat 1 pays 1, seat 2 pays 2. The button
>   pays nothing, which is why it's the cheapest seat.
> - **Before the reveal**, the order opens just past the seat that paid 2, so that seat
>   acts **last**.
> - **After the reveal**, the order opens just past the button, so the button acts **last**
>   — with the most information.
>
> As heads-up, the order is **not** the same in both betting rounds. Over six hands you
> hold every seat's position once, so nobody gets a permanently good or bad seat.

Note this is *not* the heads-up rule generalised. Heads-up the **button pays 1 and acts
first pre-reveal**; six-handed the **button pays nothing** and acts 4th. Both are the
same sentence — "forced bets start just past the button" — which at two seats wraps
round onto the button itself.

## Scoring

> Four legs again, **60 hands** each, one table rule per leg. Each leg seats **six
> players**: you plus **Dana**, **Miles**, **Theo**, **Rhea** and **Bram**.
>
> It's the same five every leg, and they play very differently from one another. Their
> names are fixed and tell you nothing.
>
> Table rules still apply, announced under the same codenames as phase 2. The mapping has
> not changed, and every opponent here plays the rule correctly.
>
> Clearing is stricter: being up isn't enough. You must finish the leg with **strictly
> highest chip delta at the table** — beating four of the five is worth nothing.
>
> **Per leg:** chip delta ≥ **+10** *and* top the table → **150 points**. Accumulating
> again; all four not required. Four legs is the full **600**, the biggest single block
> of points in the challenge.

## Glossary additions

| Term | Meaning |
|---|---|
| Multiway | A hand with three or more players still in it. Your number needs to beat all of them, not one. |
| Top the table | Finish a leg with a strictly higher chip delta than every other seat. Ties don't count. |

## The shape of the problem

Phase 2 was an inference problem. Phase 3 is two separate problems bolted onto it, and
neither is about the rule.

**a) The equity model was heads-up and is now simply wrong.** Every number in
`app/showdown.py` prices "how often do I beat *one* random number". Six-handed you must
beat five, and the statement leads with exactly this: "the same number is worth less than
it is one-on-one". Holding a 10 against a community 5 is a 65% favourite one-on-one and a
**9%** shot five-handed — below the 1/6 fair share. A bot that keeps the old model
value-bets hands that are losers to the field.

**b) The objective changed from a number to a race.** "+25 or bust" was absolute: the
opponent's stack was irrelevant except as a source of chips. "Top the table" is
*relative* — second place scores zero, so being +40 while Theo is +90 is worth exactly as
much as being −200. Chip delta ≥ +10 is the easy half; topping five opponents is the
binding constraint, and since chip deltas sum to zero across the table, an average
finish is a losing one.

The two interact: (a) says play tighter multiway, (b) says a safe second place is
worthless. The resolution we shipped is that (a) governs *how we price a hand* and (b)
governs *the endgame only* — see below.

## How the bot handles it

### Multiway equity (`app/showdown_rules.py`)

`rule_equity` grew an `opponents` argument. Against `k` live opponents, for each rule in
the posterior and each possible community number we compute `L` (chance one opponent's
number is beaten by ours) and `E` (chance it ties ours), then take our share of the pot as

```
Π over opponents of (L + E·x)   →   share = Σ_j coef_j / (j + 1)
```

`coef_j` being the chance exactly `j` opponents tie us and the rest lose, so we take
`1/(j+1)` of the pot. It is exact rather than a `L**k` approximation, it handles
opponents with *different* ranges (the seat that raised is not the seat that limped),
and at `k = 1` it collapses to `L + E/2` — the phase 1/2 formula, unchanged.

### The field-share scale (`app/showdown.py`)

Every threshold in the file — `VALUE_BET_EQ = 0.68`, `RAISE_EQ = 0.72`, `CALL_MARGIN`,
`CALL_RISK` — was calibrated one-on-one, where 0.5 is an average hand. Six-handed an
average number is worth 1/6 of the pot, so feeding raw multiway equity into a 0.68
threshold would mean never betting again.

One factor fixes both halves consistently:

```
SHARE = 2 / (live_opponents + 1)      # 1.0 heads-up, 1/3 six-handed
strength = min(1.0, equity / SHARE)   # equity on the heads-up axis: 0.5 is average
```

- **Bets and raises** are judged on `strength`, so "twice fair share" reads the same at
  every table size.
- **Calls** are judged on our real share of the pot against real pot odds — already the
  correct multiway comparison — with the *cushion* on top (`CALL_MARGIN`, `CALL_RISK`,
  tilt) multiplied by `SHARE ** FIELD_MARGIN`.

That second point is not cosmetic, and it is the one place where phase 3 collides with a
phase 2 decision. Live results pushed `CALL_RISK` to **0.55** and `RAISE_RISK` to 0.40 —
correct heads-up, where equity runs 0 to 1 and 0.5 is average. Six-handed an average
number is worth 0.167, and a full-stack call would then demand `pot odds + 0.55` of an
equity that tops out near 0.7. That does not merely play tight, it folds essentially
everything, and a bot that never contests a pot cannot top a table. `FIELD_MARGIN`
scales the cushion with the axis it was measured on. Every setting is the identity at
one opponent, so **phases 1 and 2 cannot be affected whatever we choose** — this is
purely a question about multiway play.

Swept over the seeded legs (30 attempts each, `tools/simulate3.py`):

| `FIELD_MARGIN` | points | bust | legs topped |
|---|---|---|---|
| 0.0 — full heads-up cushion | 230 | 5.0% | 23% 27% 60% 43% |
| 0.5 | 280 | 7.5% | 33% 40% 67% 47% |
| **1.0 — scales with the axis (shipped)** | **330** | 8.3% | 47% 53% 67% 53% |
| 1.5 | 355 | 9.2% | 53% 63% 63% 57% |
| 2.0 | 340 | 13.3% | 50% 63% 63% 50% |

Not compressing costs a hundred points. The bot at 0.0 has the lowest bust rate on the
board and that is exactly the problem — it folds its way to a safe, scoreless second
place, which under "beating four of the five is worth nothing" is the same as busting.

**1.5 measured best and was not taken.** 1.0 is the value the argument produces — the
cushion keeps its size *relative to a fair share* — and 1.0, 1.5 and 2.0 sit on a
plateau (330 / 355 / 340) whose ordering is inside the noise of 30 attempts against
opponents we invented. Phase 2 already has a scar from shipping a hand-tuned staking
rule that looked right; picking 1.5 here would be the same mistake at the same odds.

`strength` is likewise the identity at `k = 1`, which is what keeps phases 1 and 2 bit-for-bit
unchanged. **Everything phase 3 adds switches itself off when two players are live** —
including inside a phase 3 leg, once four opponents have busted, which is exactly the
right behaviour rather than a compatibility hack. `tests/data/phase2_decisions.json`
holds 400 two-seat spots recorded from the phase 2 engine (135 folds, 95 checks, 94
calls, 44 bets, 32 raises, exact amounts) and the suite replays every one of them.

### Reading the table (`app/showdown.py`)

- `_live_opponents` filters `players` on `folded` / `busted` as the statement instructs,
  and never counts us.
- The opponent's range is no longer applied to everyone. Seats that **bet or raised this
  round** get the sharpened, rule-relative range from phase 2; seats that are merely
  still in get the uniform one. Five limpers are not five raisers.
- **Bluffing is scaled down by `0.5 ** (live - 1)`** — a bluff has to get through every
  live opponent, so its success chance falls off geometrically. Six-handed our 10% bluff
  rate becomes 0.6%.

### Multiway showdowns teach more, not less (`app/showdown_rules.py`)

A six-way showdown shows up to six numbers against one community number. `observe` and
`showdown_winners` already handled N seats; the non-parametric `learned_order` fallback
did not — it skipped anything that was not exactly two-handed. It now takes every
(winner, loser) pair out of a multiway showdown, and scores co-winners as a tie with each
other. Losers are *not* compared against each other, because the showdown tells us
nothing about their relative order — only that the winner beat them all.

This is a real gain: a phase 2 leg of 40 heads-up hands yielded 7–16 labelled
comparisons, and a phase 3 leg of 60 six-handed hands yields several times that from the
same fraction of hands reaching showdown. The tables are the same tables — the codename
mapping "has not changed" — so phase 3 evidence sharpens the phase 2 seed and vice versa.

### The race (`app/showdown.py`)

`_objective` decides what we are playing for:

| table | target | must top? |
|---|---|---|
| 3+ seats (phase 3) | +10 | **yes** |
| 2 seats, `leg_number` set (phase 2) | +25 | no |
| 2 seats, no legs (phase 1) | +10 | no |

It keys off **seated** players (`len(players)`, busted included), not live ones, so
busting the table down to two does not switch us back to phase 2's objective mid-leg.

The endgame tilt then compares our chip delta against the **best other seat's**, not just
against the target. Inside the last 12 hands: protect a lead that is already clear, and
chase whenever we are not strictly ahead — because at that point a safe second place
scores the same zero as busting.

## Simulation results (`tools/simulate3.py`)

`tools/simulate.py` is heads-up to its bones, so phase 3 gets its own N-seat engine:
six seats, the statement's forced bets and acting order, the button skipping busted
seats, busting out while the others play on, and **real side pots** — six stacks of
different sizes is the normal case here, not an edge case. Chip conservation is checked
(40/40 legs settle to exactly 1200 chips), which is the acid test for the side-pot code.

The five opponents are the phase 1/2 archetypes, one per seat, all of which know the
table rule and reason multiway: a station, a rock, a straightforward equity bot, a
maniac and `gaston` (reconstructed from the live phase 1 log). Four legs of 60 hands,
scored the way the statement scores it — 150 points for a leg finished at +10 **and**
strictly top of the table.

Legs are the four phase 2 codenames, on the reading that "announced under the same
codenames as phase 2. The mapping has not changed" means our committed seed already
knows them. It does: 285 harvested showdowns now pin `verdigris` and `obsidian` at 1.00,
`cinnabar` at 0.95 and `amaranth` at 0.97 (`lucky7`). 30 attempts each:

| | verdigris | cinnabar | amaranth | obsidian | mean | best | bust |
|---|---|---|---|---|---|---|---|
| blind (seed ignored) | 53% | 43% | 40% | 27% | 245 | 600 | 10.8% |
| committed seed | 47% | 53% | 67% | 53% | **330** | 600 | 8.3% |

Read three things from this.

**The seed is worth ~85 points**, and it is worth most on the tables whose rule fights
the `standard` prior — `amaranth` (40% → 67%) and `obsidian` (27% → 53%). Harvesting and
committing after every attempt, which is already the phase 2 loop, matters at least as
much here as it did there.

**Only the best attempt counts, and 600 came up inside 30 attempts on both rows.** The
mean is the honest expectation for a single run; the distribution is what we are playing
for, and retries are free.

**Six-way hands teach a rule fast.** A 60-hand six-way leg yields several times the
labelled comparisons a 40-hand heads-up leg did — one six-way showdown carries five
comparisons, not one — which is why even the blind row clears 245. Measured over 40
seeds, 8 six-way showdowns price the deck better than 8 heads-up ones on 7 of 8 rules,
and 16 on 8 of 8; `tests/test_showdown_phase3.py` pins the averaged claim.

The usual caveat stands, and phase 2's notes earned it: these are opponents we invented,
and the statement says the real five "play very differently from one another". The
mechanics are faithful to the statement — the acting order, the forced bets, busting,
side pots, chip conservation checked 40/40 — but the opponents are a guess, so the
per-leg percentages are a shape, not a forecast.

## Assumptions we made

Worth raising with the challenge developers:

1. **Six seats means phase 3.** Nothing on the wire says "the target is +10 and you must
   top the table"; `phase` is in the body but the objective is read off the table size.
   A phase 3 leg that seated five would still be handled correctly; a *phase 2* table
   that ever seated three would be mis-scored by us.
2. **`players` is the whole seating, and busted seats keep their `chip_delta` of −200.**
   The statement says folded players stay in the list; it does not say explicitly that
   busted ones do, but "no cards, no forced bets, no button — while the others play on"
   only makes sense if they remain seated, and `busted` is a per-player field. We treat
   any seat we can see as a rival for "top the table".
3. **Opponents' numbers are independent of each other.** The guide says each number is
   drawn independently, so the equity product is exact for the *cards*. Our per-opponent
   *ranges* are conditioned only on that seat's own betting; correlations between what
   two opponents do are not modelled.
4. **Ties do not top the table.** "Strictly higher chip delta than every other seat. Ties
   don't count" — so a dead heat for first scores nothing, and we treat `delta > best
   other` as the bar, never `>=`.
5. **Everyone at the table plays the same rule correctly** ("every opponent here plays
   the rule correctly"), so multiway showdowns are as trustworthy as heads-up ones for
   learning the rule. We do not down-weight them.
6. **The five opponents are not identified.** "It's the same five every leg, and they
   play very differently from one another. Their names are fixed and tell you nothing."
   Names are fixed *per leg* but explicitly meaningless, so we profile a seat only within
   a hand (did this seat raise?), never across legs by name. Profiling Dana across all
   four legs is the obvious next upgrade if the names really are stable.
7. **Position is read but not yet played.** We compute the acting order from
   `button_seat` (forced bets just past the button, pre-reveal opening just past the seat
   that paid 2, post-reveal just past the button, busted seats skipped) and expose it,
   but the betting thresholds do not yet vary by how many seats act behind us. Acting
   first into five opponents is genuinely worse than acting last and the statement
   stresses it — flagged as known headroom rather than tuned on a guess.
8. **60 hands per leg is read off the wire.** `total_hands` drives the endgame window, as
   in phase 2; the statement's 60 is not hard-coded.

## Failed test cases and what fixed them

- (nothing submitted yet)
