"""SHOWDOWN phase 3 — A Crowded Table (docs/phases/showdown/phase-3/).

Six seats and multiway play, on top of everything in the guide and all of phase 2.
Three things have to be true and none of them are about the table rule:

* a number is worth less against five opponents than against one, and the equity
  model has to say so;
* the thresholds that price a bet were calibrated one-on-one and have to be put back
  onto that axis before they mean anything six-handed;
* the leg is now a race — "beating four of the five is worth nothing" — so a safe
  second place scores the same zero as busting.

Everything phase 3 adds must switch itself off when only two players are live, which
is what keeps phases 1 and 2 (700 points, still scored) bit-for-bit unchanged.
"""
import json

from fastapi.testclient import TestClient

from app.main import app
from app.showdown import (
    acting_order,
    decide,
    field_share,
    forced_bet_seats,
    live_opponents,
)
from app.showdown_rules import (
    BY_NAME,
    RuleBelief,
    forget_all,
    observe,
    posterior_for,
    rule_equity,
    showdown_winners,
)

client = TestClient(app)

DECK = 13
STANDARD = {"standard": 1.0}


def setup_function():
    forget_all()


# ────────────────────────── position at a six-seat table ────────────────────────
# The statement's table, verbatim:
#
#                  seat 0   seat 1   seat 2   seat 3   seat 4   seat 5
#                  [BUTTON]
#  forced bet         –        1        2        –        –        –
#  acts pre_reveal    4th      5th      6th      1st      2nd      3rd
#  acts post_reveal   6th      1st      2nd      3rd      4th      5th


def test_forced_bets_start_just_past_the_button():
    # "seat 1 pays 1, seat 2 pays 2. The button pays nothing, which is why it's
    # the cheapest seat."
    assert forced_bet_seats(button=0, seats=[0, 1, 2, 3, 4, 5]) == (1, 2)


def test_the_pre_reveal_order_opens_just_past_the_seat_that_paid_two():
    # seat 3 acts 1st, seat 2 (which paid 2) acts 6th and last
    assert acting_order(button=0, seats=[0, 1, 2, 3, 4, 5], round_name="pre_reveal") == [
        3, 4, 5, 0, 1, 2
    ]


def test_the_post_reveal_order_opens_just_past_the_button():
    # seat 1 acts 1st, the button acts 6th "with the most information"
    assert acting_order(button=0, seats=[0, 1, 2, 3, 4, 5], round_name="post_reveal") == [
        1, 2, 3, 4, 5, 0
    ]


def test_the_two_betting_rounds_are_not_the_same_order():
    # "As heads-up, the order is not the same in both betting rounds."
    seats = [0, 1, 2, 3, 4, 5]
    pre = acting_order(button=0, seats=seats, round_name="pre_reveal")
    post = acting_order(button=0, seats=seats, round_name="post_reveal")
    assert pre != post


def test_the_button_moves_one_seat_along_and_every_seat_holds_every_position():
    # "Over six hands you hold every seat's position once, so nobody gets a
    # permanently good or bad seat."
    seats = [0, 1, 2, 3, 4, 5]
    places = {s: set() for s in seats}
    for button in seats:
        for place, seat in enumerate(acting_order(button, seats, "post_reveal")):
            places[seat].add(place)
    assert all(spots == set(range(6)) for spots in places.values())


def test_busted_seats_are_skipped_by_the_button_and_the_order():
    # "still moves one seat along every hand — now skipping anyone who has busted"
    live = [0, 2, 5]  # seats 1, 3 and 4 have busted
    assert forced_bet_seats(button=0, seats=live) == (2, 5)
    assert acting_order(button=0, seats=live, round_name="pre_reveal") == [0, 2, 5]
    assert acting_order(button=0, seats=live, round_name="post_reveal") == [2, 5, 0]


def test_heads_up_still_follows_the_guide_not_the_six_seat_rule():
    # The guide is explicit for two seats: "The button pays the smaller forced bet
    # (1) and acts first before the reveal", and last after it. Six-handed the
    # button pays NOTHING — the same sentence, wrapped round a shorter table.
    assert forced_bet_seats(button=1, seats=[0, 1]) == (1, 0)
    assert acting_order(button=1, seats=[0, 1], round_name="pre_reveal") == [1, 0]
    assert acting_order(button=1, seats=[0, 1], round_name="post_reveal") == [0, 1]


# ──────────────────────────── multiway equity ───────────────────────────────────


def brute_force_share(rule_name, n, c, opponents):
    """Our share of the pot, by enumerating every opponent holding, exactly."""
    key = BY_NAME[rule_name].key
    ours = key(n, c)
    total = 0.0
    def walk(depth, ties):
        nonlocal total
        if depth == opponents:
            total += 1.0 / (ties + 1)
            return
        for m in range(1, DECK + 1):
            theirs = key(m, c)
            if theirs > ours:
                continue  # someone beats us, this branch is worth nothing
            walk(depth + 1, ties + (1 if theirs == ours else 0))
    walk(0, 0)
    return total / DECK**opponents


def test_one_opponent_is_exactly_the_phase_one_formula():
    # the whole compatibility guarantee rests on this: k=1 must not merely be
    # close to the old closed form, it must BE it
    from app.showdown import equity

    for n in range(1, DECK + 1):
        for c in range(1, DECK + 1):
            assert abs(rule_equity(STANDARD, n, c, opponents=1) - equity(n, c)) < 1e-12
        assert abs(rule_equity(STANDARD, n, None, opponents=1) - equity(n)) < 1e-12


def test_multiway_equity_matches_brute_force():
    for name in ("standard", "low", "near", "antipair_low"):
        for opponents in (1, 2, 3):
            for n, c in ((10, 5), (13, 13), (1, 7), (7, 7), (4, 9)):
                got = rule_equity({name: 1.0}, n, c, opponents=opponents)
                want = brute_force_share(name, n, c, opponents)
                assert abs(got - want) < 1e-9, (name, n, c, opponents, got, want)


def test_the_same_number_is_worth_less_the_more_players_are_live():
    # the statement's headline: "The same number is worth less than it is
    # one-on-one: the more players still live, the likelier one of them holds
    # something."
    for n in range(1, DECK + 1):
        shares = [rule_equity(STANDARD, n, 5, opponents=k) for k in range(1, 6)]
        assert shares == sorted(shares, reverse=True), n


def test_a_ten_is_a_favourite_heads_up_and_a_dog_six_handed():
    # 10 against a community 5 beats eight numbers of thirteen one-on-one, and
    # has to beat five of them at once six-handed — below the 1/6 fair share
    assert rule_equity(STANDARD, 10, 5, opponents=1) > 0.65
    assert rule_equity(STANDARD, 10, 5, opponents=5) < 1.0 / 6


def test_a_pair_is_still_close_to_the_whole_pot_six_handed():
    # under the standard rule a pair cannot lose, only split with another pair
    assert rule_equity(STANDARD, 7, 7, opponents=5) > 0.65


def test_equity_over_the_whole_field_sums_to_one():
    # chips are conserved: if every seat holds a uniformly random number, the
    # shares of the pot have to add up to exactly one pot
    for opponents in (1, 2, 4, 5):
        total = sum(rule_equity(STANDARD, n, 6, opponents=opponents) for n in range(1, DECK + 1))
        assert abs(total / DECK - 1.0 / (opponents + 1)) < 1e-9, opponents


def test_a_dead_heat_splits_the_pot_evenly():
    # "high" ignores the community number, so holding 13 against opponents who
    # can only be 13 is a k+1 way split
    only13 = {13: 1.0}
    for opponents in (1, 2, 5):
        got = rule_equity({"high": 1.0}, 13, 4, weights=only13, opponents=opponents)
        assert abs(got - 1.0 / (opponents + 1)) < 1e-9, opponents


def test_opponents_can_be_given_different_ranges():
    from app.showdown_rules import rule_equity_ranges

    tight = {11: 1 / 3, 12: 1 / 3, 13: 1 / 3}  # a seat that has raised
    wide = {m: 1.0 / DECK for m in range(1, DECK + 1)}  # a seat that limped
    mixed = rule_equity_ranges(STANDARD, 12, 4, [tight, wide])
    both_tight = rule_equity_ranges(STANDARD, 12, 4, [tight, tight])
    both_wide = rule_equity_ranges(STANDARD, 12, 4, [wide, wide])
    assert both_tight < mixed < both_wide
    assert abs(both_wide - rule_equity(STANDARD, 12, 4, opponents=2)) < 1e-12


# ─────────────────────────── the field-share scale ──────────────────────────────


def test_the_field_share_is_the_identity_heads_up():
    assert field_share(1) == 1.0


def test_the_field_share_puts_an_average_hand_at_a_half_at_every_table_size():
    # 0.5 has to keep meaning "an average number" or none of VALUE_BET_EQ,
    # RAISE_EQ or CALL_MARGIN mean anything six-handed
    for k in range(1, 6):
        average_equity = 1.0 / (k + 1)
        assert abs(average_equity / field_share(k) - 0.5) < 1e-12, k


# ──────────────────────── reading a six-seat table ──────────────────────────────


def seat(n, name, **over):
    body = {
        "seat": n,
        "name": name,
        "folded": False,
        "chip_delta": 0,
        "bet_this_round": 0,
        "stack": 200,
        "all_in": False,
        "busted": False,
    }
    body.update(over)
    return body


TABLE = [
    seat(0, "you"),
    seat(1, "Dana"),
    seat(2, "Miles"),
    seat(3, "Theo"),
    seat(4, "Rhea"),
    seat(5, "Bram"),
]

BASE = {
    "protocol_version": 2,
    "match_id": "phase3-leg1",
    "phase": 3,
    # pinned to the one codename whose rule the guide spells out, so every
    # assertion below is about the multiway maths and not about how far the
    # rule posterior happens to have moved
    "table_rule": "standard",
    "small_blind": 1,
    "big_blind": 2,
    "starting_stack": 200,
    "your_stack": 200,
    "hand_number": 1,
    "total_hands": 60,
    "leg_number": 1,
    "total_legs": 4,
    "round": "post_reveal",
    "your_number": 13,
    "community_number": 5,
    "your_seat": 0,
    "button_seat": 5,
    "pot": 20,
    "to_call": 0,
    "min_raise_to": 2,
    "max_raise_to": 200,
    "legal_actions": ["check", "bet"],
    "players": TABLE,
    "current_hand_actions": [],
    "recent_hands": [],
}


def move(**over):
    body = json.loads(json.dumps(BASE))
    body.update(over)
    return client.post("/move", json=body)


def test_folded_and_busted_seats_are_not_live_opponents():
    # "Folded players stay in players with folded: true — the list is the table's
    # seating, not the list of live opponents. Filter on folded / busted yourself."
    players = [
        seat(0, "you"),
        seat(1, "Dana", folded=True),
        seat(2, "Miles"),
        seat(3, "Theo", busted=True, stack=0, chip_delta=-200),
        seat(4, "Rhea"),
        seat(5, "Bram", folded=True),
    ]
    assert live_opponents({"players": players, "your_seat": 0}) == 2


def test_we_are_never_our_own_opponent():
    assert live_opponents({"players": TABLE, "your_seat": 0}) == 5
    assert live_opponents({"players": TABLE, "your_seat": 3}) == 5


def test_an_all_in_seat_is_still_live_for_the_showdown():
    # "All-in: out of chips this hand (still live for showdown) vs out of the match"
    players = [seat(0, "you"), seat(1, "Dana", all_in=True, stack=0), seat(2, "Miles")]
    assert live_opponents({"players": players, "your_seat": 0}) == 2


def test_a_six_seat_request_is_answered_legally():
    r = move()
    assert r.status_code == 200
    assert r.json()["action"] in BASE["legal_actions"]


def test_a_middling_number_is_bet_heads_up_and_checked_six_handed():
    # the whole point of the phase: a 10 on a community 5 is a value bet against
    # one opponent and a check-and-hope against five
    heads_up = [seat(0, "you"), seat(1, "Dana")]
    r = move(your_number=10, players=heads_up)
    assert r.json()["action"] == "bet"
    r = move(your_number=10)  # the full six-seat table
    assert r.json()["action"] == "check"


def test_a_pair_is_still_bet_hard_six_handed():
    r = move(your_number=5, community_number=5)
    assert r.json()["action"] == "bet"
    assert r.json()["amount"] > BASE["pot"] // 2


def test_we_still_never_fold_a_hand_that_cannot_lose_multiway():
    r = move(
        your_number=5, community_number=5, to_call=180, pot=400,
        your_stack=24, min_raise_to=None, max_raise_to=None,
        legal_actions=["fold", "call"],
    )
    assert r.json() == {"action": "call"}


def test_only_the_seats_that_raised_get_a_sharp_range():
    # five limpers are not five raisers: a table where one seat has bet must be
    # scarier than one where nobody has, but not as scary as five bets
    def eq_with(actions):
        state = json.loads(json.dumps(BASE))
        state.update(your_number=11, to_call=10, pot=40,
                     legal_actions=["fold", "call", "raise"],
                     min_raise_to=20, max_raise_to=200,
                     current_hand_actions=actions)
        from app.showdown import table_equity

        return table_equity(state)

    quiet = eq_with([])
    one_bet = eq_with([{"round": "post_reveal", "seat": 2, "action": "bet", "amount": 10}])
    all_in_on_us = eq_with([
        {"round": "post_reveal", "seat": s, "action": "bet" if s == 2 else "raise", "amount": 10}
        for s in (2, 3, 4, 5)
    ])
    assert all_in_on_us < one_bet < quiet


def test_bluffing_thins_out_as_the_table_fills():
    # a bluff has to get through EVERY live opponent, so its chance of working
    # falls off geometrically — six-handed we should almost never fire one
    from app.showdown import bluff_rate

    rates = [bluff_rate(k) for k in range(1, 6)]
    assert rates == sorted(rates, reverse=True)
    assert rates[0] > 10 * rates[-1]


# ─────────────────────────── the race, not the target ───────────────────────────


def test_a_six_seat_table_is_playing_for_the_top_of_the_table():
    from app.showdown import objective

    target, must_top = objective({"players": TABLE, "leg_number": 1})
    assert (target, must_top) == (10, True)


def test_a_two_seat_leg_is_still_phase_twos_objective():
    from app.showdown import objective

    two = [seat(0, "you"), seat(1, "Wren")]
    assert objective({"players": two, "leg_number": 3}) == (25, False)
    assert objective({"players": two, "leg_number": None}) == (10, False)


def test_busting_the_table_down_to_two_does_not_change_the_objective():
    from app.showdown import objective

    # four opponents busted, but the leg is still a six-seat phase 3 leg scored
    # on topping the table
    wreckage = [seat(0, "you"), seat(1, "Dana")] + [
        seat(n, f"p{n}", busted=True, stack=0, chip_delta=-200) for n in (2, 3, 4, 5)
    ]
    assert objective({"players": wreckage, "leg_number": 1}) == (10, True)


def test_being_up_but_second_is_worth_nothing_and_we_chase():
    from app.showdown import endgame_tilt

    # last few hands, we are +40 — comfortably past +10 — but Theo is +90
    players = [seat(0, "you", chip_delta=40), seat(3, "Theo", chip_delta=90)] + [
        seat(n, f"p{n}", chip_delta=-30) for n in (1, 2, 4, 5)
    ]
    state = {"players": players, "your_seat": 0, "hand_number": 57, "total_hands": 60,
             "leg_number": 1}
    assert endgame_tilt(state) < 0, "second place scores zero — take the risk"


def test_a_clear_lead_is_protected():
    from app.showdown import endgame_tilt

    players = [seat(0, "you", chip_delta=140)] + [
        seat(n, f"p{n}", chip_delta=-28) for n in (1, 2, 3, 4, 5)
    ]
    state = {"players": players, "your_seat": 0, "hand_number": 57, "total_hands": 60,
             "leg_number": 1}
    assert endgame_tilt(state) > 0


def test_a_tie_for_the_lead_is_not_the_lead():
    from app.showdown import endgame_tilt

    # "Ties don't count" — level with the leader is a losing position
    players = [seat(0, "you", chip_delta=60), seat(2, "Miles", chip_delta=60)] + [
        seat(n, f"p{n}", chip_delta=-30) for n in (1, 3, 4, 5)
    ]
    state = {"players": players, "your_seat": 0, "hand_number": 58, "total_hands": 60,
             "leg_number": 1}
    assert endgame_tilt(state) < 0


def test_the_early_leg_is_not_tilted_at_all():
    from app.showdown import endgame_tilt

    players = [seat(0, "you", chip_delta=40), seat(3, "Theo", chip_delta=90)]
    state = {"players": players, "your_seat": 0, "hand_number": 12, "total_hands": 60,
             "leg_number": 1}
    assert endgame_tilt(state) == 0.0


# ──────────────────── multiway showdowns are better evidence ────────────────────


def test_a_six_way_showdown_is_recorded():
    numbers = {0: 4, 1: 9, 2: 13, 3: 2, 4: 7, 5: 11}
    assert observe("garnet", match_id="m1", leg=1, hand_number=1, numbers=numbers,
                   community=6, winners=showdown_winners(BY_NAME["standard"], numbers, 6))
    assert RuleBelief.for_codename("garnet").count == 1


def test_six_handed_showdowns_identify_a_rule_faster_than_heads_up_ones():
    """The same count of showdowns has to price the deck better six-handed.

    A phase 2 leg of 40 heads-up hands yielded 7-16 labelled comparisons; one
    six-way showdown carries five at once, which is what makes phase 3 evidence
    worth folding back into the phase 2 seed.

    Averaged, not per seed: on any single seed a wrong rule can happen to name
    the same winner eight times running, and at 8 showdowns "lowest wins" really
    is a coin flip either way. The claim is about the mean.
    """
    import random
    import statistics

    for name in ("standard", "near", "high"):
        truth = {name: 1.0}
        spots = [(n, c) for n in range(1, DECK + 1) for c in (3, 7, 11)]
        error = {2: [], 6: []}
        for seed in range(6):
            for seats in (2, 6):
                forget_all()
                rng = random.Random(seed)
                rule = BY_NAME[name]
                for i in range(16):
                    numbers = {s: rng.randint(1, DECK) for s in range(seats)}
                    c = rng.randint(1, DECK)
                    observe(f"t{seats}", match_id="m", leg=1, hand_number=i,
                            numbers=numbers, community=c,
                            winners=showdown_winners(rule, numbers, c))
                belief = posterior_for(f"t{seats}")
                error[seats].append(
                    max(abs(rule_equity(belief, n, c) - rule_equity(truth, n, c))
                        for n, c in spots)
                )
        six, two = statistics.mean(error[6]), statistics.mean(error[2])
        assert six < two, f"{name}: six-handed {six:.3f} is no better than {two:.3f}"


def test_the_fitted_order_learns_from_multiway_showdowns():
    # the non-parametric fallback used to skip anything that was not exactly
    # two-handed, which would have thrown away every phase 3 showdown
    from app.showdown_rules import _fit_order, Observation

    # 13 always wins, 1 always loses, in six-way pots
    observations = [
        Observation({0: 1, 1: 5, 2: 8, 3: 13, 4: 3, 5: 6}, 7, (3,)),
        Observation({0: 13, 1: 2, 2: 4, 3: 9, 4: 1, 5: 6}, 7, (0,)),
        Observation({0: 6, 1: 13, 2: 1, 3: 3, 4: 8, 5: 2}, 7, (1,)),
    ]
    order = _fit_order(observations)
    assert order[13] > order[8] > order[1]


def test_co_winners_of_a_multiway_pot_are_scored_as_a_tie():
    from app.showdown_rules import _fit_order, Observation

    # 11 and 12 split every pot they are both in; 3 always loses to them
    observations = [
        Observation({0: 11, 1: 12, 2: 3}, 7, (0, 1)),
        Observation({0: 12, 1: 11, 2: 3}, 7, (0, 1)),
    ]
    order = _fit_order(observations)
    assert abs(order[11] - order[12]) < 1e-9
    assert order[11] > order[3]


def test_losers_of_a_multiway_pot_are_not_ranked_against_each_other():
    # the showdown says the winner beat them all; it says NOTHING about how the
    # losers compare, and inventing that would poison the fit
    from app.showdown_rules import _fit_order, Observation

    order = _fit_order([Observation({0: 13, 1: 4, 2: 5}, 7, (0,))])
    assert abs(order[4] - order[5]) < 1e-9


def test_learning_still_works_from_the_wire_six_handed():
    import random

    rng = random.Random(3)
    low = BY_NAME["low"]
    hands = []
    for i in range(10):
        numbers = {s: rng.randint(1, DECK) for s in range(6)}
        c = rng.randint(1, DECK)
        hands.append({
            "hand_number": i + 1,
            "community_number": c,
            "winners": showdown_winners(low, numbers, c),
            "pot": 30,
            "shown_numbers": {str(s): n for s, n in numbers.items()},
            "actions": [],
        })
    move(table_rule="lapis", recent_hands=hands, hand_number=11)
    assert RuleBelief.for_codename("lapis").count == 10
    belief = posterior_for("lapis")
    assert rule_equity(belief, 1, 5) > rule_equity(belief, 13, 5)


# ─────────────────────────────── robustness ─────────────────────────────────────


def test_a_table_where_everyone_else_folded_is_heads_up_maths():
    players = [seat(0, "you")] + [seat(n, f"p{n}", folded=True) for n in range(1, 6)]
    r = move(players=players, your_number=10)
    assert r.status_code == 200
    # nobody live at all must not divide by zero
    assert r.json()["action"] in ("check", "bet")


def test_a_malformed_players_list_never_breaks_the_endpoint():
    for junk in ([], None, "table", [None, 3], [{"seat": "x"}], [{}] * 6,
                 [{"seat": 0, "folded": "maybe", "busted": None}]):
        r = move(players=junk)
        assert r.status_code == 200, junk
        assert r.json()["action"] in BASE["legal_actions"], junk


def test_a_larger_table_than_six_is_still_answered():
    big = [seat(n, "you" if n == 0 else f"p{n}") for n in range(10)]
    r = move(players=big)
    assert r.status_code == 200
    assert r.json()["action"] in BASE["legal_actions"]


def test_a_six_handed_move_is_fast_enough():
    # the equity product runs over every rule we still believe in, every possible
    # community number and every live opponent — against a 5 second budget
    import random
    import time

    rng = random.Random(1)
    rule = BY_NAME["near"]
    for i in range(300):
        numbers = {s: rng.randint(1, DECK) for s in range(6)}
        c = rng.randint(1, DECK)
        observe("busy3", match_id=f"m{i // 20}", leg=1, hand_number=i, numbers=numbers,
                community=c, winners=showdown_winners(rule, numbers, c))

    start = time.perf_counter()
    for i in range(10):
        r = move(table_rule="busy3", community_number=None, round="pre_reveal",
                 hand_number=40 + i)
        assert r.status_code == 200
    per_call = (time.perf_counter() - start) / 10
    assert per_call < 0.5, f"{per_call * 1000:.0f} ms per /move against a 5 s budget"


# ───────────────────── phases 1 and 2 are untouched ─────────────────────────────


def test_the_guides_worked_example_is_still_a_fold():
    # phase 1, 300 points, still scored and still re-runnable by the grader
    r = move(
        phase=1, table_rule="standard", leg_number=None, total_legs=None,
        total_hands=100, hand_number=6, your_number=3, community_number=5,
        your_stack=185, pot=32, to_call=18, min_raise_to=36, max_raise_to=185,
        legal_actions=["fold", "call", "raise"],
        players=[seat(0, "you", stack=185, chip_delta=-8),
                 seat(1, "Gaston", stack=183, chip_delta=8, bet_this_round=18)],
    )
    assert r.json() == {"action": "fold"}


def test_two_seat_decisions_are_identical_to_the_phase_two_engine():
    """Every two-handed decision, replayed against the pre-phase-3 engine.

    Not "similar" — the field-share scale and the equity product are both the
    identity at one opponent, so 400 two-seat spots recorded from the phase 2
    engine (tests/data/phase2_decisions.json: 162 folds, 98 checks, 76 calls,
    41 bets, 23 raises, exact amounts) must come back byte-for-byte. This is the
    guard on iron rule 1 for the 700 points phases 1 and 2 are already worth.

    Re-record it with tools/record_phase2_decisions.py against a checkout that
    predates phase 3 if the phase 2 engine is ever deliberately retuned.
    """
    from pathlib import Path

    rows = json.loads((Path(__file__).parent / "data" / "phase2_decisions.json").read_text())
    assert len(rows) == 400
    for i, row in enumerate(rows):
        assert live_opponents(row["state"]) == 1
        assert decide(row["state"]) == row["reply"], f"row {i}: {row['state']}"
