# SHOWDOWN — Phase 3: A Crowded Table

- **PDFs:** `statement.pdf` here; the shared rules in `../guide.pdf`; phase 2's table
  rules and legs in `../phase-2/statement.pdf`
- **Endpoints required:** `POST /move` — the same endpoint again, no new route
- **Submitted to controller:** not yet
- **Score:** — (600 points on offer, the biggest single block in the challenge)

## What phase 3 adds

Two things, on top of the guide and phase 2: **six seats** and **a relative target**.

### 1. More than one opponent

> A bet now has to get through everyone still in the hand, not just one player. The same
> number is worth less than it is one-on-one: the more players still live, the likelier
> one of them holds something.
>
> Folded players stay in `players` with `folded: true` — the list is the table's seating,
> not the list of live opponents. **Filter on `folded`/`busted` yourself.**
>
> Busting also changes. Hit 0 chips and you're out for the rest of that match — no cards,
> no forced bets, no button — while the others play on. The match only ends early if just
> one player still has chips.

### 2. Position at a six-seat table

> Nothing about position changes, there are just more seats. The button still decides who
> pays which forced bet and who acts when, and still moves one seat along every hand — now
> **skipping anyone who has busted**.

```
              seat 0   seat 1   seat 2   seat 3   seat 4   seat 5
             [BUTTON]
forced bet       -        1        2        -        -        -
acts pre_reveal 4th      5th      6th      1st      2nd      3rd
                                (last)  (first)
acts post_reveal 6th      1st      2nd      3rd      4th      5th
              (last)  (first)
```

> Forced bets start just past the button: seat 1 pays 1, seat 2 pays 2. The button pays
> nothing, which is why it's the cheapest seat.
>
> Before the reveal, the order opens just past the seat that paid 2, so that seat acts last.
> After the reveal, the order opens just past the button, so the button acts last — with the
> most information.
>
> As heads-up, the order is not the same in both betting rounds. Over six hands you hold
> every seat's position once, so nobody gets a permanently good or bad seat.

## Scoring — 600 pts

> Four legs again, **60 hands** each, one table rule per leg. Each leg seats six players:
> you plus **Dana, Miles, Theo, Rhea and Bram**.
>
> It's the same five every leg, and **they play very differently from one another**. Their
> names are fixed and tell you nothing.
>
> Table rules still apply, announced under the same codenames as phase 2. **The mapping has
> not changed**, and every opponent here plays the rule correctly.
>
> Clearing is stricter: being up isn't enough. You must finish the leg with **strictly the
> highest chip delta at the table** — beating four of the five is worth nothing.
>
> **Per leg: chip delta ≥ +10 and top the table → 150 points.** Accumulating again; all four
> not required. Four legs is the full 600.

## Glossary additions

| Term | Meaning |
|---|---|
| Multiway | A hand with three or more players still in it. Your number needs to beat all of them, not one. |
| Top the table | Finish a leg with a strictly higher chip delta than every other seat. Ties don't count. |

## The shape of the problem

Three separate changes, and it is worth being clear which is which.

**1. The equity maths is different, not just tighter.** Phase 1 and 2 both price a hand as
"chance of taking the pot against one opponent". Against `k` live opponents drawing
independently we need our number to beat *all* of them. Under the standard rule a 10 that
missed the community number is worth 65% of the pot heads-up and **12%** against five:

| live opponents | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| share of the pot, holding a 10 on a 4 | 0.65 | 0.43 | 0.28 | 0.18 | **0.12** |

Reusing the heads-up number multiway is not a rounding error — it would have us
value-betting hands that are 7:1 against.

**2. The target is relative.** `chip delta ≥ +10` is easy over 60 hands; **topping the
table** is the whole difficulty. Chips are conserved, so if we are at +X the other five sum
to −X — but one of them can still be above us. What matters is not our delta, it is our
delta *minus the best other delta*, and the statement guarantees the five opponents "play
very differently from one another", so one of them will usually be running away with it.

Two useful consequences:

- **Busting an opponent is worth more than the chips.** A busted seat is frozen at −200 and
  can never top the table again. Every bust removes a rival for the only thing that scores.
- **Beating four of the five is worth nothing.** Late in a leg, second place and last place
  score identically — 0. That makes a *losing* position the one where variance is free, and
  a narrow lead the one worth protecting.

**3. The rule inference carries straight over.** "The mapping has not changed" and the
codenames are the same, so `app/data/showdown_seed.json` — 227 showdowns harvested across
phase 2's six attempts — is valid evidence on day one. Better still, a six-way showdown
labels up to five numbers at once instead of two, so phase 3 legs are a *much* richer
training set than phase 2's were. The binding constraint in phase 2 was evidence per table;
phase 3 relaxes it.

## What we changed, and what we deliberately did not

### The heads-up path is untouched

Iron rule 1: the grader may re-run phase 1 and phase 2, which are 700 points already
banked. So `decide()` branches on the number of **live** opponents:

- **0 or 1 live opponent → the phase-1/2 code path runs unchanged**, the same thresholds
  against the same one-opponent equity. Not "equivalent" — the same function.
- **2 or more → the multiway path.**

`tests/test_showdown_phase3.py::test_heads_up_decisions_are_unchanged_by_phase_3` replays
every phase-1 and phase-2 regression state through the new build and asserts an identical
reply, so this is checked rather than asserted. Phase 3's own six-seat hands take the new
path because five opponents are seated, and a six-seat hand that folds down to one opponent
correctly reverts to the heads-up logic — which is exactly right, because at that point it
*is* heads-up.

### Multiway equity is computed exactly, not approximated

`rule_equity_multiway()` gives the expected **share of the pot**, which is what pot odds
compare against. Against opponents drawn independently, with `p_i` = P(we beat opponent i)
and `t_i` = P(we tie them), a dynamic program over the opponents tracks the joint
distribution of "nobody beat us, `j` of them tied", and the share is `Σ_j P(j) / (1 + j)`.
Exact, `O(k²)` per rule, and it handles ties properly — which matters here, because several
of the candidate rules (`near`, the banded ones) tie numbers far more often than the
standard rule does, and a three-way tie pays a third of the pot, not none of it.

Each opponent gets **their own range**, sharpened by how many times *that seat* has bet or
raised this round. Phase 2 lumped all aggression together, which is fine with one opponent
and wrong with five: a seat that has raised twice and a seat that has called once are not
the same threat, and averaging them loses the whole read.

### Thresholds scale with the field, they are not re-tuned

The phase-1/2 constants (`VALUE_BET_EQ = 0.68`, `RAISE_EQ = 0.72`, …) are equity against
*one* opponent. Read as a multiple of a fair share — `1/(k+1)` — 0.68 heads-up is 1.36× fair.
The multiway path keeps those same multiples and applies them to the field size:

| | heads-up (k=1) | six-way (k=5) |
|---|---|---|
| fair share | 0.500 | 0.167 |
| value bet (1.36× fair) | 0.680 | 0.254 |
| raise (1.44× fair) | 0.720 | 0.269 |

with a **`FIELD_TAX`** on top: each extra live opponent adds 3% to the multiple required,
because a bet into four players yet to act gets through far less often than the same bet
heads-up, and the hands that call it are the ones that beat us. This is one knob with a
stated reason rather than eight re-tuned constants, and heads-up it is exactly 1.0 by
construction — which is what keeps phases 1 and 2 identical.

Pot-odds calls need no such adjustment: multiway equity against the pot price is already the
correct comparison, and it is the one place in the code where the maths does the work
directly.

### "Top the table" drives the endgame, not the whole leg

`_tilt()` now reads the best *other* chip delta off `players` and steers by the gap:

- **Behind the leader with the leg running out → chase.** Second place scores zero, so
  the downside of variance is nil and the upside is the only 150 points on offer. The tilt
  goes sharply negative (looser calls, more raises) and scales with how far behind we are.
- **Ahead, with a cushion the blinds cannot eat → protect.** Marginal spots are worth less
  than the lead they risk.
- **In the middle → play the hand, not the scoreboard.** Chasing from 55 hands out just
  spews chips; the position is not yet decided.

Deliberately *not* done: pushing every marginal edge all leg because "topping the table
needs chips". Phase 2 measured a stake cap that fixed the hand that lost a leg and cost 18
to 88 points overall — post-mortems on single hands are how you talk yourself into a bad
rule. The endgame tilt is the narrow version of the idea, applied only where the scoreboard
genuinely changes the value of a decision.

### Side pots make several winners honest, and the rule learner has to know

Phase 2 was burned twice by multi-winner hands: first reading all-in refunds as ties (which
invented a banded deck), then filtering them out (which manufactured the confidence that
lost a leg). Multiway makes this sharper, because **a real six-way hand can have two winners
with different numbers and nothing odd going on**: A wins the main pot, B wins a side pot
A was not eligible for.

The fix uses a fact that holds under every rule: **the best key at showdown always wins the
main pot**, because everyone contests it. So for a showdown with **three or more** shown
numbers, a rule is consistent with the hand when its predicted best-key set is a *subset* of
the reported winners. Extra winners are explained by side pots; a predicted winner who did
not win at all is a real contradiction and still costs the hypothesis its weight.

Two-player showdowns keep phase 2's exact-match test, byte for byte. That is where the
painful lessons were learned, all 227 seeded observations are two-player, and this change
must not disturb them.

## Assumptions we made

Worth raising with the challenge developers:

1. **`players` is the seating, and non-live seats can be identified from it.** We filter on
   `folded` and `busted` being truthy. A busted seat is also assumed to be excluded from the
   hand entirely — the statement says "no cards, no forced bets, no button".
2. **Opponents' numbers are drawn independently of ours and of each other**, as the guide
   says for two players ("each is drawn independently"). The multiway DP relies on this. If
   the deck were shared without replacement across six seats the equities shift slightly.
3. **The per-leg target is `+10` *and* strictly top the table.** Read off this statement.
   The code applies it when six seats are present; phase 2's `+25` and phase 1's `+10`
   still apply to their own shapes. We cannot read the target off the wire.
4. **60 hands per leg** is read from the statement, but every endgame decision keys off
   `total_hands`/`hand_number` on the wire rather than the constant.
5. **`chip_delta` on other players is comparable to ours.** The guide says it is frozen at
   the start of the hand for every seat, so the scoreboard we steer by is one hand stale.
   That is the same figure the leg is scored on, so it is the right one — but it means a
   pot won this hand is not visible until the next.
6. **A busted opponent stays in `players` with its final `chip_delta`.** We count it when
   working out who is topping the table, since a seat that busted at −200 is still a seat
   we have beaten.
7. **The same five opponents means the same five bots, not the same five strategies as
   phase 2.** We do not carry any opponent model across from phase 2, only table rules.
8. **`recent_hands` may show three or more numbers per showdown.** The guide's shape is
   `shown_numbers` keyed by seat with no stated limit of two, and "only seats that got
   there appear".

## Simulation results (`tools/simulate.py --phase3`)

The heads-up engine could not be stretched to six seats — forced bets move to the two seats
past the button, the acting order opens in two different places depending on the round, the
button and the deal both skip busted seats, and an all-in has to build **side pots** rather
than refund the difference — so phase 3 gets its own table, following the statement's
position diagram. It is checked for chip conservation on every leg (the six deltas sum to
zero) and the five opponents are the existing archetypes, upgraded to price their hands
against the whole field rather than heads-up, since a house bot that valued its number
one-on-one with five players live would be a strawman.

Four legs of 60 hands, scored exactly as the statement scores it — **+10 and strictly top
the table, 150 a leg**. `cold` is a fresh process; `warm` is a retry that has already
learned these tables.

| | leg 1 | leg 2 | leg 3 | leg 4 | points | mean Δ |
|---|---|---|---|---|---|---|
| cold | 50% | 30% | 20% | 25% | **188 / 600** | +178 |
| warm | 55% | 25% | 20% | 60% | **240 / 600** | +322 |

The interesting number is not the points, it is the finishing position. Over 96 legs we come
**first 31% and second 40%** of the time, and are below third only once:

| finish | 1st | 2nd | 3rd | 4th | 5th | 6th |
|---|---|---|---|---|---|---|
| legs | 30 | 38 | 18 | 9 | 1 | 0 |

We clear the +10 half of the condition 58% of the time and the *top the table* half 31% —
which is the statement's warning made concrete. Being reliably second is worth nothing, and
that, not chip accumulation, is what phase 4 of the tuning effort should attack.

### The stake cap, rejected again

We bust in 20% of legs, and a bust is a guaranteed zero, so charging more for hands that
play for a stack looks obviously right. Measured on identical legs and seeds it is not:

| stack-risk price | points | bust rate | mean Δ |
|---|---|---|---|
| **as shipped** | **188 / 600** | 20% | +180 |
| ×1.5 per field | 169 / 600 | 7% | +183 |
| ×2.5 per field | 100 / 600 | 1% | +104 |

Busts fall from 20% to 1% and the score falls with them. Folding the marginal-but-profitable
spots costs more than the blow-ups it prevents — the same shape as the stake cap phase 2
measured and rejected, and the same conclusion. The 20% bust rate is the price of the
aggression that wins the legs we do win. Not shipped.

### How much to trust any of this

Not very far, and it is worth being blunt about why. The phase-2 build that scored 25/400
was rated around 300 by this simulator, because opponents we invent get their chips in far
worse than the real ones do. These five archetypes were written for a heads-up game and
reused here. What the six-seat simulator is genuinely good for is the things that are true
regardless of opponent: chip conservation, side-pot arithmetic, the acting order, the fact
that folding more loses points, and the fact that we finish second far too often. It is not
evidence that any threshold is at its best value, and no threshold was tuned on it.

## Failed test cases and what fixed them

- (nothing yet — not submitted)


## Attempt 1 — 0/600

Match `phase3-seed2145184885`. The four legs were the **phase 2 codenames**, which
confirms the statement's "the mapping has not changed" and means the committed seed
applied from hand 1.

| leg | table | our delta | rank | best other |
|---|---|---|---|---|
| 1 | verdigris | **+261** | 2 of 6 | Rhea +534 |
| 2 | obsidian | **−200** (busted) | 6 | Rhea +350 |
| 3 | amaranth | **+173** | 2 of 6 | Rhea +433 |
| 4 | cinnabar | **−200** (busted) | 6 | Miles +579 |

Protocol was clean: 336 `/move` calls, every one HTTP 200, mean 8.5 ms and max 103 ms
against a 5-second budget, no illegal actions and no out-of-range amounts.

### What actually went wrong

**We were never short of chips — we were short of the *right* chips.** Two legs finished
at +261 and +173, both comfortably past the +10 threshold and both worth exactly zero,
because one opponent ran away with the table every time. Four of the five opponents bust
in every leg, dumping ~800 chips; Rhea (or Miles) collected 55-67% of that and we
collected 25-33%.

**Both busts were a single hand.** `chip_delta` is frozen at the start of a hand, and in
legs 2 and 4 we were at **−1** and **−20** at the start of the last hand we ever acted
in. We did not bleed out; we got a stack in and lost it.

**The one defect the log proves, twice: a near-nuts hand bet 2 chips.**

- leg 2 hand 57 — holding a **2** on `obsidian` ("a pair loses to any non-pair, then the
  lower number wins") against a community **10**. Only a 1 beats us: an 88% favourite,
  108 behind, 182 already in the pot. **It bet 2.** The opponent raised to 151 and we
  called off the stack.
- leg 4 hand 23 — a **13** on a community **8** under the standard rule, so only the 8
  itself beats us. Pot 114. **It bet 2.**

This is not a tuning question, it is `_put_in` falling through. The stack-risk price is
`RAISE_RISK × (chips in / stack)`, so it scales with the size of the bet: the value bet
the sizing logic asked for gets refused, and the only fallback was the *minimum*. A token
bet with a monster is the worst of both — it gives up the value and hands the opponent a
cheap raise.

### Fixes

1. **`_put_in` solves for the largest affordable size.** The equity above the floor is a
   budget, and `eq >= floor + RAISE_RISK × scale × x / stack` inverts to a size. It now
   tries intended → largest affordable → minimum, instead of intended → minimum. Replayed
   against the live log this changes **6 of 333** real decisions, every one a strong hand
   that was being under-bet, and introduces no illegal action or out-of-range amount.
   Gated on the **seating** being three or more, so phases 1 and 2 keep their sizing
   exactly — and so a phase 3 leg that has folded down to a duel, which is precisely
   where the leg 2 hand happened, still gets the fix.
2. **The chase lifts part of the stack-risk guard** (`CHASE_RISK_RELIEF`). The existing
   comment already said it — "second place scores exactly what last place scores, which
   is what makes a losing position the one where variance is free" — but the code only
   nudged a threshold by 0.16, which cannot turn a 250-chip deficit around. When the
   chase is at full pressure the guard protecting a stack that scores nothing is mostly
   released. `_chase_pressure` is 0 at any two-seat table and 0 whenever we are in front,
   so nothing outside a phase 3 run-in can see it.

### Measured, and not shipped

On the four real legs (`/tmp` harness over `tools/simulate.py --phase3`, seed loaded):

| change | points | bust |
|---|---|---|
| as deployed | 296 | 15.0% |
| + size solving | 304 | 15.6% |
| + chase relief (shipped) | 308 | 16.9% |
| chase window 18 → 30 hands | 322 | 24.4% |
| `FIELD_TAX` 0.03 → 0 | 304 | 18.1% |
| `CALL_RISK` 0.55 → 0.35 | 300 | 21.9% |

**The simulator is optimistic and must not be trusted for the last few points.** It has
us averaging **+396** a leg where the real attempt averaged **−42**, and it says we top
half the legs where we topped none of four. It reproduces the *structure* well (four
opponents busting is its modal leg, leader ~+375 against a real +474), which is why it is
worth running at all — but a 5% difference on it is not evidence. The chase window and
`FIELD_TAX` changes are left alone on exactly that basis; phase 2 already has a scar from
shipping a plausible-looking staking rule.

The honest reading of attempt 1 is that one demonstrable defect was worth fixing and the
rest was a variance contest we lost 0-for-4. Retries are free and only the best attempt
counts.


## Attempt 2 — 150/600

Match `phase3-seed3645897548`, same four codenames. The token-bet fix worked and the
busting stopped, and one leg was won outright. The other three were folded away.

| leg | table | ours | rank | leader | our biggest winning hand, all leg |
|---|---|---|---|---|---|
| 1 | verdigris | +77 | 2 of 6 | Miles **+723** | +127 |
| 2 | obsidian | **+629** | **1 — cleared, 150 pts** | Dana +27 | +600 |
| 3 | amaranth | −89 | 2 of 6 | Rhea **+889** | **+13** |
| 4 | cinnabar | −78 | 2 of 6 | Rhea **+898** | **+14** |

Protocol clean again: 318 `/move` calls, all 200, mean 8.6 ms, max 112 ms. **Zero busts**
(attempt 1 had two), so the size-solving fix did what it was meant to.

### What went wrong: we never contested a pot

In legs 3 and 4 our single biggest winning hand across sixty hands was **13 and 14
chips**. Four opponents busted in each leg, putting ~800 chips on the table, and one
opponent collected essentially all of it while we sat at −89 and −78. That is not a
losing run of cards, it is a bot that folds every pot worth winning.

Three real folds, all with the rule correctly identified:

| leg | hand | we held | community | rule read | pot | to call | pot odds | equity | played |
|---|---|---|---|---|---|---|---|---|---|
| 4 | 3 | **13** | 7 | `standard` 0.95 | 192 | 96 | 0.33 | **0.885** | **fold** |
| 4 | 10 | 12 | 2 | `standard` 0.95 | 102 | 51 | 0.33 | 0.806 | **fold** |
| 3 | 12 | 12 | 7 | `lucky7` 0.97 | 154 | 73 | 0.32 | 0.809 | **fold** |

A 13 on a community 7 under the standard rule is beaten by exactly one number, the 7
itself. Folding it getting 3:1 is indefensible. The cause is not the rule model and not
the equity — both were right — it is `CALL_RISK`:

    CALL_RISK x (risked / stack) = 0.55 x 0.63 = +0.347 of extra equity demanded

`CALL_RISK = 0.55` and `RAISE_RISK = 0.40` were measured on **live phase 2 data**, and
they are correct there: heads-up, over 40 hands, against an **absolute** +25 target,
busting forfeits a target that was still reachable, so refusing to play for a stack on a
read is right. Phase 3 scores a **relative** target. Second place and last place both pay
zero, so a stack that does not finish biggest is worth nothing, and ruin-aversion is
close to worthless — while the cost of it, every leg, is the ~800 chips of dead money
going to whichever opponent was willing to play for them.

### Fix

`PHASE3_RISK_RELIEF = 0.5` takes half the stack-risk price off for the whole of a
six-seat leg, on top of the existing chase relief in the run-in. Gated on the
**seating** being three or more, not on who is still live — leg 4 hand 3 was heads-up by
the time it reached us but still a six-seat leg scored on topping the table, and a real
two-seat phase 1/2 match is untouched. Will's `test_no_real_phase_2_request_ever_takes_
the_multiway_path` still passes, so the 700 banked points are provably unaffected.

Replayed against the live log this changes **7 of 318** real decisions — five folds
become calls, two bets get bigger, nothing becomes illegal or out of range. The five
pots it now contests are worth 514 chips in legs we finished 89 and 78 chips down.

Swept on the four real legs:

| `PHASE3_RISK_RELIEF` | points | bust |
|---|---|---|
| 0.0 (attempt 2) | 308 | 16.9% |
| 0.3 | 326 | 19.4% |
| **0.5 (shipped)** | **341** | 26.2% |
| 0.7 | 330 | 25.6% |
| 0.85 | 319 | 28.7% |

A clean inverted U peaking at the midpoint, and +11% rather than the noise-level
differences that were rejected in attempt 1's write-up. The bust rate rising to 26% is
the price and it is the right price to pay: busting and finishing second score the same
zero, so the points column already values it correctly.
