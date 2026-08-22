# Ghost Chains — **Phase 3 of 3**, "Value Signal"

> Phase 1 ("Follow the Money") lives in `docs/phases/phase-3/notes.md`, Phase 2
> ("Identity Signal") in `docs/phases/ghost-chains/phase-2/notes.md`. Everything in
> both still applies: **a Phase 3 evaluation re-tests every Phase 1 and Phase 2
> requirement in the same run.**

- **PDF:** `statement.pdf` in this folder (from
  <https://ghost-chains-0fdb9aeda564.herokuapp.com/phase/3>, 11 pages)
- **Endpoints required:** unchanged — `GET /ghost-chains/health`,
  `POST /ghost-chains/reset`, `POST /ghost-chains/transactions`
- **Submitted to controller:** no
- **Score:**

## What is new in Phase 3 (page 7)

Phase 3 introduces **no new mechanical requirements**. It activates the one *required*
field Phases 1 and 2 accepted and deliberately ignored: `amount`.

Briefing card, verbatim: **"Follow the trail of value that leaves no trace."**

> Some networks go dark: no IP, no device fingerprint. Just the money, moving in ways
> that betray its origin. That is what we call ghost chains.
>
> Layering often pushes value along a chain where each hop keeps most of the prior
> amount. A single amount means little alone; along an inferred flow, the trail of
> amounts can confirm or contradict a pattern.
>
> Assign a higher risk score when value evidence increases combined suspicion.

### Core Principle (verbatim, page 7)

> `amount` forms a value signal inside structurally inferred flow segments. Do not
> blindly aggregate amounts across unrelated branches without structural segmentation.
>
> **Combining with identity.** Identity signals from Phase 2 remain active in Phase 3.
> In particular, an identity attribute that vanishes mid-flow on a connected path
> (present on earlier legs, absent on a later leg) is a distinct evasion pattern —
> treat the absence as an observable state, not merely a missing value, when weighing
> the flow.

### Objectives (page 7)

- Combine value scoring with structural and identity signals
- Interpret amount progression inside inferred flow segments

## The four worked examples (verbatim, pages 8–9)

The last transaction of each sequence is the one being scored. Amounts use a single
synthetic currency unit.

### Example 1 — Consistent Value Decay
1. Meridian Holdings → Apex Logistics (`10000`)
2. Apex Logistics → Cascade Payments (`9910`)
3. Cascade Payments → Horizon Capital (`9820.81`)
4. Horizon Capital → Nimbus Trading (`9732.42`)

> A single directed path carries a consistent progressive value reduction. Each step
> retains slightly less than the previous amount.

### Example 2 — Competing Flow Hypotheses
1. Meridian Holdings → Apex Logistics (`10000`)
2. Apex Logistics → Cascade Payments (`9800`)
3. Apex Logistics → Sterling Bridge (`5000`)
4. Cascade Payments → Horizon Capital (`9700`)
5. Sterling Bridge → Oakridge Imports (`4900`)

> Two branches from Apex Logistics each carry their own internally consistent value
> progression. The graph supports two independent flow interpretations; no single
> global value ratio applies across the full graph.

### Example 3 — Value Trajectory Reversal
1. Meridian Holdings → Apex Logistics (`10000`)
2. Apex Logistics → Cascade Payments (`9950`)
3. Cascade Payments → Horizon Capital (`9800`)
4. Horizon Capital → Nimbus Trading (`9950`)

> A structurally continuous path Meridian Holdings → Apex Logistics → Cascade Payments
> → Horizon Capital → Nimbus Trading exists. The amount at Horizon Capital → Nimbus
> Trading (`9950`) exceeds the preceding step Cascade Payments → Horizon Capital
> (`9800`), reversing the prior reduction along the same path.

### Example 4 — Convergence of Separate Value Paths
1. Meridian Holdings → Apex Logistics (`10000`)
2. Apex Logistics → Cascade Payments (`9800`)
3. Apex Logistics → Sterling Bridge (`5000`)
4. Cascade Payments → Horizon Capital (`9700`)
5. Sterling Bridge → Horizon Capital (`4950`)

> Two independent branches from Apex Logistics arrive at the same destination (Horizon
> Capital). The graph now contains structural convergence, while the value trajectories
> that arrive at Horizon Capital remain distinct. Structural and value observations
> must therefore be considered together when interpreting the resulting flow.

### Expected Ordering (page 9, verbatim) — **the one hard requirement in three phases**

> - **Example 1 should receive the lowest risk score of the four.** Consistent value
>   decay along a single path represents the characteristic layering pattern rather
>   than a deviation from it.
> - **Example 3 should receive the highest risk score of the four.** A value trajectory
>   reversal against structural continuity is a direct contradiction: the expected
>   degradation pattern is violated while the structural path remains intact.
> - Examples 2 and 4 test value continuity under qualitatively different conditions —
>   divergence and convergence respectively — and are not directly comparable in risk.

Phases 1 and 2 both said outright that their examples "do not define a strict risk
ordering between scenarios". This one does, and it is by far the most useful thing in
the document: it is a testable, falsifiable statement about our own output.

## Cross-signal examples (pages 10–11, no expected ordering given)

Copied verbatim; all three are pinned as tests, asserting only what the statement
asserts — that the signals are *simultaneously* present, not how they rank.

**Phase 1 and Phase 2** — `M→A` (`dev_ios_7f3a91`), `A→C` (`dev_ios_7f3a91`),
`C→H` (`dev_android_c2e4b8`), `H→M` (`dev_android_c2e4b8`).
> Transaction 4 closes a directed cycle […] The device fingerprint changes at Cascade
> Payments → Horizon Capital. The cycle is completed on device `dev_android_c2e4b8`,
> while earlier edges used `dev_ios_7f3a91`.

**Phase 1 and Phase 3** — `M→A` (10000), `A→C` (9800), `C→H` (9700), `H→A` (9850).
> Transaction 4 creates a return path […] The amount for Horizon Capital → Apex
> Logistics (9850) exceeds the preceding Cascade Payments → Horizon Capital edge (9700).

**Phase 2 and Phase 3** — `M→A` (10000, `10.0.0.1`), `C→H` (10000, `10.0.0.1`),
`A→N` (9800, `10.0.0.1`), `H→N` (10100, `10.0.0.2`).
> Transactions 1–3 share a network address across two structurally disconnected chains
> […] Transaction 4 creates structural convergence at Nimbus Trading […] It carries a
> different network address […] The amount for Horizon Capital → Nimbus Trading (10100)
> exceeds Cascade Payments → Horizon Capital (10000).

## Diagnostics vocabulary (page 11)

Phase 3 evaluations can emit `STRUCTURAL_DEVIATION`, `TEMPORAL_DEVIATION`,
`IDENTITY_DEVIATION` and — new this phase — **`VALUE_FLOW_DEVIATION`** ("disagreement
detected in the evaluation of value signals") and **`CROSS_SIGNAL_DEVIATION`**
("disagreement detected under scenarios involving multiple simultaneous signal types").

## The reading that decides the whole model

Example 1 is a **textbook layering chain** — four hops each keeping 99.1% of the last,
exactly the pattern the briefing card describes — and the statement requires it to
score **lowest**. That is not an oversight; the statement explains it: consistent decay
"represents the characteristic layering pattern **rather than a deviation from it**".

So the value signal does **not** score layering. It scores the trail of amounts
**contradicting** the flow it sits inside. Confirmation is worth nothing; contradiction
is worth a great deal. Every design choice below follows from that one sentence.

The second consequence is about magnitude, and it collides head-on with the discipline
Phases 1 and 2 arrived at. Examples 1 and 3 are the *same graph* — same entities, same
order, same timings — so only value can separate them, and the structural model scores
both at 0.157. Example 4 is a structural **convergence**, scored 0.382. The statement
requires Example 3 above Example 4: **a whole band apart, in the wrong direction.**

Phase 2 closed with the rule "structure chooses the band, identity orders within it,
and nothing identity can say promotes a transaction past a structurally hotter one" —
and that rule is why Phase 2 stopped reordering Phase 1's ranking. Phase 3 cannot obey
it and satisfy its own statement. The resolution is to split the value signal in two
along the line the statement itself draws:

| | statement's words | what it may do |
|---|---|---|
| `reversal` | "a **direct contradiction**: the expected degradation pattern is violated while the structural path remains intact" — and Example 3 *must* outrank Example 4 | **changes the band** |
| `incoherence` | Examples 2 and 4, "not directly comparable in risk" — the statement declines to rank them | orders **within** the band, like identity |

A reversal is allowed across a band because it is a claim about the *structure*: an
intact structural path whose value contradicts it. A shared address is not — it is "not
automatic proof of risk on its own" and can exist with no structure at all. That is the
whole justification, and it is the statement's, not ours.

## Our model — value in band placement, everything else within the band

`app/ghost_value.py` holds the whole of Phase 3; `app/routers/phase3.py` calls it
alongside `IdentityIndex`. The structural function is **unchanged for the third phase
running**.

### The inferred flow segment

For a transaction from `u` with amount `a` at time `t`, walk backwards from `u`: take
the most recent leg that had arrived at `u` by `t`, then the most recent leg that had
arrived at *that* sender by *its* time, and so on, up to `MAX_SEGMENT = 6` legs. Each
hop is no later than the one it feeds, so the segment is a path money could actually
have travelled — the same temporal discipline the structural traversals use.

Following **only the latest leg into each entity** is what "structural segmentation"
means here. The trail is one inferred path, never a sum over branches — the statement's
"do not blindly aggregate amounts across unrelated branches" taken literally. In
Example 2 the segment feeding `S→O` is `M→A→S` and the sibling branch `A→C→H` never
enters it, pinned by `test_value_is_not_aggregated_across_unrelated_branches`, which
rewrites the sibling branch's amounts to 3 and 1 and asserts the score does not move.

### The two value signals

With amounts `a₀ … aₘ` along the segment and `a` on the transaction, the retention
ratios are `rᵢ = aᵢ / aᵢ₋₁`.

| signal | fires when | weight |
|---|---|---|
| `reversal` | the final ratio exceeds 1 — value **grew** along a structurally continuous flow | 0.85 · established · (0.55 + 0.45 · sat(r−1, 0.05)) |
| `incoherence` | the ratios disagree with each other — the trail does not confirm one progression | 0.45 · (max r − min r) / max r |

`reversal` is deliberately near-**qualitative**. The statement describes it as an event,
and its own reversals are 1.0–1.6% excesses, which a magnitude-proportional signal would
score as almost nothing. So any genuine excess carries 55% of the weight and its size
only refines the rest.

**`established` is the selectivity that makes it usable on real data.** The statement
says "reversing **the prior reduction** along the same path" — a reversal needs a
reduction to reverse. `established` is the fraction of the earlier ratios that were
reductions: 1.0 for a chain that has been shedding value at every hop and then grows
(Example 3), lower for a trail that was already erratic. With no earlier ratio at all
there is nothing established either way, and the statement still calls a lone step up a
value observation — its Phase 2 + Phase 3 cross-signal example is exactly that shape —
so that counts at half strength. On the real graded stream this is the difference
between a signal that fires at full strength on 39% of transactions (a coin flip, on
amounts that are essentially random) and one that concentrates on the layering shape the
statement describes.

`incoherence` needs **two** ratios to exist, so a first onward hop carries no value
signal however much of the prior amount it keeps — "a single amount means little alone".

### How the signals combine

```
promoted = structural + (value_ceiling(structural) - structural) · 0.9 · reversal
weak     = 1 - (1 - identity) · (1 - incoherence)
score    = promoted + (band_ceiling(promoted) - promoted) · 0.9 · weak
```

`value_ceiling` is `VALUE_PROMOTE_BANDS = 2` steps up the same ladder structure uses;
`band_ceiling` is one step, as Phase 2 shipped it. Identity and an incoherent trail
combine as independent dimensions, the same form Phase 2 uses for its two attributes.
Both stages are **upward-only**.

`W_INCOHERENCE = 0.45` is sized against the band architecture rather than guessed.
Example 2's structural score sits 0.016 *below* Example 1's — its trail is a hop shorter
— and Example 1 must be lowest of the four, so incoherence has to buy more than that gap
inside the onward band. A 0.9 share of the room left to `TIER_FAN` puts the break-even at
0.223, which is why the 0.22 that worked under the pre-merge headroom lift (where the
same evidence bought four times as much) no longer clears it.

### Scores our model gives the statement's examples

| example | structural | with value |
|---|---|---|
| 1 — consistent decay along a single path | 0.157 | **0.157** |
| 2 — divergence, competing hypotheses | 0.141 | **0.173** |
| 3 — value trajectory reversal | 0.157 | **0.470** |
| 4 — convergence of separate value paths | 0.382 | **0.416** |

**0.157 < 0.173 < 0.416 < 0.470** — Example 1 lowest, Example 3 highest, exactly as
required, with Examples 2 and 4 between them and never asserted against each other.

Holding the structure fixed (`M→A` 10000, `A→C` 9900, then a third leg `C→H`):

| third leg | ratio | score |
|---|---|---|
| keeps 99% — consistent decay | 0.9900 | 0.141 |
| identical amount | 1.0000 | 0.142 |
| +0.005% — below the reversal tolerance | 1.0001 | 0.142 |
| keeps 40% — the trail breaks | 0.4000 | 0.180 |
| +1% — a reversal, the statement's own scale | 1.0100 | **0.448** |
| +10% | 1.1000 | 0.566 |
| triples | 3.0000 | 0.667 |

The cross-signal examples:

| example | structural | all signals |
|---|---|---|
| P1+P2 — cycle closed on a changed device | 0.721 | **0.729** |
| P1+P3 — return path whose amount reverses | 0.733 | **0.869** |
| P2+P3 — convergence, changed address, raised amount | 0.135 | **0.290** |

### The identity change Phase 3 asks for

Phase 3's Core Principle promotes the vanished identifier from Phase 2's "**can** be a
signal" to "a **distinct evasion pattern** — treat the absence as an observable state,
not merely a missing value". `DROP_SHARE` in `app/ghost_identity.py` therefore rises
**0.75 → 0.90**. Nothing else in the Phase 2 model moves.

On `M→A→C` tagged `dev_ios_7f3a91` with a third leg `C→H`:

| third leg | score |
|---|---|
| keeps the device | **0.173** |
| drops the device | 0.166 |
| switches to another device | 0.163 |
| no identity anywhere | 0.141 |

Deliberately dropping an identifier now outranks merely changing it, which is what
"distinct evasion pattern" argues for, while a flow that *keeps* its identifier still
tops both — Phase 2's `test_dropped_identifier_stays_below_a_flow_that_keeps_it` passes
unchanged.

## Measured against the real graded stream

`amount` is a **required** field, so unlike identity — which never appeared in the
Phase 1 evaluation at all (0 of 109) — the value signal fires on the graded stream.
Replayed against `docs/phases/ghost-chains/logs/2026-08-22-graded-runs.json`:

| | Phase 1 run | Phase 2 run |
|---|---|---|
| reversal fires on | 36 / 109 | 29 / 109 |
| incoherent trail on | 56 / 109 | 46 / 109 |
| scores moved | 70 | 55 |
| band crossings | 29 | 22 |
| **demotions** | **0** | **0** |
| mean score | 0.369 → 0.455 | 0.351 → 0.428 |
| Spearman vs. no value | 0.929 | 0.887 |

This is a change of the same size as the decay-free lever (30 crossings, measured
~neutral), and in the same direction: **upward-only**. Under-scoring a reference-hot
transaction was measured at ~4× the cost of over-scoring a cold one, so all of it is
spent in the cheap direction. `test_the_value_signal_is_upward_only_on_the_graded_stream`
pins the property against the archive for both runs; if a later edit makes it demote
anything, that reasoning no longer covers the edit.

It is worth being blunt about the residual risk: this is far too much movement to ship
on the strength of four worked examples alone, and the properties above are what stand
in for a reference we cannot see.

## `STRUCTURAL_DEVIATION: High, TEMPORAL_DEVIATION: High`

The last graded feedback, and it is worth reading carefully because two things about it
are odd.

**It names no value dimension.** Phase 3 can emit `VALUE_FLOW_DEVIATION` and
`CROSS_SIGNAL_DEVIATION`, and the build being graded had no value model at all. Two
readings:

1. **It was not a Phase 3 evaluation** — a Phase 1/2 run, where those categories do not
   exist. Then `TEMPORAL_DEVIATION: High` points squarely at the freshest temporal
   change: `DECAY_FREE_BANDS` was flipped ON, removing *every* recency term from band
   placement, and both-High is the exact signature the Phase 1 notes record from the
   era when the router ignored time along paths. That flag is one line
   (`app/routers/phase3.py`), and Phase 3 is now pinned to work either way — see below.
2. **It was a Phase 3 evaluation** and a missing value model surfaced as structural
   disagreement, because value evidence changes *which* transactions the reference
   ranks hot without being a category we were failing to emit. This branch is the fix.

These are discriminable, and cheaply: deploy this branch and re-run. If
`TEMPORAL_DEVIATION` stays High with a value model in place, reading 1 stands and
`DECAY_FREE_BANDS` is the next lever to flip back. If it clears, reading 2 was right.

**We did not flip the flag here.** It is Phase 1's lever, it was shipped with
leaderboard evidence behind it (run 7 priced demoting stale cycles at −19), and this
challenge's own method is one lever per evaluation — spending two at once is what made
runs 6 and 7 unattributable. What Phase 3 owes that decision is not to constrain it, so
`test_the_required_ordering_holds_whichever_way_the_decay_flag_is_set` pins the
statement's required ordering under **both** settings.

## Where the required ordering stops holding

The statement gives its examples as ordered sequences with **no timestamps**, so the
ordering has to survive whatever spacing the grader uses. Measured, streaming each
example one transaction per request:

| gap between transactions | decay-free (shipped) | with decay |
|---|---|---|
| 0 min (all one instant) … 30 min | ✅ | ✅ |
| 60 – 240 min | ✅ | ❌ |
| 480 min and beyond | ❌ | ❌ |

Decay-free is materially more robust here, which is an argument for that flag
independent of anything the leaderboard has said. Where it fails, it fails because by
Example 2's fifth transaction the 24-hour window has expired the head of the chain, the
trail feeding `S→O` is one leg long, and one leg has no ratios to disagree. Expired
transactions "must not influence scoring", so the scenario has genuinely stopped being
the scenario. We accept it.

## Measured cost

Value scoring adds a bounded backward walk — at most `MAX_SEGMENT = 6` legs, one
`bisect` each — and no new traversal. Random-graph worst case on this laptop, flat
amounts versus every transaction carrying a distinct amount:

| graph | flat amounts | varied amounts |
|---|---|---|
| 200 entities / 2 000 transactions | 0.270 ms/tx | 0.263 ms/tx |
| 1 000 entities / 5 000 transactions | 0.073 ms/tx | 0.069 ms/tx |

The difference is inside run-to-run noise: the walk is dominated by the three temporal
traversals Phase 1 already runs. Memory is one `(when, seq, amount, sender)` tuple per
live leg, expiring on the same half-open 24-hour window as the graph.

## Assumptions we made

1. **Consistent decay is worth exactly zero, not a small negative.** The statement
   requires Example 1 lowest of the four but never says value evidence should *lower* a
   score, and only ever says to "assign a higher risk score when value evidence
   increases combined suspicion". Example 1 is lowest because everything else has some
   deviation, not because clean layering is exonerating. Value therefore only ever
   adds — the same call Phase 2 made, and the same measured 4:1 penalty asymmetry
   behind it. Pinned by `test_value_evidence_never_lowers_a_structural_score`.
2. **The expected pattern is a roughly constant retention ratio slightly below 1**, and
   the signal is departure from it. "Each hop keeps most of the prior amount."
3. **A branch split is a value deviation, mildly.** Example 2's `A→S` keeps 50% of what
   reached Apex, which is not "most of the prior amount", and the statement calls the
   result "competing flow hypotheses". This is the *only* observation available to
   separate Example 2 from Example 1, and the statement requires them separated. It
   never crosses a band, so it can only ever reorder transactions the structural model
   had already placed together.
4. **Only the most recent leg into each entity is followed.** Reconstructing every
   possible flow segment and scoring the best or the average would be a different
   model; the statement says to segment structurally, not to enumerate. A transaction
   whose sender received twice can therefore have its trail read through the wrong leg.
5. **The segment is read back at most 6 hops.** Reading further makes `incoherence` a
   statement about the whole graph's history rather than about this flow. The
   statement's own segments are 2–3 hops.
6. **"Exceeds the preceding step" means by more than 0.01%.** Amounts carry fees and
   rounding; a hop arriving a hundredth of a percent higher is an artefact. This sits
   two orders of magnitude below the smallest reversal the statement asks us to detect
   (1.0%). Pinned by `test_a_rounding_artefact_is_not_a_reversal`.
7. **Zero, negative, infinite and NaN amounts are valid transactions that carry no
   value signal.** `amount` is required and the graph edge is real, so Phase 1 scores
   them exactly as before; but there is no progression to read from them, so they end
   the value trail rather than poisoning the arithmetic of everything downstream. (Left
   unguarded, an infinite amount produced a NaN risk score that only avoided reaching
   the wire because `min(1.0, nan)` happens to return 1.0.)
8. **Value evidence expires with the window**, exactly as identity does. An amount from
   25 hours ago is not part of any flow any more.
9. **A leg later in event time than the transaction being scored is invisible to it** —
   the same rule Phase 2 adopted after `TEMPORAL_DEVIATION` appeared in three
   evaluations. Scoring on evidence from the future is the mistake that cost us there.
10. **A value reversal may cross a band and nothing else may.** This is the one place
    Phase 3 overrules the discipline Phase 2 closed on, and it is the statement that
    forces it: Example 3 must outrank Example 4, which is a band away. A reversal
    earns the exception because it is a claim about the structure itself — an intact
    structural path whose value contradicts it — while a shared address "does not
    independently establish risk". Two bands (`VALUE_PROMOTE_BANDS`) is what puts
    Example 3 clear of Example 4 at every spacing tested; one band leaves it below.
11. **A reversal is scaled by how much prior reduction there was to reverse**
    (`established`), and half-weighted when there is no prior ratio at all. Without
    this the signal fires at full strength on 39% of the real graded stream, because
    roughly half of any random sequence of amounts steps up. The statement's phrase is
    "reversing *the prior reduction* along the same path".
12. **We do not model amount conservation at a node.** Apex Logistics emits 14 800 from
    a 10 000 inflow in Examples 2 and 4, which is arguably a value anomaly in its own
    right, but the statement frames branching as something to *segment around* rather
    than to flag, and the split already reaches the score through `incoherence`. Adding
    a second overlapping term would be tuning, not modelling.

## Clarifications from challenge developers

- Q: Example 1 is described as "the characteristic layering pattern" yet must score
  lowest of the four. Confirming: the value signal scores *deviation from* an expected
  decay, not the presence of layering itself? → A: …
- Q: Example 3 must outrank Example 4, a structural convergence. Is value evidence
  expected to outweigh a structural band step in general, or only in this pairing? → A: …
- Q: In Example 2, is the 50% drop at `A→S` itself the value evidence, or is the branch
  split expected to be segmented away entirely? → A: …
- Q: When an entity has received on several legs, which leg defines the inferred flow
  segment for its next outgoing transaction? → A: …

## Failed test cases and what fixed them

-
