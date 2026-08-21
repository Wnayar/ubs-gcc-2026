# UBS Global Coding Challenge 2026 — team repo

One-day competition (2026-08-22, Singapore). UBS releases ONE product statement in
phases of increasing complexity on their "controller" platform. Each phase: save the
statement PDF to docs/phases/phase-N/, implement it in this service, deploy, submit
our base URL to the controller, which runs test cases and scores us on a leaderboard.
Security, reliability and product judgment are scored, not just correctness.

## Layout
- `app/main.py` — FastAPI app; each phase adds a router in `app/routers/`, mounted here
- `app/reqlog.py` — middleware logging every request/response (ring buffer + stdout JSON lines)
- `GET /debug/requests?token=$DEBUG_TOKEN` — see exactly what the grader sent us and what we replied
- `docs/phases/phase-N/` — statement PDF + notes.md per phase (copy TEMPLATE.md)
- `docs/decisions.md` — change/decision log, kept current for Product Owner check-ins
- `docs/entry-challenge/` — the qualifying-round problem and our solution, for style reference
- `LINKS.md` — controller URL, deployed URL
- `scripts/dev.sh` — run locally with reload; `scripts/smoke.sh <url>` — curl checks

## Iron rules
1. Never break an earlier phase's endpoints — the grader may re-run them. Run `pytest` before every push.
2. Deploy = push to `main` (Render auto-deploys, ~2 min). Verify with `scripts/smoke.sh <url>`; `GET /health` shows the live commit hash.
3. Debug locally, not on Render: `scripts/dev.sh` + `pytest`. Every push-to-debug round costs a ~2 min deploy.
4. Per phase: save PDF → notes.md → turn the statement's examples into tests → implement → green locally → push → smoke → submit URL to controller → one line in decisions.md.
5. No secrets in this repo — it is public.
6. Commit messages: plain description only, no AI-attribution lines.
