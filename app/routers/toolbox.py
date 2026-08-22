"""tool-box, sheet 1 of 3 — "The Nursery" (docs/phases/tool-box-1/).

Not a REST endpoint this time: the grader drives an LLM agent that speaks MCP to
{teamUrl}/mcp and answers with whatever our tools hand it. The agent does not
check our work, so every tool returns the finished answer and nothing else.

Their qna page says they try /mcp/ first and /mcp second, so both are registered
here rather than left to a redirect.
"""
import os
import re

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

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
    version="1.0.0",
    instructions=(
        "Answer with exactly what a tool returns, word for word. "
        "get_my_name gives your own name, calculate does arithmetic, "
        "identify_shape reads a base64 PNG, count_characters counts text."
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


# --- transport -------------------------------------------------------------


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
