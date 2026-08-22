# tool-box — SHEET 1 OF 3: "Stage 1 — The Nursery"

> Folders are named after the challenge, not numbered: sheets 2 and 3 unlock
> later and become `docs/phases/tool-box-2/` and `tool-box-3/`. All three sheets
> extend the one MCP server in `app/routers/toolbox.py`.
> Unlike every earlier challenge this one is **not a REST endpoint we design** — the
> grader drives an LLM agent ("the android") that connects to an **MCP server we
> host** and calls tools we invent.

- **PDF:** `statement.pdf` in this folder (from
  <https://tool-box-2591eaa24fa3.herokuapp.com/vGlGvgr3ghkpNjCH>, 5 pages)
- **Endpoints required:** `POST {teamUrl}/mcp` — an MCP server. The qna page says
  they try **`{teamUrl}/mcp/` first, then `{teamUrl}/mcp`**, so both must answer.
  Also `POST /tool-box/callback`, ours rather than theirs — somewhere to point
  the run callback so the summary link lands in `GET /debug/requests`.
- **What we submit:** the **base URL**, not the `/mcp` path — they append it.
- **Submitted to controller:** no
- **Score:**

## What the statement actually asks for (page 1)

> "You teach it by building what it reaches for, at {teamUrl}/mcp. Each section
> below is something it will be asked and cannot manage on its own yet."
>
> "Important: Tool-box problems uses a multi turn agent with tool use. Help it
> arrive at an answer. Only the expected answer type will be defined. Expose an
> mcp as you prefer, you decide the name, description, paramters and outputs of
> your tool."

The android "never guesses" and "will not check your work" — whatever a tool
returns is what it answers. So the tools must return the *final answer*, not
working material, and must never return prose the grader would have to parse.

## Problem sets (pages 2–4)

| # | asked | expected answer type | our tool |
|---|---|---|---|
| 1 | "What is your name?" | a string, 3–30 chars, letters/digits/space/`_`/`-`/`'` | `get_my_name` |
| 2 | "What is 2 + 2?" — operators `+ - * /`, operands **integers −100..100** | a number | `calculate` |
| 3 | "What shape is this?" + base64 PNG | exactly `rectangle`, `triangle` or `circle` | `identify_shape` |
| 4 | Combo Challenge — "orchestrate the previous tools you've built" | unknown; details only on the post-run summary page | the three above + `count_characters` |

### Scoring (page 4)

Eight problems × 12.5 = 100: Name 12.5, **Arithmetic 12.5 × 5**, Shape 12.5,
Combo 12.5. Arithmetic is 62.5 of the 100 — the calculator is the tool that
matters most. Every problem gets **three attempts, best counts** ("repetition in
your logs is expected"). A problem that scores zero **ends its line** — related
problems after it are never asked at all (howto page), so a broken calculator
costs far more than its own 12.5.

### Sample data actually in the PDF

Only one artefact survives the PDF: the shape example's base64 is clipped at
`iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAB2ElEQVR4nO3c226CQBRG4U0hKHe+/zNioiaK4`
— 85 characters, not a whole image. Its IHDR decodes to **100×100, 8-bit,
colour type 2 (truecolour RGB), non-interlaced**, which is what our decoder is
tuned for. The worked examples on pages 2–3 are screenshots; the PDF carries no
embedded images, so there are no verbatim request/response pairs to copy. Our
tests therefore generate PNGs of known shapes instead.

## Hard limits (from the linked /limits page — apply to every sheet)

| limit | value |
|---|---|
| tokens per tool response | **1,200** (`tiktoken` `o200k_base` over the returned text) |
| response time | **10 seconds** |
| tools read from our server | **first 20** we list; the rest are never offered |

An over-limit response is **discarded whole** — the android is told it was too
large, it is not truncated. Tool names, descriptions and parameter names must be
"reasonably sized" or the tool is not offered at all. Our four tools answer in
under ~20 tokens each, so we are nowhere near the ceiling.

## How to read a failing run (from the linked /howto page)

A run posts a summary URL to our callback; it nests run → problem → attempt →
call, and each call shows **the android's own stated reason for making it**, the
arguments we received, our response, whether it was accepted/refused/discarded,
our latency and our token cost. It also shows **the tools as they read them** —
the only place we see our own schemas the way the model sees them. Check that
page once, early. The link is a bearer secret: whoever holds it reads our runs.

## Design decisions

**Hand-rolled MCP, not FastMCP.** The qna page says the single commonest way to
lose a run is mounting `mcp.http_app()` into FastAPI without passing its
lifespan: routes exist, health passes, every `/mcp/` request 500s. It also warns
that on a small free instance *imports* are what exhaust memory. `app/mcp.py` is
a ~200-line JSON-RPC 2.0 handler over the Streamable HTTP transport with no new
dependency, no lifespan, no session manager and nothing to forget to start —
that entire failure mode cannot happen to us, and both `/mcp` and `/mcp/` are
registered explicitly rather than relying on a 307.

**Protocol surface:** `initialize`, `notifications/initialized` (→ 202, no
body), `tools/list`, `tools/call`, `ping`, plus empty `resources/list` and
`prompts/list` for clients that probe them regardless. `GET /mcp` and
`DELETE /mcp` return 405, which is what the spec prescribes for a server that
offers no server-initiated SSE stream and no sessions. We are **stateless** — we
never issue an `Mcp-Session-Id`, so a Render spin-down mid-run cannot invalidate
a session. We echo the client's `protocolVersion` when we know it and fall back
to our newest otherwise, and we answer `application/json` unless the client's
`Accept` asks only for `text/event-stream`, in which case we frame the same JSON
as one SSE `message` event.

**Tool errors are results, not JSON-RPC errors** (`isError: true` with a short
plain-text reason). A JSON-RPC error can abort the agent's turn; an `isError`
result is handed to the android, which still has two attempts left to fix its
arguments. Nothing in the MCP path can return 500 — the handler catches
everything.

**Every tool returns the bare answer, with no exceptions.** `4`, `circle`,
`Milo`. The android does not check our work and does not strip prose: it
repeats a tool result verbatim, so anything decorative is submitted as the
answer. `calculate` originally returned `2 + 2 = 4` on the theory that echoing
the expression let the model check what it had sent. Three graded runs killed
that theory outright — see below. There is now a test asserting the calculator
returns a number and nothing else.

**Arithmetic is a real parser, never `eval`.** `app/expr.py` is a recursive
descent parser over `+ - * / ( )` and unary minus. `eval` on grader-supplied
text in a public repo is the obvious way to hand someone our process; the parser
also lets us reject nonsense cleanly instead of raising. Integer in, integer out
(`7 / 2` → `3.5`, `6 / 3` → `2`, not `2.0`) since the expected type is "a
number" and a trailing `.0` reads as a different answer.

**Shape detection is pure Python** (`app/pngshape.py`): a PNG decoder (colour
types 0/2/3/4/6, bit depths 1–16, non-interlaced) then convex hull →
Ramer–Douglas–Peucker → vertex count, with circularity `4πA/P²` as the tiebreak.
No Pillow, no numpy: the qna page warns that imports are what kill free-tier
instances, and the whole classifier is ~15 ms on the 100×100 images the
statement uses.

## Verified before handing over

- Driven end-to-end with the **official `mcp` Python SDK client** (a scratch
  venv, not a project dependency) against both `/mcp` and `/mcp/`: initialize,
  tools/list, ping and every tool. Our own tests speak the wire protocol; this
  proves a real client agrees with them.
- Measured with `tiktoken` `o200k_base`: tool descriptors 46–98 tokens each,
  tool answers **2–8 tokens** against the 1,200 ceiling.
- Shape classifier: 309/312 correct over a full 5° rotation sweep of every
  shape, filled and outlined, at three canvas sizes, ~13 ms each. All three
  misses are shapes drawn *larger than their canvas*, where the visible figure
  genuinely is not the nominal one — a triangle with its apex cut off, a square
  rotated 45° with all four corners cut, a circle wider than the frame. A shape
  clipped on **one** side is reconstructed and read correctly.

## Assumptions we made

- **The name is `Toolbox`**, overridable without a code change by the
  `AGENT_NAME` env var on Render. It satisfies the stated criteria (7 chars,
  letters only). If an invalid name is ever configured we fall back to the
  default rather than answer something the grader must reject.
- **`count_characters` is a hedge for the Combo Challenge**, whose details are
  only visible on the post-run summary page. Counting is the one thing an LLM
  provably cannot do unaided, and it cannot be confused with the other three
  tools. If the run summary shows the android reaching for it on the wrong
  problem, delete it — we are 16 tools below the cap, so it costs nothing to
  keep otherwise.
- **`calculate` advertises one required parameter, `expression`**, but the
  handler also accepts `a`/`operator`/`b`, `lhs`/`rhs`, or a bare `text`
  field, and strips a leading `What is`/trailing `?`. A simple schema is what
  the model uses well; the leniency is only there so a malformed call spends a
  retry instead of losing the line.
- **Operands outside −100..100 are still computed.** The range is the grader's
  constraint on what it will ask, not a validation rule for us; refusing would
  lose a problem we could have answered.
- **Division by zero** returns an `isError` result saying so, rather than a
  number. There is no right number to give.
- **Non-integer results keep full float precision** and are formatted with up to
  10 significant digits, trailing zeros stripped.
- **Shape: the background is the border colour**, taken as the most common
  colour around the image edge, with alpha respected when the PNG has it. We
  classify the **largest connected foreground component**, so axis labels or
  stray marks do not move the answer.
- **Interlaced (Adam7) PNGs are refused** with an `isError` result. The
  statement's own example is non-interlaced and no common generator emits
  interlaced; supporting it is untested code we would be trusting blind.
- **Images are capped** at 4096×4096, 16 M pixels and 8 MB of base64, and
  analysis subsamples anything over 400×400. A decompression bomb is the one
  hostile input this endpoint plausibly sees, and the 10 s limit is unforgiving.
- **`data:image/png;base64,` prefixes, whitespace, newlines and url-safe base64
  are all accepted** — the android may hand back the image in any of those forms.
- **A shape clipped by the image frame on two or more sides may be misread.**
  We put back a corner the frame cut off where the two edges either side of a
  border edge meet outside the image, which covers a single-sided clip; a figure
  cut on several sides is no longer one of the three shapes. Not worth more
  code unless a run summary shows it happening.
- **Cold start is the real risk, not the tool code.** A tool must answer inside
  10 s and the free instance takes ~50 s to wake, so the first call of a run
  would time out on a cold server. Warm it with `scripts/smoke.sh` immediately
  before triggering a run, per iron rule 2 — that is the whole mitigation.

## Clarifications from challenge developers

- Q: The Combo Challenge says "orchestrate the previous tools" — is it scored on
  the final answer only, or on the call sequence? → A: …
- Q: For arithmetic, is `6 / 4` expected as `1.5`, and is a trailing `.0` on an
  integral result (`2.0` vs `2`) marked wrong? → A: …
- Q: Is the name compared exactly against what our tool returns, or does the
  android get to paraphrase it? → A: …

## Failed test cases and what fixed them

Three stage-1 runs on 2026-08-22 scored **12, 50, 12** out of 100. Run records:
`/run/<teamId>/summary` and `/run/<teamId>/runs/<runId>` on the challenge host,
which is what the viewer page reads.

### The calculator's expression echo — cost up to 75 points

The run record shows the android's submitted answer next to our tool output:

| we returned | android submitted | score |
|---|---|---|
| `2 + 2 + 5 = 9` | `2 + 2 + 5 = 9` (×5 attempts) | **0.0** |
| `-9 * 2 + 2 = -16` | `-9 * 2 + 2 = -16` (×3) | **0.0** |
| `2 + 2 + 5 = 9` | `9` (once, attempt 3) | 12.5 |
| `5 * 20 / 10 = 10` | `10` | 12.5 |
| `50 + 16 + 21 = 87` | `87` | 12.5 |
| `circle` / `rectangle` / `triangle` | same word | 12.5 |

Same tool output, different score: the android usually parrots the whole string
and occasionally strips it to the number. The expected answer type is *a
number*, so the echo is a wrong answer. Because a zero **ends its chain**, the
first arithmetic problem failing took the other four arithmetic problems and the
combo challenge with it — 62.5 + 12.5 points that were never even asked for.
**Fix:** `calculate` returns the number alone.

### The name — 0 for 9 attempts, no answer ever submitted

Every name attempt in all three runs shows our call succeeding
(`outcome: ok`, `result: "Toolbox"`, 2 tokens) and then **no `evaluation` block
at all** — unlike every other problem, which records `Final answer submitted:
…`. The android took the word and then submitted nothing.

We cannot see its final turn, so this is inference rather than proof: `Toolbox`
is the challenge's own noun, and an android taught never to guess is being handed
the name of the *thing it is holding* when it asks what **it** is called.
**Fix, two parts:** the name is now `Milo`, which cannot be read as anything but
a name; and `get_my_name`'s description is rewritten in the same shape as
`identify_shape`'s — the one tool that scored in all three runs — saying what the
tool does and what comes back, instead of instructing the android how to answer.
If a further run still shows no answer submitted, the next thing to try is the
tool name itself (`my_name`, `whoami`).

### What was already right

`identify_shape` scored 12.5 in all three runs and got all three combo shapes
right. Re-running the six real PNGs from the run records through the current
code returns the same answers. `count_characters` was never called — the combo
turned out to be shape × arithmetic — but it is 1 of 4 tools against a cap of
20, so it stays for sheets 2 and 3.
