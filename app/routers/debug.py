import os

from fastapi import APIRouter, Header, HTTPException

from app.reqlog import RECENT

router = APIRouter(prefix="/debug", tags=["debug"])


def _check(token: str | None) -> None:
    expected = os.environ.get("DEBUG_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=404)  # don't advertise the endpoint


@router.get("/requests")
async def recent_requests(
    n: int = 50,
    only_errors: bool = False,
    token: str | None = None,
    x_debug_token: str | None = Header(default=None),
):
    """Last n request/response pairs, newest last.

    Open when DEBUG_TOKEN is unset (local dev); on Render pass
    ?token=... or the X-Debug-Token header.
    """
    _check(token or x_debug_token)
    entries = list(RECENT)
    if only_errors:
        entries = [e for e in entries if e.get("status", 500) >= 400]
    return entries[-n:]
