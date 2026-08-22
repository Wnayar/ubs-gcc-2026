"""tool-box — one MCP server for all three sheets.

sheet 1, "The Nursery"   (docs/phases/tool-box-1/): name, arithmetic, shapes.
sheet 2, "School Days"   (docs/phases/tool-box-2/): recall, journeys, the trip.
sheet 3, "Working Life"  (docs/phases/tool-box-3/): venues, diaries, the outing.

Not a REST endpoint: the grader drives an LLM agent that speaks MCP to
{teamUrl}/mcp and answers with whatever our tools hand it. On sheet 1 the agent
does not check our work, so those tools return the finished answer and nothing
else. Sheet 2's recall tool is the one deliberate exception — it is specified to
return *passages, not answers*, and the android writes the answer itself.

Their qna page says they try /mcp/ first and /mcp second, so both are registered
here rather than left to a redirect.
"""
import json
import os
import re

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app import cityclock, graphroute, recall as recall_module
from app.expr import ExpressionError, clean, evaluate, format_number
from app.mcp import Server, ToolError, error, sse
from app.pngshape import ImageError, classify

router = APIRouter(tags=["tool-box"])

# statement: 3-30 characters, letters, digits, spaces, _, - and '
NAME_PATTERN = re.compile(r"[A-Za-z0-9 _'-]{3,30}")
# Not "Toolbox": that was the challenge's own noun, and across three runs the
# android took it from us and then submitted no answer at all (nine attempts,
# not one evaluation recorded). A plain personal name cannot be mistaken for
# the name of the thing it is holding.
DEFAULT_NAME = "Milo"

MAX_TEXT = 4000

server = Server(
    name="ubs-gcc-toolbox",
    version="2.0.0",
    instructions=(
        "get_my_name gives your own name, calculate does arithmetic, "
        "identify_shape reads a base64 PNG, count_characters counts text: "
        "answer with exactly what those return, word for word. "
        "recall_study_material is different — it returns passages from your "
        "revision material for you to read and answer from. "
        "next_step_towards gives the next node to move to on a map, and "
        "find_location_code turns a place name into its map marker. "
        "For anything about your week: find_places_to_eat, find_meeting_time, "
        "find_meeting_point, and plan_outing when you have to meet people and "
        "then go on somewhere to eat."
    ),
)


def _text(arguments: dict, *keys: str) -> str | None:
    for key in keys:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def _integer(arguments: dict, *keys: str) -> int | None:
    """A count the android may send as 3, 3.0 or "3 left"."""
    for key in keys:
        value = arguments.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            found = re.search(r"-?\d+", value)
            if found:
                return int(found.group())
    return None


def _node_list(arguments: dict, *keys: str) -> list[str] | None:
    """A route the android may send as a list, a JSON array, or "A -> B -> C"."""
    for key in keys:
        value = arguments.get(key)
        if isinstance(value, (list, tuple)):
            names = [str(v).strip() for v in value if str(v).strip()]
            if names:
                return names
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                names = [str(v).strip() for v in parsed if str(v).strip()]
                if names:
                    return names
            names = [part.strip() for part in re.split(r"->|→|,|\s+", value) if part.strip()]
            if len(names) > 1:
                return names
    return None


# --- problem set 1: what is my name? ---------------------------------------


@server.tool(
    "get_my_name",
    # Phrased like identify_shape, which scored 3 runs out of 3: say what it
    # does and what comes back, and leave the android's own turn alone.
    "Say what you are called. Takes no arguments and returns exactly one "
    "word: your name.",
    {"type": "object", "properties": {}, "required": []},
)
def get_my_name(arguments: dict) -> str:
    configured = os.environ.get("AGENT_NAME", "").strip()
    # a misconfigured name would be rejected by the grader; the default never is
    return configured if NAME_PATTERN.fullmatch(configured) else DEFAULT_NAME


# --- problem set 2: how do numbers work? -----------------------------------


@server.tool(
    "calculate",
    "Work out a sum. Handles + - * / and brackets over whole numbers, for "
    "example '2 + 2' or '(7 - 3) * 5'. Returns exactly one number: the answer.",
    {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The sum to work out, for example '2 + 2'.",
            }
        },
        "required": ["expression"],
    },
)
def calculate(arguments: dict) -> str:
    expression = _text(arguments, "expression", "text", "question", "problem", "input")
    if expression is None:
        # the agent sometimes splits the sum up; take it either way rather than
        # spend one of its three attempts on the shape of our schema
        left = _text(arguments, "a", "left", "lhs", "first", "x")
        operator = _text(arguments, "operator", "op", "operation", "symbol")
        right = _text(arguments, "b", "right", "rhs", "second", "y")
        if left is None or operator is None or right is None:
            raise ToolError("give me the sum as text, for example {\"expression\": \"2 + 2\"}")
        expression = f"{left} {operator} {right}"
    try:
        # The answer and nothing else. We used to return "2 + 2 + 5 = 9"; the
        # android repeats a tool result verbatim, so it submitted the whole
        # string where a number was expected and scored 0 on eight attempts out
        # of nine. Every bare number we have ever returned scored full marks.
        return format_number(evaluate(expression))
    except ExpressionError as problem:
        raise ToolError(str(problem)) from None


# --- problem set 3: what is this shape? ------------------------------------


@server.tool(
    "identify_shape",
    "Say which shape a picture shows. Takes a base64-encoded PNG and returns "
    "exactly one word: rectangle, triangle or circle.",
    {
        "type": "object",
        "properties": {
            "image_base64": {
                "type": "string",
                "description": "The PNG image, base64-encoded. A data: URI is fine.",
            }
        },
        "required": ["image_base64"],
    },
)
def identify_shape(arguments: dict) -> str:
    image = _text(arguments, "image_base64", "image", "png", "base64", "data", "input")
    if image is None:
        raise ToolError("give me the picture as base64 text in \"image_base64\"")
    try:
        return classify(image)
    except ImageError as problem:
        raise ToolError(str(problem)) from None


# --- problem set 4: the combo challenge ------------------------------------


@server.tool(
    "count_characters",
    "Count the characters and the words in a piece of text. Use it whenever an "
    "answer depends on how long something is — counting by eye is unreliable.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to measure."}
        },
        "required": ["text"],
    },
)
def count_characters(arguments: dict) -> str:
    text = _text(arguments, "text", "input", "value", "string", "word")
    if text is None:
        raise ToolError("give me the text to measure in \"text\"")
    if len(text) > MAX_TEXT:
        raise ToolError("that text is too long to measure")
    return f"{len(text)} characters, {len(text.split())} words"


# --- sheet 2, problem set 1: exam time -------------------------------------


RETRIEVAL_DESCRIPTION = (
    "Look something up in the material you were set to revise. Give it the "
    "question you are trying to answer and it returns a JSON array of "
    "passages from that material, for you to read and answer from."
)
RETRIEVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "The question you are trying to answer.",
        }
    },
    "required": ["question"],
}


def recall_passages(arguments: dict) -> str:
    """A JSON array of strings, in one text block. Nothing else parses.

    The grader's rule (`retrieval-shape`): 'A JSON array of strings.
    ["passage", "passage"] is the shape. An object, a bare string, or
    {"chunks": [...]} is not.' Returning one MCP content block per passage
    reads as a bare string once the blocks are joined, and voids the question.
    """
    question = _text(arguments, "question", "query", "q", "text", "topic", "search")
    if question is None:
        raise ToolError("give me the question in \"question\"")
    passages = recall_module.recall(question)
    if not passages:
        raise ToolError("nothing in the study material covers that")
    # ensure_ascii=False: escaping an em dash to — spends six characters
    # of the response ceiling to say nothing.
    return json.dumps(passages, ensure_ascii=False)


# Registered three times on purpose. The grader routes revision questions
# through its own `_recall` wrapper, which calls whichever of our tools the
# android names — and on the 0/100 run it twice named `retrieve`, a tool we did
# not have, before finding the real one on its last attempt. Naming a tool we
# never exposed is scored as the grader's fault and retried, but a retry spent
# on our tool surface is a retry not spent on the answer. These are the names
# it reaches for; they are the same function.
server.tool("retrieve", RETRIEVAL_DESCRIPTION, RETRIEVAL_SCHEMA)(recall_passages)
server.tool("recall", RETRIEVAL_DESCRIPTION, RETRIEVAL_SCHEMA)(recall_passages)
server.tool("recall_study_material", RETRIEVAL_DESCRIPTION, RETRIEVAL_SCHEMA)(recall_passages)


# --- sheet 2, problem set 2: out after school ------------------------------

# The 0/100 run asked three travel problems and our server was never called
# once: "No tool or answer could be found." The grader walks a journey through
# its own `_travel` wrapper, which takes a *whole route* — `{"route": ["B",
# "G", "H"]}` — and then checks every hop. A tool that hands back one node at a
# time does not fit that shape, so the android had nothing it could use and
# gave up without calling us. plan_route answers in the shape the wrapper eats.


def _route_for(arguments: dict) -> tuple[dict, list[str]]:
    """Shared by plan_route and route_cost: (graph, cheapest legal route)."""
    map_id = _text(arguments, "map_id", "mapId", "map", "id")
    if map_id is None:
        raise ToolError("give me the map_id from the question in \"map_id\"")
    origin = _text(arguments, "from", "start", "source", "current", "at", "origin")
    if origin is None:
        raise ToolError("tell me where the journey starts in \"from\"")
    target = _text(arguments, "to", "destination", "goal", "target", "end")
    if target is None:
        raise ToolError("tell me where the journey ends in \"to\"")
    limit = _integer(arguments, "max_moves", "moves", "moves_left", "hops_left", "hops",
                     "allowance", "budget", "steps", "limit")

    try:
        graph = graphroute.load_graph(map_id)
    except graphroute.RouteError as problem:
        raise ToolError(str(problem)) from None

    start = graphroute.resolve_node(graph, origin)
    if start is None:
        raise ToolError(f"{origin!r} is not a node on that map")
    goal = graphroute.resolve_node(graph, target)
    if goal is None:
        code = recall_module.resolve_location(target)
        goal = graphroute.resolve_node(graph, code) if code else None
    if goal is None:
        raise ToolError(f"I cannot find {target!r} on that map")

    try:
        return graph, graphroute.plan(graph, start, goal, limit)
    except graphroute.RouteError as problem:
        raise ToolError(str(problem)) from None


@server.tool(
    "plan_route",
    "Work out the cheapest way across a map. Give it the map_id from the "
    "question, where the journey starts and where it ends — a node name, or a "
    "place named in your study material — and how many moves are allowed if "
    "you were told. Returns the whole route as a JSON array of node names, "
    "starting where you are and ending at the destination.",
    {
        "type": "object",
        "properties": {
            "map_id": {"type": "string", "description": "The map_id given in the question."},
            "from": {"type": "string", "description": "Where the journey starts."},
            "to": {
                "type": "string",
                "description": "Where it ends: a node name, or a place from your "
                "study material.",
            },
            "max_moves": {
                "type": "integer",
                "description": "Moves allowed for the whole journey, if you were told.",
            },
        },
        "required": ["map_id", "from", "to"],
    },
)
def plan_route(arguments: dict) -> str:
    _graph, route = _route_for(arguments)
    return json.dumps(route, ensure_ascii=False)


@server.tool(
    "route_cost",
    "Work out what a journey costs. Give it the map_id and either the route "
    "you walked, as a list of node names, or just where it starts and ends. "
    "Counts every edge plus the toll of each place entered. Returns exactly "
    "one number.",
    {
        "type": "object",
        "properties": {
            "map_id": {"type": "string", "description": "The map_id given in the question."},
            "route": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The nodes travelled, in order, if you already have them.",
            },
            "from": {"type": "string", "description": "Where the journey starts."},
            "to": {"type": "string", "description": "Where it ends."},
        },
        "required": ["map_id"],
    },
)
def route_cost(arguments: dict) -> str:
    walked = _node_list(arguments, "route", "path", "nodes", "steps")
    if walked is None:
        _graph, route = _route_for(arguments)
        graph = _graph
    else:
        map_id = _text(arguments, "map_id", "mapId", "map", "id")
        if map_id is None:
            raise ToolError("give me the map_id from the question in \"map_id\"")
        try:
            graph = graphroute.load_graph(map_id)
        except graphroute.RouteError as problem:
            raise ToolError(str(problem)) from None
        route = []
        for name in walked:
            node = graphroute.resolve_node(graph, name)
            if node is None:
                raise ToolError(f"{name!r} is not a node on that map")
            route.append(node)
        if len(route) < 2:
            raise ToolError("give me at least two nodes in \"route\"")
        for previous, node in zip(route, route[1:]):
            if node not in graph["adjacency"].get(previous, {}):
                raise ToolError(f"{node} is not adjacent to {previous} on that map")
    return format_number(graphroute.path_cost(graph, route))


@server.tool(
    "next_step_towards",
    "Work out the next move on a map. Give it the map_id from the question, "
    "where you are standing now, and where you are going — a node name or a "
    "place from your study material — plus how many moves you have left if you "
    "were told. Returns exactly one node name: the next one to travel to.",
    {
        "type": "object",
        "properties": {
            "map_id": {"type": "string", "description": "The map_id given in the question."},
            "current": {"type": "string", "description": "The node you are standing on now."},
            "destination": {
                "type": "string",
                "description": "Where the journey ends: a node name, or a place named in "
                "your study material.",
            },
            "hops_left": {
                "type": "integer",
                "description": "Moves remaining, if the question said. Counts this one.",
            },
        },
        "required": ["map_id", "current", "destination"],
    },
)
def next_step_towards(arguments: dict) -> str:
    map_id = _text(arguments, "map_id", "mapId", "map", "id")
    if map_id is None:
        raise ToolError("give me the map_id from the question in \"map_id\"")
    here = _text(arguments, "current", "current_node", "from", "at", "start", "position", "node")
    if here is None:
        raise ToolError("tell me where you are standing in \"current\"")
    there = _text(arguments, "destination", "to", "goal", "target", "end", "destination_node")
    if there is None:
        raise ToolError("tell me where you are going in \"destination\"")
    hops_left = _integer(arguments, "hops_left", "hops", "moves_left", "moves", "remaining",
                         "allowance", "budget", "steps_left", "hops_remaining")

    try:
        graph = graphroute.load_graph(map_id)
    except graphroute.RouteError as problem:
        raise ToolError(str(problem)) from None

    start = graphroute.resolve_node(graph, here)
    if start is None:
        raise ToolError(f"{here!r} is not a node on that map")

    goal = graphroute.resolve_node(graph, there)
    if goal is None:
        # Part 3: the destination is a place, and the map only knows markers.
        # Getting this wrong is the statement's "likeliest way to lose the
        # points", so we resolve it rather than hope the android already did.
        code = recall_module.resolve_location(there)
        goal = graphroute.resolve_node(graph, code) if code else None
    if goal is None:
        raise ToolError(f"I cannot find {there!r} on that map")

    if start == goal:
        raise ToolError(f"you are already at {goal}")

    trail = graphroute.visited_for(map_id, goal, start, graph)
    try:
        route = graphroute.plan(graph, start, goal, hops_left, forbidden=set(trail))
    except graphroute.RouteError as problem:
        raise ToolError(str(problem)) from None

    step = route[1]
    graphroute.record_step(map_id, goal, step)
    return step


@server.tool(
    "find_location_code",
    "Find the map marker that serves a named place. Give it a place named in "
    "your study material and it returns exactly one marker name, for example "
    "STOP_07.",
    {
        "type": "object",
        "properties": {
            "place": {
                "type": "string",
                "description": "The name of the place, for example 'Marrowgate Market'.",
            }
        },
        "required": ["place"],
    },
)
def find_location_code(arguments: dict) -> str:
    place = _text(arguments, "place", "location", "name", "destination", "query", "text")
    if place is None:
        raise ToolError("give me the place name in \"place\"")
    code = recall_module.resolve_location(place)
    if code is None:
        raise ToolError(f"no marker in the study material serves {place!r}")
    return code


# --- transport -------------------------------------------------------------



# --- sheet 3: working life -------------------------------------------------

# The android is asked four things about a week it half-remembers: where it can
# eat, when everyone is free, where to meet, and all three at once. Sheets 1 and
# 2 settled how to answer: it repeats a tool result word for word and does not
# check our work, so every tool here returns the finished answer in the shape
# the question asks for and nothing else. The last two are the means rather than
# the answer — they are there for an android that would rather look the raw day
# up itself than trust a total it did not compute.


def _plain_errors(function):
    """A PlanError is a sentence for the android, not a stack trace."""

    def wrapped(arguments: dict) -> str:
        try:
            return function(arguments)
        except cityclock.PlanError as problem:
            raise ToolError(str(problem)) from None

    wrapped.__name__ = function.__name__
    wrapped.__doc__ = function.__doc__
    return wrapped


def _day_argument(arguments: dict) -> str:
    return cityclock.to_day(_text(arguments, "day", "weekday", "date", "on", "when"))


def _minute_argument(arguments: dict, *keys: str) -> int | None:
    for key in keys:
        if key in arguments:
            minute = cityclock.to_minutes(arguments[key])
            if minute is not None:
                return minute
    return None


def _people_argument(arguments: dict) -> list[str]:
    for key in ("people", "guests", "friends", "with", "attendees", "persons",
                "names", "who", "person"):
        if key in arguments:
            found = cityclock.to_people(arguments[key])
            if found:
                return found
    return []


def _point_argument(arguments: dict, *keys: str):
    for key in keys:
        if key in arguments:
            point = cityclock.to_point(arguments[key])
            if point is not None:
                return point
    return None


_CLOCKS = re.compile(r"\d{1,2}(?::\d{2})?\s*(?:am|pm)?", re.IGNORECASE)


def _range_argument(arguments: dict):
    """"between 13:00 and 18:00", however the android chose to hand it over."""
    earliest = _minute_argument(
        arguments, "earliest", "earliest_time", "from", "after", "start",
        "start_time", "not_before", "range_start", "between_start")
    latest = _minute_argument(
        arguments, "latest", "latest_time", "until", "to", "before", "end",
        "end_time", "range_end", "between_end")
    if earliest is None or latest is None:
        written = _text(arguments, "between", "range", "window", "time_range")
        if written:
            marks = [cityclock.to_minutes(bit) for bit in _CLOCKS.findall(written)]
            marks = [mark for mark in marks if mark is not None]
            if len(marks) >= 2:
                earliest = marks[0] if earliest is None else earliest
                latest = marks[1] if latest is None else latest
    return earliest, latest


def _length_argument(arguments: dict) -> int:
    length = _integer(arguments, "minutes", "duration", "duration_minutes",
                      "length", "length_minutes", "for", "how_long")
    if length is None:
        return cityclock.HOUR
    if 1 <= length <= 12:  # "a 2 hour window" rather than a 2 minute one
        return length * cityclock.HOUR
    return length


DAY_PROPERTY = {"type": "string", "description": "A weekday name, for example 'Tuesday'."}
PEOPLE_PROPERTY = {
    "type": "array",
    "items": {"type": "string"},
    "description": "The friends to meet, for example ['ada', 'bram']. Leave "
                   "yourself out — you are always counted.",
}
POSITION_PROPERTY = {
    "type": "array",
    "items": {"type": "integer"},
    "description": "Where you are, as [x, y] with x first, for example [4, 5].",
}


@server.tool(
    "find_places_to_eat",
    "Every place you can eat at on one day at one hour. A place trading that "
    "day is not necessarily trading at that hour, so it checks. Returns their "
    "names as one comma-separated string.",
    {
        "type": "object",
        "properties": {
            "day": DAY_PROPERTY,
            "time": {"type": "string",
                     "description": "The hour, 24-hour HH:MM, for example '08:00'."},
        },
        "required": ["day", "time"],
    },
)
@_plain_errors
def find_places_to_eat(arguments: dict) -> str:
    day = _day_argument(arguments)
    minute = _minute_argument(arguments, "time", "at", "hour", "when", "start", "start_time")
    if minute is None:
        raise ToolError("give me the hour in \"time\", 24-hour, for example '08:00'")
    places = cityclock.open_at(day, minute)
    if not places:
        raise ToolError(f"nowhere is open on {day} at {cityclock.to_clock(minute)}")
    return ", ".join(place["name"] for place in places)


@server.tool(
    "find_meeting_time",
    "The best window on one day when you and the friends you name can all "
    "meet. It reads their diaries and your own inbox, keeps anything you "
    "accepted, ignores anything you declined, and gives up a tentative "
    "commitment only when nothing else in the range is clear. Returns one "
    "window as 'HH:MM-HH:MM'.",
    {
        "type": "object",
        "properties": {
            "day": DAY_PROPERTY,
            "people": PEOPLE_PROPERTY,
            "earliest": {"type": "string",
                         "description": "Earliest the meeting may start, HH:MM."},
            "latest": {"type": "string",
                       "description": "Latest the meeting may finish, HH:MM."},
            "minutes": {"type": "integer",
                        "description": "How long the meeting is, in minutes. 60 if not said."},
        },
        "required": ["day", "people"],
    },
)
@_plain_errors
def find_meeting_time(arguments: dict) -> str:
    day = _day_argument(arguments)
    earliest, latest = _range_argument(arguments)
    window = cityclock.find_window(
        day, _people_argument(arguments), earliest, latest, _length_argument(arguments))
    return f"{cityclock.to_clock(window['start'])}-{cityclock.to_clock(window['end'])}"


@server.tool(
    "find_meeting_point",
    "The point on the grid that makes the total travel of everyone — you and "
    "every friend you name — as small as possible. Say where you are going "
    "afterwards in 'eat_at' if there is somewhere, because that changes the "
    "point. Returns one point as '[x, y]'.",
    {
        "type": "object",
        "properties": {
            "day": DAY_PROPERTY,
            "my_position": POSITION_PROPERTY,
            "people": PEOPLE_PROPERTY,
            "eat_at": {"type": "string",
                       "description": "Optional: where the party goes next, by name."},
        },
        "required": ["day", "my_position", "people"],
    },
)
@_plain_errors
def find_meeting_point(arguments: dict) -> str:
    day = _day_argument(arguments)
    positions = cityclock.gather(
        day, _point_argument(arguments, "my_position", "my_location", "position",
                             "me", "you", "your_position", "current_position",
                             "start_position", "location"),
        _people_argument(arguments))
    onward = None
    named = _text(arguments, "eat_at", "then", "next", "afterwards", "then_go_to",
                  "venue", "place", "destination")
    if named:
        onward = cityclock.to_point(named)
        if onward is None:
            venue = cityclock.find_venue(day, named)
            onward = (venue["x"], venue["y"])
        onward = cityclock.on_grid(onward)
    x, y = cityclock.best_point(positions, then_on_to=onward)
    return f"[{x}, {y}]"


@server.tool(
    "plan_outing",
    "The whole outing in one answer: meet your friends, then go on somewhere "
    "to eat. It finds the window everyone can make, a place open for the hour "
    "the meeting ends, and the meeting point that makes the whole journey — "
    "everyone's travel to the meeting point plus the trip on to the place you "
    "eat — as short as possible. Returns JSON with 'meeting', 'meeting_point' "
    "and 'eat_at'.",
    {
        "type": "object",
        "properties": {
            "day": DAY_PROPERTY,
            "my_position": POSITION_PROPERTY,
            "people": PEOPLE_PROPERTY,
            "earliest": {"type": "string",
                         "description": "Earliest the meeting may start, HH:MM."},
            "latest": {"type": "string",
                       "description": "Latest the meeting may finish, HH:MM."},
            "minutes": {"type": "integer",
                        "description": "How long the meeting is, in minutes. 60 if not said."},
        },
        "required": ["day", "my_position", "people"],
    },
)
@_plain_errors
def plan_outing(arguments: dict) -> str:
    day = _day_argument(arguments)
    earliest, latest = _range_argument(arguments)
    plan = cityclock.plan_outing(
        day,
        _point_argument(arguments, "my_position", "my_location", "position", "me",
                        "you", "your_position", "current_position",
                        "start_position", "location"),
        _people_argument(arguments),
        earliest,
        latest,
        _length_argument(arguments),
    )
    return json.dumps(
        {
            "meeting": f"{cityclock.to_clock(plan['start'])}-{cityclock.to_clock(plan['end'])}",
            "meeting_point": list(plan["point"]),
            "eat_at": plan["venue"],
        },
        ensure_ascii=False,
    )


@server.tool(
    "get_day_schedule",
    "One person's day. For a friend it returns the hours they are already "
    "busy; for your own day — pass 'me' — it also returns the hours you have "
    "only pencilled in. JSON, times as HH:MM.",
    {
        "type": "object",
        "properties": {
            "person": {"type": "string",
                       "description": "A friend's name, or 'me' for your own day."},
            "day": DAY_PROPERTY,
        },
        "required": ["person", "day"],
    },
)
@_plain_errors
def get_day_schedule(arguments: dict) -> str:
    day = _day_argument(arguments)
    written = _text(arguments, "person", "name", "who", "friend", "whose")
    if written is None:
        raise ToolError("whose day? give a name, or 'me', in \"person\"")
    named = cityclock.to_people(written)
    if not named:  # 'me', 'you', 'myself' — the inbox is the only diary it has
        accepted, tentative = cityclock.commitments(day)
        return json.dumps({"busy": _spans(accepted), "tentative": _spans(tentative)})
    return json.dumps({"busy": _spans(cityclock.busy(named[0], day))})


def _spans(spans) -> list[list[str]]:
    return [[cityclock.to_clock(start), cityclock.to_clock(end)] for start, end in spans]


@server.tool(
    "where_is",
    "Where one of your friends is on one day. People are somewhere different "
    "on different days. Returns one point as '[x, y]'.",
    {
        "type": "object",
        "properties": {
            "person": {"type": "string", "description": "The friend's name, for example 'ada'."},
            "day": DAY_PROPERTY,
        },
        "required": ["person", "day"],
    },
)
@_plain_errors
def where_is(arguments: dict) -> str:
    day = _day_argument(arguments)
    written = _text(arguments, "person", "name", "who", "friend", "whose")
    named = cityclock.to_people(written or "")
    if not named:
        raise ToolError(
            "give a friend's name in \"person\" — your own position is in the question")
    x, y = cityclock.position(named[0], day)
    return f"[{x}, {y}]"



@router.post("/mcp")
@router.post("/mcp/")
async def mcp(request: Request) -> Response:
    answer = server.handle_body(await request.body())
    if answer is None:
        return Response(status_code=202)  # a notification gets no body
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept and "application/json" not in accept:
        return Response(content=sse(answer), media_type="text/event-stream")
    return JSONResponse(answer)


@router.get("/mcp")
@router.get("/mcp/")
@router.delete("/mcp")
@router.delete("/mcp/")
async def mcp_post_only() -> Response:
    """No server-initiated stream and no sessions, so 405 is the spec's answer."""
    return JSONResponse(
        error(None, -32601, "this MCP server only accepts POST"), status_code=405
    )


@router.post("/tool-box/callback")
async def run_callback(request: Request) -> dict:
    """Somewhere to point tool-box's run callback if they ask for one.

    Their howto page says a finished run is posted to a callback URL and that
    the message leads with the run summary address. Accepting anything and
    answering 200 means the request lands in the ring buffer behind
    GET /debug/requests, so we can read the summary link back off our own
    server instead of hunting for it. Drop this if they never ask for a URL.
    """
    await request.body()  # the middleware records it; we only need the 200
    return {"received": True}
