# UBS Global Coding Challenge 2026

Team service for the UBS Global Coding Challenge finals (Singapore, 22 Aug 2026).
One product, released in phases of increasing complexity throughout the day — this
repo holds the single FastAPI service that grows a router per phase, plus the docs
trail (statements, clarifications, decision log) the format asks for.

## Stack

FastAPI + Uvicorn, deployed on Render (Singapore region) with auto-deploy from
`main`. `render.yaml` is the full infrastructure definition.

## Running locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./scripts/dev.sh          # serve on :8000 with reload
.venv/bin/pytest -q       # tests
./scripts/smoke.sh        # curl the running local instance
```

## Workflow per phase

1. Statement drops → save the PDF to `docs/phases/phase-N/statement.pdf`, start `notes.md` from the template.
2. Turn the statement's worked examples into tests.
3. Implement as a new router in `app/routers/`, mount it in `app/main.py`.
4. Green locally → push to `main` → Render deploys (~2 min) → `./scripts/smoke.sh https://<service>.onrender.com`.
5. Submit the URL to the controller; log the outcome in `docs/decisions.md`.

## Observability

Every request/response is logged (stdout JSON lines + in-memory ring buffer).
`GET /debug/requests?token=...&only_errors=true` shows exactly which grader
payloads failed and what we replied — no dashboard digging mid-competition.
