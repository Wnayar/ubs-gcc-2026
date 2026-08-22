# UBS Global Coding Challenge 2026 — team repo

One-day competition (2026-08-22, Singapore). UBS releases ONE product statement in
phases of increasing complexity on their "controller" platform. Each phase: save the
statement PDF to docs/phases/<challenge>/, implement it in this service, deploy, submit
our base URL to the controller, which runs test cases and scores us on a leaderboard.
Security, reliability and product judgment are scored, not just correctness.

## Layout
- `app/main.py` — FastAPI app; auto-mounts every `app/routers/*.py` exposing a
  module-level `router` — adding a phase never touches main.py (keeps branches conflict-free)
- `app/reqlog.py` — middleware logging every request/response (ring buffer + stdout JSON lines)
- `GET /debug/requests?token=$DEBUG_TOKEN` — see exactly what the grader sent us and what we replied
- `docs/phases/<challenge>/` — statement PDF + notes.md, one folder per statement,
  named after the challenge (`tool-box-1`, not `phase-4`); copy TEMPLATE.md
- `docs/decisions.md` — change/decision log, kept current for Product Owner check-ins
- `docs/entry-challenge/` — the qualifying-round problem and our solution, for style reference
- `LINKS.md` — deployed service URL(s); if we ever split into multiple services, every service's URL goes there, one line per service labelled with its challenge
- `scripts/dev.sh` — run locally with reload; `scripts/smoke.sh <url>` — curl checks

## Iron rules
1. Never break an earlier phase's endpoints — the grader may re-run them. Run `pytest` before every push.
2. Deploy = push to `main` (Render auto-deploys, ~2 min). Verify with `scripts/smoke.sh <url>`; `GET /health` shows the live commit hash.
   We stay on the free plan (team decision): the service spins down after ~15 idle
   minutes and takes ~50 s to wake. No keep-warm cron — the smoke test doubles as the
   warm-up, so submit to the controller right after smoking, without a long pause.
   After the first deploy (or if the service is ever recreated): copy DEBUG_TOKEN from
   Render dashboard → service → Environment into the local `.env` (gitignored) so
   Claude can pull `/debug/requests` from the live server when a grader run fails.
3. Debug locally, not on Render: `scripts/dev.sh` + `pytest`. Every push-to-debug round costs a ~2 min deploy.
4. Per phase, on its own branch: branch off main (named after the challenge) → save
   PDF → notes.md → turn the statement's examples into tests → implement → green
   locally → push branch (smoke on its branch preview server if one exists) → merge
   to main → smoke → submit the MAIN URL to controller → one line in decisions.md.
   Never implement directly on main; main only changes by merging finished branches.
   Fast path: drop the PDF in `docs/inbox/` and run `/phase` — Claude does everything
   up to the push, then hands off for review.
5. No secrets in this repo — it is public.
6. Commit messages: plain description only, no AI-attribution lines.

## Branch preview servers (fast iteration without touching main)

Each phase is developed on its own branch. For a live preview of a branch, create a
Render service pinned to it: Dashboard → New → Web Service → this repo → pick the
branch → free instance (PR Preview Environments need a paid plan, so we create these
by hand). It auto-deploys on every push to that branch; delete the service when the
branch merges. Rules:
- Branch URLs are for smoking/debugging only — the controller ALWAYS gets the main
  service URL (the grader may re-run earlier phases, which live on main).
- Each branch service generates its OWN DEBUG_TOKEN (service → Environment tab).
- List active branch service URLs in `LINKS.md`, labelled with the branch; remove
  the line when the service is deleted.
- Free instances cold-start (~50 s) and share the monthly free-hours pool — fine
  for competition day, but delete stale ones.

## Backup plan (only if a statement forces one server per challenge — we don't expect this)

Default is ONE service, one URL, all phase routers mounted — don't split preemptively.
If a statement forces separate servers: add more entries to the `services:` list in
`render.yaml` (same repo, `branch: main`, unique `name` → unique URL) and push. The
Blueprint sync creates the new services; every push to main then rebuilds all of them
in parallel with the same commit — `/health` shows one hash to verify across URLs.
Only if a challenge demands isolation, gate router mounting behind a per-service env
var (e.g. `ROLE`) in main.py. Servers talking to each other is just outbound httpx
calls in a router — not a deployment concern. Note: `generateValue: true` gives each
service its OWN DEBUG_TOKEN — if we split, move DEBUG_TOKEN into a shared Render env
group so one token works on every server.
