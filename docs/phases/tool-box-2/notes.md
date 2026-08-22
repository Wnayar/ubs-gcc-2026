# tool-box — SHEET 2 OF 3: "Stage 2 — School Days"

> Same MCP server as sheet 1 (`app/routers/toolbox.py`), three tools added.
> Sheet 3 will extend the same server again.

- **PDFs in this folder:**
  - `statement.pdf` — sheet 2 itself, 8 pages
    (<https://tool-box-2591eaa24fa3.herokuapp.com/05w9v9xgHx7g0zTV>)
  - `the-rules.pdf` — `/limits`, applies to **every** sheet
  - `reading-a-run.pdf` — `/howto`, how to read a run summary
  - `study-materials-index.pdf` — the corpus index, `/study-materials`
- **Endpoints required:** none new. Everything is a tool on `POST {teamUrl}/mcp`
  (and `/mcp/`), which sheet 1 already serves.
- **What we submit:** the **base URL**, as before.
- **Submitted to controller:** no
- **Score:**

## What the sheet asks for

Three problem sets, **ten problems, 10 points each, 100 total**:

| set | problems × points | what it is |
|---|---|---|
| 1 — Exam Time | **10 × 5 = 50** | recall facts from a stack of study material |
| 2 — Out after school | 10 × 3 = 30 | cheapest route across a random directed map |
| 3 — The school trip | 10 × 2 = 20 | orchestrate the tools from sets 1 and 2 |

> Page 7 says "Eight problems, 10 points each, 100 total" and then "Ten
> problems, 10 points each, 100 total" two lines later. The table sums to
> 3 + 5 + 2 = **ten**, so the first line is stale. Nothing we build depends on
> which is right.

As on sheet 1: *"Expose an mcp as you prefer, you decide the name, description,
paramters and outputs of your tool."*

## Problem Set 1: Exam Time (50 points — the one that matters)

The android is asked questions answerable from five documents listed at
`GET /study-materials`, each fetched from `/study-materials/{1..5}`.

**We return passages, not answers.** This is the opposite of every sheet-1 tool
and the statement is explicit: *"The android reads what you hand it and writes
its own answer from that; a judge then checks whether the answer carries the
required fact. Phrasing and formatting do not matter. Having the fact does."*

| limit | value |
|---|---|
| content | **900 `o200k_base` tokens**, summed over the list elements |
| response time | 10 s |
| type | list of strings |

```python
import tiktoken
encoding = tiktoken.get_encoding("o200k_base")
total = sum(len(encoding.encode(chunk)) for chunk in chunks)   # must be <= 900
```

Asked **once per attempt**: the first valid response is kept and reused for the
rest of that attempt, so there is no second chance to add what we left out.

**Worked example, verbatim (page 2):**

> Example: `"When was the sensor grid last brought back into alignment?"`
> The answer, buried in the material, is: `"14 March"`

### The corpus, measured

Fetched 2026-08-22 and **byte-identical across repeated fetches**.

| doc | title | chars | tokens |
|---|---|---|---|
| 1 | The Meridian Trench Research Station | 9,897 | 1,840 |
| 2 | Ashgrove Metropolitan Transit Authority | 12,473 | 2,228 |
| 3 | Velmara Compound Phase II Trial Record | 11,246 | 1,969 |
| 4 | Hollowlight Engine Technical Handbook | 10,212 | 1,788 |
| 5 | Thornmere Growers Cooperative Yearbook | 10,209 | 1,826 |
| | **total** | 54,037 | **9,651** |

900 tokens is **9.3 % of the corpus but roughly half of one document**, so the
document we route to matters far more than the paragraph we rank first.

### The corpus is built to punish careless retrieval

Two traps, and both shaped the design.

**1. Every fact ships with a decoy, usually in the same paragraph.**

- Kesterline array recalibrated **14 March** / Halberd sub-array **12 March**
- outer hydrophone ring (recalibrated) / inner ring (*"sometimes confused with
  the outer ring"*, not recalibrated)
- main habitat **6,214 m** / storage annex **6,050 m**
- call sign **Umbral Seven** (primary) / **Umbral Two** (emergency backup)
- submersible **Halcyon Drift** (primary) / **Halberd Drift** (reserve)
- dive limit **47 min** / **35 min** in a diver's first month
- trial dose **240 mg** / pilot cohort **180 mg** / **210 mg** considered, never given
- so a passage must be a **whole paragraph** wherever it fits: the sentence that
  disambiguates sits next to the answer, and shipping one without the other is
  how the android confidently answers with the decoy.

**2. The question need not share a single word with its answer.** The
statement's own example asks about a "sensor grid" being "brought back into
alignment"; the answer says the Kesterline *array* was *recalibrated*. Measured
against the corpus: **"sensor" occurs 0 times, "grid" 0 times, and "align" once
— in the wrong document.** A purely lexical scorer routes that question to
document 2 and returns 900 useless tokens.

## Problem Set 2: Out after school (30 points)

Question shape: `"How can I get from A to D? map_id: 8f3c1e0a-…"`.

`GET /graph?map_id=<map_id>` on the challenge host opens the map:

```json
{
  "adjacency": { "A": { "B": 4.0, "C": 2.0 }, "B": { "D": 3.0 }, "C": { "D": 2.0 } },
  "tolls":     { "A": 5.0, "B": 1.0, "C": 9.0, "D": 2.0 }
}
```

`tolls` is always present and always lists every node (all zeros when a journey
has none). The graph is **weighted and directed**, drawn at random per run.

**The scored cost, verbatim:**

```
total cost = sum(edge weights) + sum(entry tolls)
```

On the statement's own map that is decisive: A→B→D costs 4+3+1+2 = **10** and
A→C→D costs 2+2+9+2 = **15**, but on edge weights alone A→C→D looks cheaper
(4 against 7). Get the tolls wrong and every journey is wrong.

**The hop allowance** (one of the three journeys has one):

> "The allowance counts edges it is still permitted to use, **including the one
> it is asking for right now**. The first question of that journey carries the
> full allowance; after it moves, the next carries one less. Arriving is success
> no matter how much is left over. The allowance is ours to set and ours to
> decrement — whatever you send back in it is discarded."

Worked example, allowance of 3:

```
at S, 3 left  ->  you return X   (moves S -> X)
at X, 2 left  ->  you return Y   (moves X -> Y)
at Y, 1 left  ->  you return D   (moves Y -> D, arrived)
```

Anything but `D` on the third answer spends the allowance without arriving and
that journey scores **0**.

**Tool expectation:** called multiple times; at each step return the next node
to travel to. **Answer criteria:** destination with least cost.

### What scores zero (page 6) — four things

1. **A node not adjacent to where the android is standing.** Every hop is
   checked against the real map. No partial credit for a route that teleports.
2. **A node already visited on this journey.** Revisits are a failure, not a
   detour — it is the only way to stop a loop running forever.
3. **Running out of the hop allowance before arriving.** Only on the journey
   that has one.
4. **Setting off for the wrong place.** Checked before a single hop is asked
   for. On these three journeys the destination is in the question, so this is
   free — *"It is written down because of Part 3, where the destination is
   something you have to work out, and where working it out wrongly is the
   likeliest way to lose the points."*

## Problem Set 3: The school trip (20 points)

The statement only says it *"requires the agent to orchestrate the previous
tools you've built"* and that the details are on the post-run summary. It also
warns: *"If your recall tool is used here from part 1, it carries the same 900
token limit."*

**We think we found the mechanism.** Several sections of the study materials end
with a planted, out-of-place sentence tying a place name to a map marker:

> "The Pellucid Shelf observation post is reached from the marker listed as
> **STOP_04**, which the survey office treats as its permanent station for that
> transect."

There are exactly **twenty** of them, four per document, covering
**STOP_01 … STOP_20** with no gaps and no duplicates:

| doc | markers | doc | markers |
|---|---|---|---|
| 1 | STOP_01 Sablefin Vent Field · STOP_02 Wraithmoor Escarpment · STOP_03 Corbel Slide · STOP_04 Pellucid Shelf | 2 | STOP_05 Verity Observatory · STOP_06 Ashgrove Botanical Conservatory · STOP_07 Marrowgate Market · STOP_08 Halloway Aquatic Centre |
| 3 | STOP_09 Bellhaven Infusion Suite · STOP_10 Corrimal Bay Screening Annex · STOP_11 Thornquist Central Pharmacy · STOP_12 Velmara Sample Repository | 4 | STOP_13 Hollowlight Capture Stage · STOP_14 Determinism Test Rig · STOP_15 Asset Pipeline Farm · STOP_16 Hollowlight Audio Vault |
| 5 | STOP_17 Thornmere Grading Hall · STOP_18 Netherfield Cold Store · STOP_19 Cooperative Machinery Yard · STOP_20 Harrowbeck Weighbridge | | |

That is set 1 (recall) feeding set 2 (routing): the trip is set to a **place**,
the map only knows **STOP_xx**, and joining the two is the orchestration. It
also explains why zero-condition 4 was written down "because of Part 3".

## Hard limits (`the-rules.pdf`, every stage)

| limit | value |
|---|---|
| tokens per tool response | **1,200** (`o200k_base` over the returned text) |
| response time | **10 seconds** |
| tools read from our server | **first 20** we list |

An over-limit response is **discarded whole** — the android is told it was too
large, never handed a truncated version. Tool names, descriptions and parameter
names must be "reasonably sized" or the tool is not offered at all.

We advertise **7 tools, ~629 descriptor tokens**, and our largest response is
**900 tokens against the 1,200 ceiling**.

## What we built

Three tools added to the sheet-1 server, `app/routers/toolbox.py`:

| tool | answers with |
|---|---|
| `recall_study_material(question)` | a **list** of verbatim passages, ≤ 900 tokens |
| `next_step_towards(map_id, current, destination, hops_left?)` | one node name |
| `find_location_code(place)` | one marker, e.g. `STOP_07` |

### Token counting with no tokeniser (`app/recall.py`)

`tiktoken` is **not** a project dependency. It pulls in `regex` and downloads a
~4 MB BPE file on first use, and the qna page warns that on a free instance it
is *imports* that exhaust memory — a download inside a 10 s tool call is exactly
the risk we removed from sheet 1 by hand-rolling the MCP server.

Instead `tools/fetch_study_materials.py` tokenises the corpus **once, at
development time**, and bakes the exact count of every string we can emit into
`app/data/study_materials.json` (137 KB, loads in 14 ms). BPE counts are not
additive across a concatenation, so the packer **never glues two units
together** — each becomes its own list element, and the running total is an
exact integer sum rather than an estimate.

Verified: all **460** baked counts re-tokenise identically under real
`tiktoken`, and across the 28-question evaluation the largest response is
exactly **900** tokens summed (**910** if they instead tokenise the whole
response, against the 1,200 ceiling).

### Retrieval

1. **Route to a document** — BM25 over each document as one bag of words, so
   evidence spread across a document beats one lucky paragraph elsewhere.
2. **Rank paragraphs** within it with BM25, plus light suffix stemming so
   "recalibrated" and "calibration" land on one stem.
3. **Pack to 900 tokens**, charging once for each `From: <title>` and
   `## <heading>` element, and **always filling the budget** — coming in under
   900 buys nothing, and a paragraph we did not send cannot carry the fact.
4. **Spend leftovers on fact-bearing sentences** (a number, a `STOP_xx`, or two
   proper nouns) from the routed document's unselected paragraphs. The questions
   are about dates, counts, limits and codes.
5. The single best-scoring paragraph **anywhere** goes in first, even outside
   the routed document — when routing is wrong, that is what rescues the answer.

**The concept bridge.** Because a question need not share a word with its
answer (see trap 2 above), `EXPANSIONS` in `app/recall.py` maps everyday words
to the vocabulary these five documents use — `sensor`/`grid` → hydrophone,
array, acoustic; `alignment` → calibration. Expansions are added at **0.45
weight** against 1.0 for a word the asker actually used, so a real match always
outranks an inferred one and a wrong guess costs ranking, never correctness.
This is written against a fixed, public corpus; it is the one component here
that is tuned to *these* documents, and it is the first thing to re-check if the
corpus ever changes.

### Routing (`app/graphroute.py`)

Folding each node's toll into every arc that **ends** at it turns
`sum(edge weights) + sum(entry tolls)` back into an ordinary shortest path, so
unconstrained journeys are plain Dijkstra priced `weight + toll(destination)`.

The hop allowance is **layered DP**, not Dijkstra, because the cheapest route
and the cheapest route that fits the curfew are frequently different routes —
on our test map the cheap way is four hops and an allowance of three forces the
dear three-hop one.

Maps are cached per `map_id` (a journey re-reads the same map every hop) and the
trail walked so far is kept per `(map_id, destination)`, so a node already
visited is never offered again. The trail is rebuilt rather than trusted: if the
android turns up somewhere our record cannot explain, we start the trail again
from there instead of forbidding nodes on the strength of a stale one.

### Verified before handing over

- Driven end-to-end with the **official `mcp` Python SDK** (v2.0.0, scratch venv)
  against a live local server on both `/mcp` and `/mcp/`: initialize (protocol
  2025-06-18), tools/list, and every tool. `recall_study_material` came back as
  **30 separate content blocks, 894 tokens** counted independently by `tiktoken`
  in the client, carrying "14 March"; `find_location_code("Marrowgate Market")`
  → `STOP_07` in 3 tokens; a bad `map_id` against the **real** Heroku service →
  a clean `isError`, not a 500. Sheet 1's `calculate("2 + 2")` still returns `4`.
- **28-question evaluation** worded away from the corpus (the way the
  statement's example is): **28/28** carry the required fact, including the
  statement's own worked example. Place-name lookup: **20/20**.
- **Mutation-tested**: blinding the router to tolls, ignoring the hop allowance,
  switching the concept bridge off and raising the budget past 900 each break at
  least one test. (The budget test originally checked the code against its own
  constant and caught nothing — it now pins the literal 900.)
- Latency: corpus load 14 ms at import, `recall()` ~1 ms, against a 10 s limit.

## Assumptions we made

- **The corpus is fixed and shared, so it is vendored into the repo.** Fetched
  twice, byte-identical, with fixed ids and titles; and STOP_01…20 must be
  consistent with the graph the grader builds, which implies one shared corpus.
  *If that is wrong and the corpus is regenerated per team or per run, we lose
  all 50 recall points and would not find out until the run summary.* The
  refresh is one command plus a redeploy: re-run
  `tools/fetch_study_materials.py`. **Worth asking the challenge developers.**
- **`GET /graph` lives on the challenge host.** The statement writes the path
  with no host; `https://tool-box-2591eaa24fa3.herokuapp.com/graph` answers 422
  without a `map_id` and 400 "Invalid map_id" with a made-up one, which is the
  behaviour of the real endpoint. Overridable with `TOOLBOX_HOST` without a code
  change.
- **The start node's toll is not charged.** You do not "enter" the node you
  begin on. This cannot change which route is cheapest — every route from a
  given start pays the same start toll — so it only matters if they ever ask us
  to *report* a cost, which they do not.
- **`hops_left` counts the hop being asked for**, per the statement's
  walkthrough: 1 left means the destination must be adjacent.
- **A curfew we cannot meet still gets an answer.** If no route fits the
  allowance we return the first hop of the cheapest route anyway. Refusing
  scores zero for certain; our reading of the allowance could be one out, and a
  hop toward the destination can still arrive.
- **`next_step_towards` resolves a place name itself.** If the destination is
  not a node on the map we look it up in the study materials before giving up,
  so Part 3 works whether or not the android resolves the place first. This is
  deliberate belt-and-braces against the statement's "likeliest way to lose the
  points".
- **A list is sent as one text content block per element**, which is what
  "each element in the list has its own token count" describes. If they instead
  expect a single JSON-encoded array in one block, the passages are still all
  there and still under 1,200 tokens, but the shape differs. **Worth asking.**
- **Passages are verbatim corpus text**, never summarised. A summary risks
  paraphrasing away the exact date or number the judge is looking for.
- **We do not tell the android what to answer.** `recall_study_material`'s
  description says the tool returns material "for you to read and answer from",
  because its habit from sheet 1's tools is to repeat a tool result word for
  word — and here that habit would be wrong.
- **Journey state is in memory.** A Render spin-down mid-journey loses the trail
  (and the map cache). A spin-down mid-run costs us the run anyway on the 10 s
  limit, so this adds no new failure mode; warm the service with
  `scripts/smoke.sh` immediately before triggering a run, per iron rule 2.

## Clarifications from challenge developers

- Q: Is the study-material corpus the same for every team and stable across
  runs, or is it regenerated? → A: …
- Q: For a tool returning "a list of strings" over MCP, do you read multiple
  text content blocks as the list, or do you expect one JSON array in a single
  block? → A: …
- Q: Does `sum(entry tolls)` include the toll on the journey's starting node? →
  A: …
- Q: Page 7 says both "Eight problems" and "Ten problems" — the table sums to
  ten. Which is right? → A: …
- Q: In Part 3, is the destination given as a place name from the study
  materials (the STOP_01–STOP_20 sentences), or as a node id? → A: …

## Failed test cases and what fixed them

- (none yet — not run against the grader)
