"""SHOWDOWN phase 1 — docs/phases/phase-3/ (statement.pdf + showdown-guide.pdf).

The guide gives one fully worked /move request and no worked *reply*, so most of
these tests pin the rules the guide states in prose: reply with a legal action,
keep `amount` inside [min_raise_to, max_raise_to], omit `amount` for
check/call/fold, and never hand the coordinator anything it would substitute.
"""
import json
import random
import time

from fastapi.testclient import TestClient

from app.main import app
from app.showdown import equity, equity_vs_range

client = TestClient(app)

# ── verbatim from showdown-guide.pdf, "POST {your_base_url}/move" (pages 5-6) ──
GUIDE_EXAMPLE = {
    "protocol_version": 2,
    "match_id": "phase1-seed7",
    "phase": 1,
    "table_rule": "standard",
    "small_blind": 1,
    "big_blind": 2,
    "starting_stack": 200,
    "your_stack": 185,
    "hand_number": 6,
    "total_hands": 100,
    "round": "post_reveal",
    "your_number": 3,
    "community_number": 5,
    "your_seat": 0,
    "button_seat": 1,
    "pot": 32,
    "to_call": 18,
    "min_raise_to": 36,
    "max_raise_to": 185,
    "legal_actions": ["fold", "call", "raise"],
    "players": [
        {
            "seat": 0,
            "name": "you",
            "folded": False,
            "chip_delta": -8,
            "bet_this_round": 0,
            "stack": 185,
            "all_in": False,
            "busted": False,
        },
        {
            "seat": 1,
            "name": "Gaston",
            "folded": False,
            "chip_delta": 8,
            "bet_this_round": 18,
            "stack": 183,
            "all_in": False,
            "busted": False,
        },
    ],
    "current_hand_actions": [
        {"round": "pre_reveal", "seat": 1, "action": "raise", "amount": 7},
        {"round": "pre_reveal", "seat": 0, "action": "call", "amount": 7},
        {"round": "post_reveal", "seat": 0, "action": "check"},
        {"round": "post_reveal", "seat": 1, "action": "bet", "amount": 18},
    ],
    "recent_hands": [
        {
            "hand_number": 2,
            "community_number": 13,
            "winners": [1],
            "pot": 24,
            "shown_numbers": {"0": 9, "1": 11},
            "actions": [
                {"round": "pre_reveal", "seat": 1, "action": "raise", "amount": 5},
                {"round": "pre_reveal", "seat": 0, "action": "call", "amount": 5},
                {"round": "post_reveal", "seat": 0, "action": "check"},
                {"round": "post_reveal", "seat": 1, "action": "bet", "amount": 7},
                {"round": "post_reveal", "seat": 0, "action": "call", "amount": 7},
            ],
        }
    ],
}


def move(**overrides):
    body = json.loads(json.dumps(GUIDE_EXAMPLE))
    body.update(overrides)
    return client.post("/move", json=body)


def assert_legal(response, state):
    """Every rule the guide states about a well-formed reply."""
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) <= {"action", "amount"}, body
    action = body.get("action")
    assert action in state["legal_actions"], f"{action} not in {state['legal_actions']}"
    if action in ("bet", "raise"):
        amount = body.get("amount")
        assert isinstance(amount, int) and not isinstance(amount, bool), body
        # "Keep amount inside [min_raise_to, max_raise_to]" — out of range counts
        # as an illegal move and gets substituted
        assert state["min_raise_to"] <= amount <= state["max_raise_to"], body
    else:
        # "Omit amount for check, call and fold."
        assert "amount" not in body, body
    return body


# ────────────────────────────── the worked example ──────────────────────────────


def test_guide_example_is_a_legal_reply():
    assert_legal(move(), GUIDE_EXAMPLE)


def test_guide_example_folds():
    # the guide's own reading: "it's your turn holding a 3 — no pair, no
    # straightforward call". A 3 against a community 5 only beats a 1 or a 2,
    # so 19% equity (with the split) against 18/(32+18) = 36% pot odds.
    assert move().json() == {"action": "fold"}


# ─────────────────────────────── equity (the maths) ──────────────────────────────


def test_equity_pre_reveal_matches_closed_form():
    # your number n, opponent's number and the community number both unknown:
    # P(win) = (11n+1)/169, P(tie) = 13/169
    for n in range(1, 14):
        assert equity(n, None) == (11 * n + 7.5) / 169


def test_equity_pre_reveal_is_symmetric_around_seven():
    assert equity(7, None) == 0.5
    assert equity(1, None) + equity(13, None) == 1.0


def test_equity_post_reveal_pair_is_near_certain():
    # "any pair beats any non-pair"; only the opponent holding the same number
    # (a split) stops us, so 12/13 wins + 1/13 tie
    for n in range(1, 14):
        assert equity(n, n) == (12 + 0.5) / 13


def test_equity_post_reveal_counts_only_lower_numbers_that_are_not_the_community():
    # holding 13 with a community 5: we lose to the opponent pairing (they hold
    # a 5), split when they hold 13, and beat the other 11 numbers
    assert equity(13, 5) == (11 + 0.5) / 13
    # holding 1 with a community 5: nothing to beat, only the split
    assert equity(1, 5) == 0.5 / 13


# ───────────────────────── rules the guide states in prose ──────────────────────


def test_checking_is_free_so_trash_never_folds():
    # fold "only appears when someone has bet at you"; when check is legal a bot
    # that folds is setting money on fire
    body = move(
        round="post_reveal",
        your_number=2,
        community_number=11,
        to_call=0,
        pot=10,
        min_raise_to=2,
        max_raise_to=185,
        legal_actions=["check", "bet"],
    ).json()
    assert body["action"] in ("check", "bet")


def test_pair_post_reveal_puts_money_in():
    # a pair is 96% to win — checking it back or folding it is a leak
    state = dict(
        GUIDE_EXAMPLE,
        round="post_reveal",
        your_number=9,
        community_number=9,
        to_call=0,
        pot=20,
        min_raise_to=2,
        max_raise_to=185,
        legal_actions=["check", "bet"],
    )
    body = assert_legal(client.post("/move", json=state), state)
    assert body["action"] == "bet"


def test_pair_post_reveal_raises_a_bet():
    state = dict(GUIDE_EXAMPLE, your_number=5, community_number=5)
    body = assert_legal(client.post("/move", json=state), state)
    assert body["action"] == "raise"


def test_big_number_pre_reveal_raises():
    state = dict(
        GUIDE_EXAMPLE,
        round="pre_reveal",
        community_number=None,
        your_number=13,
        pot=3,
        to_call=1,
        min_raise_to=4,
        max_raise_to=199,
        legal_actions=["fold", "call", "raise"],
    )
    body = assert_legal(client.post("/move", json=state), state)
    assert body["action"] == "raise"


def test_trash_pre_reveal_does_not_pay_a_big_raise():
    state = dict(
        GUIDE_EXAMPLE,
        round="pre_reveal",
        community_number=None,
        your_number=2,
        pot=60,
        to_call=40,
        min_raise_to=80,
        max_raise_to=185,
        legal_actions=["fold", "call", "raise"],
    )
    body = assert_legal(client.post("/move", json=state), state)
    assert body["action"] == "fold"


def test_min_raise_equal_to_max_raise_is_still_legal():
    # "If the two are equal, betting your whole stack is the only raise you can
    # afford — and it is legal."
    state = dict(
        GUIDE_EXAMPLE, your_number=7, community_number=7, min_raise_to=185, max_raise_to=185
    )
    body = assert_legal(client.post("/move", json=state), state)
    assert body == {"action": "raise", "amount": 185}


def test_amount_is_a_round_total_not_an_increment():
    # "amount is the total you will have put in for that betting round ... If
    # you've already put in 6 this round and want to add 18 more, send 24."
    state = json.loads(json.dumps(GUIDE_EXAMPLE))
    state["your_number"] = 11
    state["community_number"] = 11
    state["to_call"] = 12
    state["pot"] = 40
    state["min_raise_to"] = 30
    state["max_raise_to"] = 185
    state["players"][0]["bet_this_round"] = 6
    state["players"][1]["bet_this_round"] = 18
    body = assert_legal(client.post("/move", json=state), state)
    # calling costs 12 to reach 18, so any raise total must clear that outright
    assert body["action"] == "raise"
    assert body["amount"] >= 30


# ──────────────────────── never hand back an illegal move ───────────────────────


def random_state(rng):
    pre = rng.random() < 0.5
    stack = rng.randint(1, 400)
    pot = rng.randint(2, 300)
    to_call = rng.choice([0, 0, rng.randint(1, min(stack, 200))])
    seat = rng.choice([0, 1])
    if to_call:
        legal = ["fold", "call"]
        opener = "raise"
    else:
        legal = ["check"]
        opener = "bet"
    can_open = rng.random() < 0.8 and stack > to_call
    min_raise_to = max_raise_to = None
    if can_open:
        legal.append(opener)
        min_raise_to = to_call + rng.randint(1, 10)
        max_raise_to = max(min_raise_to, stack)
    return {
        "protocol_version": 2,
        "match_id": f"seed{rng.randint(0, 99)}",
        "phase": 1,
        "table_rule": "standard",
        "small_blind": 1,
        "big_blind": 2,
        "starting_stack": 200,
        "your_stack": stack,
        "hand_number": rng.randint(1, 100),
        "total_hands": 100,
        "round": "pre_reveal" if pre else "post_reveal",
        "your_number": rng.randint(1, 13),
        "community_number": None if pre else rng.randint(1, 13),
        "your_seat": seat,
        "button_seat": rng.choice([0, 1]),
        "pot": pot,
        "to_call": to_call,
        "min_raise_to": min_raise_to,
        "max_raise_to": max_raise_to,
        "legal_actions": legal,
        "players": [
            {
                "seat": s,
                "name": "you" if s == seat else "Gaston",
                "folded": False,
                "chip_delta": rng.randint(-100, 100),
                "bet_this_round": rng.randint(0, 20),
                "stack": stack if s == seat else rng.randint(1, 400),
                "all_in": False,
                "busted": False,
            }
            for s in (0, 1)
        ],
        "current_hand_actions": [],
        "recent_hands": [],
    }


def test_never_returns_an_illegal_move():
    rng = random.Random(20260822)
    for _ in range(400):
        state = random_state(rng)
        assert_legal(client.post("/move", json=state), state)


def test_survives_every_field_being_missing():
    # a reply the coordinator can use even if the protocol drifts under us
    r = client.post("/move", json={"legal_actions": ["check", "bet"]})
    assert r.status_code == 200
    assert r.json()["action"] in ("check", "bet")


def test_unknown_fields_are_ignored():
    # "ignore any field you don't recognise — we add fields over the course of
    # the event and never remove them"
    state = dict(GUIDE_EXAMPLE, table_rule="wild", surprise_field={"nested": [1, 2]})
    assert_legal(client.post("/move", json=state), GUIDE_EXAMPLE)


def test_garbage_bodies_still_get_a_usable_action():
    # a bad response is substituted with check and five in a row forfeits the
    # match, so there is never a reason to answer a /move with an error
    for body in ({}, {"legal_actions": []}, {"legal_actions": "check"}, {"pot": "lots"}):
        r = client.post("/move", json=body)
        assert r.status_code == 200, body
        assert r.json()["action"] in ("check", "call", "fold", "bet", "raise"), body


def test_non_json_body_still_gets_a_usable_action():
    r = client.post("/move", content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.json()["action"] == "check"


def test_replies_well_inside_the_five_second_budget():
    start = time.perf_counter()
    for _ in range(50):
        move()
    assert (time.perf_counter() - start) / 50 < 0.05


# ─────────────────────────────── iron rule 1 ────────────────────────────────


def test_earlier_phases_still_work():
    assert client.post("/square", json={"value": 5}).json() == {"result": 25}
    assert client.get("/health").status_code == 200


# ───────────────── reading the opponent's range (the anti-bust fix) ──────────────


def test_equity_vs_range_with_the_whole_deck_is_plain_equity():
    for n in range(1, 14):
        for c in [None, *range(1, 14)]:
            assert abs(equity_vs_range(n, c, 1) - equity(n, c)) < 1e-12


def test_equity_vs_range_falls_as_the_opponent_narrows():
    # a 12 is 83% against a random number and a coin flip against a range that
    # only ever holds 9 or better
    assert equity(12, None) > 0.82
    assert equity_vs_range(12, None, 9) < 0.70
    assert equity_vs_range(12, None, 12) < 0.40


def test_a_twelve_folds_pre_reveal_to_a_fourth_raise():
    # the leak that busted the first draft: raising a 12 on its vs-random
    # equity into an opponent who has already re-raised three times
    state = dict(
        GUIDE_EXAMPLE,
        round="pre_reveal",
        community_number=None,
        your_number=12,
        your_stack=169,
        pot=62,
        to_call=34,
        min_raise_to=48,
        max_raise_to=169,
        legal_actions=["fold", "call", "raise"],
        current_hand_actions=[
            {"round": "pre_reveal", "seat": 1, "action": "raise", "amount": 4},
            {"round": "pre_reveal", "seat": 0, "action": "raise", "amount": 9},
            {"round": "pre_reveal", "seat": 1, "action": "raise", "amount": 14},
            {"round": "pre_reveal", "seat": 0, "action": "raise", "amount": 31},
            {"round": "pre_reveal", "seat": 1, "action": "raise", "amount": 48},
        ],
    )
    body = assert_legal(client.post("/move", json=state), state)
    assert body["action"] != "raise", "re-raising here is how the bot goes broke"


def test_a_pair_still_re_raises_a_raising_war():
    # the same spot with an actual pair: the read does not talk us out of a
    # hand that is 96% to win
    state = dict(
        GUIDE_EXAMPLE,
        your_number=11,
        community_number=11,
        your_stack=169,
        pot=62,
        to_call=34,
        min_raise_to=48,
        max_raise_to=169,
        current_hand_actions=[
            {"round": "post_reveal", "seat": 1, "action": "bet", "amount": 14},
            {"round": "post_reveal", "seat": 0, "action": "raise", "amount": 34},
            {"round": "post_reveal", "seat": 1, "action": "raise", "amount": 48},
        ],
    )
    body = assert_legal(client.post("/move", json=state), state)
    assert body["action"] == "raise"


def test_a_shove_narrows_the_range_enough_to_beat_raw_pot_odds():
    # holding 7 against a community 8: beats 6 of 13 numbers, so vs a *random*
    # number it is 50% against 38% pot odds — a call. But the opponent has shoved
    # a pot-sized bet, and against the range that implies it is 31%, so raw pot
    # odds are the wrong comparison and this is a fold.
    state = dict(
        GUIDE_EXAMPLE,
        your_number=7,
        community_number=8,
        your_stack=120,
        pot=200,
        to_call=120,
        min_raise_to=None,
        max_raise_to=None,
        legal_actions=["fold", "call"],
        current_hand_actions=[
            {"round": "post_reveal", "seat": 1, "action": "bet", "amount": 120}
        ],
    )
    assert equity(7, 8) > 120 / (200 + 120)  # pot odds alone would call
    body = assert_legal(client.post("/move", json=state), state)
    assert body["action"] == "fold"


def test_no_raise_is_ever_larger_than_the_stack_allows():
    rng = random.Random(11)
    for _ in range(300):
        state = random_state(rng)
        body = assert_legal(client.post("/move", json=state), state)
        if body["action"] in ("bet", "raise"):
            assert body["amount"] <= state["max_raise_to"]


# ──────────────── hands the grader actually beat us with (2026-08-22) ────────────
# Attempt 1 on phase1-seed1382113882 scored 0: +44 at hand 13, then these three
# hands took the match. Every field is transcribed from GET /debug/requests on the
# live service. See docs/phases/showdown/phase-1/notes.md.


def live_state(**over):
    """A /move body shaped exactly like the coordinator's, seat 0."""
    state = {
        "protocol_version": 2,
        "match_id": "phase1-seed1382113882",
        "phase": 1,
        "table_rule": "standard",
        "small_blind": 1,
        "big_blind": 2,
        "starting_stack": 200,
        "total_hands": 100,
        "your_seat": 0,
        "button_seat": 1,
        "round": "post_reveal",
        "min_raise_to": None,
        "max_raise_to": None,
        "current_hand_actions": [],
        "recent_hands": [],
    }
    state.update(over)
    state.setdefault(
        "players",
        [
            {
                "seat": 0,
                "name": "you",
                "folded": False,
                "chip_delta": 0,
                "bet_this_round": 0,
                "stack": state["your_stack"],
                "all_in": False,
                "busted": False,
            },
            {
                "seat": 1,
                "name": "Gaston",
                "folded": False,
                "chip_delta": 0,
                "bet_this_round": 0,
                "stack": 200,
                "all_in": False,
                "busted": False,
            },
        ],
    )
    return state


def test_hand_55_never_folds_a_pair_to_a_bet_bigger_than_our_stack():
    # holding 11 on a community 11 — 96% to win — with 24 chips behind facing
    # to_call 202. `to_call` is NOT capped at our stack by the coordinator, and
    # treating it as a fraction of the stack made the risk term 8x any equity.
    state = live_state(
        hand_number=55,
        your_number=11,
        community_number=11,
        your_stack=24,
        pot=376,
        to_call=202,
        legal_actions=["fold", "call"],
        current_hand_actions=[
            {"round": "pre_reveal", "seat": 0, "action": "raise", "amount": 4},
            {"round": "pre_reveal", "seat": 1, "action": "raise", "amount": 9},
            {"round": "pre_reveal", "seat": 0, "action": "call", "amount": 9},
            {"round": "post_reveal", "seat": 1, "action": "bet", "amount": 22},
            {"round": "post_reveal", "seat": 0, "action": "raise", "amount": 78},
            {"round": "post_reveal", "seat": 1, "action": "raise", "amount": 280},
        ],
    )
    body = assert_legal(client.post("/move", json=state), state)
    assert body["action"] == "call", "folding a pair for 24 into a 376 pot is the leak"


def test_hand_72_never_folds_a_pair_to_a_bet_bigger_than_our_stack():
    state = live_state(
        hand_number=72,
        your_number=5,
        community_number=5,
        your_stack=18,
        pot=162,
        to_call=90,
        legal_actions=["fold", "call"],
        current_hand_actions=[
            {"round": "pre_reveal", "seat": 1, "action": "call", "amount": 2},
            {"round": "pre_reveal", "seat": 0, "action": "check"},
            {"round": "post_reveal", "seat": 0, "action": "bet", "amount": 4},
            {"round": "post_reveal", "seat": 1, "action": "raise", "amount": 19},
            {"round": "post_reveal", "seat": 0, "action": "raise", "amount": 34},
            {"round": "post_reveal", "seat": 1, "action": "raise", "amount": 124},
        ],
    )
    body = assert_legal(client.post("/move", json=state), state)
    assert body["action"] == "call"


def test_hand_19_does_not_stack_off_with_a_high_card_into_a_shove():
    # holding 13 on a community 7 is NOT a pair — it loses to exactly one number,
    # the 7, and a shove over our raise is overwhelmingly that 7. We called 117
    # of our 168 and lost 164 chips, the single hand that decided the match.
    state = live_state(
        hand_number=19,
        your_number=13,
        community_number=7,
        your_stack=168,
        pot=211,
        to_call=117,
        min_raise_to=209,
        max_raise_to=209,
        legal_actions=["fold", "call", "raise"],
        current_hand_actions=[
            {"round": "pre_reveal", "seat": 0, "action": "raise", "amount": 6},
            {"round": "pre_reveal", "seat": 1, "action": "call", "amount": 6},
            {"round": "post_reveal", "seat": 1, "action": "bet", "amount": 15},
            {"round": "post_reveal", "seat": 0, "action": "raise", "amount": 41},
            {"round": "post_reveal", "seat": 1, "action": "raise", "amount": 158},
        ],
    )
    state["players"][0]["bet_this_round"] = 41
    state["players"][1]["bet_this_round"] = 158
    body = assert_legal(client.post("/move", json=state), state)
    assert body["action"] == "fold"


def test_a_call_never_risks_more_than_our_stack():
    # the invariant behind both pair folds: whatever `to_call` says, we can only
    # ever lose what is in front of us
    rng = random.Random(55)
    for _ in range(200):
        state = random_state(rng)
        state["to_call"] = state["your_stack"] + rng.randint(1, 300)
        # the coordinator's `pot` always includes the live bet we are facing
        state["pot"] = state["to_call"] + rng.randint(2, 50)
        state["legal_actions"] = ["fold", "call"]
        state["min_raise_to"] = state["max_raise_to"] = None
        state["your_number"] = state["community_number"] = 9  # a pair, 96%
        state["round"] = "post_reveal"
        body = assert_legal(client.post("/move", json=state), state)
        assert body["action"] == "call", state
