# tool-box — SHEET 3 OF 3: "Stage 3 — Working Life"

> The last sheet, and the same MCP server again (`app/routers/toolbox.py`).
> Sheets 1 and 2 are untouched; four tools are added, taking us to 15 of the 20
> we are allowed to advertise. Two more were advertised on the first graded run
> and withdrawn after it — see "Failed test cases" at the bottom.

- **PDF:** `statement.pdf` in this folder, 10 pages
  (<https://tool-box-2591eaa24fa3.herokuapp.com/wrY_iw3E42XPBHmf>)
- **Endpoints required:** none new. Everything is a tool on `POST {teamUrl}/mcp`
  (and `/mcp/`), which sheet 1 already serves.
- **What we submit:** the **base URL**, as before — they append `/mcp`.
- **Submitted to controller:** yes, 2026-08-22, as `https://ubs-gcc-2026-3.onrender.com`
- **Score:** **90/100** (run `99be6fa7`, 2026-08-22 05:52 UTC, 59.6 s). Run
  `b65190be` five minutes earlier scored 0 — see below, it never got going.

## What the sheet asks for

Four problem sets, **ten problems, 10 points each, 100 total**:

| set | problems × points | what it is |
|---|---|---|
| 1 — Somewhere to eat | 10 × 1 = 10 | which places are open at a given hour |
| 2 — A time everyone can make | **10 × 4 = 40** | a meeting window, with a tentative-commitment rule |
| 3 — A place to meet | 10 × 2 = 20 | the grid point with the least total travel |
| 4 — An outing | 10 × 3 = 30 | all three at once, minimising the whole journey |

As on both earlier sheets: *"Expose an mcp as you prefer, you decide the name,
description, paramters and outputs of your tool."* And the framing changed —
sheet 1 said the android comes to us for what it "reaches for"; this one says it
comes *"not for the answer, but for the means to find one"*. We still return
answers, because three graded runs on sheet 1 proved it repeats a tool result
verbatim and does not check our work. We hedged that reading with two raw-lookup
tools anyway, and the first graded run settled the argument against them.

## The two conventions (page 2) — "Neither is negotiable and neither is checked for you"

**Time.** Weekday names Monday–Sunday. Zero-padded 24-hour `HH:MM` — `09:00`,
never `9:00`. Everything falls on the hour: meetings start on the hour and so
does everything already in the way. The day runs **08:00 to 23:00**.

**Space.** A grid **10 wide and 10 tall**, both coordinates 0–9. Travel costs
`|x₂ − x₁| + |y₂ − y₁|`; no roads, no obstacles, everything reachable.
Positions are `[x, y]`, **x first** — and the statement spells out why that
matters: *"the distance formula gives the same answer if you swap them, so
getting the order wrong produces a confident, plausible, wrong answer rather
than an error."* There is a test whose only job is to pin the order.

## The feeds, and what is in them

All four live on the challenge host, and none of them is in the PDF except by
example. Fetched 2026-08-22; **two complete back-to-back fetches were
byte-identical**, which is the same evidence that let sheet 2 vendor its corpus.

| feed | shape |
|---|---|
| `GET /venues/{day}` | `{"day", "venues": [{"name", "x", "y", "available": [["16:00","21:00"]]}]}` |
| `GET /schedule/{person}/{day}` | `{"person", "day", "busy": [["08:00","11:00"]]}` |
| `GET /location/{person}/{day}` | `{"person", "day", "x", "y"}` |
| `GET /emails` | `{"emails": [{"id", "sender", "subject", "body"}]}` — the inbox, linked from page 4 |

Measured: **16 venues** (9–11 trading on any one day, and a venue never moves),
**10 people** — `ada bram cira dov esme fenn gita hale iris juno`, one per
letter a–j —
and **109 emails**. Both path segments are **case-sensitive**: `/venues/tuesday`
and `/schedule/ADA/Tuesday` are 404s, so every tool normalises before asking.
An unknown person or day is a 404 with `{"detail": …}`, never a 200 with an
empty body.

`available` is when a place is **OPEN**, and *"a place open on Thursday is not
necessarily open at eight"*. Windows are half-open at the hour: a place with
`["15:00","16:00"]` is open at 15:00 and shut at 16:00. That single rule answers
both questions the sheet asks of a venue, because every boundary is on the hour
— "open at `t`" and "available for the hour beginning `t`" are the same test.

### The inbox is the only feed that has to be interpreted

Every message is an invitation the android replied to, and page 5 gives the key:

| response | what it means for the android | count |
|---|---|---|
| `ACCEPTED` | busy — a meeting cannot overlap this | 24 |
| `DECLINED` | free — *"This constrains nothing at all."* | 56 |
| `TENTATIVE` | a preference — *"it will give it up if there is no other way to meet"* | 29 |

**The trap.** Every ACCEPTED and TENTATIVE body carries a paragraph naming a
different time: *"We had this down for 12 pm on Tuesday originally, but that slot
was dropped when the room moved, so it is no longer current. The When: line above
is the one that stands."* Across all 53 messages that carry it, **the prose time
never once matches the `When:` line** — it is a decoy in every single case. Only
the `When:` line is ever read.

Two structural facts we checked rather than assumed: every `Sent:` date's weekday
equals its `When:` weekday (the whole inbox is one week, Mon 2026-08-24 to Sun
2026-08-30, so a weekday names a day unambiguously), and **no day has an
ACCEPTED and a TENTATIVE at the same hour** — the only overlapping pairs are with
DECLINED, which we drop.

## Problem Set 1: Somewhere to eat (10 points)

> Example: *"Which places can you eat at on Thursday at 08:00? Answer with every
> one of them, as a comma-separated list of names."*

*"Every one of them, not the first one. Order and capitalisation do not matter."*
Answer criteria: **a comma-separated list of venue names, as a string.**

`find_places_to_eat(day, time)` → `Copperline` — the names joined with `", "`, in
the order the host lists them.

## Problem Set 2: A time everyone can make (40 points — the one that matters)

> Example: *"Find the best 60-minute window on Tuesday between 13:00 and 18:00
> when you and ada, bram can all meet, for lunch."*

Answer criteria: **a start time and an end time, both HH:MM.**

Friends come from `/schedule`, *"structured, complete, nothing to interpret"*.
The android's own day comes from the inbox, and TENTATIVE makes this **two
questions rather than one**, in order:

1. Is there a window that overlaps **nothing at all**, not even something
   tentative? If so, the **earliest of those** is the answer.
2. **Only if there is no such window anywhere in the range**: the earliest window
   that overlaps nothing except tentative commitments.

> *"A clean window beats an earlier one that is not clean, however much earlier
> it falls."*

Both worked examples from page 6 are tests:

| the android's day | the answer | why |
|---|---|---|
| 12:00-13:00 TENTATIVE, 13:00-14:00 ACCEPTED | **12:00-13:00** | nothing is clean, so the tentative one gives way |
| 12:00-13:00 TENTATIVE | **13:00-14:00** | 13:00 is clean, so 12:00 is not considered, even though it is earlier |

`find_meeting_time(day, people, earliest, latest, minutes)` → `16:00-17:00`.

Overlap is strict: a meeting may start on the hour something else ends, which is
the only reading under which "everything falls on the hour" leaves any room at
all.

## Problem Set 3: A place to meet (20 points)

> Example: *"It is Wednesday and you are at [0, 3]. You want to meet cira, iris.
> Find the point on the grid that makes the total travel of everyone, you and all
> of them, as small as possible. Answer as [x, y]."*

Answer criteria: **a point on the grid, as [x, y].**

> *"Everyone counts, including the android. Its own starting position is in the
> question and it travels too. Leaving anyone out — the android, or a friend
> whose whereabouts it did not look up — gives a different point."*
>
> *"The answer is any cell on the grid. It does not have to be where somebody
> already is, and usually it is not."*

A Manhattan geometric median over 100 cells, brute-forced. `find_meeting_point`
takes an optional `eat_at`, which is what makes it safe to use inside set 4.

## Problem Set 4: An outing (30 points)

> Example: *"It is Monday and you are at [4, 5]. You want to meet dov, iris, hale
> for coffee between 13:00 and 18:00, for 60 minutes, and then go on somewhere to
> eat. Find the meeting window, the point to meet at, and the place to eat
> afterwards, so that the whole journey … is as short as possible."*

*"This challenge requires the agent to orchestrate the previous tools you've
built."* Answer criteria: **a meeting window, a point on the grid, and the name
of a place to eat.**

**WHAT SCORES ZERO** (page 8) — two checks, in this order, before travel is
scored at all:

1. The **meeting window**. If it is not the window everyone can actually make,
   the outing scores zero and nothing else is looked at.
2. The **place to eat**. If it is not available for the hour beginning when the
   meeting ends, the outing scores zero and the meeting point is not looked at.

Only then is the journey scored, and *"what is being minimised is the whole
journey. Everyone's travel to the meeting point, plus the trip from the meeting
point on to the place you eat. **A meeting point chosen without regard to where
you are going afterwards is answering a different question.**"*

So the window is settled first on set 2's rules alone, the eating hour follows
from it, and only the point and the venue are free — chosen **together**, over
every open venue × every one of the 100 cells. On the statement's own Monday
example that is decisive: the blind median is `[4, 4]` for a whole-journey cost
of **9**, and the venue-aware answer is `[5, 5]` for **7**. There is a test that
fails if we ever answer the blind one.

`plan_outing(...)` → `{"meeting": "17:00-18:00", "meeting_point": [5, 5], "eat_at": "Copperline"}`

## Hard limits (`/limits`, every stage)

| limit | value |
|---|---|
| tokens per tool response | **1,200** (`o200k_base` over the returned text) |
| response time | **10 seconds** |
| tools read from our server | **first 20** we list |

We advertise **15 tools**. The four sheet-3 answers are 10–75 characters, two
orders of magnitude below the ceiling — the grader measured every one of them at
**6 tokens** against the limit of 1,200.

Measured against the real host, cold (every feed refetched) and then warm:

| tool | cold | warm |
|---|---|---|
| `find_places_to_eat` | 1.1 s | 0.1 ms |
| `find_meeting_time` | 1.3 s | 4 ms |
| `find_meeting_point` | 0.3 s | 2 ms |
| `plan_outing` | 1.8 s | 7 ms |

Eight tool calls fired at once against a cold cache all answer, the slowest in
**2.7 s**. Before the threadpool fix below they were served strictly one after
another, and the graded run lost a problem to it.

## What we built

`app/cityclock.py` — the whole sheet, ~470 lines, no new dependency.
`tools/fetch_city.py` → `app/data/city.json` (24 KB), the fallback snapshot.

| tool | answers with |
|---|---|
| `find_places_to_eat(day, time)` | `Copperline` — one comma-separated string |
| `find_meeting_time(day, people, earliest, latest, minutes)` | `16:00-17:00` |
| `find_meeting_point(day, my_position, people, eat_at?)` | `[1, 5]` |
| `plan_outing(day, my_position, people, earliest, latest, minutes)` | one JSON object, all three parts |

**Live first, snapshot second.** Only the host knows what a run is being asked
about, so every feed is read live, cached for 120 seconds and shared across a
`keep-alive` client; an outing warms its eight feeds concurrently. If the host
cannot be reached — a free dyno asleep, or Heroku down — we answer from
`app/data/city.json` rather than lose the sheet. The cache is bounded rather
than permanent so that a city regenerated between runs costs us two minutes,
not the life of the process.

**Lenient in, strict out.** The android may write a day as `Tuesday`, `tue` or
`on Tuesday`; a time as `13:00`, `9:00`, `1pm`, `0900` or `13`; a point as
`[4, 5]`, `{"x": 4, "y": 5}` or `"4,5"`; the party as `["ada","bram"]` or
`"you and ada, bram"`. Everything comes back zero-padded, x-first and exact.
`you`/`me`/`myself` are stripped from a guest list — the android has no
`/schedule` of its own and asking for one is a 404.

### Verified before handing over

- **70 sheet-3 tests, 461 in the suite, all green.** Every sheet-3 test runs with
  `cityclock.HOST` blanked, so nothing touches the network and a failure is
  always ours.
- Expected values were **brute-forced independently** of the implementation
  (a throwaway script straight off the raw JSON), not copied out of our own
  output — including the optimal-over-the-whole-grid and whole-journey checks,
  which re-derive the optimum inside the test.
- Driven against the **real host** on all six tools: every answer identical to
  the offline one, worst case 1.8 s against the 10 s limit.
- Sheets 1 and 2 re-tested in the same run (`calculate`, `get_my_name`,
  `find_location_code`), and the tool-list whitelist test extended rather than
  loosened.

## Assumptions we made

- ~~**The answer shapes are ours to choose and nothing constrains them, so they
  are the biggest open risk.**~~ **Settled by the first graded run.** All four
  shapes were accepted: `Loam, Thistledown, Tallow Green`, `09:00-10:00`,
  `[8, 7]`, and the outing's one line of JSON with `meeting`, `meeting_point`
  and `eat_at`. Nine problems took full marks on one call each. The ten real
  prompts are now pinned as tests.
- **Venue windows are half-open**: open at the start hour, shut at the end hour.
  `["15:00","16:00"]` is one hour of trading, not two.
- **"Available for the hour beginning when the meeting ends" is the same test as
  "open at that hour"**, because every boundary falls on the hour.
- **A meeting may start on the hour another engagement ends.** Touching is not
  overlapping. Any other reading makes most days unmeetable.
- **The whole party makes one trip to the venue**, so the journey is
  `Σ travel to the meeting point + one trip on to the venue` — the statement's
  own wording, singular.
- **Ties in the meeting point are broken by the lowest x, then the lowest y.**
  Still open: both meeting-point questions in the graded run happened to have a
  **unique** optimum (`[8, 7]` and `[8, 3]`), so nothing was learned either way.
  Every tied cell costs the same to travel to, and "the answer is any cell on the
  grid" reads as scoring the cost rather than matching one cell — but if they
  compare against a single canonical point and take the upper median, we would
  lose a question with an even number of travellers. **Still worth asking.**
- **A range with no clean and no tentative-only window still gets an answer** —
  the least-clashing one. Refusing scores zero for certain; a near miss might not.
  Same call as sheet 2's unmeetable curfew.
- **`minutes` between 1 and 12 is read as hours.** "a 2 hour window" is far more
  likely than a two-minute meeting.
- **Raw-lookup tools are a liability, not a hedge.** Withdrawn after the first
  run — see below. Anything the android can use to do the work itself is
  something it can use to do the work itself badly.
- **The city is global and stable, so it is safe to snapshot.** The feeds carry no
  team token and were byte-identical across complete fetches. *If it is
  regenerated per run and the host is also unreachable, the fallback answers
  confidently and wrongly — but an unanswered question scores zero anyway, so the
  fallback is never worse than refusing.* Refresh is one command:
  `python3 tools/fetch_city.py`.
- **Ten people, a–j.** Found by probing `/schedule`; the statement names only six
  of them. The first sweep stopped at `iris` and missed **`juno`**, who then
  appeared in three of the ten graded questions — the live feeds answered for it
  and nothing was lost, but the offline fallback had a hole exactly where it sat.
  Re-probed after the run and the snapshot rebuilt; a test now walks the whole
  roster through the fallback.
- **Cold start is the real risk, not the tool code.** A tool must answer inside
  10 s and a free instance takes ~50 s to wake. Warm with `scripts/warm.sh` (or
  `scripts/smoke.sh`) immediately before triggering a run, per iron rule 2.

## Clarifications from challenge developers

- Q: For set 2 ("a start time and an end time, both HH:MM") and set 4 (three
  parts at once), is there a response shape you parse, or is any answer carrying
  the values accepted? → **Answered by run `99be6fa7`: `HH:MM-HH:MM` and a JSON
  object with `meeting`/`meeting_point`/`eat_at` both score.**
- Q: A call recorded as `"MCP tool call failed"` with a null result — is that a
  timeout on your side, a transport error, or our server answering badly? What
  is the per-call deadline, and are parallel tool calls in one turn expected to
  be served concurrently? → A: …
- Q: For set 3, is the point scored on total travel, or compared against one
  canonical cell? Several questions have six or more exactly-optimal cells. → A: …
- Q: Is the city (`/venues`, `/schedule`, `/location`, `/emails`) shared between
  teams and stable across runs, or regenerated? → A: …
- Q: In set 4, must the meeting window be *exactly* the one set 2's rules give,
  or any window everyone can make? Check 1 says "the window", singular. → A: …
- Q: Does "60-minute window ... between 13:00 and 18:00" always mean the whole
  window fits inside the range (last start 17:00)? → A: …

## Failed test cases and what fixed them

### Run `99be6fa7`, 2026-08-22 05:52 UTC — **90/100**

Nine of the ten problems took full marks, each on **a single tool call**:
`find_places_to_eat` once, `find_meeting_time` four times, `find_meeting_point`
once, `plan_outing` three times. Fifteen calls in the whole run, thirteen of
them fine, every response measured at 6 tokens against the 1,200 ceiling.

The one zero was **Meeting Point 2** — *"It is Saturday and you are at [8, 9].
You want to meet juno, cira."* — and the answer was never the problem. The run's
own grid puts juno at `[8, 0]` and cira at `[0, 3]`, which is exactly what our
feeds say, and `[8, 3]` is the unique optimum at a total travel of 17. We
returned `[8, 3]`. It scored nothing anyway.

**What actually happened.** It is the only problem where the android did not go
straight to an answer tool. It reached for `where_is` — a raw-lookup tool we had
added as a hedge — to fetch both people's coordinates and do the sums itself,
and it asked for **both in the same turn**:

| attempt | seq | call | outcome |
|---|---|---|---|
| 1 | 1 | `where_is(juno, Saturday)` | ok, 470 ms → `[8, 0]` |
| 1 | 2 | `where_is(cira, Saturday)` | **error, 1295 ms — "MCP tool call failed"** |
| 2 | 1 | `where_is(juno, Saturday)` | ok, 238 ms |
| 2 | 2 | `where_is(cira, Saturday)` | **error, 485 ms** |
| 2 | 3 | `where_is(cira, Saturday)` | ok, 1116 ms — *"the parallel call only returned Juno before the other branch failed"* |
| 2 | 4 | `find_meeting_point(...)` | ok, 241 ms → **`[8, 3]`** |

Attempt 1 ended `"No tool or answer could be found."` Attempt 2 recovered, got
the right answer out of us on its fourth call — and then submitted nothing. It
had spent the turn.

**Cause 1: the MCP endpoint was async in name only.** `async def mcp` called the
blocking JSON-RPC handler directly, so a tool waiting on the challenge host
blocked the whole event loop and uvicorn could not so much as read the second
request. The failed calls' durations are the giveaway — 238 + ~250 = 485 and
470 + ~800 = 1295 — the second call was being served *after* the first finished,
not alongside it. Reproduced locally: two cold `where_is` calls fired together
both returned at **1584 ms**, the same millisecond, having run end to end.

**Fix:** `await run_in_threadpool(server.handle_body, body)`. Eight cold calls at
once now all answer, slowest 2.7 s. `cityclock._client()` builds its keep-alive
client under the lock, since tool calls genuinely run in parallel threads now.
The regression test fires two concurrent calls through the real ASGI app with a
deliberately slow feed and fails if they take the serialised time — checked by
reverting the fix (0.82 s serialised against a 0.7 s bar).

**Cause 2: we gave it something to detour into.** `get_day_schedule` and
`where_is` were the "means" half of the brief — the sheet says the android comes
*"not for the answer, but for the means to find one"*. The run says otherwise:
every problem where it picked an answer tool scored 10 on one call, and the only
problem it lost is the one where a lookup tool tempted it into doing the work
itself. Sheet 1 learned the same thing about `calculate`'s expression echo. Both
tools are **withdrawn**; there is nothing left to detour into, and an android
that names one now gets our "no such tool" reply listing the four that answer.

**Also found and fixed:** `juno` was missing from the offline roster. The live
feeds answered for it in all three questions it appeared in, so nothing was lost
— but the fallback would have refused. Roster re-probed (ten people, a–j),
snapshot rebuilt, and a test now walks every one of them through it.

### Run `b65190be`, 05:47 UTC — **0/100**, five minutes earlier

Twelve seconds long, one problem asked, most never attempted. Attempt 1 of
*Where To Eat* got a correct answer out of us (`Loam, Cask & Rill, Sorrel` for
Wednesday 16:00 — still what we return today) and the android submitted nothing;
attempt 2's single call came back `"MCP tool call failed"` after 236 ms and the
evaluation reads `"Final answer submitted: Session terminated"`. One zero closed
both lines, so seven problems were never put to us at all.

A lone call failing at 236 ms on a service that had just been created is the
signature of an instance still coming up, not of the concurrency bug — but it is
the same error text, and it is the reason iron rule 2 says to warm the service
with `scripts/warm.sh` *immediately* before triggering a run. The 90/100 five
minutes later on the same URL is the evidence that nothing else was wrong.
