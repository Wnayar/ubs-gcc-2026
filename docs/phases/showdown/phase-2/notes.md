# SHOWDOWN — Phase 2: Reading the Table

- **PDFs:** `statement.pdf` here; shared rules in `../guide.pdf` (re-downloaded 10:31,
  byte-identical to the 08:54 copy apart from the printed timestamp — the guide has
  **not** changed, and it never mentions legs, so `leg_number`/`total_legs` are new
  fields added for this phase)
- **Endpoints required:** `POST /move` — same endpoint as phase 1, no new route
- **Submitted to controller:** yes — attempts scored 100 → 200 → **300** / 400
- **Score:** **300/400** on attempt 3. Attempt-4 fixes below, not yet submitted.

## What phase 2 adds

Two things, on top of everything in the guide:

### 1. Table rules — the showdown is no longer the rule we know

> Every match is played under one **table rule** — a modification to how the showdown is
> decided. It is fixed for the whole match and announced in `table_rule` on every
> request. **Only the showdown changes**: betting, forced bets, position and sizing are
> identical under every rule.
>
> **We are not telling you what the rules are, or how many there are.**
>
> Here is a rule that is **not** in play, so you know the shape of the thing:
> *Odd numbers beat even numbers; within each group, higher still wins.*
>
> That is an illustration of the *kind* of change a rule can make — nothing more. The
> real rules are not this one. **Do not code against it.**

`table_rule` is an **opaque codename** (their example: `chalcedony`, also not real).

> The mapping is fixed for the whole event: the same codename always means the same
> ruleset, in every match, every attempt, and every later phase.
>
> Read it on every request rather than assuming it carries over. The same number can be
> a monster under one rule and worthless under another.

### 2. Legs

> An attempt is four **legs** played back to back. Each leg is a complete match with
> fresh 200-chip stacks and its own table rule — `hand_number` restarts at 1 and every
> `chip_delta` restarts at 0. `leg_number` and `total_legs` tell you where you are; both
> are `null` in a single-match phase.
>
> `recent_hands` does not carry across legs. It resets when a new leg starts.

## Scoring

> Four legs, **40 hands** each, a different table rule on each.
>
> The same opponent plays all four legs, under the same name, and plays the same way
> throughout. Their name is drawn fresh each attempt so it never means anything.
>
> **The leg order and each leg's rule are identical on every retry — only the cards
> change.**
>
> **Per leg: chip delta ≥ +25 → 100 points.** Points accumulate per leg; you don't need
> all four to score. All four is the full **400**.

Note the bar is much steeper than phase 1: **+25 over 40 hands**, four times, versus +10
over 100. And a leg where we never work out the rule is a leg we are betting blind in.

## Glossary additions

| Term | Meaning |
|---|---|
| Leg | One complete match inside a multi-match attempt. Fresh stacks, its own rule, its own `recent_hands`. |
| Table rule (`table_rule`) | The showdown ruleset a match is played under. Announced on every request as a codename, never changes mid-match. |
| Codename | The opaque string `table_rule` carries. Identifies a ruleset without describing it; the same codename always means the same ruleset. |

## The shape of the problem

This is not a betting-tuning phase, it is an **inference** phase. Phase 1's strategy hard
codes one showdown rule (a pair beats any non-pair, otherwise higher wins). Under an
unknown rule that model is not merely imprecise, it is *actively wrong* — it will value a
worthless number as a monster.

Three facts make it tractable:

1. **`recent_hands` is a labelled training set.** Each completed hand that reached
   showdown carries `shown_numbers` (both seats' numbers), `community_number`, and
   `winners`. That is exactly one labelled comparison per showdown: "under this rule,
   this number beat that number with this community number".
2. **Codenames are stable event-wide.** Anything learned about `chalcedony` in leg 2 of
   attempt 1 is still true in every later attempt *and every later phase*. So we key what
   we learn off the codename, not the match.
3. **Retries are free and the leg order is fixed.** Attempt 1 can be treated as
   reconnaissance; attempts 2+ start already knowing the rules, provided the service
   process has not restarted in between.

## How the bot handles it (`app/showdown_rules.py` + `app/showdown.py`)

- A rule is represented as a **strength function** `key(n, c)`, higher wins, equal keys
  split. That one shape covers every "one sentence" showdown rule we can think of.
- A **hypothesis set** of candidate rules is scored against the observed showdowns by
  Bayes, giving a posterior over rules per codename.
- Every decision uses **posterior-averaged equity**: `Σ P(rule) · equity(n, c | rule)`.
  When the rules disagree the equity collapses toward 0.5 on its own, which is exactly
  the caution warranted while we still do not know the table.
- The opponent's range is modelled by **strength rank under the believed rule**, not by
  numeric value — a softmax over rank that sharpens as they bet and raise. Under the
  standard rule this reproduces phase 1's "a big shove is usually the pair" read without
  hard-coding the idea of a pair.
- Observations are cached per codename in-process and survive across legs and attempts.
- A **non-parametric fallback** (`learned_order`) fits a strength order over the 13
  numbers straight from play, for tables whose rule is in no hypothesis we wrote. It can
  only represent rules where strength does not depend on the community number — but that
  covers a large family ("primes beat composites", "n mod 3", any fixed reordering) that
  hand-written hypotheses will not reliably anticipate.
- Every hypothesis, fixed and fitted alike, is scored by **two-fold cross-validation**:
  each is judged on showdowns it was not fitted on. The fixed rules have no parameters so
  this changes nothing for them, which makes it a fair comparison and stops the flexible
  fitted order from winning just by memorising the data.

## Simulation results (`tools/simulate.py --phase2`)

Four legs of 40 hands, a different hidden rule on each, scored the way the statement
scores it (100 points a leg at chip delta ≥ +25). **cold** is a fresh process meeting
these tables for the first time; **warm** is a retry, where an earlier attempt already
taught us the rules — which the statement guarantees is legitimate, since "the leg order
and each leg's rule are identical on every retry".

Rules drawn from our hypothesis set:

| opponent | cold | warm |
|---|---|---|
| sane | 212 / 400 | **242 / 400** |
| gaston | 228 / 400 | **270 / 400** |
| rock | 200 / 400 | **232 / 400** |

Rules deliberately chosen to be *outside* the hypothesis set (`n mod 3`, primes, cyclic
distance, parity of n+c) — the honest worst case:

| opponent | cold | warm |
|---|---|---|
| sane | 92 / 400 | **155 / 400** |
| gaston | 118 / 400 | **182 / 400** |
| rock | 88 / 400 | **145 / 400** |

Two things to read from this. **Retries are worth a lot** — 30 to 60 points on in-set
rules and 50 to 60 on unfamiliar ones — because the second attempt starts knowing the
tables. And **an unfamiliar rule is expensive**: before the fallback existed, the `n mod 3`
leg cleared 2% of the time; with it, 55% warm. If a real leg looks hopeless, the fix is to
read `GET /debug/showdown-rules`, work out the rule by hand, and add it to the hypothesis
set — not to retune the betting.

Latency, which the 5-second budget makes a correctness concern: 8 ms per `/move` with 600
accumulated showdowns on one codename and a fresh 20-hand history every call.

## Assumptions we made

Worth raising with the challenge developers:

1. **`standard` is pinned, not learned.** Phase 1's `table_rule` reads `standard` and the
   guide spells that showdown out in full, so that codename is pinned to the known rule
   rather than re-derived. Everything else starts from a uniform prior. This is what keeps
   phase 1 (300 pts, still scored) bit-for-bit unchanged.
2. **A rule depends only on `(your number, community number)`.** Every rule we can build
   from the guide's vocabulary has this shape, and the statement says only the *showdown*
   changes. A rule that depended on position, hand number or betting history would not be
   representable and we would fail to learn it.
3. **The explicitly-excluded example is excluded.** "Odd beats even, then higher" is left
   out of the hypothesis set because we are told it is not in play; the mirrored version
   (even beats odd) is kept, since only the specific rule was ruled out.
4. **We do not know the per-leg target from the protocol.** +25 is read from the statement
   and applied when `leg_number` is present; phase 1's +10 applies when it is `null`.
5. **`total_hands` reads 40 per leg.** The statement says 40 hands per leg and
   `hand_number` restarts, so the endgame logic keys off the values on the wire rather
   than a constant.
6. **In-process memory only.** Learned codename→rule mappings live in memory. A Render
   restart or redeploy loses them, and the free plan spins down after ~15 idle minutes.
   Mappings we become confident about should be baked into `KNOWN_RULES` and committed —
   `GET /debug/showdown-rules` dumps what has been learned so far for exactly that.

## Failed test cases and what fixed them

**Attempt 1 scored 100/400** — one leg of four. Legs were `verdigris`, `cinnabar`,
`amaranth`, `obsidian`, 40 hands each. Raw logs are in `../logs/`.

| leg | table | final chip delta | cleared (+25)? |
|---|---|---|---|
| 1 | verdigris | +16 (peak +16) | no |
| 2 | cinnabar | **+97** | **yes** |
| 3 | amaranth | −16 | no |
| 4 | obsidian | −90 | no |

Protocol was clean: 241 `/move` calls, all 200, max 68 ms, no illegal actions.

### What actually went wrong

**We never saw enough showdowns to identify a table.** Only 33–55% of hands reach a
showdown, so a 40-hand leg yields 7–16 labelled comparisons — nowhere near enough to
separate fifteen hypotheses. Our fold rate was only 17%, so this is not us folding the leg
away; it is the information budget of the format.

**Two of the tables are not expressible in the hypothesis set at all.** Refitting the
recovered showdowns by hand:

- `cinnabar`: `{13, 12}` split the pot — **12 and 13 are equal strength**. Also `8 beats 12`.
- `amaranth`: `7 beats 8`.

No "higher/lower/pair" variant can produce either. These rules group numbers into
equivalence classes or reorder them, and the best any fixed hypothesis managed was 80–92%.

**Every deploy wiped what we had learned.** The learning was in-process only, so the
redeploy that shipped phase 2 reset it, and each attempt started from nothing.

**Our own request log destroyed the evidence.** `MAX_BODY` was 4096, and phase-2 bodies
carry up to 20 completed hands in `recent_hands`: **161 of 241 bodies were clipped**,
losing roughly a quarter of the showdowns we had actually been shown.

### Fixes

1. **`MAX_BODY` 4096 → 32768** so an attempt's evidence survives in the log.
2. **A committed seed file** (`app/data/showdown_seed.json`, 45 showdowns from attempt 1)
   replayed at startup, plus `GET /debug/showdown-observations` to harvest an attempt's
   learning in exactly that shape. The codename mapping is fixed for the whole event, so
   this is the durable half of a memory the dyno keeps killing. All four tables now start
   informed instead of blank.
3. **The prior is no longer flat — it starts at phase 1's rule** (`PRIOR_STANDARD = 0.40`).
   Three of the four real tables were best explained by the standard rule (verdigris 100%,
   amaranth 92%, cinnabar 80%); a uniform prior over fifteen hypotheses threw that away and
   left us near a coin flip for the first dozen hands of every 40-hand leg. Evidence still
   overrules it — `obsidian` correctly reads `antipair_low`, and the bot now bets a 2 and
   checks a 13 there from hand 1.

### What was tried and rejected

A Bradley-Terry ranking fit over the 13 numbers — which *can* express "12 == 13" and
"7 beats 8" — was measured by leave-one-out against the real showdowns and was **worse**
than the fixed rules at this data volume (67–80% vs 80–100%). It needs far more data than a
leg provides, so it stays as the low-weight fallback rather than becoming the main model.
The binding constraint is evidence per table, which is why the seed file matters more than
any modelling change.

### The loop that should raise the score

After every attempt, harvest and commit, so each run starts from all prior evidence:

```
curl -s "https://ubs-gcc-2026.onrender.com/debug/showdown-observations?token=$DEBUG_TOKEN" \
  > app/data/showdown_seed.json.new
```


## Attempt 2 — 200/400

| leg | table | final delta | cleared (+25)? |
|---|---|---|---|
| 1 | verdigris | **+102** | **yes** |
| 2 | cinnabar | +7 | no — missed by 18 |
| 3 | amaranth | **+199** (busted the opponent in 9 hands) | **yes** |
| 4 | obsidian | **−162** | no |

The seed worked: 45 observations became 87, and `obsidian` went from 0.46 confidence
to **`antipair_low` at 1.00** — "a pair loses to any non-pair, then the lower number
wins". `verdigris` and `cinnabar` both sit at 0.84 standard. Only `amaranth` is still
unsettled, and its evidence is now internally inconsistent — no hypothesis clears 93%.

### What lost the obsidian leg — and it was not the rule

Hand 9 of 40. We held a **2** against a community **7**. Under `antipair_low` that is a
monster: the opponent's 7 would pair and lose, and only a 1 beats us — about 88%. We
raised to 42, then called 83 more, putting **135 of our 200 chips** in. The opponent held
the 1. From −149 at hand 10 the leg never recovered.

The rule read was right and the hand was a favourite. **The staking was wrong.** A leg is
scored on clearing **+25**, not on maximising chips. Winning that pot would have cleared
the target five times over — the upside was worthless — while losing it ended the leg. At
88%, one hand in eight plays out exactly like this.

**A stake cap was built for this and then rejected.** Capping the chips we will
voluntarily put into one hand at `45 + 2.2 × (chips still needed)` does fix hand 9 in
isolation — replayed against the real state it calls instead of raising to 42, and folds
the 83, losing ~50 instead of 135. But measured over whole attempts on identical legs and
seeds it **cost 18 to 88 points against every opponent**:

| opponent | cap off | cap on |
|---|---|---|
| sane | 232 | 215 |
| gaston | 302 | 215 |
| rock | 222 | 158 |

Folding the marginal-but-profitable spots the cap catches costs more than the occasional
blow-up it prevents. The obsidian hand was a *well-played* 88% favourite that lost — one
hand in eight does — and post-mortems on single hands are exactly how you talk yourself
into a bad rule. Not shipped.

### Still open

- **`amaranth` is inconsistent.** Attempt 1 had `7 beating 8`; the fuller set has no
  hypothesis above 93%. Its `/matches/` replay would settle it — that endpoint returns the
  numbers dealt in *every* hand, including the ones that ended in a fold, which is several
  times the evidence a showdown-only view gives.
- **`cinnabar` missed by 18 chips.** Nothing diagnostic in the log; it read 0.84 standard
  and simply did not get there.


## Attempt 3 — 300/400

| leg | table | final delta | cleared (+25)? |
|---|---|---|---|
| 1 | verdigris | +79 | **yes** |
| 2 | cinnabar | +133 (busted them in 11 hands) | **yes** |
| 3 | amaranth | +19 (peaked +48) | no — **missed by 6 chips** |
| 4 | obsidian | **+39** | **yes** |

**Obsidian flipped from −162 to +39** — exactly the leg the seed was supposed to fix, and
it went from 0.46 confidence to fully identified. The seed loop is working: 87 observed
showdowns became 131.

### Amaranth, finally identified

Amaranth is the last failing leg and it was the one table nothing explained. With 26
showdowns, two facts stood out and no ordering by size accounts for either:

- **`7 beats 8`, twice, at two different community numbers** — and a 7 never lost.
- **`13` and `12` split a pot**, so those two are equal strength.

`a 7 beats everything, then a pair beats any non-pair, then numbers in bands of two`
explains **26 of 26**. Adding a "lucky number" family (one candidate per number, with and
without banding) lets the posterior find it rather than us naming it, and it now reads
**`lucky7_band2` at 0.97**.

Two checks before trusting it. Seat bias exists in the data (14 wins to 8) but "seat 0
always wins" explains only 14 of 22 decided hands, so position is not the rule. And the
banding half is independently corroborated — cinnabar split a 13 against a 12 back in
attempt 1, so grouped decks are a real feature of this event, not a curve fit.

The 7-specialness still rests on **only two hands**, which is why it is a hypothesis with
a prior rather than a hard-coded mapping. If a later attempt contradicts it, the posterior
will move.

### Where the four tables now stand

| table | rule | confidence | explains |
|---|---|---|---|
| verdigris | a pair beats any non-pair, then higher | 0.97 | 41/43 |
| cinnabar | a pair beats any non-pair, then higher | 0.86 | 21/23 |
| amaranth | a 7 beats everything, then a pair, then bands of two | 0.97 | **26/26** |
| obsidian | a pair *loses* to any non-pair, then lower wins | 1.00 | 38/39 |

Cost of the larger hypothesis set: 58 rules after dedupe, and a `/move` still answers in
**10 ms** against a 5-second budget.


## Attempt 4 — scored 0, and no hand was played

The controller **never reached our service**. Pulled from the live log afterwards:

- **3 `/move` calls total**, all of them my own smoke tests (`total_hands: 100`, no
  `table_rule` — phase-1 shaped, not phase-2). No grader traffic, no legs, no codenames.
- 139 of the 145 `/health` hits came from `10.209.26.167` — Render's internal
  health-check poller on a 5 second cycle, not the coordinator.

So this was a deployment failure, not a strategy failure, and the 300 from attempt 3
still stands because only the best attempt counts.

Two ways a branch deployment silently fails, both now fixed on this branch:

1. **A cold service scores exactly 0.** Free dynos spin down after ~15 idle minutes and
   take ~50 s to wake; the coordinator allows 5 s per `/move` and forfeits a leg after
   five failures in a row. A service nobody warmed loses every leg without playing a hand.
   `scripts/warm.sh <url> [expected-commit]` wakes it, waits until `/health` answers in
   under a second, and **fails loudly if the commit served is not the one expected** —
   which is exactly the second failure mode:
2. **A Blueprint takes the branch from `render.yaml`, not from the branch the file is on.**
   A service created from this repo without an explicit entry builds `main` and serves the
   old code however many times you push to `showdown-phase-2`. `render.yaml` now declares
   a second service, `ubs-gcc-2026-showdown`, pinned to `branch: showdown-phase-2`.

Note its `DEBUG_TOKEN` is `sync: false`, not `generateValue: true` — `generateValue` mints
a *different* token per service, so the value in the local `.env` would not authenticate
against it and `/debug/requests` would be unreadable exactly when it is needed. Set it by
hand in the dashboard to match the main service.

Before every submission from now on:

```
./scripts/warm.sh https://<service>.onrender.com 4e5dc6c
```


## Attempt 5 — 300/400, and the bug behind all of it

Legs: verdigris **+13 FAILED**, cinnabar +114, amaranth **+63 cleared**, obsidian +40 in
eight hands. The lucky-7 fix worked — amaranth had been the failing leg and now clears —
but the failure simply rotated to verdigris, which had cleared comfortably twice before.

Verdigris reads `standard` at 0.97, the rule we know best, so this was not a rule we had
failed to learn. Its only two unexplained showdowns were **splits between different
numbers**: `12 vs 11` and, stranger still, `10 vs 12` where the 10 *paired the community
and still did not win*.

### Two winners with different numbers is not a tie

Checking the pot sizes settled it:

| kind of hand | count | median pot |
|---|---|---|
| decided | 73 | **8** |
| split, identical numbers (genuine tie) | 15 | 24 |
| split, **different** numbers | 3 | **307** (127, 307, 405) |

Every one is an all-in. When both players are all in, chips nobody could cover go back and
the hand log lists **both** seats as winners. They are refunds, not ties — and we had been
feeding them to the rule learner as evidence that two different numbers were equal in
strength.

That single misreading is the only reason the deck ever looked like it was grouped into
bands. Discard those three hands and **every table is explained exactly**:

| table | rule | fit |
|---|---|---|
| verdigris | a pair beats any non-pair, then higher | **52/52** |
| cinnabar | a pair beats any non-pair, then higher | **37/37** |
| amaranth | **a 7 beats everything**, then a pair, then higher | **36/36** |
| obsidian | a pair *loses* to any non-pair, then lower wins | **40/40** |

Note amaranth is plain `lucky7`, not the banded `lucky7_band2` we shipped last time: the
banding half was fitting one refund.

### The fix, and the trap inside it

`observe()` now rejects a two-winner hand whose numbers differ **when the pot is at least
half a starting stack**. The pot is the discriminator, not the numbers — plenty of rules
tie different numbers honestly (under "closest to the community" a 3 and a 7 both sit two
away from a 5), so filtering on the numbers alone would throw away real evidence for every
distance-based rule. A first attempt at this fix did exactly that and a test caught it.

The banded-rule family is removed, since the evidence for it was those refunds. That takes
the hypothesis set from 58 back to **27**, which also sharpens every other table's read by
not splitting the posterior between near-identical explanations.


## Attempt 6 — 25/400, and the fix that caused it

Legs: verdigris −52, cinnabar +91, amaranth **−171**, obsidian **−176**. Amaranth and
obsidian were the two tables read at 1.00 confidence, and they were the two that lost most.

**The rule reads were not the problem.** Fitting only this attempt's showdowns, with no
seed: verdigris `standard` 100%, cinnabar `standard` 100%, obsidian `antipair_low` 100%.
The tables are stable and we have them right.

**Nor was the strategy.** Replaying all 257 of this attempt's real `/move` requests through
the previous build and the new one, **6 decisions differ — 2%**. A 2% difference cannot
move a leg from +63 to −171. Most of the swing is the opponent (the bot was named Vince
this time, Tess before) and the cards.

But one of those 2% was catastrophic, and it was my doing.

### How a filter became a stack-off

Leg 3, hand 6: holding a **7** on amaranth, we raised to 43 and then shoved all 211 chips.
We lost 187. `unbeatable()` had said the hand could not lose, and `unbeatable()` waives
**every** stack-risk guard we own — that is the whole point of it, and it is correct for a
pair under the standard rule.

The hand that would have stopped us was in the log all along: `7 vs 8, community 8`, with
**both** seats listed as winners. That directly contradicts "a 7 beats everything". The
previous attempt's fix had discarded it as an all-in refund because its pot was 400.

- keeping it: no rule explains amaranth better than **87%**, the posterior spreads, and a 7
  is not unbeatable
- discarding it: `lucky7` reaches **100%**, and the bot bets its whole stack on it

The filter removed exactly the hands that discriminate between rules, because those are the
hands people play for stacks. It manufactured the confidence that lost the leg.

### The fix

1. **The refund filter is reverted.** Odd hands are evidence, especially the expensive ones.
2. **`unbeatable()` now takes an empirical veto.** Before waiving the risk guards, it checks
   whether we have ever *seen* that number fail to win outright at that community number.
   One direct counter-example outranks any amount of posterior. The check is
   community-scoped — a 9 losing when it does not pair says nothing about a 9 that does —
   and a genuine pair under the standard rule is still unbeatable, which is what keeps
   phase 1 intact.
3. **The seed is rebuilt from the raw request logs**, not from harvested observations. The
   deployed build had already filtered the contradicting hands out of what
   `/debug/showdown-observations` returns, so harvesting from a running service loses
   exactly the evidence a bad attempt was supposed to teach us. 227 showdowns.

Amaranth now reads `lucky7` at 0.50 rather than 1.00, and a 7 there is **not** treated as
unbeatable. That is the honest state of the evidence: two hands say a 7 beat an 8, one says
it did not.


## Where the points actually are

Per-table results across every graded attempt:

| table | rule | cleared | deltas |
|---|---|---|---|
| cinnabar | standard | **6/6** | +91, +91, +97, +114, +133, +136 |
| obsidian | antipair_low | 2/6 | −176 … +40 |
| amaranth | lucky7 | 1/6 | −171 … +63 |
| verdigris | standard | 1/6 | −52 … +79 |

Overall per-leg clear rate **42%**, so P(all four in one attempt) ≈ **3%** — roughly 33
attempts for an even chance. Retrying alone will not reach 400.

Cinnabar and verdigris are **the same rule** and produce opposite results, which rules out
the rule as the explanation. Opponent aggression is 30-44% on every table and we are seat 0
in all of them, so it is not position or opponent style either. The difference is how much
we lose in the hands we lose.

## The one measurable leak

Bucketing all 337 hands by the largest share of stack we voluntarily committed:

| commitment | hands | net chips |
|---|---|---|
| <20% | 314 | +47 |
| 20-40% | 3 | −19 |
| 40-60% | 2 | +244 |
| **≥60%** | **18** | **−484** |

Within that 18 we **won 2 and lost 16 — an 11% win rate**. Under a fair coin that is about
a 1-in-1000 result: we are not unlucky in those spots, our equity model badly underrates
the opponent's big bets. Every disaster this event has that shape — a 13 against a
community 7, a 2 against a 1, a 12 into a shove, a 7 shoved on a contested rule.

`CALL_RISK` 0.20 → **0.55** and `RAISE_RISK` 0.18 → **0.40**. The term is
`RISK × (chips in ÷ stack)`, so it is negligible on an ordinary call and heavy on one that
plays for a stack; a hand that cannot lose stays exempt. Replayed over all 502 real logged
decisions it changes 23, cutting 7 of the 16 losers for a net **+433 chips**.

**This is shipped against the simulator's advice**, and that deserves recording. The sim
says the change costs ~50 points; it said the same about a stack ceiling earlier. But the
sim has been wrong about live results repeatedly — it rated the build that scored 25/400 at
roughly 300 — because its invented opponents get their chips in far worse than the real one
does. Against a 42% per-leg baseline that cannot reach 400 anyway, a measured risk backed
by 337 real hands beats a synthetic estimate.

**How to tell quickly whether it worked:** watch amaranth, verdigris and obsidian. If their
deltas move from −170 toward break-even, the change is doing its job even if the score has
not moved yet — those three legs are the entire gap between 100 and 400.
