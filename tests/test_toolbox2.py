"""tool-box sheet 2 ("School Days") — see docs/phases/tool-box-2/notes.md.

Same shape as tests/test_toolbox.py: the grader never calls us directly, it
drives an LLM agent that speaks MCP to {teamUrl}/mcp, so these talk the wire
protocol and then the three new tools behind it.

Nothing here touches the network. The map tests prime `graphroute`'s cache with
a graph built by hand — including the statement's own worked examples — so a
failure is always ours and never Heroku's.
"""
import pytest
from fastapi.testclient import TestClient

from app import graphroute
from app.main import app
from app.recall import BUDGET, CORPUS, recall, resolve_location, token_total

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
    return "".join(blocks(result))


@pytest.fixture(autouse=True)
def clean_map_state():
    graphroute.forget_journeys()
    graphroute.forget_maps()
    yield
    graphroute.forget_journeys()
    graphroute.forget_maps()


# --- problem set 1: exam time ----------------------------------------------

# Worded away from the corpus on purpose, the way the statement's own example is.
QUESTIONS = [
    ("When was the sensor grid last brought back into alignment?", "14 March"),
    ("What is the station's primary radio call sign?", "Umbral Seven"),
    ("Which call sign is kept for emergency traffic?", "Umbral Two"),
    ("How far below the surface does the main habitat sit?", "6,214"),
    ("How deep is the storage annex?", "6,050"),
    ("How often does the resupply vessel dock?", "19 days"),
    ("How long may a diver stay out on one excursion?", "47 minutes"),
    ("What excursion limit applies to a newly arrived diver?", "35 minutes"),
    ("How tightly is the hydrophone housing gasket tightened?", "12 newton-meters"),
    ("How many people normally live at the station?", "forty-one"),
    ("What is the name of the main submersible?", "Halcyon Drift"),
    ("What is the upkeep dose given in the drug trial?", "240 milligram"),
    ("How often is follow-up bloodwork taken?", "21 days"),
    ("At what liver enzyme reading is a participant taken off dosing?", "260 units"),
    ("What internal code identifies the study?", "VLM-204-B"),
    ("How long must someone be watched after an infusion?", "90 minutes"),
    ("Which build first carried the Emberline lighting path?", "Release 14"),
    ("What is the texture memory ceiling on the baseline console?", "512 megabytes"),
    ("How much frame time is the render thread allowed on console?", "11 milliseconds"),
    ("When was the shared drier rota adopted by the board?", "21 May"),
    ("When did the cold store compressor break down?", "6 April"),
]


def test_the_statements_worked_example():
    """The one example the statement gives, verbatim.

    "When was the sensor grid last brought back into alignment?" -> "14 March".
    Not one of "sensor", "grid" or "alignment" occurs in the document that holds
    the answer, so this is the case that decides whether the tool works at all.
    """
    passages = recall("When was the sensor grid last brought back into alignment?")
    assert any("14 March" in p for p in passages)
    assert any("Kesterline" in p for p in passages)


@pytest.mark.parametrize("question,fact", QUESTIONS)
def test_recall_carries_the_fact(question, fact):
    assert any(fact.lower() in p.lower() for p in recall(question))


# The statement's number, written out rather than imported: a test that checks
# the code against its own constant would keep passing if that constant drifted.
STATED_LIMIT = 900
STATED_RESPONSE_LIMIT = 1200  # /limits, every tool response in every stage


def test_our_budget_is_the_one_the_statement_states():
    assert BUDGET == STATED_LIMIT


@pytest.mark.parametrize("question,_fact", QUESTIONS)
def test_recall_stays_inside_the_900_token_budget(question, _fact):
    """The budget is the sum over list elements, o200k_base (statement, "HOW THE
    900 TOKENS ARE COUNTED"). An over-budget response is discarded whole."""
    passages = recall(question)
    # token_total only knows strings whose count was baked in by
    # tools/fetch_study_materials.py, so this also proves we never emit a
    # string we cannot count -- the property the whole design rests on.
    assert token_total(passages) <= STATED_LIMIT


def test_recall_fills_the_budget():
    """Coming in under 900 buys nothing and costs coverage."""
    for question, _ in QUESTIONS:
        assert token_total(recall(question)) > STATED_LIMIT * 0.8, question


def test_recall_answers_with_a_list_of_separate_passages():
    result = call_tool("recall_study_material", {"question": "What is the primary call sign?"})
    assert result["isError"] is False
    assert len(result["content"]) > 1  # a list, not one glued-together string
    assert all(b["type"] == "text" for b in result["content"])


def test_recall_over_mcp_stays_in_budget():
    result = call_tool("recall_study_material", {"question": "How deep is the main habitat?"})
    passages = blocks(result)
    assert token_total(passages) <= STATED_LIMIT
    # and under the all-stages ceiling even if they tokenise the whole response
    # rather than summing the elements
    assert token_total(passages) <= STATED_RESPONSE_LIMIT


def test_recall_passages_are_verbatim_corpus_text():
    known = {p.text for p in CORPUS.paragraphs} | {s.text for s in CORPUS.sentences}
    known |= {h["text"] for h in CORPUS.headers.values()}
    known |= {h["text"] for h in CORPUS.headings.values()}
    for passage in recall("What torque is applied to the gasket?"):
        assert passage in known


def test_recall_needs_a_question():
    result = call_tool("recall_study_material", {})
    assert result["isError"] is True


def test_recall_survives_a_question_with_no_usable_words():
    for junk in ("", "   ", "???", "the a of"):
        passages = recall(junk)
        assert passages
        assert token_total(passages) <= BUDGET


def test_recall_accepts_the_argument_under_other_names():
    assert blocks(call_tool("recall_study_material", {"query": "call sign"}))


# --- problem set 2: out after school ---------------------------------------

# The statement's own map, page 4.
STATEMENT_MAP = {
    "adjacency": {"A": {"B": 4.0, "C": 2.0}, "B": {"D": 3.0}, "C": {"D": 2.0}},
    "tolls": {"A": 5.0, "B": 1.0, "C": 9.0, "D": 2.0},
}

# A cheap long way and a dear short one, for the curfew.
CURFEW_MAP = {
    "adjacency": {
        "S": {"X": 10.0, "P": 1.0}, "X": {"Y": 10.0}, "Y": {"D": 10.0},
        "P": {"Q": 1.0}, "Q": {"R": 1.0}, "R": {"D": 1.0},
    },
    "tolls": {n: 0.0 for n in "SXYDPQR"},
}


def prime(map_id, payload):
    graphroute.remember(map_id, graphroute.parse_graph(payload))


def test_cost_counts_entry_tolls_not_just_edges():
    """total cost = sum(edge weights) + sum(entry tolls).

    On the statement's map the two routes are A->B->D at 4+3+1+2 = 10 and
    A->C->D at 2+2+9+2 = 15. Ignore the tolls and A->C->D looks like the
    cheaper one (4 against 7), so this single answer decides whether our notion
    of cost is theirs.
    """
    prime("m1", STATEMENT_MAP)
    graph = graphroute.load_graph("m1")
    assert graphroute.path_cost(graph, ["A", "B", "D"]) == 10.0
    assert graphroute.path_cost(graph, ["A", "C", "D"]) == 15.0
    assert answer("next_step_towards", {"map_id": "m1", "current": "A", "destination": "D"}) == "B"


def test_the_statements_hop_allowance_walkthrough():
    """at S, 3 left -> X; at X, 2 left -> Y; at Y, 1 left -> D (arrived).

    The allowance counts the hop being asked for, so the cheap four-hop route
    through P is not available at 3 and the dear three-hop one must be taken.
    """
    prime("m2", CURFEW_MAP)
    assert answer("next_step_towards",
                  {"map_id": "m2", "current": "S", "destination": "D", "hops_left": 3}) == "X"
    assert answer("next_step_towards",
                  {"map_id": "m2", "current": "X", "destination": "D", "hops_left": 2}) == "Y"
    assert answer("next_step_towards",
                  {"map_id": "m2", "current": "Y", "destination": "D", "hops_left": 1}) == "D"


def test_without_a_curfew_the_cheap_long_way_wins():
    prime("m3", CURFEW_MAP)
    assert answer("next_step_towards", {"map_id": "m3", "current": "S", "destination": "D"}) == "P"


def test_one_hop_left_means_the_destination_must_be_adjacent():
    prime("m4", CURFEW_MAP)
    graph = graphroute.load_graph("m4")
    assert graphroute.cheapest_route_within(graph, "S", "D", 1) is None
    assert graphroute.cheapest_route_within(graph, "R", "D", 1) == ["R", "D"]


def test_a_curfew_it_cannot_meet_still_gets_a_move_towards_the_goal():
    """Refusing scores zero for certain; a hop toward the goal might not."""
    prime("m5", CURFEW_MAP)
    step = answer("next_step_towards",
                  {"map_id": "m5", "current": "S", "destination": "D", "hops_left": 1})
    assert step in {"X", "P"}


def test_every_step_returned_is_adjacent_to_where_it_is_standing():
    """"Returning a node that is not adjacent" is one of the four zeroes."""
    prime("m6", CURFEW_MAP)
    graph = graphroute.load_graph("m6")
    here = "S"
    for _ in range(6):
        step = answer("next_step_towards", {"map_id": "m6", "current": here, "destination": "D"})
        assert step in graph["adjacency"][here], f"{here} -> {step} is not an edge"
        here = step
        if here == "D":
            break
    assert here == "D"


def test_a_node_already_visited_is_never_returned_again():
    """"Returning a node already visited on this journey" is another zero."""
    prime("m7", {
        "adjacency": {"A": {"B": 1.0}, "B": {"A": 1.0, "C": 5.0}, "C": {"D": 1.0}, "D": {}},
        "tolls": {n: 0.0 for n in "ABCD"},
    })
    walked = ["A"]
    here = "A"
    for _ in range(5):
        here = answer("next_step_towards", {"map_id": "m7", "current": here, "destination": "D"})
        assert here not in walked, f"{here} was already visited: {walked}"
        walked.append(here)
        if here == "D":
            break
    assert here == "D"


def test_asking_twice_at_the_same_node_is_not_treated_as_a_revisit():
    prime("m8", STATEMENT_MAP)
    first = answer("next_step_towards", {"map_id": "m8", "current": "A", "destination": "D"})
    again = answer("next_step_towards", {"map_id": "m8", "current": "A", "destination": "D"})
    assert first == again == "B"


def test_arriving_is_reported_rather_than_answered_with_a_revisit():
    prime("m9", STATEMENT_MAP)
    result = call_tool("next_step_towards", {"map_id": "m9", "current": "D", "destination": "D"})
    assert result["isError"] is True


def test_node_names_are_matched_however_they_are_written():
    prime("m10", STATEMENT_MAP)
    assert answer("next_step_towards", {"map_id": "m10", "current": "a", "destination": "d"}) == "B"


def test_hops_left_is_accepted_as_text_or_a_float():
    prime("m11", CURFEW_MAP)
    assert answer("next_step_towards",
                  {"map_id": "m11", "current": "S", "destination": "D", "hops_left": "3 left"}) == "X"
    graphroute.forget_journeys()
    assert answer("next_step_towards",
                  {"map_id": "m11", "current": "S", "destination": "D", "hops_left": 3.0}) == "X"


def test_an_unreachable_destination_is_an_error_result_not_a_crash():
    prime("m12", {"adjacency": {"A": {"B": 1.0}, "B": {}, "Z": {}}, "tolls": {"A": 0, "B": 0, "Z": 0}})
    result = call_tool("next_step_towards", {"map_id": "m12", "current": "A", "destination": "Z"})
    assert result["isError"] is True


def test_missing_arguments_are_error_results_not_crashes():
    for arguments in ({}, {"map_id": "m13"}, {"map_id": "m13", "current": "A"}):
        result = call_tool("next_step_towards", arguments)
        assert result["isError"] is True


def test_an_unknown_node_is_an_error_result():
    prime("m14", STATEMENT_MAP)
    result = call_tool("next_step_towards",
                       {"map_id": "m14", "current": "A", "destination": "nowhere at all"})
    assert result["isError"] is True


def test_a_map_that_cannot_be_parsed_is_refused_cleanly():
    for payload in ({}, {"adjacency": {}}, {"adjacency": "no"}, []):
        with pytest.raises(graphroute.RouteError):
            graphroute.parse_graph(payload)


# --- problem set 3: the school trip ----------------------------------------

# Every marker planted in the study materials, four per document.
PLACES = [
    ("Sablefin Vent Field", "STOP_01"),
    ("Wraithmoor Escarpment", "STOP_02"),
    ("Corbel Slide", "STOP_03"),
    ("Pellucid Shelf observation post", "STOP_04"),
    ("Verity Observatory", "STOP_05"),
    ("Ashgrove Botanical Conservatory", "STOP_06"),
    ("Marrowgate Market", "STOP_07"),
    ("Halloway Aquatic Centre", "STOP_08"),
    ("Bellhaven Infusion Suite", "STOP_09"),
    ("Corrimal Bay Screening Annex", "STOP_10"),
    ("Thornquist Central Pharmacy", "STOP_11"),
    ("Velmara Sample Repository", "STOP_12"),
    ("Hollowlight Capture Stage", "STOP_13"),
    ("Determinism Test Rig", "STOP_14"),
    ("Asset Pipeline Farm", "STOP_15"),
    ("Hollowlight Audio Vault", "STOP_16"),
    ("Thornmere Grading Hall", "STOP_17"),
    ("Netherfield Cold Store", "STOP_18"),
    ("Cooperative Machinery Yard", "STOP_19"),
    ("Harrowbeck Weighbridge", "STOP_20"),
]


@pytest.mark.parametrize("place,code", PLACES)
def test_every_place_resolves_to_its_marker(place, code):
    """Part 3's destination is a place, not a node. The statement calls working
    it out wrongly "the likeliest way to lose the points"."""
    assert resolve_location(place) == code
    assert answer("find_location_code", {"place": place}) == code


def test_a_marker_written_directly_is_passed_through():
    for written in ("STOP_07", "stop_7", "stop 7", "Stop-07"):
        assert resolve_location(written) == "STOP_07"


def test_an_unknown_place_is_refused_rather_than_guessed():
    assert resolve_location("the Ministry of Silly Walks") is None
    assert call_tool("find_location_code", {"place": "the Ministry of Silly Walks"})["isError"]


def test_a_journey_can_be_set_by_place_name():
    """The android may hand the destination straight through unresolved."""
    prime("m15", {
        "adjacency": {"STOP_01": {"STOP_05": 1.0}, "STOP_05": {"STOP_07": 1.0}, "STOP_07": {}},
        "tolls": {"STOP_01": 0.0, "STOP_05": 0.0, "STOP_07": 0.0},
    })
    step = answer("next_step_towards",
                  {"map_id": "m15", "current": "STOP_01", "destination": "Marrowgate Market"})
    assert step == "STOP_05"


def test_the_recall_tool_can_find_a_marker_too():
    """Part 3 may route through recall rather than find_location_code; the
    statement warns that path carries the same 900-token budget."""
    passages = recall("Which stop serves Marrowgate Market?")
    assert any("STOP_07" in p for p in passages)
    assert token_total(passages) <= BUDGET
