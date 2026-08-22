---
name: phase
description: Run the full per-phase pipeline from a statement PDF — file it, extract the spec into notes.md, generate tests from the statement's examples, scaffold and implement the router, get pytest green, then stop for the user to review and push.
argument-hint: "[path-to-pdf] (optional — defaults to newest PDF in docs/inbox/)"
---

# /phase — statement PDF to green tests, in one shot

You are running one phase of the UBS GCC 2026 competition workflow. The user dumps a
statement PDF; you do everything up to (but not including) `git push`. Follow the
repo's iron rules in CLAUDE.md at all times — especially: never break an earlier
phase's endpoints, and debug locally, never on Render.

## 1. Get the PDF from the user — never go looking for it

- If an argument was given: a local path is used as-is; an http(s) link is downloaded
  with curl into `docs/inbox/`.
- Otherwise, if the user has dropped a `*.pdf` into `docs/inbox/`, take the newest one.
- Otherwise ASK the user for the path or link and STOP until answered. Never search
  Downloads, the home directory, or anywhere else for candidate PDFs, and never guess
  which file the user means — the statement must come explicitly from the user.

## 2. File it

- Name the folder after the challenge, not a phase number — take the name from
  the statement itself (a PDF called `tool-box-1.pdf` becomes `tool-box-1`).
  Numbered `phase-N` folders are older ones; do not extend that scheme.
- `mkdir -p docs/phases/<name>` and MOVE (not copy) the PDF to
  `docs/phases/<name>/statement.pdf` so the inbox stays clean.

## 3. Read and extract

Read the entire PDF with the Read tool (use `pages` in ≤20-page chunks until you have
read every page — never skim or stop early; late pages often carry edge cases and
scoring rules). Then write `docs/phases/<name>/notes.md` starting from
`docs/phases/TEMPLATE.md`, filled in with:

- every required endpoint: method, path, request/response JSON shape
- **all worked examples from the statement, copied verbatim** — these become tests
- edge cases, constraints, limits, and anything about scoring/penalties
- an "Assumptions we made" list for anything ambiguous, each with your chosen
  interpretation — flag these to the user in your final summary so they can be
  raised with the challenge developers

## 4. Tests first

Create `tests/test_phaseN.py` following the style of `tests/test_smoke.py`
(FastAPI `TestClient` against `app.main.app`, no live server):

- one test per worked example from the statement, asserting the exact expected output
- tests for malformed input (expect 422 from pydantic validation)
- tests for the edge cases and limits the statement mentions

Run `pytest` and confirm the new tests FAIL and all existing tests still PASS.
If a new test passes before any implementation exists, it is testing nothing — fix it.

## 5. Implement

- Create `app/routers/phaseN.py` in the style of the existing phase routers
  (e.g. `app/routers/phase1.py`):
  pydantic models for request/response, an `APIRouter(tags=["<name>"])`.
- Mount it in `app/main.py` next to the `# phase routers get added here` comment.
- Validate inputs strictly; never 500 on bad input (security/reliability are scored).
- Iterate with `pytest` until the ENTIRE suite is green — all phases, not just this one.

## 6. Log and hand off — do NOT push

- Append one line to `docs/decisions.md`: what the challenge required, what was shipped,
  and any judgment calls.
- Then STOP and give the user a summary containing:
  1. what the phase requires (one paragraph) and the endpoints you added
  2. the assumptions/ambiguities they should double-check against the PDF
  3. pytest result (full suite)
  4. a proposed plain-description commit message (no AI-attribution lines)
  5. the remaining manual steps: `git push`, wait ~2 min, `./scripts/smoke.sh <url>`,
     check `/health` commit hash matches, submit URL to the controller.

Never push yourself unless the user explicitly says to. If the user says "push"
after reviewing, commit with the proposed message and push, then remind them of the
smoke-test and submission steps.
