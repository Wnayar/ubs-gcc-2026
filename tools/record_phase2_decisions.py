#!/usr/bin/env python3
"""Record the two-seat regression fixture that guards phases 1 and 2.

`tests/test_showdown_phase3.py` replays `tests/data/phase2_decisions.json` and
demands every reply come back byte-for-byte. Phase 3's additions are all the
identity at one opponent, so any difference is a bug in phase 3, not a retune.

RUN THIS AGAINST A CHECKOUT THAT PREDATES PHASE 3 — otherwise the fixture
records the behaviour it is supposed to be checking and proves nothing. The
guard below refuses to run anywhere else:

    git worktree add /tmp/mainbase <commit-before-phase-3>
    cd /tmp/mainbase && python3 tools/record_phase2_decisions.py \\
        /path/to/repo/tests/data/phase2_decisions.json

Re-record only when the phase 2 engine is *deliberately* retuned (as happened
when live results pushed CALL_RISK to 0.55 and the bet sizes up), and say so in
docs/decisions.md when you do.
"""
from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.getcwd())

import app.showdown as engine  # noqa: E402

DEFAULT_OUT = "tests/data/phase2_decisions.json"


def states(count: int = 400):
    """A deterministic spread of two-seat spots: both rounds, every legal set,
    bets from nothing to more than our stack, and three betting histories."""
    rng = random.Random(17)
    for _ in range(count):
        n = rng.randint(1, 13)
        c = rng.choice([None] + list(range(1, 14)))
        pot = rng.randint(2, 200)
        to_call = rng.choice([0, 0, 4, 18, 60, 202])  # 202 exceeds any stack
        stack = rng.randint(1, 200)
        legal = ["fold", "call", "raise"] if to_call else ["check", "bet"]
        yield {
            "protocol_version": 2, "match_id": "regress", "phase": 2,
            "table_rule": "standard",  # pinned, so the store cannot drift the result
            "small_blind": 1, "big_blind": 2,
            "starting_stack": 200, "your_stack": stack,
            "hand_number": rng.randint(1, 40), "total_hands": 40,
            "leg_number": rng.choice([None, 1, 3, 4]), "total_legs": 4,
            "round": "pre_reveal" if c is None else "post_reveal",
            "your_number": n, "community_number": c,
            "your_seat": 0, "button_seat": rng.choice([0, 1]),
            "pot": pot, "to_call": to_call,
            "min_raise_to": min(to_call + 2, stack), "max_raise_to": stack,
            "legal_actions": legal,
            "players": [
                {"seat": 0, "name": "you", "folded": False,
                 "chip_delta": rng.randint(-100, 100), "bet_this_round": 0,
                 "stack": stack, "all_in": False, "busted": False},
                {"seat": 1, "name": "Wren", "folded": False,
                 "chip_delta": rng.randint(-100, 100), "bet_this_round": to_call,
                 "stack": 200, "all_in": False, "busted": False},
            ],
            "current_hand_actions": rng.choice([
                [],
                [{"round": "post_reveal", "seat": 1, "action": "bet", "amount": to_call}],
                [{"round": "post_reveal", "seat": 1, "action": "bet", "amount": 6},
                 {"round": "post_reveal", "seat": 0, "action": "raise", "amount": 20},
                 {"round": "post_reveal", "seat": 1, "action": "raise", "amount": to_call}],
            ]),
            "recent_hands": [],
        }


def main() -> int:
    if hasattr(engine, "field_share"):
        print("REFUSING: app.showdown already has phase 3 in it (field_share exists).\n"
              "Recording here would capture the behaviour the fixture is meant to\n"
              "check. Run this from a worktree of a pre-phase-3 commit.", file=sys.stderr)
        return 1

    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    rows = [{"state": s, "reply": engine.decide(s)} for s in states()]
    with open(out, "w") as fh:
        json.dump(rows, fh, indent=0)

    tally: dict[str, int] = {}
    for row in rows:
        action = row["reply"]["action"]
        tally[action] = tally.get(action, 0) + 1
    print(f"{len(rows)} spots -> {out}")
    print("  engine: RAISE_RISK=%s CALL_RISK=%s SIZE_STRONG=%s"
          % (engine.RAISE_RISK, engine.CALL_RISK, engine.SIZE_STRONG))
    print("  " + "  ".join(f"{a}={n}" for a, n in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
