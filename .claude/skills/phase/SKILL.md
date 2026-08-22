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

## 2. Start a branch — never implement on main

- Branch from up-to-date main, named after the challenge:
  `git fetch origin && git checkout -b <challenge-name> origin/main`
  (use the same name as the docs folder you'll create in step 3).
- If the working tree already has uncommitted changes, STOP and ask the user what to
  do with them before branching.
- All work for this phase happens on this branch. Main only changes by merging the
  finished branch — that's what keeps parallel phase work conflict-free.

## 3. File it

- Name the folder after the challenge, not a phase number — take the name from
  the statement itself (a PDF called `tool-box-1.pdf` becomes `tool-box-1`).
  Numbered `phase-N` folders are older ones; do not extend that scheme.
- `mkdir -p docs/phases/<name>` and MOVE (not copy) the PDF to
  `docs/phases/<name>/statement.pdf` so the inbox stays clean.

## 4. Read and extract

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

## 5. Tests first

Create `tests/test_<challenge>.py` (challenge name with underscores, e.g.
`tests/test_tool_box_1.py` — the numbered `test_phaseN.py` files are older ones,
do not extend that scheme) following the style of `tests/test_smoke.py`
(FastAPI `TestClient` against `app.main.app`, no live server):

- one test per worked example from the statement, asserting the exact expected output
- tests for malformed input (expect 422 from pydantic validation)
- tests for the edge cases and limits the statement mentions

Run `pytest` and confirm the new tests FAIL and all existing tests still PASS.
If a new test passes before any implementation exists, it is testing nothing — fix it.

## 6. Implement

- Create `app/routers/<challenge>.py` (underscores) in the style of the existing
  phase routers (e.g. `app/routers/toolbox.py`; the numbered `phaseN.py` routers
  are older ones):
  pydantic models for request/response, an `APIRouter(tags=["<name>"])`.
- Do NOT edit `app/main.py` — it auto-discovers and mounts any module in
  `app/routers/` that exposes a module-level `router`.
- Validate inputs strictly; never 500 on bad input (security/reliability are scored).
- Iterate with `pytest` until the ENTIRE suite is green — all phases, not just this one.

## 7. Log and hand off — do NOT push

- Append one line to `docs/decisions.md`: what the challenge required, what was shipped,
  and any judgment calls.
- Then STOP and give the user a summary containing:
  1. what the phase requires (one paragraph) and the endpoints you added
  2. the assumptions/ambiguities they should double-check against the PDF
  3. pytest result (full suite)
  4. a proposed plain-description commit message (no AI-attribution lines)
  5. the remaining manual steps, in this order:
     - `git push -u origin <challenge-name>` (the branch, not main)
     - optional preview: if a Render branch service exists for this branch it
       auto-deploys — `./scripts/smoke.sh <branch-url>` there (see CLAUDE.md
       "Branch preview servers"; branch URLs are NEVER submitted to the controller)
     - merge to main: `git checkout main && git pull && git merge <challenge-name>
       && git push` — this deploys the graded service (~2 min)
     - `./scripts/smoke.sh <main-url>`, check `/health` commit hash matches
     - submit the MAIN service URL to the controller

Never push or merge yourself unless the user explicitly says to. If the user says
"push" after reviewing, commit with the proposed message and push the branch; if they
say "merge" or "ship", also do the merge-to-main step — then remind them of the
smoke-test and submission steps either way.
