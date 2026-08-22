"""tool-box sheet 3 ("Working Life") — see docs/phases/tool-box-3/notes.md.

Same shape as tests/test_toolbox2.py: the grader never calls us directly, it
drives an LLM agent that speaks MCP to {teamUrl}/mcp, so these talk the wire
protocol and then the tools behind it.

Nothing here touches the network. `offline` blanks cityclock.HOST for every
test, so every answer comes from the snapshot in app/data/city.json and a
failure is always ours and never Heroku's.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import cityclock
from app.main import app

client = TestClient(app)
HEADERS = {"Accept": "application/json, text/event-stream"}


def rpc(method, params=None, req_id=1):
    body = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=HEADERS)


def result_of(method, params=None):
    r = rpc(method, params)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert "error" not in payload, payload
    return payload["result"]


def call_tool(name, arguments):
    return result_of("tools/call", {"name": name, "arguments": arguments})


def blocks(result):
    return [b["text"] for b in result["content"] if b["type"] == "text"]


def answer(name, arguments):
    result = call_tool(name, arguments)
    assert result["isError"] is False, blocks(result)
    assert len(result["content"]) == 1, "one text block; the grader joins them"
    return blocks(result)[0]


def refusal(name, arguments):
    result = call_tool(name, arguments)
    assert result["isError"] is True, blocks(result)
    return blocks(result)[0]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No network in tests: read the vendored city, never the challenge host."""
    monkeypatch.setattr(cityclock, "HOST", "")
    cityclock.forget()
    yield
    cityclock.forget()


def minutes(text):
    return cityclock.to_minutes(text)


# --- the conventions the statement says are not checked for us --------------


def test_times_are_zero_padded_24_hour():
    assert cityclock.to_clock(9 * 60) == "09:00"       # "Never 9:00"
    assert cityclock.to_clock(21 * 60) == "21:00"
    assert cityclock.to_clock(23 * 60) == "23:00"


@pytest.mark.parametrize(
    "written,expected",
    [("13:00", 780), ("09:00", 540), ("9:00", 540), ("1pm", 780), ("1 PM", 780),
     ("12am", 0), ("12pm", 720), (14, 840), ("0900", 540), ("21:00", 1260)],
)
def test_clock_reading_is_lenient(written, expected):
    assert cityclock.to_minutes(written) == expected


@pytest.mark.parametrize("written", ["Tuesday", "tuesday", "TUE", "on Tuesday", " tuesday "])
def test_weekday_reading_is_lenient(written):
    assert cityclock.to_day(written) == "Tuesday"


def test_an_unreadable_day_is_refused_not_guessed():
    with pytest.raises(cityclock.PlanError):
        cityclock.to_day("someday")


def test_x_comes_first():
    # "the distance formula gives the same answer if you swap them, so getting
    # the order wrong produces a confident, plausible, wrong answer"
    assert cityclock.to_point([3, 8]) == (3, 8)
    assert cityclock.to_point({"x": 3, "y": 8}) == (3, 8)
    assert cityclock.to_point("[3, 8]") == (3, 8)
    assert cityclock.position("ada", "Tuesday") == (0, 1)


def test_travel_is_manhattan():
    assert cityclock.distance((0, 0), (3, 4)) == 7
    assert cityclock.distance((9, 9), (9, 9)) == 0


def test_the_android_is_never_a_person_to_look_up():
    assert cityclock.to_people("you and ada, bram") == ["ada", "bram"]
    assert cityclock.to_people(["me", "Ada", "BRAM"]) == ["ada", "bram"]
    assert cityclock.to_people("cira & iris") == ["cira", "iris"]


def test_off_grid_is_refused():
    with pytest.raises(cityclock.PlanError):
        cityclock.on_grid((10, 0))
    with pytest.raises(cityclock.PlanError):
        cityclock.on_grid((0, -1))


# --- problem set 1: somewhere to eat ---------------------------------------


def test_the_statements_own_eating_question():
    # "Which places can you eat at on Thursday at 08:00?"
    assert answer("find_places_to_eat", {"day": "Thursday", "time": "08:00"}) == "Copperline"


@pytest.mark.parametrize(
    "day,time,expected",
    [
        ("Tuesday", "16:00", {"Nine Quarters", "Pellet & Vine", "Cask & Rill"}),
        ("Monday", "12:00", {"Loam", "Marrow House", "Tallow Green"}),
        ("Sunday", "22:00", {"Loam"}),
        ("Friday", "08:00", {"Ember Yard"}),
    ],
)
def test_every_place_open_at_that_hour_not_the_first(day, time, expected):
    given = answer("find_places_to_eat", {"day": day, "time": time})
    assert set(given.split(", ")) == expected


def test_open_is_half_open_at_the_hour():
    # Sorrel trades 08:00-14:00 and 15:00-16:00 on Tuesday: open at 15:00,
    # shut at 14:00 and at 16:00.
    sorrel = cityclock.find_venue("Tuesday", "Sorrel")
    assert cityclock.is_open(sorrel, minutes("13:00"))
    assert not cityclock.is_open(sorrel, minutes("14:00"))
    assert cityclock.is_open(sorrel, minutes("15:00"))
    assert not cityclock.is_open(sorrel, minutes("16:00"))


def test_a_place_never_moves():
    for day in cityclock.DAYS:
        for venue in cityclock.venues(day):
            if venue["name"] == "Amber Hall":
                assert (venue["x"], venue["y"]) == (6, 3)


def test_eating_question_without_a_day_is_refused_not_guessed():
    assert "weekday" in refusal("find_places_to_eat", {"time": "08:00"})


# --- problem set 2: a time everyone can make -------------------------------


def test_the_statements_own_meeting_question():
    # "Find the best 60-minute window on Tuesday between 13:00 and 18:00 when
    # you and ada, bram can all meet, for lunch."
    given = answer(
        "find_meeting_time",
        {"day": "Tuesday", "people": "you and ada, bram",
         "earliest": "13:00", "latest": "18:00", "minutes": 60, "reason": "lunch"},
    )
    assert given == "16:00-17:00"


@pytest.mark.parametrize(
    "day,people,earliest,latest,expected",
    [
        ("Monday", ["dov", "iris", "hale"], "13:00", "18:00", "17:00-18:00"),
        ("Wednesday", ["cira"], "08:00", "23:00", "13:00-14:00"),
        ("Thursday", ["ada", "esme", "gita"], "09:00", "15:00", "10:00-11:00"),
        ("Saturday", ["fenn"], "08:00", "12:00", "11:00-12:00"),
    ],
)
def test_meeting_windows(day, people, earliest, latest, expected):
    given = answer(
        "find_meeting_time",
        {"day": day, "people": people, "earliest": earliest, "latest": latest},
    )
    assert given == expected


def test_everyone_free_all_week_still_answers():
    given = answer(
        "find_meeting_time",
        {"day": "Sunday", "people": list(cityclock.SNAPSHOT["people"]),
         "earliest": "08:00", "latest": "23:00"},
    )
    assert given == "16:00-17:00"


def _own_day(accepted=(), tentative=()):
    """Stand in for the inbox so the statement's worked examples can be run."""
    def commitments(day):
        return ([(minutes(a), minutes(b)) for a, b in accepted],
                [(minutes(a), minutes(b)) for a, b in tentative])
    return commitments


def test_worked_example_a_tentative_gives_way_when_nothing_is_clean(monkeypatch):
    # page 6: 12:00-13:00 TENTATIVE, 13:00-14:00 ACCEPTED  ->  12:00-13:00
    monkeypatch.setattr(
        cityclock, "commitments",
        _own_day(accepted=[("13:00", "14:00")], tentative=[("12:00", "13:00")]),
    )
    window = cityclock.find_window("Tuesday", [], minutes("12:00"), minutes("14:00"), 60)
    assert (cityclock.to_clock(window["start"]), cityclock.to_clock(window["end"])) == (
        "12:00", "13:00")


def test_worked_example_b_a_clean_window_beats_an_earlier_unclean_one(monkeypatch):
    # page 6: 12:00-13:00 TENTATIVE only  ->  13:00-14:00, "even though it is earlier"
    monkeypatch.setattr(
        cityclock, "commitments", _own_day(tentative=[("12:00", "13:00")]))
    window = cityclock.find_window("Tuesday", [], minutes("12:00"), minutes("14:00"), 60)
    assert (cityclock.to_clock(window["start"]), cityclock.to_clock(window["end"])) == (
        "13:00", "14:00")


def test_declined_constrains_nothing_at_all(monkeypatch):
    monkeypatch.setattr(cityclock, "commitments", _own_day())
    window = cityclock.find_window("Tuesday", [], minutes("12:00"), minutes("14:00"), 60)
    assert cityclock.to_clock(window["start"]) == "12:00"
    assert window["quality"] == "clear"


def test_a_meeting_may_start_when_something_else_ends(monkeypatch):
    monkeypatch.setattr(cityclock, "commitments", _own_day(accepted=[("12:00", "13:00")]))
    window = cityclock.find_window("Tuesday", [], minutes("12:00"), minutes("14:00"), 60)
    assert cityclock.to_clock(window["start"]) == "13:00"


def test_a_fully_booked_range_still_gets_an_answer(monkeypatch):
    monkeypatch.setattr(
        cityclock, "commitments",
        _own_day(accepted=[("12:00", "13:00"), ("13:00", "14:00")]),
    )
    window = cityclock.find_window("Tuesday", [], minutes("12:00"), minutes("14:00"), 60)
    assert cityclock.to_clock(window["start"]) in {"12:00", "13:00"}
    assert "clash" in window["quality"]


def test_windows_start_on_the_hour_and_stay_inside_the_range():
    windows = cityclock.candidate_windows(minutes("13:00"), minutes("18:00"), 60)
    assert windows[0] == (minutes("13:00"), minutes("14:00"))
    assert windows[-1] == (minutes("17:00"), minutes("18:00"))
    assert all(start % 60 == 0 for start, _ in windows)


def test_the_range_is_clamped_to_the_working_day():
    windows = cityclock.candidate_windows(0, 24 * 60, 60)
    assert windows[0][0] == cityclock.DAY_OPENS
    assert windows[-1][1] == cityclock.DAY_CLOSES


def test_a_range_too_short_for_the_meeting_is_refused():
    assert "fits" in refusal(
        "find_meeting_time",
        {"day": "Tuesday", "people": ["ada"], "earliest": "13:00",
         "latest": "13:30", "minutes": 60},
    )


def test_a_two_hour_meeting_is_two_hours_long():
    given = answer(
        "find_meeting_time",
        {"day": "Wednesday", "people": ["cira"], "earliest": "08:00",
         "latest": "23:00", "minutes": 120},
    )
    start, end = given.split("-")
    assert minutes(end) - minutes(start) == 120


def test_an_unknown_guest_is_refused_not_ignored():
    assert "nobody" in refusal(
        "find_meeting_time", {"day": "Tuesday", "people": ["ada", "zebedee"]}
    )


# --- problem set 3: a place to meet ----------------------------------------


def test_the_statements_own_meeting_point_question():
    # "It is Wednesday and you are at [0, 3]. You want to meet cira, iris."
    given = answer(
        "find_meeting_point",
        {"day": "Wednesday", "my_position": [0, 3], "people": "cira, iris"},
    )
    assert given == "[1, 5]"


@pytest.mark.parametrize(
    "day,me,people,expected",
    [
        ("Monday", [4, 5], ["dov", "iris", "hale"], "[4, 4]"),
        ("Friday", [9, 9], ["ada"], "[0, 7]"),
        ("Tuesday", [0, 0], ["ada", "bram", "cira", "dov"], "[0, 1]"),
    ],
)
def test_meeting_points(day, me, people, expected):
    given = answer(
        "find_meeting_point", {"day": day, "my_position": me, "people": people})
    assert given == expected


def test_the_android_counts_too():
    # "Everyone counts, including the android." Drop it and the point moves.
    people = ["ada", "bram"]
    with_me = cityclock.best_point(cityclock.gather("Monday", [9, 9], people))
    without_me = cityclock.best_point([cityclock.position(p, "Monday") for p in people])
    assert with_me == (7, 7) and without_me == (7, 1)


def test_the_meeting_point_is_optimal_over_the_whole_grid():
    positions = cityclock.gather("Wednesday", [0, 3], ["cira", "iris"])
    chosen = cityclock.best_point(positions)
    best = min(
        sum(cityclock.distance(p, (x, y)) for p in positions)
        for x in range(cityclock.GRID) for y in range(cityclock.GRID)
    )
    assert sum(cityclock.distance(p, chosen) for p in positions) == best


def test_ties_are_broken_the_same_way_every_time():
    positions = cityclock.gather("Monday", [4, 5], ["dov", "iris", "hale"])
    assert cityclock.best_point(positions) == cityclock.best_point(positions) == (4, 4)


def test_a_meeting_point_told_where_it_goes_next_moves():
    # "A meeting point chosen without regard to where you are going afterwards
    # is answering a different question."
    positions = cityclock.gather("Monday", [4, 5], ["dov", "iris", "hale"])
    blind = cityclock.best_point(positions)
    aimed = cityclock.best_point(positions, then_on_to=(5, 5))
    assert blind == (4, 4) and aimed == (5, 5)


def test_a_meeting_point_without_a_position_is_refused():
    assert "where are you" in refusal(
        "find_meeting_point", {"day": "Wednesday", "people": ["cira"]})


# --- problem set 4: an outing ----------------------------------------------


def test_the_statements_own_outing_question():
    # "It is Monday and you are at [4, 5]. You want to meet dov, iris, hale for
    # coffee between 13:00 and 18:00, for 60 minutes, and then go on somewhere
    # to eat."
    given = json.loads(answer(
        "plan_outing",
        {"day": "Monday", "my_position": [4, 5], "people": "dov, iris, hale",
         "earliest": "13:00", "latest": "18:00", "minutes": 60, "reason": "coffee"},
    ))
    assert given == {
        "meeting": "17:00-18:00",
        "meeting_point": [5, 5],
        "eat_at": "Copperline",
    }


def test_the_outing_uses_the_window_everyone_can_actually_make():
    # check 1: "If it is not the window everyone can actually make, the outing
    # scores zero and nothing else about it is looked at."
    asked = {"day": "Monday", "my_position": [4, 5], "people": ["dov", "iris", "hale"],
             "earliest": "13:00", "latest": "18:00"}
    outing = json.loads(answer("plan_outing", asked))
    alone = answer("find_meeting_time", {k: asked[k] for k in
                                         ("day", "people", "earliest", "latest")})
    assert outing["meeting"] == alone


def test_the_place_to_eat_is_open_for_the_hour_the_meeting_ends():
    # check 2: "If it is not available for the hour beginning when the meeting
    # ends, the outing scores zero and the meeting point is not looked at."
    for day, me, people, lo, hi in [
        ("Monday", [4, 5], ["dov", "iris", "hale"], "13:00", "18:00"),
        ("Thursday", [0, 0], ["ada", "bram"], "08:00", "23:00"),
        ("Saturday", [9, 0], ["cira", "esme"], "12:00", "20:00"),
    ]:
        outing = json.loads(answer(
            "plan_outing", {"day": day, "my_position": me, "people": people,
                            "earliest": lo, "latest": hi}))
        ends = minutes(outing["meeting"].split("-")[1])
        assert cityclock.is_open(cityclock.find_venue(day, outing["eat_at"]), ends)


def test_the_whole_journey_is_what_is_minimised():
    plan = cityclock.plan_outing(
        "Monday", [4, 5], ["dov", "iris", "hale"], minutes("13:00"), minutes("18:00"))
    positions = plan["positions"]
    best = min(
        sum(cityclock.distance(p, (x, y)) for p in positions)
        + cityclock.distance((x, y), (venue["x"], venue["y"]))
        for venue in cityclock.open_at("Monday", plan["end"])
        for x in range(cityclock.GRID) for y in range(cityclock.GRID)
    )
    assert plan["travel"] == best


def test_the_outing_beats_meeting_first_and_choosing_a_venue_after():
    """The trap the statement names: pick the point, then the nearest place."""
    day, me, people = "Monday", [4, 5], ["dov", "iris", "hale"]
    plan = cityclock.plan_outing(day, me, people, minutes("13:00"), minutes("18:00"))
    positions = plan["positions"]
    blind = cityclock.best_point(positions)
    naive = min(
        sum(cityclock.distance(p, blind) for p in positions)
        + cityclock.distance(blind, (venue["x"], venue["y"]))
        for venue in cityclock.open_at(day, plan["end"])
    )
    assert plan["travel"] < naive


def test_an_outing_answer_carries_all_three_parts():
    given = json.loads(answer(
        "plan_outing",
        {"day": "Thursday", "my_position": [0, 0], "people": ["ada", "bram"]}))
    assert set(given) == {"meeting", "meeting_point", "eat_at"}
    start, end = given["meeting"].split("-")
    assert minutes(start) is not None and minutes(end) == minutes(start) + 60
    assert len(given["meeting_point"]) == 2
    assert all(0 <= n < cityclock.GRID for n in given["meeting_point"])


def test_an_outing_off_the_grid_is_refused():
    assert "grid" in refusal(
        "plan_outing", {"day": "Monday", "my_position": [12, 0], "people": ["ada"]})


# --- the means, for an android that would rather work it out itself ---------


def test_a_friends_day_can_be_looked_up():
    given = json.loads(answer("get_day_schedule", {"person": "ada", "day": "Tuesday"}))
    assert given == {"busy": [["13:00", "14:00"], ["15:00", "16:00"], ["17:00", "18:00"]]}


def test_my_own_day_reads_the_inbox_not_the_schedule_feed():
    given = json.loads(answer("get_day_schedule", {"person": "me", "day": "Tuesday"}))
    assert given["busy"] == [["08:00", "09:00"], ["13:00", "14:00"], ["19:00", "20:00"]]
    assert ["14:00", "15:00"] in given["tentative"]


def test_a_persons_whereabouts_can_be_looked_up():
    assert answer("where_is", {"person": "ada", "day": "Tuesday"}) == "[0, 1]"


def test_a_declined_invitation_never_reaches_the_diary():
    accepted, tentative = cityclock.commitments("Monday")
    booked = {cityclock.to_clock(start) for start, _ in accepted}
    pencilled = {cityclock.to_clock(start) for start, _ in tentative}
    assert booked == {"09:00", "13:00", "14:00", "16:00", "18:00"}
    assert pencilled == {"10:00", "17:00", "19:00"}
    assert not booked & pencilled


# --- limits, and the sheets that came before -------------------------------


def test_no_more_than_twenty_tools_are_offered():
    tools = result_of("tools/list")["tools"]
    assert len(tools) <= 20
    assert len({tool["name"] for tool in tools}) == len(tools)


def test_every_sheet_three_tool_is_advertised():
    names = {tool["name"] for tool in result_of("tools/list")["tools"]}
    assert {"find_places_to_eat", "find_meeting_time", "find_meeting_point",
            "plan_outing", "get_day_schedule", "where_is"} <= names


def test_answers_are_nowhere_near_the_token_ceiling():
    # /limits: 1,200 o200k_base tokens over the whole response. Four characters
    # per token is the pessimistic rule of thumb; ours are two orders below.
    for name, arguments in [
        ("find_places_to_eat", {"day": "Monday", "time": "12:00"}),
        ("find_meeting_time", {"day": "Tuesday", "people": ["ada", "bram"]}),
        ("find_meeting_point", {"day": "Wednesday", "my_position": [0, 3],
                                "people": ["cira", "iris"]}),
        ("plan_outing", {"day": "Monday", "my_position": [4, 5],
                         "people": ["dov", "iris", "hale"]}),
    ]:
        assert len(answer(name, arguments)) < 400


def test_earlier_sheets_still_answer():
    assert answer("calculate", {"expression": "2 + 2"}) == "4"
    assert answer("get_my_name", {}) == "Milo"
    assert answer("find_location_code", {"place": "Marrowgate Market"}) == "STOP_07"


def test_nothing_in_the_mcp_path_returns_a_five_hundred():
    for name in ("find_places_to_eat", "find_meeting_time", "find_meeting_point",
                 "plan_outing", "get_day_schedule", "where_is"):
        for arguments in ({}, {"day": None}, {"day": ["Tuesday"], "people": 7},
                          {"day": "Tuesday", "my_position": "over there"}):
            result = call_tool(name, arguments)
            assert isinstance(result["isError"], bool)
            assert blocks(result) and all(isinstance(b, str) for b in blocks(result))
