# Ghost Chains — **Phase 2 of 3**, "Identity Signal"

> Phase 1 ("Follow the Money") lives in `docs/phases/phase-3/notes.md` — written
> before CLAUDE.md switched to challenge-named folders. Everything in it still
> applies: **a Phase 2 evaluation re-tests every Phase 1 requirement.**

- **PDF:** `statement.pdf` in this folder (from
  <https://ghost-chains-0fdb9aeda564.herokuapp.com/phase/2>, 10 pages)
- **Endpoints required:** unchanged — `GET /ghost-chains/health`,
  `POST /ghost-chains/reset`, `POST /ghost-chains/transactions`
- **Submitted to controller:** yes
- **Score:** ~368/400, same as Phase 1. Graded stream archived at
  `docs/phases/ghost-chains/logs/2026-08-22-graded-runs.json`.

## What is new in Phase 2 (pages 7–8)

Phase 2 introduces **no new mechanical requirements**. It activates the two optional
fields that Phase 1 already accepted and ignored:

- `ipAddress` — network address used to initiate the transaction
- `deviceId` — device identifier used to initiate the transaction

Briefing card, verbatim: **"Look for shared infrastructure behind the surface."**

> Coordinated financial networks often share underlying infrastructure. Transactions
> that look unrelated on the graph may share a network address or device — a hint of
> common control.
>
> A single shared attribute can be coincidence (office Wi-Fi, cloud NAT). When
> identity lines up with structural flow — or the same identity appears across
> disconnected components — treat it as a stronger combined signal.
>
> Assign a higher risk score when identity evidence increases combined suspicion.

### Core Principle (verbatim, page 7–8)

> Optional fields `ipAddress` and `deviceId` contribute an identity signal relative
> to where the transaction sits in the active graph. When both are present, treat
> them as **independent dimensions**.
>
> Shared identity across disconnected components is a distinct coordination hint —
> **not automatic proof of risk on its own**.
>
> **Missing identity on a connected path.** When an identity attribute that appeared
> on earlier legs of a continuous flow is absent on a later leg, the absence itself
> can be a signal: dropping a network address or device identifier mid-path is a way
> to break the trail. Missing fields are normal on unrelated transactions; the
> suspicious case is a consistent flow that stops carrying its identity. Weigh
> absence against the surrounding structure rather than treating every missing field
> as suspicious.

### Objectives (page 8)

- Combine identity scoring with structural scoring
- Tolerate missing identity fields

## The four worked examples (verbatim, pages 8–10)

The statement is explicit: *"These examples show how evidence changes — they do not
define a strict risk ordering between scenarios."* The last transaction of each
sequence is the one being scored.

### Example 1 — Consistent Identity
1. Meridian Holdings → Apex Logistics (`deviceId`: `dev_ios_7f3a91`)
2. Apex Logistics → Cascade Payments (`deviceId`: `dev_ios_7f3a91`)
3. Cascade Payments → Horizon Capital (`deviceId`: `dev_ios_7f3a91`)

> A single directed flow carries a consistent device identifier throughout. No
> identity anomaly exists within this segment.

### Example 2 — Identity Divergence Under Branching
1. Meridian Holdings → Apex Logistics (`dev_ios_7f3a91`)
2. Apex Logistics → Cascade Payments (`dev_ios_7f3a91`)
3. Apex Logistics → Sterling Bridge (`dev_ios_7f3a91`)
4. Cascade Payments → Oakridge Imports (`dev_android_c2e4b8`)

> Two branches extend from Apex Logistics. One branch introduces a new device
> identifier on Cascade Payments → Oakridge Imports. Device `dev_ios_7f3a91` is no
> longer uniform across the full reachable subgraph from Meridian Holdings.

### Example 3 — Identity Shift Mid-Flow
1. Meridian Holdings → Apex Logistics (`dev_ios_7f3a91`)
2. Apex Logistics → Cascade Payments (`dev_ios_7f3a91`)
3. Cascade Payments → Horizon Capital (`dev_android_c2e4b8`)
4. Horizon Capital → Nimbus Trading (`dev_android_c2e4b8`)

> A structurally continuous path M → A → C → H → N exists. The device identifier
> changes at the Cascade Payments → Horizon Capital transition, weakening the
> confidence that a single identity cluster explains the full path. The structural
> relationship between entities remains valid; identity and structural observations
> must be considered together rather than in isolation.

### Example 4 — Shared Identity Across Disconnected Components
1. Meridian Holdings → Apex Logistics (`ipAddress`: `10.0.0.1`)
2. Cascade Payments → Horizon Capital (`ipAddress`: `10.0.0.1`)
3. Oakridge Imports → Sterling Bridge (`ipAddress`: `10.0.0.1`)

> Three transactions share a network address with no structural connectivity between
> their participants. This creates a potential identity relationship between entities
> that is not visible from graph structure alone. Shared network infrastructure may
> indicate coordination, but may also arise from legitimate network aggregation.
> Structural or value-flow evidence from the same components may be required to
> determine the significance of this identity signal.

### Signal Relationships (page 10, verbatim summary)

- Ex. 1 (identity agreement): structural and identity observations **reinforce each
  other** within the segment.
- Ex. 2 (divergence at a branch): the two branches carry different identity evidence,
  and **neither independently characterises** the full reachable subgraph.
- Ex. 3 (disagreement within a continuous flow): both observations are valid and must
  be **weighed together**, not in isolation.
- Ex. 4 (reuse across disconnected components): a potential **cross-structural**
  relationship invisible from structure alone, but it **does not independently
  establish risk**.

## Diagnostics vocabulary (page 10)

Phase 2 evaluations can emit `STRUCTURAL_DEVIATION`, `TEMPORAL_DEVIATION` and — new
this phase — **`IDENTITY_DEVIATION`** ("disagreement detected in the evaluation of
identity signals"). Severity is relative magnitude of disagreement and is computed
dynamically; no absolute scores are ever disclosed.

## Our model — structure picks the band, identity orders within it

`app/ghost_identity.py` holds the whole of Phase 2; `app/routers/phase3.py` calls it
after `structural_score` and combines the two. The structural function is
**unchanged**, and with no identity fields anywhere in the stream every score is
bit-for-bit what Phase 1 returns on its own — the five worked examples and all nine
`hf-` grader probes are pinned by
`test_identity_free_stream_matches_phase_1_baseline`.

For each attribute *k* ∈ {`ipAddress`, `deviceId`} we derive an evidence value
`E_k ∈ [0,1]` from where the transaction sits in the active graph, then:

```
identity = 1 - (1 - E_ip) * (1 - E_device)        # independent dimensions
ceiling  = top of the structural band this score is already in
score    = structural + (ceiling - structural) * BAND_SHARE * identity
```

- **`1 - (1-a)(1-b)`** is the statement's "independent dimensions": two attributes
  agreeing is more than either alone, but neither can saturate the other.
- **The lift is a share of the band, not of the headroom to 1.0.** Phase 1 is a
  ladder of structural bands (`nothing < onward < fan/convergence < return <
  multi-loop`) with continuous signals refining *within* each band, and that
  discipline is the whole reason Structural Consistency holds up in a busy graph.
  Identity is now held to the same rule: at `BAND_SHARE = 0.9` it can claim most of
  the room left in its own band and never the boundary itself, so a fully
  corroborated identity signal on the weakest onward transfer still ranks below the
  weakest convergence that carries no identifier at all. Pinned by
  `test_identity_can_never_move_a_transaction_out_of_its_band`.
- **It still never *lowers* a score** — the Phase 1 post-mortems measured
  under-scoring a reference-hot transaction at ~4× the cost of over-scoring a cold
  one, so disagreement adds less rather than subtracting.
- **A structural 0.0 gets the band below onward flow.** Cross-component reuse with
  no structure behind it is "a distinct coordination hint — not automatic proof of
  risk on its own": it lands strictly above a genuinely isolated pair and strictly
  below the weakest real chain, which is exactly the ordering the statement's
  Example 4 describes. This replaces the old `corroboration` factor, which was
  doing the same job with a second tunable knob.

### The five identity signals

| signal | fires when | weight |
|---|---|---|
| `align` | the value already appears on entities that are on this transaction's own time-respecting flow (upstream of the sender, feeding the receiver, or downstream of it) | 0.45 · sat(n, 2) |
| `pair` | both ends of this transfer have initiated with the value before — common control across the transfer itself | 0.30 |
| `cross` | the value also appears in **other, structurally disconnected** groups; scored on the number of such groups **minus one**, so the second component alone is worth nothing ("a single shared attribute can be coincidence") | 0.55 · sat(g−1, 1) |
| `shift` | the leg that fed the sender carried this attribute with a **different** value | 0.15 · freshness |
| `drop` | this transaction is **missing** the attribute, and the leg that fed the sender carried it | 0.75 · own · (align+pair+cross of the *dropped* value) · freshness |

`drop` is deliberately derived from the evidence the vanished identifier itself
carried, not from a constant. That is the statement's "weigh absence against the
surrounding structure": a four-leg flow that has been tagged with one device all the
way and then stops says a great deal, a single leg that never really carried it says
almost nothing, and a flow that keeps its identifier always outranks one that drops
it (`own` is 1.0 when the sender used to initiate with the value itself, else 0.85,
and the 0.75 share keeps `drop` under the `align` it is derived from).

`sat(x, k) = x / (x + k)`, the same saturating form Phase 1 uses; `freshness` is
`exp(-age / 3 h)`, Phase 1's `TAU_TRAIL`. Weights are summed and clamped to 1.

Grouping for `cross` is a BFS over the window graph restricted to the entities that
carry the value, so the three components of Example 4 count as three and one busy
office subnet counts as one. It is capped at `MAX_GROUPED = 32` entities per lookup,
and an identifier that more than `MAX_SHARED = 256` entities initiate from stops
counting as reuse at all — that is the cloud NAT the statement names, and the cap
also bounds the per-transaction work.

Two guards keep identity from repeating Phase 1's temporal mistakes: every identity
record expires on the graph's own half-open 24-hour window, and a leg that fed the
sender *later in event time* than the transaction being scored is invisible to it.

### Scores our model gives the statement's examples

| example | structural | with identity |
|---|---|---|
| 1 — consistent device along a chain | 0.141 | **0.173** |
| 2 — new device on a branch | 0.140 | **0.161** |
| 3 — device shifts mid-flow | 0.156 | **0.175** |
| 4 — same IP, three disconnected components | 0.000 | **0.020** |
| a 4-leg return, no identity | 0.731 | 0.731 |
| the same return, one device throughout | 0.731 | **0.743** |

Holding the structure fixed (`M→A→C` tagged `dev_ios_7f3a91`, then a third leg
`C→H`), the identity ladder is:

| third leg | score |
|---|---|
| keeps the device | **0.173** |
| switches to another device | 0.162 |
| drops the device | 0.161 |
| no identity anywhere in the chain | 0.141 |

Switching and dropping land close together *here* by arithmetic, not by design: a
switch is a flat small anomaly, while a drop scales with how much the broken trail
was carrying, so on a longer tagged chain the drop pulls clearly ahead and on a
one-leg chain it falls behind (pinned by
`test_a_dropped_identifier_weighs_the_trail_it_broke`).

Example 4 sits above a structurally isolated pair (0.0) and below ordinary onward
flow — a hint, not proof. Under band containment that is now true *by construction*
rather than by arithmetic: with no structure at all, the ceiling is `TIER_ONWARD`,
so Example 4 cannot reach 0.08 however many components share the address
(`test_identity_only_evidence_ranks_below_every_real_flow`).

### What replacing the headroom lift actually changed

Measured on a 96-transaction motif stream shaped like the graded dataset (six blocks
of 16 with onward chains, fan-ins, convergences, returns and multi-loops planted at
fixed offsets), 60 of them carrying at least one identity field:

| | old headroom lift | band-contained |
|---|---|---|
| transactions moved into a higher band | 6 | **0** |
| largest band jump | 1 | **0** |
| Spearman vs the pure structural score | 0.9578 | 0.9559 |
| largest single lift | 0.1577 | 0.1357 |

So the shipped model was **not** wildly mis-scoring — it is a tighter change than it
looks, and honesty about that matters when the next result comes back. But six
band crossings on a stream this size is not nothing: run 7 priced a demotion at
~4 points, and a promotion across a band demotes every structurally hotter
transaction that happens to carry no identifier. The old model reached **0.2993** on
a long consistently-tagged chain — one thousandth under the 0.30 fan boundary, which
is a coincidence of the constants rather than a property of the design. The
contained form cannot get there by construction.

## Measured cost

Identity scoring adds no traversal: the three temporal traversals Phase 1 already
runs are computed once and shared. Random-graph worst case on this laptop, every
transaction carrying both attributes: 200 entities / 2 000 transactions
0.245 → 0.282 ms per transaction, 1 000 entities / 5 000 transactions
0.028 → 0.085 ms. A single address shared by 3 000 entities — the `MAX_SHARED`
case — costs 0.019 ms.

## Assumptions we made

0. **Identity never changes which structural band a transaction is in.** The
   statement asks us to "combine identity scoring with structural scoring", and a
   Phase 2 evaluation re-tests every Phase 1 requirement — the structural ranking is
   still being scored underneath. Identity that could jump a band would be
   overwriting the model that scored 369/400 rather than combining with it.
1. **Identity never lowers a score.** Ex. 2 and 3 describe identity *disagreement*
   as weakening the single-cluster hypothesis, not as exonerating; the statement only
   ever says "assign a higher risk score when identity evidence increases combined
   suspicion". We add for agreement, add less for disagreement, and never subtract.
   Also the safe direction given the measured 4:1 penalty asymmetry.
2. **The identity belongs to the initiator.** Both fields are defined as "used to
   initiate the transaction", so a value is indexed against `fromUserId`. `pair`
   is the only signal that looks at the receiver's own initiating history.
3. **A single shared attribute is worth zero**, not a little: `cross` counts
   *groups − 1*. Ex. 4's third component is what makes it a signal; office Wi-Fi and
   cloud NAT are named in the statement as the reason.
4. **Identity evidence expires with the window.** An IP shared with a transaction
   25 h ago is not shared any more — identity records live and die with the
   transactions that carried them, on the same half-open 24 h window.
5. **`drop` requires a carrying flow.** It fires only when the leg that fed this
   sender actually carried the attribute. A stream with no identity fields at all
   therefore produces no identity signal whatsoever, and Phase 1 behaviour is
   preserved exactly. "Missing fields are normal on unrelated transactions."
6. **Self-transfers stay at 0.0** even with identity attached (Phase 1's
   `hf-struct01-tx1` probe pins this, and a self-transfer connects nothing).
7. **Optional identity fields are parsed leniently**: numbers are stringified,
   `null`, `""` and structured junk are treated as *absent* rather than rejected.
   Rejecting a transaction over a decorative optional field would fail the
   statement's own "must not cause processing to fail" rule.
8. **Two different values of the same attribute on one transaction** cannot happen —
   one value per attribute per transaction.
9. **An identifier used by more than 256 entities inside the window is
   infrastructure**, and contributes no cross-component signal at all. The
   statement names cloud NAT as the coincidence case; this is where that line is
   drawn, and it also bounds the work per transaction.
10. **Only the most recent leg into the sender is consulted** for `shift` and
   `drop`, and a leg whose event time is *later* than the transaction being scored
   is invisible to it. A transaction arriving out of chronological order can
   therefore lose a `drop` signal it arguably deserves — a deliberate false
   negative: scoring on evidence from the future is precisely what had Phase 1
   reporting `TEMPORAL_DEVIATION` for three evaluations, and the eight archived
   grader runs contain no out-of-order arrival at all.
11. **Amounts are still ignored.** The statement mentions "value-flow evidence" once,
   as something that *may* be required to interpret Ex. 4; it defines no amount
   semantics, and Phase 1 deliberately has none. Left for Phase 3.

## What the captured graded stream says

The capture worked. `GET /ghost-chains/debug/stream` on the branch service held
**both** evaluations whole — 220 entries, split on the `/reset` markers into two
runs of 109 — and they are archived at
`docs/phases/ghost-chains/logs/2026-08-22-graded-runs.json`. Replaying either run
through `app/routers/phase3.py` reproduces all 109 answers exactly, so the archive
is a faithful offline copy of the evaluator and every question below was settled by
measurement rather than argument.

**The Phase 1 stream carries no identity fields. The Phase 2 stream does.** Run 1:
zero `ipAddress`, zero `deviceId`, in all 109. Run 2: the same 109 txIds over
freshly generated entities, with `ipAddress` on 55 and `deviceId` on 67. Two things
follow:

- Phase 1's score is **purely the structural model**. No identity change can move
  it — the whole Phase 2 model never fires on a single graded Phase 1 transaction.
  So the two phases need two different levers, and this was worth knowing before
  spending another run.
- The identity model *is* live in Phase 2, on 67 of 109 transactions.

**Containment was doing real work.** On this exact stream the headroom lift it
replaced promoted **7** transactions out of their structural band — `txn-68`
0.230 → 0.344 and `txn-80` 0.035 → 0.100 among them — while the band-contained form
promotes **0**, at a Spearman against the pure structural score of 0.9869 versus
0.9840. Pinned against the archive by
`test_identity_never_moves_a_graded_transaction_out_of_its_band`.

That said: both runs scored ~368, the same as runs 8 and 9 before any of this. The
identity work has not yet been shown to be worth points — only to be better behaved.

## Clarifications from challenge developers

- Q: Should identity *disagreement* (Ex. 2/3) lower a score relative to no identity
  information at all, or only fail to raise it? → A: …
- Q: Is `ipAddress` the initiator's address only, or is it meaningful on the receiving
  side too? → A: …
- Q: Does the same identity on two disconnected components already count as a signal,
  or does it need a third? → A: …

## Failed test cases and what fixed them

-
