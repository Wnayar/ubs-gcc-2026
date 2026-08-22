import os

from fastapi import APIRouter, Header, HTTPException

from app.reqlog import RECENT
from app.showdown_rules import learned_summary

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


@router.get("/showdown-rules")
async def showdown_rules(
    token: str | None = None,
    x_debug_token: str | None = Header(default=None),
):
    """What each `table_rule` codename looks like so far.

    Phase 2 hides the showdown rule behind a codename, and the mapping is fixed
    for the whole event — so anything here that reads confident is worth baking
    into app.showdown_rules.KNOWN_RULES and committing, since in-process memory
    does not survive a Render restart.
    """
    _check(token or x_debug_token)
    return learned_summary()
