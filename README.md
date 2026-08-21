# UBS Global Coding Challenge 2026

Team service for the UBS Global Coding Challenge finals (Singapore, 22 Aug 2026).
One product, released in phases of increasing complexity throughout the day. This
repo holds the single FastAPI service that grows a router per phase, plus the docs
trail (statements, clarifications, decision log) the format asks for.

New to the setup? Read `docs/design.md` first: the full operating flow, the
architecture, and the debugging playbook, written for the whole team.

## Stack

FastAPI + Uvicorn, deployed on Render (Singapore region) with auto-deploy from
`main`. `render.yaml` is the full infrastructure definition. Live at
<https://ubs-gcc-2026.onrender.com>; `GET /health` shows the running commit hash.

## Running locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./scripts/dev.sh          # serve on :8000 with reload
.venv/bin/pytest -q       # tests
./scripts/smoke.sh        # curl the running local instance
```

## Workflow per phase

Fast path: drop the statement PDF into `docs/inbox/` and run `/phase` in Claude
Code. It files the PDF, writes notes and tests, implements the router, gets the
suite green, then stops for human review before anything is pushed.

The same steps by hand:

1. Statement drops: save the PDF to `docs/phases/phase-N/statement.pdf`, start `notes.md` from the template.
2. Turn the statement's worked examples into tests.
3. Implement as a new router in `app/routers/`, mount it in `app/main.py`.
4. Green locally, push to `main`, Render deploys in about a minute, then `./scripts/smoke.sh https://ubs-gcc-2026.onrender.com`.
5. Submit the URL to the controller; log the outcome in `docs/decisions.md`.

## Observability

Every request/response is logged (stdout JSON lines plus an in-memory ring
buffer). `GET /debug/requests?token=...&only_errors=true` shows exactly which
grader payloads failed and what we replied, no dashboard digging mid-competition.
