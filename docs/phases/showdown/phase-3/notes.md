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
