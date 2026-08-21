"""Phase 1 — Square Function Task (docs/phases/phase-1/)."""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["phase-1"])


class SquareRequest(BaseModel):
    # int | float keeps int results as ints (5 -> 25, not 25.0) to match the
    # statement's example output exactly
    value: int | float


@router.post("/square")
async def square(payload: SquareRequest):
    return {"result": payload.value ** 2}
