"""Record every request/response pair so a failing grader run can be inspected.

Each entry is printed to stdout as a JSON line (shows up in Render's log tail)
and kept in an in-memory ring buffer served by GET /debug/requests.
"""
import json
import time
import traceback
from collections import deque
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

RECENT = deque(maxlen=500)
# Phase 2 bodies carry up to 20 completed hands in `recent_hands` and run past
# 4 KB — the old cap silently clipped 161 of 241 bodies in the first attempt and
# destroyed a quarter of the showdown evidence needed to work a table out.
MAX_BODY = 32768


def _clip(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace")
    if len(text) > MAX_BODY:
        return text[:MAX_BODY] + f"…[{len(text)} chars total]"
    return text


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/debug"):
            return await call_next(request)

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query),
            "client": request.client.host if request.client else None,
            "req_body": _clip(await request.body()),
        }
        start = time.perf_counter()
        try:
            response = await call_next(request)
            resp_body = b""
            async for chunk in response.body_iterator:
                resp_body += chunk
            entry["status"] = response.status_code
            entry["resp_body"] = _clip(resp_body)
            response = Response(
                content=resp_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception as exc:
            entry["status"] = 500
            entry["error"] = "".join(traceback.format_exception(exc))
            response = Response(
                content=json.dumps({"error": type(exc).__name__, "detail": str(exc)}),
                status_code=500,
                media_type="application/json",
            )
        entry["ms"] = round((time.perf_counter() - start) * 1000, 1)
        RECENT.append(entry)
        print(json.dumps(entry), flush=True)
        return response
