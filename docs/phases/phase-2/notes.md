# Phase 2 — Adaptive API Gateway

> **Superseded by `docs/phases/adaptive-api-gateway/`.** This folder holds the
> earlier `/adapt` guide. The challenge later published `/adapt-slo`, which adds
> SLO metrics to the same `POST /solve` and overturns one rule recorded below:
> an unknown or missing priority defaults to **2**, not 0. Read that folder
> first; keep this one for the history.

- **PDF:** `statement.pdf` in this folder (printed from
  <https://adaptive-api-gateway-be2304567894.herokuapp.com/adapt>; the base64 in the
  PDF is visually clipped — the full string below came from the page's markdown
  source at `/static//adapt-amb.md`, which is otherwise identical to the PDF)
- **Endpoints required:** `POST /solve` — body `{"payload": "<base64 JSON>"}`,
  respond `{"adaptOutput": {...}}`, HTTP 200
- **Submitted to controller:** no
- **Score:**

## What the statement says

Context: "Server A recently moved from Version 1 (V1) to Version 2 (V2). The
participant server is expected to help bridge the old and new models." Goal:
"expose `POST /solve` and return a transformed payload based on the incoming
request." The wording "the payload **somehow** decodes to this" is the only hint
about the encoding — it is deliberately vague (the source file is named
`adapt-amb.md`, i.e. the *ambiguous* variant of the guide).

## Examples from the statement (verbatim)

Request:

```json
{
	"payload": "ewoJImFkYXB0SW5wdXQiOiB7CgkJInVzZXIiOiB7CgkJCSJpZCI6ICJVNDIiLAoJCQkiZnVsbE5hbWUiOiAiSmFuZSBEb2UiCgkJfSwKCQkiYWN0aW9uIjogIkNSRUFURSIsCgkJIm1ldGFkYXRhIjogewoJCQkicHJpb3JpdHkiOiAiSElHSCIKCQl9Cgl9Cn0="
}
```

which decodes (verified: standard base64 → UTF-8 → JSON) to:

```json
{
	"adaptInput": {
		"user": { "id": "U42", "fullName": "Jane Doe" },
		"action": "CREATE",
		"metadata": { "priority": "HIGH" }
	}
}
```

Response:

```json
{
	"adaptOutput": { "id": "U42", "name": "Jane Doe", "action": "create", "priority": 3 }
}
```

Status: 200 OK.

## The transformation, as derived from the single example

| Output field | Source | Rule |
|---|---|---|
| `id` | `adaptInput.user.id` | copied |
| `name` | `adaptInput.user.fullName` | copied (renamed) |
| `action` | `adaptInput.action` | lowercased (`CREATE` → `create`) |
| `priority` | `adaptInput.metadata.priority` | string → number (`HIGH` → 3) |

## Clarifications from challenge developers

- Q: What is the full priority scale? Only `HIGH → 3` is given. Is it
  `LOW=1, MEDIUM=2, HIGH=3`, and what about `CRITICAL`/`URGENT`? → A: …
- Q: Is the payload always standard base64, or should we accept URL-safe base64 /
  unpadded / plain JSON too? "somehow decodes" suggests variation. → A: …
- Q: "Bridge the old and new models" — will `adaptInput` ever arrive in the V1
  shape (e.g. `firstName`/`lastName` instead of `fullName`)? → A: …
- Q: What should `POST /solve` return for an undecodable payload or an unknown
  priority — 4xx, or a best-effort 200? → A: …

## Assumptions we made

- **Encoding:** standard base64 of UTF-8 JSON, verified against the sample. We
  decode leniently — standard *and* URL-safe alphabets, missing `=` padding
  restored, surrounding whitespace stripped — and, as a last resort, accept a
  payload that is already plain JSON (or an already-decoded object). Every one of
  these still produces the statement's answer for the statement's input.
- **Priority scale:** `LOW=1, MEDIUM=2, HIGH=3` (the only anchor is `HIGH=3`, and a
  1–3 ladder is the natural reading), extended with `CRITICAL`/`URGENT`/`SEVERE=4`
  and `NONE=0`. Matching is case-insensitive. A priority that is already a number
  passes through unchanged. **An unrecognised string maps to 0** — chosen so we
  never 500 and never invent a rank; flagged for the developers, this is the single
  most likely place to lose points.
- **Missing `metadata`/`priority`:** treated as `priority: 0` rather than an error —
  a gateway should pass an incomplete-but-parseable message through.
- **Field aliases (the V1/V2 "bridge"):** `id` also read from `userId`/`user_id`;
  `name` also from `name`/`full_name`/`fullname`, or `firstName` + `lastName`
  joined; `priority` also read from a top-level `priority`. The V2 spellings in the
  example always win when present. This cannot change the statement's example.
- **Strict where it counts:** a missing/non-string `payload`, or one that cannot be
  decoded to a JSON object with an `adaptInput`, is a 422 — never a 500.
- **Response shape:** exactly `{"adaptOutput": {...}}` with the four keys in the
  statement's order and no extras.
- `action` is lowercased with `str.lower()`; a non-string action is rejected (422).

## Failed test cases and what fixed them

-
