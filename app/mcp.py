"""A minimal MCP server over the Streamable HTTP transport (JSON-RPC 2.0).

Deliberately hand-rolled rather than FastMCP. The challenge's own qna page says
the commonest way to lose a run is mounting `mcp.http_app()` into FastAPI
without passing its lifespan — the routes answer, the health check passes, and
every MCP call 500s — and warns that on a small free instance it is imports that
exhaust memory. There is no lifespan here, no session manager and no dependency,
so neither failure has anywhere to happen.

Stateless by design: we never issue an Mcp-Session-Id, so a spun-down instance
waking mid-run cannot invalidate a session.
"""
import json

JSONRPC = "2.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL = PROTOCOL_VERSIONS[0]

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


class ToolError(Exception):
    """A tool could not answer. Reported to the agent, never to the transport."""


class Server:
    def __init__(self, name: str, version: str, instructions: str = ""):
        self.name = name
        self.version = version
        self.instructions = instructions
        self._tools: dict[str, dict] = {}

    # --- registration ------------------------------------------------------

    def tool(self, name: str, description: str, schema: dict):
        def register(function):
            self._tools[name] = {
                "descriptor": {
                    "name": name,
                    "description": description,
                    "inputSchema": schema,
                },
                "run": function,
            }
            return function

        return register

    @property
    def tools(self) -> list[dict]:
        # /limits: only the first 20 tools we list are offered to the agent
        return [entry["descriptor"] for entry in self._tools.values()][:20]

    # --- transport ---------------------------------------------------------

    def handle_body(self, body: bytes):
        """Raw request body -> the object to send back, or None for 202."""
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return error(None, PARSE_ERROR, "request body is not valid JSON")
        return self.handle_payload(payload)

    def handle_payload(self, payload):
        if isinstance(payload, list):
            if not payload:
                return error(None, INVALID_REQUEST, "empty batch")
            answers = [a for a in (self.handle_message(m) for m in payload) if a is not None]
            return answers or None
        return self.handle_message(payload)

    def handle_message(self, message):
        if not isinstance(message, dict):
            return error(None, INVALID_REQUEST, "request must be a JSON object")
        identifier = message.get("id")
        notification = "id" not in message or identifier is None
        method = message.get("method")
        if not isinstance(method, str):
            return None if notification else error(identifier, INVALID_REQUEST, "no method")

        params = message.get("params")
        if not isinstance(params, dict):
            params = {}

        if method.startswith("notifications/"):
            return None  # initialized, cancelled, progress: nothing to answer
        try:
            result = self._dispatch(method, params)
        except LookupError:
            return None if notification else error(
                identifier, METHOD_NOT_FOUND, f"method not found: {method}"
            )
        except Exception:  # nothing reaches the client as a 500
            return None if notification else error(identifier, INTERNAL_ERROR, "internal error")
        if notification:
            return None
        return {"jsonrpc": JSONRPC, "id": identifier, "result": result}

    def _dispatch(self, method: str, params: dict):
        if method == "initialize":
            asked = params.get("protocolVersion")
            return {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else LATEST_PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": self.name, "version": self.version},
                "instructions": self.instructions,
            }
        if method == "tools/list":
            return {"tools": self.tools}
        if method == "tools/call":
            return self.call_tool(params.get("name"), params.get("arguments"))
        if method == "ping":
            return {}
        # answered rather than refused: some clients probe these regardless of
        # what we advertise, and an error there can end the agent's turn
        if method == "resources/list":
            return {"resources": []}
        if method == "resources/templates/list":
            return {"resourceTemplates": []}
        if method == "prompts/list":
            return {"prompts": []}
        if method == "logging/setLevel":
            return {}
        raise LookupError(method)

    def call_tool(self, name, arguments):
        """Always a result. A tool that fails says so and keeps the agent's turn."""
        if not isinstance(arguments, dict):
            arguments = {}
        entry = self._tools.get(name)
        if entry is None:
            return tool_result(
                f"There is no tool called {name!r}. Available: "
                + ", ".join(self._tools),
                failed=True,
            )
        try:
            return tool_result(entry["run"](arguments))
        except ToolError as problem:
            return tool_result(str(problem), failed=True)
        except Exception:
            return tool_result("that call did not work — check the arguments", failed=True)


def tool_result(text: str, failed: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": failed}


def error(identifier, code: int, message: str) -> dict:
    return {"jsonrpc": JSONRPC, "id": identifier, "error": {"code": code, "message": message}}


def sse(payload) -> str:
    """The same JSON, framed as the one event a Streamable HTTP client expects."""
    return f"event: message\ndata: {json.dumps(payload)}\n\n"
