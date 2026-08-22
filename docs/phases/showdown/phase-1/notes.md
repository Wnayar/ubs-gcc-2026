# SHOWDOWN — Phase 1: First Contact

- **PDFs:** `../guide.pdf` (the shared rules, in force for *every* SHOWDOWN phase)
  and `statement.pdf` in this folder — see "Missing file" below.
- **Endpoints required:** `POST /move` (and `GET /health`, optional but recommended —
  we already had it)
- **Submitted to controller:** yes — attempt 1 on 2026-08-22, match `phase1-seed1382113882`
- **Score:** **0** on attempt 1 (chip delta −198). Root-caused and fixed; see "Failed test cases" below.

> **Numbering:** the challenge's own "Phase 1" is *not* this repo's phase 1 (that was
> the `/square` practice task). SHOWDOWN gets its own folder tree — `docs/phases/showdown/`
> — because its phases 2-4 all extend the same `/move` endpoint, and because a second
> challenge (Kan Cheong Delivery Driver) landed the same morning also calling itself
> phase 3. Router is `app/routers/showdown.py`, not `phaseN.py`, for the same reason.

## Missing file

`statement.pdf` in this folder was overwritten before it was committed: the SHOWDOWN
Phase 1 PDF was moved here while the parallel Kan Cheong work was writing its own
`statement.pdf` into the same `docs/phases/phase-3/` path, and the original in
`docs/entry-challenge/` had already been moved away. **Re-save it** from
<https://showdown-gcc2026-8096557b5962.herokuapp.com/1>. Nothing below was lost —
the whole page is transcribed in "What phase 1 asks" — but the PDF itself needs
re-downloading before this folder is complete.

## What phase 1 asks

Transcribed from the phase 1 page:

> One-on-one against one of our bots. **100 hands**, one match per attempt. `table_rule`
> reads `standard` the whole way through.
> **Clear:** finish with a chip delta of **+10 or better** → **300 points**.
> That is the whole phase — everything else works exactly as the main guide describes.
> One thing to expect: with no cap on bet sizes, results swing hard from attempt to
> attempt. Only your best attempt counts, so don't rewrite everything after one bad run.

So the bar is low (+10 over 100 hands) and **retries are free** — only the best attempt
counts. That argues for a strategy with a high *probability of clearing*, not a high
mean, and against anything that risks busting (a bust is a flat −200 and ends the match).

## The game (from guide.pdf)

- Heads-up. Both start with **200 chips**. Blinds **1 / 2**. Score = `chip_delta` vs the
  starting 200. Stack hits 0 → busted, out for the rest of the match, chip delta −200.
- Each player is dealt one secret number **1–13**, drawn independently (so both players
  holding the same number is common). One shared **community number**, same deal.
- `pre_reveal` betting → community number revealed → `post_reveal` betting → showdown.
- **Who wins:** your number == community number is a **pair**, and any pair beats any
  non-pair. Otherwise the higher number wins. Identical results split the pot.
- **Button** (`button_seat`) alternates every hand: pays the small blind (1), acts
  **first** pre-reveal and **last** post-reveal. The other seat pays 2 and acts last
  pre-reveal, first post-reveal. *The order reverses between the two rounds.*
- `legal_actions` is **authoritative** — reply with one of those. `fold` only appears
  when someone has bet at you.
- `bet`/`raise` need `amount`, which is the **total you will have put in for that
  betting round**, not the increment ("raise *to* 24, not *by* 24"), and must sit inside
  `[min_raise_to, max_raise_to]`. Out of range is **not clamped** — it is an illegal move.
  Omit `amount` for `check`/`call`/`fold`.
- No limit on bet size; your stack is the ceiling.
- **5 second** budget, HTTP 200. A timeout, bad response, illegal action or bad amount is
  **substituted with `check`** (or `fold`), and **five in a row forfeits the match**.
  `/move` is **never retried**, so it must be fast and side-effect-free.
- `players` is a list in seat order and we are always in it as `"you"`. `amount` in action
  logs is that seat's round total after the action, absent for check/fold; forced bets
  never appear as actions (read `bet_this_round`). **Ignore unrecognised fields** — they
  add fields during the event and never remove them.

## Worked example

The guide's one fully worked request is transcribed verbatim as `GUIDE_EXAMPLE` in
`tests/test_showdown.py`. It gives **no worked reply**, so the only example-derived
assertion is the guide's own reading of the spot: holding a 3 against a community 5,
facing 18 into a pot of 32 — "no pair, no straightforward call". We fold it (19% equity
against 36% pot odds).

## The maths (verified by brute force in tests)

Against an opponent holding a uniformly random number, with splits counted as half a pot:

| | equity |
|---|---|
| pre-reveal, holding `n` | `(11n + 7.5) / 169` |
| post-reveal, `n == c` (a pair) | `12.5 / 13` ≈ 0.96 |
| post-reveal, `n != c` | `(#{m < n, m != c} + 0.5) / 13` |

Pre-reveal equity runs 0.11 (holding 1) to 0.89 (holding 13), and **7 is exactly 50%**.

## How the bot plays (`app/showdown.py`)

1. **Equity vs the opponent's *range*, not vs random.** Uniform is the right prior only
   until the opponent puts chips in. `RANGE_LADDER` narrows the numbers we credit them
   with by how many times they have bet/raised *this round* (1 → 4 → 7 → 9 → 10), plus one
   step if the bet is bigger than the pot it was aimed at. `RANGE_TRUST = 0.85` blends
   that read with the uniform figure, so a bluffer can't fold us off everything.
2. **Stack-risk pricing.** The equity we demand rises with the share of our stack going in
   (`RAISE_RISK`, `CALL_RISK`) — our read is least reliable exactly when the opponent is
   happy to play for stacks.
3. **A cap on raising wars.** A *second* raise in the same betting round needs
   `RERAISE_EQ = 0.82` effective equity, not the ordinary `RAISE_EQ = 0.72`.
4. Value-bet above `VALUE_BET_EQ`, thin-bet above `THIN_BET_EQ`, call when effective
   equity beats pot odds plus a margin, and bluff `BLUFF_RATE = 10%` of the time with a
   hopeless hand — priced by the pot, never for more than half the stack.
5. Bluff randomness is a **hash of `match_id` + hand + round + action count**, not `random`
   — reproducible in tests and replays, unpredictable to the opponent, and stable if a
   `/move` were ever duplicated.

Points 1–3 are the whole difference between busting and not. The first draft used
vs-random equity with no cap and busted **48–61%** of matches against disciplined
opponents: it would hold a 12 pre-reveal, keep re-raising on its 83% vs-random equity,
and get stacked by a 13. See `docs/decisions.md`.

## Simulation results (`tools/simulate.py`, 4000 matches × 100 hands, seats alternated)

Post-fix, on the **corrected** simulator (uncapped `to_call`, plus the `gaston`
opponent reconstructed from the live log):

| opponent | mean Δ | median | P(Δ ≥ +10) | P(bust) |
|---|---|---|---|---|
| station (never folds) | +172.3 | +198 | 100% | 0.0% |
| rock (tight/aggressive) | +142.9 | +200 | 87% | 1.5% |
| maniac (bets huge, always) | +194.6 | +200 | 99% | 1.1% |
| sane (equity + pot odds) | +143.5 | +200 | 90% | 0.9% |
| gaston (jams pairs, bluff-shoves) | +155.8 | +200 | 89% | 8.9% |
| random legal moves | +178.1 | +200 | 95% | 4.4% |

**Worst case ≈ 87% chance of clearing per attempt**, and retries are free. Gaston still
carries the highest bust rate (8.9%) — he is the archetype that beat us, and calling his
shoves with a high card is the remaining variance.

Thresholds come from `--sweep` (one knob at a time, ranked on worst-case clear rate).
`PAIR_GAIN`, `PAIR_MAX` and `RANGE_TRUST` all sit on a plateau where the differences are
inside sim noise at that sample size, so they were left at their principled values rather
than tuned to the last percent against opponents we invented.

## Assumptions we made

Worth raising with the challenge developers:

1. **`pot` includes the bet we are facing.** The guide's example has `pot: 32` with
   `to_call: 18` after "seat 1 bet 18 into a pot that now holds 32", so pot odds are
   `to_call / (pot + to_call)`. If `pot` were exclusive of the live bet, every call
   threshold is slightly off.
2. **We never return a non-200.** A malformed body gets a legal action rather than the
   422 it would normally deserve, because the guide says a bad response is substituted
   and five in a row forfeit the match. This is deliberately *unlike* our other phase
   endpoints — flagged since "security and reliability are scored".
3. **`min_raise_to`/`max_raise_to` are always right**, including the "both equal" all-in
   case. We clamp into that window and never compute our own legality.
4. **Ties split evenly**, and we treat a split as half a pot when pricing decisions.
5. **The opponent is not adaptive within a match.** We keep a 10% bluff rate as cheap
   insurance, but we do not model them adjusting to us. The sim says bluffing costs about
   1.5 chips of mean — it is bought as unexploitability, not as EV.
6. **`recent_hands` is unused.** It carries the opponent's shown numbers and full action
   logs — enough to actually profile them (how often they fold to a bet, how wide they
   raise). That is the obvious phase-2 upgrade; phase 1's bar did not need it.
7. **The endgame tilt is unproven.** `PROTECT_TILT` / `CHASE_TILT` shift thresholds in the
   last 12 hands to protect a banked +10 or chase a shortfall. It is the right idea for a
   target-based score, but the simulation **cannot distinguish it from noise** (83% vs 84%)
   because our sim usually wins by busting the opponent long before the endgame. Do not
   trust it; do not tune it on this evidence.

## Failed test cases and what fixed them

**Attempt 1 (match `phase1-seed1382113882`) scored 0 — chip delta −198.**

The protocol side was clean: 135 `/move` calls, every one HTTP 200 in under 1.5 ms,
and **zero illegal actions or out-of-range amounts** (re-validated from the live
`GET /debug/requests` log). We were **+44 up at hand 13**. Three hands took the match,
and two of them were outright bugs, not variance:

| hand | what happened | cost |
|---|---|---|
| 19 | held **13** on community **7** — a high card, *not* a pair — raised to 41, then called a 117 shove with our last 168 | −164 |
| 55 | held **11** on community **11** — a **pair, 96% to win** — and **folded** it with 24 behind facing `to_call: 202` into a 376 pot | −87 + a ~200 pot forgone |
| 72 | held **5** on community **5** — again a **pair** — and **folded** again | −34 |

Three defects, all now covered by regression tests transcribed from the live log
(`test_hand_19_*`, `test_hand_55_*`, `test_hand_72_*`, `test_a_call_never_risks_more_than_our_stack`):

1. **`to_call` is not capped at our stack.** The guide says an opponent may bet more
   than we can cover and we "can still call for everything you have". The risk term
   was `CALL_RISK × (to_call / stack)` — with `to_call` 202 and a stack of 24 that is
   **1.68**, larger than any possible equity, so we folded a hand that cannot lose.
   Fixed by pricing everything off `risked = min(to_call, stack)`.
2. **A pair was treated as a risky hand.** "Any pair beats any non-pair" and identical
   results split, so holding the pair *every* opponent number either loses or ties —
   there is no downside at all. The stack-risk floor and the raising-war cap both exist
   to stop us getting stacked and are simply wrong here. `_cannot_lose()` now exempts
   the pair from both, and never folds it at any price.
3. **The range read modelled the wrong threat.** `RANGE_LADDER` narrows the opponent to
   *high numbers*, but post-reveal the only hand that beats a high card is the community
   number itself. A shove over our raise is overwhelmingly that pair. `_pair_weight()`
   now moves that mass from its 1/13 prior up to `PAIR_MAX` with the size and count of
   their raises, which turns hand 19 from a call into a fold.

**Why the simulator missed all of it:** `tools/simulate.py` capped `to_call` at the
player's stack, so the state that caused defects 1 and 2 *could not occur* in tuning.
Fixed, and a `gaston` opponent reconstructed from the live log (jams pairs, re-raises
big, bluff-shoves ~30%) was added — the archetype the original five lacked.

Measured on the corrected simulator, 1500 matches, old code vs new:

| opponent | P(clear) old → new | P(bust) old → new |
|---|---|---|
| rock | 81% → **87%** | 6.3% → **1.6%** |
| sane | 82% → **90%** | 5.3% → **0.9%** |
| gaston | 81% → **89%** | 17.3% → **9.2%** |
| random | 90% → **95%** | 6.9% → **4.5%** |
| **worst case** | **81% → 87%** | |

Honest caveat: at a modelled ~84% clear rate, scoring 0 once is a ~1-in-6 event and
would not on its own prove anything was broken. The pair folds are what make it a bug
report rather than a bad beat — folding a 96% hand for 24 chips into a 376 pot is
indefensible at any variance.
