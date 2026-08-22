"""Phase 2 — Adaptive API Gateway (docs/phases/phase-2/).

The statement gives one worked example and says the request payload "somehow
decodes" to JSON — so the decoding side is deliberately loose and the mapping
side is pinned to the example. See notes.md for every assumption made here.
"""
import base64
import binascii
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["phase-2"])

# Only HIGH -> 3 is given by the statement; the rest is the natural ladder around
# it. Anything unrecognised becomes 0 rather than an error (notes.md).
PRIORITIES = {
    "NONE": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "MED": 2,
    "NORMAL": 2,
    "HIGH": 3,
    "CRITICAL": 4,
    "URGENT": 4,
    "SEVERE": 4,
}


class SolveRequest(BaseModel):
    # a dict is accepted too, in case the grader ever sends the payload already
    # decoded; anything else (number, list, null, missing) is a 422
    payload: str | dict[str, Any]


class AdaptOutput(BaseModel):
    # field order here is the field order in the response body — keep it exactly
    # as the statement's sample response
    id: str | int
    name: str
    action: str
    priority: int | float


class SolveResponse(BaseModel):
    adaptOutput: AdaptOutput


def _reject(reason: str) -> HTTPException:
    return HTTPException(status_code=422, detail=f"invalid payload: {reason}")


def _candidates(text: str) -> list[bytes | str]:
    """Every way we are willing to read the payload, best guess first."""
    compact = "".join(text.split())  # tolerate line-wrapped base64
    padded = compact + "=" * (-len(compact) % 4)
    standard = padded.replace("-", "+").replace("_", "/")  # url-safe alphabet
    out: list[bytes | str] = []
    for variant in dict.fromkeys((padded, standard)):
        try:
            out.append(base64.b64decode(variant, validate=True))
        except (binascii.Error, ValueError):
            continue
    out.append(text)  # last resort: the payload was already plain JSON
    return out


def _decode(payload: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    text = payload.strip()
    if not text:
        raise _reject("payload is empty")
    for candidate in _candidates(text):
        try:
            decoded = json.loads(candidate)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(decoded, dict):
            return decoded
    raise _reject("not base64-encoded JSON")


def _first(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value is not None:
            return value
    return None


def _name(user: dict[str, Any]) -> str | None:
    full = _first(user, "fullName", "full_name", "fullname", "name")
    if isinstance(full, str) and full.strip():
        return full
    # V1 shape: separate name parts (the "bridge" the context asks for)
    parts = [
        part
        for part in (_first(user, "firstName", "first_name"), _first(user, "lastName", "last_name"))
        if isinstance(part, str) and part.strip()
    ]
    return " ".join(parts) if parts else None


def _priority(raw: Any) -> int | float:
    if isinstance(raw, bool):  # bools are ints in Python — not a priority
        return 0
    if isinstance(raw, (int, float)):
        return raw
    if isinstance(raw, str):
        word = raw.strip()
        if word.upper() in PRIORITIES:
            return PRIORITIES[word.upper()]
        try:
            return int(word)
        except ValueError:
            return 0
    return 0


def _transform(decoded: dict[str, Any]) -> SolveResponse:
    body = decoded.get("adaptInput")
    if not isinstance(body, dict):
        raise _reject("no adaptInput object")

    raw_user = body.get("user")
    user = raw_user if isinstance(raw_user, dict) else {}

    identifier = _first(user, "id", "userId", "user_id") or _first(body, "id", "userId", "user_id")
    if not isinstance(identifier, (str, int)) or isinstance(identifier, bool):
        raise _reject("adaptInput.user.id missing")

    name = _name(user) or _name(body)
    if name is None:
        raise _reject("adaptInput.user.fullName missing")

    action = body.get("action")
    if not isinstance(action, str):
        raise _reject("adaptInput.action missing")

    metadata = body.get("metadata")
    raw_priority = (
        metadata.get("priority") if isinstance(metadata, dict) else body.get("priority")
    )

    return SolveResponse(
        adaptOutput=AdaptOutput(
            id=identifier,
            name=name,
            action=action.lower(),
            priority=_priority(raw_priority),
        )
    )


@router.post("/solve", response_model=SolveResponse)
async def solve(request: SolveRequest) -> SolveResponse:
    try:
        return _transform(_decode(request.payload))
    except HTTPException:
        raise
    except Exception:  # a payload we failed to anticipate is bad input, not a 500
        raise _reject("could not be transformed") from None
