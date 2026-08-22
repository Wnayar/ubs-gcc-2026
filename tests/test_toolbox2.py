"""tool-box sheet 2 ("School Days") — see docs/phases/tool-box-2/notes.md.

Same shape as tests/test_toolbox.py: the grader never calls us directly, it
drives an LLM agent that speaks MCP to {teamUrl}/mcp, so these talk the wire
protocol and then the three new tools behind it.

Nothing here touches the network. The map tests prime `graphroute`'s cache with
a graph built by hand — including the statement's own worked examples — so a
failure is always ours and never Heroku's.
"""
import json

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


RETRIEVAL_NAMES = ["retrieve", "recall", "recall_study_material"]


@pytest.mark.parametrize("tool", RETRIEVAL_NAMES)
def test_retrieval_answers_with_one_block_holding_a_json_array_of_strings(tool):
    """The 0/100 run voided every retrieval with "Retrieval must return a JSON
    array of strings". We were returning one MCP content block per passage; the
    grader joins the blocks and parses the text, so that read as a bare string.
    """
    result = call_tool(tool, {"question": "What is the primary call sign?"})
    assert result["isError"] is False
    assert len(result["content"]) == 1, "one block, or the array is lost in the join"
    parsed = json.loads(result["content"][0]["text"])
    assert isinstance(parsed, list) and parsed
    assert all(isinstance(p, str) and p for p in parsed)


@pytest.mark.parametrize("tool", RETRIEVAL_NAMES)
def test_every_name_the_android_reaches_for_is_exposed(tool):
    """It named `retrieve` on two of three attempts and we did not have it."""
    assert tool in {t["name"] for t in result_of("tools/list")["tools"]}
    assert call_tool(tool, {"query": "call sign"})["isError"] is False


def test_the_retrieval_names_are_the_same_function():
    answers = {t: answer(t, {"question": "How deep is the main habitat?"})
               for t in RETRIEVAL_NAMES}
    assert len(set(answers.values())) == 1, answers


def test_recall_over_mcp_stays_in_budget():
    result = call_tool("retrieve", {"question": "How deep is the main habitat?"})
    passages = json.loads(result["content"][0]["text"])
    assert token_total(passages) <= STATED_LIMIT


def test_the_serialised_response_clears_the_all_stages_ceiling():
    """`response-ceiling` measures the whole serialised response, not the
    passages: "Fifteen passages of 60 tokens serialise to about 950". Charging
    a JSON array's punctuation at a generous 4 tokens an element still has to
    fit inside 1,200 alongside the 900 of content.
    """
    for question, _ in QUESTIONS:
        passages = recall(question)
        assert token_total(passages) + 4 * len(passages) + 2 <= STATED_RESPONSE_LIMIT, question


def test_recall_passages_are_verbatim_corpus_text_behind_a_source_prefix():
    known = {p.passage for p in CORPUS.paragraphs} | {s.passage for s in CORPUS.sentences}
    for passage in recall("What torque is applied to the gasket?"):
        assert passage in known
        assert passage.startswith("[")  # carries its own document and section


def test_recall_needs_a_question():
    result = call_tool("retrieve", {})
    assert result["isError"] is True


def test_recall_survives_a_question_with_no_usable_words():
    for junk in ("", "   ", "???", "the a of"):
        passages = recall(junk)
        assert passages
        assert token_total(passages) <= BUDGET


def test_recall_accepts_the_argument_under_other_names():
    assert blocks(call_tool("retrieve", {"query": "call sign"}))


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


# --- the shape the grader's travel wrapper actually eats --------------------

# The 0/100 run asked three travel problems and never called us once: "No tool
# or answer could be found." The grader walks a journey through its own
# `_travel` wrapper, which takes a whole route — {"route": ["B", "G", "H"]} —
# so a tool that returns one node at a time is no use to the android.


def test_plan_route_returns_the_whole_route_as_a_json_array():
    prime("r1", STATEMENT_MAP)
    result = call_tool("plan_route", {"map_id": "r1", "from": "A", "to": "D"})
    assert result["isError"] is False
    assert len(result["content"]) == 1
    route = json.loads(result["content"][0]["text"])
    assert route == ["A", "B", "D"], "toll-blind routing would say A, C, D"


def test_plan_route_is_walkable_and_never_revisits():
    """The two hard zeroes in `travel-move`: a hop must be adjacent, and no node
    may be entered twice."""
    prime("r2", {
        "adjacency": {
            "A": {"B": 1.0, "C": 9.0}, "B": {"A": 1.0, "C": 1.0, "D": 9.0},
            "C": {"B": 1.0, "D": 1.0}, "D": {"A": 1.0},
        },
        "tolls": {n: 0.5 for n in "ABCD"},
    })
    graph = graphroute.load_graph("r2")
    route = json.loads(answer("plan_route", {"map_id": "r2", "from": "A", "to": "D"}))
    assert route[0] == "A" and route[-1] == "D"
    assert len(set(route)) == len(route), f"revisit in {route}"
    for previous, node in zip(route, route[1:]):
        assert node in graph["adjacency"][previous], f"{previous} -> {node} is not an edge"


def test_route_cost_counts_edges_plus_entry_tolls():
    prime("r3", STATEMENT_MAP)
    assert answer("route_cost", {"map_id": "r3", "route": ["A", "B", "D"]}) == "10"
    assert answer("route_cost", {"map_id": "r3", "route": ["A", "C", "D"]}) == "15"
    assert answer("route_cost", {"map_id": "r3", "from": "A", "to": "D"}) == "10"


def test_the_source_toll_is_never_paid_and_the_destination_toll_always_is():
    """`travel-proportional`, verbatim: "Tolls are charged on entry, so the
    source node's toll is never paid and the destination's always is"."""
    prime("r4", {
        "adjacency": {"S": {"T": 1.0}, "T": {}},
        "tolls": {"S": 1000.0, "T": 4.0},
    })
    assert answer("route_cost", {"map_id": "r4", "route": ["S", "T"]}) == "5"


def test_plan_route_honours_a_move_allowance():
    prime("r5", CURFEW_MAP)
    assert json.loads(answer("plan_route", {"map_id": "r5", "from": "S", "to": "D"})) == [
        "S", "P", "Q", "R", "D"]
    assert json.loads(
        answer("plan_route", {"map_id": "r5", "from": "S", "to": "D", "max_moves": 3})
    ) == ["S", "X", "Y", "D"]


def test_route_cost_refuses_a_route_that_is_not_walkable():
    prime("r6", STATEMENT_MAP)
    result = call_tool("route_cost", {"map_id": "r6", "route": ["A", "D"]})
    assert result["isError"] is True


def test_a_route_can_be_sent_as_text():
    prime("r7", STATEMENT_MAP)
    assert answer("route_cost", {"map_id": "r7", "route": "A -> B -> D"}) == "10"
    assert answer("route_cost", {"map_id": "r7", "route": '["A","B","D"]'}) == "10"


def test_plan_route_accepts_a_place_name_as_the_destination():
    prime("r8", {
        "adjacency": {"STOP_01": {"STOP_05": 1.0}, "STOP_05": {"STOP_07": 1.0}, "STOP_07": {}},
        "tolls": {"STOP_01": 0.0, "STOP_05": 0.0, "STOP_07": 0.0},
    })
    route = json.loads(answer("plan_route", {
        "map_id": "r8", "from": "STOP_01", "to": "Marrowgate Market"}))
    assert route == ["STOP_01", "STOP_05", "STOP_07"]


def test_travel_tools_fail_as_error_results_not_crashes():
    for arguments in ({}, {"map_id": "r9"}, {"map_id": "r9", "from": "A"}):
        assert call_tool("plan_route", arguments)["isError"] is True
    assert call_tool("route_cost", {})["isError"] is True


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
