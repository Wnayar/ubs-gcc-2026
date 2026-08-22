"""SHOWDOWN — POST /move (docs/phases/phase-3/, guide at docs/phases/showdown-guide.pdf).

The coordinator calls this whenever it is our turn and gives us 5 seconds. It
never retries, and "a timeout, a bad response, an illegal action or a bad
amount gets substituted with check ... five in a row forfeits the match" — so
this endpoint answers 200 with a legal action for *any* body, rather than
returning the 422 an unparseable request would normally deserve. The decision
itself lives in app/showdown.py.
"""
from fastapi import APIRouter, Request

from app.showdown import decide

router = APIRouter(tags=["showdown"])


@router.post("/move")
async def move(request: Request) -> dict:
    try:
        state = await request.json()
    except Exception:
        state = None
    return decide(state if isinstance(state, dict) else {})
