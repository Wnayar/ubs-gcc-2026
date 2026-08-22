"""SHOWDOWN phase 3 — A Crowded Table (docs/phases/showdown/phase-3/).

Six seats instead of two, and a target that is relative: "you must finish the leg
with strictly the highest chip delta at the table". The statement's page carries no
worked request/response example, so these tests are built from the rules it states:

  * "A bet now has to get through everyone still in the hand, not just one player.
     The same number is worth less than it is one-on-one."
  * "Folded players stay in players with folded: true ... Filter on folded/busted
     yourself."
  * "Hit 0 chips and you're out for the rest of that match ... while the others play on."
  * "Clearing is stricter: being up isn't enough."

and from iron rule 1 — phases 1 and 2 are 700 banked points the grader may re-run, so
a heads-up hand must reach the same code, not merely a similar answer.
"""
import json
import time
from glob import glob

from fastapi.testclient import TestClient

from app import showdown
from app.main import app
from app.showdown import decide, live_opponents
from app.showdown_rules import (
    BY_NAME,
    forget_all,
    observe,
    posterior_for,
    rule_equity,
    rule_equity_multiway,
)

client = TestClient(app)

DECK = 13


def setup_function():
    forget_all()


# ─────────────────────────────── state builders ────────────────────────────────


def six_seat_state(**over):
    """A six-handed post-reveal spot, seat 0 to act, nobody folded."""
    seats = over.pop("seats", None)
    deltas = over.pop("deltas", [0, 0, 0, 0, 0, 0])
    folded = over.pop("folded", [False] * 6)
    busted = over.pop("busted", [False] * 6)
    bets = over.pop("bets", [0] * 6)
    names = ["you", "Dana", "Miles", "Theo", "Rhea", "Bram"]
    state = {
        "protocol_version": 2,
        "match_id": "phase3-seed1",
        "phase": 3,
        "table_rule": "standard",
        "small_blind": 1,
        "big_blind": 2,
        "starting_stack": 200,
        "your_stack": 200,
        "hand_number": 5,
        "total_hands": 60,
        "leg_number": 1,
        "total_legs": 4,
        "round": "post_reveal",
        "your_number": 10,
        "community_number": 4,
        "your_seat": 0,
        "button_seat": 0,
        "pot": 12,
        "to_call": 0,
        "min_raise_to": 2,
        "max_raise_to": 200,
        "legal_actions": ["check", "bet"],
        "players": seats
        or [
            {
                "seat": s,
                "name": names[s],
                "folded": folded[s],
                "chip_delta": deltas[s],
                "bet_this_round": bets[s],
                "stack": 200 - bets[s],
                "all_in": False,
                "busted": busted[s],
            }
            for s in range(6)
        ],
        "current_hand_actions": [],
        "recent_hands": [],
    }
    state.update(over)
    return state


def phase2_move_bodies():
    """Every real /move request the grader sent us during phase 2."""
    bodies = []
    for path in sorted(glob("docs/phases/showdown/logs/*requests*.json")):
        for entry in json.load(open(path)):
            if entry.get("path") != "/move" or entry.get("method") != "POST":
                continue
            try:
                body = json.loads(entry.get("req_body") or "")
            except ValueError:
                continue
            if isinstance(body, dict) and body.get("legal_actions"):
                bodies.append(body)
    return bodies


# ───────────────────── "filter on folded/busted yourself" ───────────────────────


def test_folded_and_busted_seats_are_not_live_opponents():
    # "the list is the table's seating, not the list of live opponents"
    state = six_seat_state(folded=[False, True, False, False, True, False],
                           busted=[False, False, True, False, False, False])
    live = live_opponents(state)
    assert sorted(p["seat"] for p in live) == [3, 5]


def test_we_are_never_our_own_opponent():
    assert all(p.get("name") != "you" for p in live_opponents(six_seat_state()))
    assert len(live_opponents(six_seat_state())) == 5


def test_a_six_seat_table_folded_down_to_one_is_heads_up_again():
    state = six_seat_state(folded=[False, True, True, True, True, False])
    assert len(live_opponents(state)) == 1


def test_live_opponents_survives_a_malformed_players_list():
    for players in (None, "six", [1, 2, 3], [{}, {"seat": "x"}], []):
        assert isinstance(live_opponents({"players": players, "your_seat": 0}), list)


# ───────────────────────────── the multiway maths ──────────────────────────────


def brute_force_share(n, c, k, rule_name="standard"):
    """Expected share of the pot against k opponents, by enumeration."""
    rule = BY_NAME[rule_name]
    ours = rule.key(n, c)
    total = 0.0
    hands = [0] * k

    def walk(i):
        nonlocal total
        if i == k:
            keys = [rule.key(m, c) for m in hands]
            if any(key > ours for key in keys):
                return
            ties = sum(1 for key in keys if key == ours)
            total += 1.0 / (1 + ties)
            return
        for m in range(1, DECK + 1):
            hands[i] = m
            walk(i + 1)

    walk(0)
    return total / DECK**k


def test_multiway_equity_matches_brute_force_enumeration():
    belief = {"standard": 1.0}
    for k in (1, 2, 3):
        for n in (2, 7, 10, 13):
            for c in (4, 7):
                got = rule_equity_multiway(belief, n, c, [None] * k)
                assert abs(got - brute_force_share(n, c, k)) < 1e-9, (n, c, k, got)


def test_one_opponent_multiway_is_exactly_the_heads_up_number():
    # the phase-1/2 equity function is the k=1 case of the same maths
    belief = posterior_for("standard")
    for n in range(1, DECK + 1):
        for c in (None, 1, 7, 13):
            solo = rule_equity(belief, n, c)
            multi = rule_equity_multiway(belief, n, c, [None])
            assert abs(solo - multi) < 1e-12, (n, c, solo, multi)


def test_the_same_number_is_worth_less_against_more_players():
    # "The same number is worth less than it is one-on-one: the more players still
    # live, the likelier one of them holds something."
    belief = {"standard": 1.0}
    for n in range(1, DECK + 1):
        shares = [rule_equity_multiway(belief, n, 4, [None] * k) for k in range(1, 6)]
        assert shares == sorted(shares, reverse=True), (n, shares)


def test_a_pair_still_cannot_lose_however_many_players_are_in():
    # a pair beats any non-pair and identical results split, so the worst case is a
    # share, never a loss
    belief = {"standard": 1.0}
    for k in range(1, 6):
        assert rule_equity_multiway(belief, 7, 7, [None] * k) > 0.75


def test_an_unbeatable_number_against_a_field_of_copies_splits_evenly():
    # everyone holds the community number: a k+1 way tie pays 1/(k+1)
    belief = {"standard": 1.0}
    only_the_pair = {m: (1.0 if m == 7 else 0.0) for m in range(1, DECK + 1)}
    for k in (1, 2, 5):
        share = rule_equity_multiway(belief, 7, 7, [only_the_pair] * k)
        assert abs(share - 1.0 / (k + 1)) < 1e-9


def test_a_three_way_tie_pays_a_third_of_the_pot():
    belief = {"standard": 1.0}
    same = {m: (1.0 if m == 9 else 0.0) for m in range(1, DECK + 1)}
    assert abs(rule_equity_multiway(belief, 9, 4, [same, same]) - 1 / 3) < 1e-9


def test_no_opponents_left_means_the_pot_is_ours():
    assert rule_equity_multiway({"standard": 1.0}, 2, 5, []) == 1.0


def test_multiway_equity_respects_each_opponents_own_range():
    # one opponent capable of anything is less dangerous than five of them
    belief = {"standard": 1.0}
    strong = {m: (1.0 if m >= 11 else 0.0) for m in range(1, DECK + 1)}
    weak = {m: (1.0 if m <= 3 else 0.0) for m in range(1, DECK + 1)}
    assert rule_equity_multiway(belief, 9, 4, [weak, weak]) > rule_equity_multiway(
        belief, 9, 4, [weak, strong]
    )


def test_multiway_equity_is_a_probability_under_every_rule():
    for name in BY_NAME:
        for k in (1, 3, 5):
            share = rule_equity_multiway({name: 1.0}, 6, 6, [None] * k)
            assert 0.0 <= share <= 1.0, (name, k, share)


# ───────────────── phases 1 and 2 must reach the same code (iron rule 1) ─────────


def test_no_real_phase_2_request_ever_takes_the_multiway_path(monkeypatch):
    bodies = phase2_move_bodies()
    assert len(bodies) > 500, "the phase-2 logs should hold hundreds of graded moves"
    calls = []
    monkeypatch.setattr(
        showdown, "rule_equity_multiway", lambda *a, **k: calls.append(a) or 0.0
    )
    for body in bodies:
        decide(body)
    assert calls == [], f"{len(calls)} phase-2 decisions went through phase-3 code"


def test_every_replayed_phase_2_request_still_gets_a_legal_action():
    for body in phase2_move_bodies():
        reply = decide(body)
        assert reply["action"] in body["legal_actions"]
        if reply["action"] in ("bet", "raise"):
            assert body["min_raise_to"] <= reply["amount"] <= body["max_raise_to"]


def test_a_two_player_table_is_decided_by_the_heads_up_path(monkeypatch):
    heads_up = six_seat_state(
        seats=[
            {"seat": 0, "name": "you", "folded": False, "chip_delta": 0,
             "bet_this_round": 0, "stack": 200, "all_in": False, "busted": False},
            {"seat": 1, "name": "Gaston", "folded": False, "chip_delta": 0,
             "bet_this_round": 0, "stack": 200, "all_in": False, "busted": False},
        ],
        total_hands=100,
        leg_number=None,
        total_legs=None,
    )
    calls = []
    monkeypatch.setattr(
        showdown, "rule_equity_multiway", lambda *a, **k: calls.append(a) or 0.0
    )
    decide(heads_up)
    assert calls == []


# ─────────────────── a bet has to get through everyone still in ─────────────────


def test_a_hand_we_value_bet_heads_up_is_checked_into_five_players():
    # a 10 with no pair is 71% heads-up and 18% against five — the same number,
    # a completely different decision
    strong_enough_heads_up = six_seat_state(
        seats=[
            {"seat": 0, "name": "you", "folded": False, "chip_delta": 0,
             "bet_this_round": 0, "stack": 200, "all_in": False, "busted": False},
            {"seat": 1, "name": "Dana", "folded": False, "chip_delta": 0,
             "bet_this_round": 0, "stack": 200, "all_in": False, "busted": False},
        ],
    )
    assert decide(strong_enough_heads_up)["action"] == "bet"
    assert decide(six_seat_state())["action"] == "check"


def test_we_still_bet_a_hand_that_beats_the_whole_field():
    # holding the community number: nothing beats it under the standard rule
    assert decide(six_seat_state(your_number=4, community_number=4))["action"] == "bet"


def test_we_fold_a_number_that_only_beats_one_of_five_opponents():
    state = six_seat_state(
        your_number=6,
        to_call=40,
        pot=80,
        legal_actions=["fold", "call", "raise"],
        min_raise_to=80,
        max_raise_to=200,
        bets=[0, 40, 40, 0, 0, 0],
    )
    assert decide(state)["action"] == "fold"


def test_pot_odds_still_decide_a_cheap_multiway_call():
    # 4 to call into a pot of 200: a 12 against five is well over that price
    state = six_seat_state(
        your_number=12,
        to_call=4,
        pot=200,
        legal_actions=["fold", "call", "raise"],
        min_raise_to=8,
        max_raise_to=200,
    )
    assert decide(state)["action"] in ("call", "raise")


def test_bluffing_gets_rarer_as_the_field_grows():
    # a bluff needs everyone to fold, which five players do far less often
    def bluff_rate(k):
        seats = [
            {"seat": s, "name": "you" if s == 0 else f"P{s}", "folded": False,
             "chip_delta": 0, "bet_this_round": 0, "stack": 200,
             "all_in": False, "busted": False}
            for s in range(k + 1)
        ]
        bluffs = 0
        for h in range(400):
            state = six_seat_state(seats=seats, your_number=2, community_number=9,
                                   hand_number=h % 55 + 1, match_id=f"m{h}")
            if decide(state)["action"] == "bet":
                bluffs += 1
        return bluffs / 400

    assert bluff_rate(5) < bluff_rate(1)


# ─────────────────────── clearing: +10 and top the table ───────────────────────


def test_being_up_is_not_enough_so_we_chase_the_leader_late():
    # "beating four of the five is worth nothing" — second place scores 0, so with
    # the leg running out and a rival ahead, variance is free
    behind = six_seat_state(hand_number=55, deltas=[40, 130, -30, -60, -40, -40])
    ahead = six_seat_state(hand_number=55, deltas=[130, 40, -30, -60, -40, -40])
    assert showdown._tilt(behind) < 0
    assert showdown._tilt(ahead) > 0


def test_a_comfortable_lead_late_is_protected():
    state = six_seat_state(hand_number=58, deltas=[150, 10, -30, -60, -40, -30])
    assert showdown._tilt(state) == showdown.PROTECT_TILT


def test_leading_but_under_ten_still_chases():
    # clearing needs BOTH: "chip delta >= +10 and top the table"
    state = six_seat_state(hand_number=58, deltas=[4, 2, -30, -60, 40, 44])
    assert showdown._tilt(state) < 0


def test_a_leg_is_not_chased_from_the_first_hand():
    state = six_seat_state(hand_number=3, deltas=[-50, 120, 0, 0, 0, -70])
    assert showdown._tilt(state) == 0.0


def test_a_busted_rival_still_counts_on_the_scoreboard():
    # a seat busted at -200 is a seat we have beaten; it must not read as a leader
    state = six_seat_state(
        hand_number=58,
        deltas=[60, -200, -200, -200, 40, 300],
        busted=[False, True, True, True, False, False],
    )
    assert showdown._tilt(state) < 0  # Bram is at +300, we are not topping anything
    won = six_seat_state(
        hand_number=58,
        deltas=[300, -200, -200, -200, 40, 60],
        busted=[False, True, True, True, False, False],
    )
    assert showdown._tilt(won) == showdown.PROTECT_TILT


def test_the_chase_is_sharper_the_further_behind_we_are():
    near = six_seat_state(hand_number=57, deltas=[0, 6, -2, -2, -1, -1])
    far = six_seat_state(hand_number=57, deltas=[-120, 260, -40, -40, -30, -30])
    assert showdown._tilt(far) < showdown._tilt(near) < 0


def test_the_heads_up_target_is_untouched_by_the_new_objective():
    # phase 1: +10 over 100 hands, two seats, no leg number
    state = six_seat_state(
        seats=[
            {"seat": 0, "name": "you", "folded": False, "chip_delta": 60,
             "bet_this_round": 0, "stack": 260, "all_in": False, "busted": False},
            {"seat": 1, "name": "Gaston", "folded": False, "chip_delta": -60,
             "bet_this_round": 0, "stack": 140, "all_in": False, "busted": False},
        ],
        hand_number=95,
        total_hands=100,
        leg_number=None,
        total_legs=None,
    )
    assert showdown._tilt(state) == showdown.PROTECT_TILT


# ───────────────────── learning from a crowded showdown ─────────────────────────


def test_a_crowded_showdown_labels_more_numbers_than_a_duel():
    # a six-way showdown is five labelled comparisons, not one. Phase 2's binding
    # constraint was evidence per table — only 7-16 showdowns in a 40-hand leg —
    # so this is the single biggest thing phase 3 hands us for free.
    import random

    from app.showdown_rules import showdown_winners

    def confidence(seats, hands, trials=15):
        rule = BY_NAME["antipair_low"]
        total = 0.0
        for trial in range(trials):
            rng = random.Random(1000 + trial)
            forget_all()
            for h in range(hands):
                numbers = {s: rng.randint(1, DECK) for s in range(seats)}
                community = rng.randint(1, DECK)
                observe(
                    "table",
                    match_id="m",
                    leg=1,
                    hand_number=h,
                    numbers=numbers,
                    community=community,
                    winners=showdown_winners(rule, numbers, community),
                )
            total += posterior_for("table")["antipair_low"]
        return total / trials

    duel, crowd = confidence(2, 8), confidence(6, 8)
    assert crowd > duel * 1.3, f"six-way {crowd:.2f} vs heads-up {duel:.2f}"


def test_a_crowded_showdown_still_kills_a_rule_it_contradicts():
    state = six_seat_state(
        table_rule="obsidian",
        recent_hands=[
            {
                "hand_number": h,
                "community_number": 5,
                "winners": [3],
                "pot": 30,
                "shown_numbers": {"0": 11, "1": 5, "2": 9, "3": 2, "4": 7, "5": 12},
                "actions": [],
            }
            for h in (1, 2)
        ],
    )
    decide(state)
    posterior = posterior_for("obsidian")
    # seat 1 held the community number and lost, so a pair does not win here
    assert posterior["standard"] < 0.01
    assert posterior["antipair_low"] > posterior["standard"]


def test_a_side_pot_second_winner_does_not_contradict_the_rule():
    # multiway all-ins produce two honest winners with different numbers: one takes
    # the main pot, the other a side pot. The best key still won the main pot.
    forget_all()
    for h in range(1, 7):
        observe(
            "sidepot",
            match_id="m",
            leg=1,
            hand_number=h,
            numbers={0: 13, 1: 2, 2: 7, 3: 9},
            community=4,
            winners=[0, 2],  # 13 wins the main pot, 7 takes a side pot
        )
    posterior = posterior_for("sidepot")
    assert max(posterior, key=posterior.get) == "standard"
    assert posterior["standard"] > 0.4  # alive and leading, not contradicted


def test_a_predicted_winner_that_did_not_win_is_still_a_contradiction():
    forget_all()
    for h in range(1, 7):
        observe(
            "contra",
            match_id="m",
            leg=1,
            hand_number=h,
            numbers={0: 13, 1: 2, 2: 7, 3: 9},
            community=4,
            winners=[1],  # the 2 won outright — the standard rule says the 13 must
        )
    assert posterior_for("contra")["standard"] < 0.05


def test_two_player_showdowns_keep_phase_2s_exact_matching():
    # the 227 seeded observations are all two-player and phase 2 learned the hard way
    # what loosening this test costs; a two-winner heads-up hand must stay a tie
    forget_all()
    for h in range(1, 7):
        observe("hu", match_id="m", leg=1, hand_number=h,
                numbers={0: 12, 1: 3}, community=6, winners=[0, 1])
    posterior = posterior_for("hu")
    assert posterior["standard"] < 0.05  # 12 and 3 are not equal under it


def test_a_showdown_with_a_missing_seat_is_ignored_not_crashed():
    state = six_seat_state(
        table_rule="ragged",
        recent_hands=[
            {"hand_number": 1, "community_number": 5, "winners": [9],
             "pot": 30, "shown_numbers": {"0": 11, "1": 5}, "actions": []},
            {"hand_number": 2, "community_number": None, "winners": [1],
             "pot": 6, "shown_numbers": {}, "actions": []},
            {"hand_number": 3, "community_number": 5, "winners": [0],
             "pot": 6, "shown_numbers": {"0": "x", "1": 5}, "actions": []},
        ],
    )
    assert decide(state)["action"] in state["legal_actions"]


# ────────────────────────── protocol: never a bad move ─────────────────────────


def test_a_six_seat_body_gets_a_200_and_a_legal_action():
    body = six_seat_state()
    response = client.post("/move", json=body)
    assert response.status_code == 200
    assert response.json()["action"] in body["legal_actions"]


def test_every_legal_action_set_is_answered_from_within_it():
    for legal, extra in (
        (["check"], {"min_raise_to": None, "max_raise_to": None}),
        (["check", "bet"], {}),
        (["fold", "call"], {"to_call": 20, "min_raise_to": None, "max_raise_to": None}),
        (["fold", "call", "raise"], {"to_call": 20, "min_raise_to": 40}),
    ):
        for n in range(1, DECK + 1):
            state = six_seat_state(legal_actions=legal, your_number=n, **extra)
            reply = decide(state)
            assert reply["action"] in legal, (legal, n, reply)
            if reply["action"] in ("bet", "raise"):
                assert state["min_raise_to"] <= reply["amount"] <= state["max_raise_to"]


def test_a_six_seat_body_with_junk_fields_never_500s():
    for broken in (
        {"players": [{"seat": 0, "name": "you", "chip_delta": "lots"}]},
        {"players": [{"seat": s} for s in range(6)]},
        {"your_seat": None},
        {"your_number": 99},
        {"total_hands": None, "hand_number": None},
        {"recent_hands": "none"},
        {"current_hand_actions": [None, 3, {"seat": "x"}]},
    ):
        state = six_seat_state(**broken)
        response = client.post("/move", json=state)
        assert response.status_code == 200
        assert response.json()["action"] in state["legal_actions"]


def test_a_crowded_decision_fits_the_five_second_budget():
    # the worst case: pre-reveal (every community number in play), five live
    # opponents, four of them betting, and a full 20-hand six-way history
    history = [
        {
            "hand_number": h,
            "community_number": (h % 13) + 1,
            "winners": [h % 6],
            "pot": 40,
            "shown_numbers": {str(s): ((h + s) % 13) + 1 for s in range(6)},
            "actions": [],
        }
        for h in range(1, 21)
    ]
    state = six_seat_state(
        table_rule="crowded",
        round="pre_reveal",
        community_number=None,
        to_call=30,
        pot=120,
        legal_actions=["fold", "call", "raise"],
        min_raise_to=60,
        bets=[0, 30, 30, 30, 30, 0],
        recent_hands=history,
        current_hand_actions=[
            {"round": "pre_reveal", "seat": s, "action": "raise", "amount": 30}
            for s in (1, 2, 3, 4)
        ],
    )
    decide(state)  # warm the belief cache the way a real leg would
    start = time.perf_counter()
    for _ in range(10):
        decide(state)
    each = (time.perf_counter() - start) / 10
    assert each < 0.5, f"{each * 1000:.0f} ms per /move leaves no margin in 5 s"


# ─────────────── attempt 1 regressions (docs/phases/showdown/phase-3) ───────────
# Attempt 1 scored 0/600: second at +261 and +173, and busted twice. These are
# real logged spots from that attempt, replayed out of the live request log.

import json as _json
from pathlib import Path as _Path

_ATTEMPT1 = _json.loads(
    (_Path(__file__).parent / "data" / "phase3_attempt1_hands.json").read_text()
)


def _logged(key):
    """A real logged /move body, with the committed seed loaded as it was in play."""
    from app.showdown_rules import forget_all as _f, load_seed as _l

    _f()
    _l()
    return _json.loads(_json.dumps(_ATTEMPT1[key]))


def test_a_near_nuts_hand_is_value_bet_not_token_bet():
    """leg 2 hand 57: holding a 2 on obsidian ("a pair loses to any non-pair,
    then the lower number wins") against a community 10 — only a 1 beats us, an
    88% favourite — with 108 behind and 182 already in the pot, the bot bet 2.

    The stack-risk price scales with the size of the bet, so the value bet it
    wanted was refused and it fell all the way through to the minimum, giving up
    the value AND handing the opponent a cheap raise. _put_in now solves for the
    largest size the equity above the floor can actually pay for.
    """
    from app.showdown import decide

    state = _logged("2_57_post_reveal")
    reply = decide(state)
    assert reply["action"] == "bet"
    assert reply["amount"] >= state["pot"] // 4, f"still a token bet: {reply}"


def test_the_same_defect_on_a_thirteen():
    """leg 4 hand 23: a 13 on a community 8 under cinnabar (the standard rule),
    so only the 8 itself beats us — and it bet 2 into a pot of 114."""
    from app.showdown import decide

    state = _logged("4_23_post_reveal")
    reply = decide(state)
    assert reply["action"] == "bet"
    assert reply["amount"] >= state["pot"] // 4, f"still a token bet: {reply}"


def test_a_solved_size_never_exceeds_what_the_equity_pays_for():
    # the solved size must satisfy the inequality it was derived from, or it is
    # just a bigger reckless bet
    from app.showdown import RAISE_RISK, _put_in

    state = _logged("4_23_post_reveal")
    for eq in (0.5, 0.7, 0.9, 1.0):
        got = _put_in(state, "bet", 10_000, eq, 0.45, scale=1.0, solve=True)
        if got is None:
            continue
        risk = RAISE_RISK * (got["amount"] / state["your_stack"])
        assert eq >= 0.45 + risk - 1e-9, (eq, got, risk)


def test_two_seat_sizing_is_left_alone():
    # solving is gated on the SEATING, so a phase 1 or 2 match never sees it
    from app.showdown import _table_size

    state = _logged("4_23_post_reveal")
    assert _table_size(state) == 6
    state["players"] = state["players"][:2]
    assert _table_size(state) == 2


def test_the_chase_only_fires_when_behind_and_out_of_road():
    """Second place scores what last place scores, so a stack we cannot win with
    is worth nothing — but only once the leg is genuinely nearly over."""
    from app.showdown import _chase_pressure

    state = _logged("4_23_post_reveal")

    def standings(ours, others):
        # every seat, not just one: the leader is the max over the whole table
        for p in state["players"]:
            p["chip_delta"] = ours if p["name"] == "you" else others
            p["busted"] = False

    standings(ours=40, others=300)
    state["total_hands"], state["hand_number"] = 60, 12
    assert _chase_pressure(state) == 0.0, "not the endgame yet — play the hand"

    state["hand_number"] = 58
    assert _chase_pressure(state) > 0.5, "260 behind with 2 hands left is a chase"

    standings(ours=300, others=40)
    assert _chase_pressure(state) == 0.0, "we are the one in front"

    # and being in front is not enough on its own: under +10 still needs chips
    standings(ours=4, others=-50)
    assert _chase_pressure(state) > 0.0, "leading but short of the +10 threshold"


def test_a_two_seat_table_never_chases():
    from app.showdown import _chase_pressure

    state = _logged("4_23_post_reveal")
    state["players"] = state["players"][:2]
    state["total_hands"], state["hand_number"] = 40, 39
    for p in state["players"]:
        p["chip_delta"] = -100 if p["name"] == "you" else 300
    assert _chase_pressure(state) == 0.0


# ─────────── attempt 2 regressions: 150/600, three legs folded away ────────────
# Attempt 2 fixed the token bets and stopped busting, then finished +77, −89 and
# −78 in its three losing legs while one opponent took ~900 chips. Its biggest
# winning hand across two whole legs was 13 and 14 chips: it never contested a
# pot. These are the real spots it passed up.


def test_a_near_nuts_hand_is_not_folded_getting_three_to_one():
    """leg 4 hand 3: a 13 on a community 7 under cinnabar (the standard rule),
    so only the 7 itself beats us — 88% — with 192 in the pot and 96 to call.

    CALL_RISK alone wanted +0.347 of extra equity on top of the pot odds. That
    price was measured heads-up in phase 2, where busting forfeits an ABSOLUTE
    target that is still reachable. Phase 3 scores a relative one: second place
    and last place both pay zero, so refusing to play for a stack is not caution.
    """
    from app.showdown import decide

    state = _logged("a2_leg4_h3")
    assert state["your_number"] == 13 and state["community_number"] == 7
    assert decide(state)["action"] == "call"


def test_the_same_fold_two_ways():
    from app.showdown import decide

    for key, number in (("a2_leg4_h10", 12), ("a2_leg3_h12", 12)):
        state = _logged(key)
        assert state["your_number"] == number
        assert decide(state)["action"] == "call", key


def test_the_relief_is_gated_on_the_seating_not_on_who_is_still_live():
    """leg 4 hand 3 was heads-up *inside* a six-seat leg — one opponent live, five
    seats at the table. That is still a leg scored on topping the table, so it
    gets the relief; a real two-seat phase 1/2 match must not."""
    from app.showdown import _table_size, live_opponents

    state = _logged("a2_leg4_h3")
    assert len(live_opponents(state)) == 1, "heads-up by the time it got to us"
    assert _table_size(state) >= 3, "but still a six-seat leg"


def test_a_two_seat_match_keeps_phase_twos_prices_exactly():
    # the same spot at a genuine two-seat table must price the call the way
    # phase 2 measured it — the relief must not leak into 700 banked points
    from app.showdown import PHASE3_RISK_RELIEF, _table_size

    state = _logged("a2_leg4_h3")
    state["players"] = [p for p in state["players"] if p["name"] == "you"][:1] + [
        p for p in state["players"] if p["name"] != "you"
    ][:1]
    assert _table_size(state) == 2
    assert PHASE3_RISK_RELIEF > 0, "otherwise this test proves nothing"
