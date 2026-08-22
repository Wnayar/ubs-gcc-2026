"""tool-box sheet 1 ("The Nursery") — see docs/phases/tool-box-1/notes.md.

The grader does not call us directly: it drives an LLM agent that speaks MCP to
{teamUrl}/mcp. So these tests exercise the JSON-RPC transport as a client would,
then the four tools behind it.

The statement's only sample artefact is a clipped base64 PNG (85 chars, not a
whole image), so the shape tests synthesise PNGs of known shapes instead — an
encoder small enough to be obviously correct lives at the top of this file.
"""
import base64
import json
import math
import re
import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# the android's client sends both, per the MCP spec
HEADERS = {"Accept": "application/json, text/event-stream"}


# --- talking MCP -----------------------------------------------------------


def rpc(method, params=None, req_id=1, path="/mcp", headers=None):
    body = {"jsonrpc": "2.0", "method": method}
    if req_id is not None:
        body["id"] = req_id
    if params is not None:
        body["params"] = params
    return client.post(path, json=body, headers=headers or HEADERS)


def result_of(method, params=None, path="/mcp"):
    r = rpc(method, params, path=path)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["jsonrpc"] == "2.0"
    assert "error" not in payload, payload
    return payload["result"]


def call_tool(name, arguments):
    return result_of("tools/call", {"name": name, "arguments": arguments})


def text_of(result):
    assert result["content"], result
    return "".join(b["text"] for b in result["content"] if b["type"] == "text")


def answer(name, arguments):
    """The one thing the android will repeat back as its answer."""
    result = call_tool(name, arguments)
    assert result.get("isError") is not True, result
    return text_of(result)


# --- drawing PNGs to identify ----------------------------------------------


def _png(width, height, rows, color_type=2, depth=8):
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + row for row in rows)  # filter type 0 on every row
    ihdr = struct.pack(">IIBBBBB", width, height, depth, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def draw(inside, size=100, color_type=2, outline=False):
    """base64 PNG of whatever `inside(x, y)` says is part of the shape."""
    if outline:
        solid = inside
        # a 2px rim: inside the shape but close to a point that is not
        inside = lambda x, y: solid(x, y) and not all(  # noqa: E731
            solid(x + dx, y + dy) for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2))
        )
    ink, paper = (b"\x20\x40\xc0", b"\xff\xff\xff") if color_type == 2 else (b"\x00", b"\xff")
    rows = [
        b"".join(ink if inside(x + 0.5, y + 0.5) else paper for x in range(size))
        for y in range(size)
    ]
    return base64.b64encode(_png(size, size, rows, color_type=color_type)).decode()


def polygon(points):
    def inside(x, y):
        hit = False
        for i in range(len(points)):
            (x0, y0), (x1, y1) = points[i - 1], points[i]
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                hit = not hit
        return hit

    return inside


def rotate(points, degrees, about=(50, 50)):
    rad = math.radians(degrees)
    cx, cy = about
    return [
        (
            cx + (x - cx) * math.cos(rad) - (y - cy) * math.sin(rad),
            cy + (x - cx) * math.sin(rad) + (y - cy) * math.cos(rad),
        )
        for x, y in points
    ]


def disc(cx=50, cy=50, r=36):
    return lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= r * r


SQUARE = [(18, 18), (82, 18), (82, 82), (18, 82)]
OBLONG = [(8, 32), (92, 32), (92, 68), (8, 68)]
TRIANGLE = [(50, 10), (90, 88), (10, 88)]
RIGHT_TRIANGLE = [(12, 12), (12, 88), (88, 88)]


# --- transport -------------------------------------------------------------


def test_initialize_reports_tool_capability():
    result = result_of("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", result["protocolVersion"])


def test_initialize_echoes_a_protocol_version_we_support():
    result = result_of("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    assert result["protocolVersion"] == "2024-11-05"


def test_initialize_falls_back_for_an_unknown_protocol_version():
    result = result_of("initialize", {"protocolVersion": "1999-01-01", "capabilities": {}})
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", result["protocolVersion"])


def test_both_mcp_paths_answer():
    # the qna page: "We try {teamUrl}/mcp/ first, {teamUrl}/mcp then this"
    for path in ("/mcp", "/mcp/"):
        assert result_of("tools/list", path=path)["tools"]


def test_initialized_notification_is_accepted_with_no_body():
    r = rpc("notifications/initialized", req_id=None)
    assert r.status_code == 202
    assert r.content in (b"", b"null")


def test_ping_answers():
    assert result_of("ping") == {}


def test_sse_accept_header_gets_an_event_stream():
    r = rpc("ping", headers={"Accept": "text/event-stream"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    payload = json.loads(r.text.split("data: ", 1)[1].strip())
    assert payload["result"] == {}


def test_get_and_delete_are_405_not_500():
    for r in (client.get("/mcp", headers=HEADERS), client.delete("/mcp", headers=HEADERS)):
        assert r.status_code == 405


def test_unknown_method_is_a_jsonrpc_error():
    r = rpc("tools/nope")
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32601


def test_malformed_json_is_a_parse_error_not_a_500():
    r = client.post("/mcp", content=b"{not json", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32700


def test_batched_requests_are_answered_in_order():
    r = client.post(
        "/mcp",
        json=[
            {"jsonrpc": "2.0", "id": "a", "method": "ping"},
            {"jsonrpc": "2.0", "id": "b", "method": "tools/list"},
        ],
        headers=HEADERS,
    )
    assert [entry["id"] for entry in r.json()] == ["a", "b"]


# --- the tools as the android reads them -----------------------------------


def test_tool_list_is_within_the_advertised_limits():
    tools = result_of("tools/list")["tools"]
    assert 0 < len(tools) <= 20  # /limits: only the first 20 are offered
    for tool in tools:
        # MCP's own name rule, not a stricter one of ours: the grader's
        # reference server exposes a two-character tool, `go`.
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", tool["name"]), tool["name"]
        assert 0 < len(tool["description"]) <= 600
        assert tool["inputSchema"]["type"] == "object"
        for param in tool["inputSchema"].get("properties", {}):
            assert len(param) <= 30


def test_every_advertised_tool_is_callable():
    for tool in result_of("tools/list")["tools"]:
        assert tool["name"] in {
            # sheet 1 — "The Nursery"
            "get_my_name",
            "calculate",
            "identify_shape",
            "count_characters",
            # sheet 2 — "School Days"
            "retrieve",
            "id_of_map",
            "go",
            "recall",
            "recall_study_material",
            "plan_route",
            "route_cost",
            "next_step_towards",
            "find_location_code",
        }


def test_calling_an_unknown_tool_is_a_result_not_a_transport_error():
    # an isError result leaves the android its remaining attempts; a JSON-RPC
    # error can end its turn
    result = call_tool("no_such_tool", {})
    assert result["isError"] is True
    assert text_of(result)


# --- problem set 1: what is my name? ---------------------------------------


def test_name_meets_the_stated_criteria():
    name = answer("get_my_name", {})
    assert 3 <= len(name) <= 30
    assert re.fullmatch(r"[A-Za-z0-9 _'-]+", name), name


def test_name_is_not_the_challenge_s_own_word():
    # "Toolbox" came back to the android as the name of the thing it was
    # holding; it submitted no answer at all, nine attempts running.
    assert answer("get_my_name", {}).lower() not in {"toolbox", "tool-box", "tool box"}


def test_name_is_stable():
    assert answer("get_my_name", {}) == answer("get_my_name", {})


def test_name_tolerates_stray_arguments():
    assert answer("get_my_name", {"question": "What is your name?"})


# --- problem set 2: how do numbers work? -----------------------------------


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("2 + 2", "4"),          # the statement's own example
        ("100 + -100", "0"),
        ("-45 - 55", "-100"),
        ("7 * -8", "-56"),
        ("100 * 100", "10000"),
        ("6 / 3", "2"),          # integral division stays an integer
        ("7 / 2", "3.5"),
        ("-9 / 4", "-2.25"),
        ("2 + 3 * 4", "14"),     # precedence, in case a combo asks for it
        ("(2 + 3) * 4", "20"),
    ],
)
def test_arithmetic(expression, expected):
    assert answer("calculate", {"expression": expression}) == expected


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("2 + 2 + 5", "9"),        # scored 0 eight times as "2 + 2 + 5 = 9"
        ("5 * 20 / 10", "10"),
        ("-9 * 2 + 2", "-16"),     # scored 0 three times as "-9 * 2 + 2 = -16"
        ("5 * 10", "50"),          # the combo challenge, run 7189e270
        ("4 * 4", "16"),
        ("3 * 7", "21"),
        ("50 + 16 + 21", "87"),
    ],
)
def test_sums_the_grader_actually_asked(expression, expected):
    assert answer("calculate", {"expression": expression}) == expected


def test_calculate_returns_the_number_alone():
    # The regression that cost the arithmetic chain: the android repeats a tool
    # result verbatim, so anything but the bare number is submitted as the
    # answer and marked wrong. Every "<expression> = <number>" we returned
    # scored 0; every bare number scored full marks.
    for expression in ("2 + 2", "2 + 2 + 5", "(7 - 3) * 5", "-9 * 2 + 2"):
        result = answer("calculate", {"expression": expression})
        assert "=" not in result, result
        assert not any(symbol in result for symbol in "+*/()"), result
        float(result)  # nothing but a number came back


def test_arithmetic_accepts_the_question_verbatim():
    assert answer("calculate", {"expression": "What is 2 + 2?"}) == "4"


def test_arithmetic_accepts_operand_operator_operand():
    assert answer("calculate", {"a": 12, "operator": "*", "b": -3}) == "-36"


def test_division_by_zero_is_an_error_not_a_number():
    result = call_tool("calculate", {"expression": "5 / 0"})
    assert result["isError"] is True
    assert "zero" in text_of(result).lower()


def test_nonsense_expression_is_an_error_not_a_crash():
    assert call_tool("calculate", {"expression": "banana"})["isError"] is True


def test_arithmetic_never_evaluates_arbitrary_python():
    result = call_tool("calculate", {"expression": "__import__('os').getcwd()"})
    assert result["isError"] is True


def test_arithmetic_answers_are_short():
    # /limits: 1200 o200k_base tokens, and an over-limit response is discarded
    assert len(answer("calculate", {"expression": "100 * 100"})) < 60


# --- problem set 3: what is this shape? ------------------------------------


@pytest.mark.parametrize(
    "name,image",
    [
        ("rectangle", draw(polygon(SQUARE))),
        ("rectangle", draw(polygon(OBLONG))),
        ("rectangle", draw(polygon(rotate(SQUARE, 30)))),
        ("rectangle", draw(polygon(rotate(OBLONG, 12)))),
        ("triangle", draw(polygon(TRIANGLE))),
        ("triangle", draw(polygon(RIGHT_TRIANGLE))),
        ("triangle", draw(polygon(rotate(TRIANGLE, 47)))),
        ("triangle", draw(polygon(rotate(RIGHT_TRIANGLE, 200)))),
        ("circle", draw(disc())),
        ("circle", draw(disc(r=20))),
        ("circle", draw(disc(cx=40, cy=60, r=30))),
    ],
)
def test_filled_shapes_are_identified(name, image):
    assert answer("identify_shape", {"image_base64": image}) == name


@pytest.mark.parametrize(
    "name,image",
    [
        ("rectangle", draw(polygon(SQUARE), outline=True)),
        ("triangle", draw(polygon(TRIANGLE), outline=True)),
        ("circle", draw(disc(), outline=True)),
    ],
)
def test_outlined_shapes_are_identified(name, image):
    assert answer("identify_shape", {"image_base64": image}) == name


def test_grayscale_png_is_decoded():
    image = draw(polygon(TRIANGLE), color_type=0)
    assert answer("identify_shape", {"image_base64": image}) == "triangle"


def test_shape_answer_is_exactly_one_of_the_three_words():
    assert answer("identify_shape", {"image_base64": draw(disc())}) in {
        "rectangle",
        "triangle",
        "circle",
    }


def test_data_uri_prefix_is_accepted():
    image = "data:image/png;base64," + draw(polygon(SQUARE))
    assert answer("identify_shape", {"image_base64": image}) == "rectangle"


def test_wrapped_base64_is_accepted():
    raw = draw(polygon(TRIANGLE))
    wrapped = "\n".join(raw[i : i + 60] for i in range(0, len(raw), 60))
    assert answer("identify_shape", {"image_base64": wrapped}) == "triangle"


def test_garbage_base64_is_an_error_not_a_crash():
    assert call_tool("identify_shape", {"image_base64": "not-an-image"})["isError"] is True


def test_a_non_png_payload_is_an_error_not_a_crash():
    jpegish = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 64).decode()
    assert call_tool("identify_shape", {"image_base64": jpegish})["isError"] is True


def test_blank_image_is_an_error_not_a_guess():
    blank = base64.b64encode(
        _png(20, 20, [b"\xff\xff\xff" * 20 for _ in range(20)])
    ).decode()
    assert call_tool("identify_shape", {"image_base64": blank})["isError"] is True


def test_oversized_image_is_refused_quickly():
    # a decompression bomb is the one hostile input this endpoint plausibly sees
    header = _png(9000, 9000, [], color_type=2)
    assert call_tool("identify_shape", {"image_base64": base64.b64encode(header).decode()})[
        "isError"
    ] is True


def test_missing_argument_is_an_error_not_a_crash():
    assert call_tool("identify_shape", {})["isError"] is True


# --- problem set 4: the combo challenge ------------------------------------


def test_count_characters_counts():
    assert answer("count_characters", {"text": "Hello world"}).split()[0] == "11"


def test_the_three_tools_compose():
    # the shape of a combo: name -> its length -> arithmetic over it
    name = answer("get_my_name", {})
    counted = int(answer("count_characters", {"text": name}).split()[0])
    assert counted == len(name)
    assert answer("calculate", {"expression": f"{counted} * 2"}) == str(counted * 2)


# --- run callback ----------------------------------------------------------


def test_callback_accepts_a_run_summary():
    r = client.post(
        "/tool-box/callback",
        json={"runId": "abc", "summaryUrl": "https://tool-box.example/run/abc"},
    )
    assert r.status_code == 200
    # the middleware keeps the body, so the summary link is readable afterwards
    logged = client.get("/debug/requests").json()
    assert any("summaryUrl" in entry.get("req_body", "") for entry in logged)


def test_callback_tolerates_a_body_it_cannot_parse():
    assert client.post("/tool-box/callback", content=b"anything at all").status_code == 200


# --- the other challenges --------------------------------------------------------


def test_other_challenges_still_work():
    assert client.post("/square", json={"value": 5}).json() == {"result": 25}
    assert client.get("/health").json()["status"] == "ok"
