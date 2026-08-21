"""Throwaway endpoint that proves the deploy pipeline end to end.

Real phase routers live next to this file and get mounted in app/main.py.
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["sample"])


class SquareRequest(BaseModel):
    number: float


@router.post("/square")
async def square(payload: SquareRequest):
    return {"result": payload.number ** 2}
