# Phase 1 — Square Function Task

- **PDF:** `statement.pdf` in this folder (save it the moment it drops)
- **Endpoints required:** `POST /square` — body `{"value": <number>}`, respond `{"result": <value squared>}`, HTTP 200
- **Submitted to controller:** no (practice dry-run)
- **Score:**

## Examples from the statement (verbatim)

| Input | Expected Output | Status |
|---|---|---|
| `{"value": 5}` | `{"result": 25}` | 200 OK |

## Clarifications from challenge developers

- Q: … → A: …

## Assumptions we made

- Statement says "a value" with an integer example. We accept ints and floats;
  an int input returns an int result (`5 → 25`, not `25.0`) in case the grader
  compares JSON exactly. Floats square to floats (`2.5 → 6.25`).
- Non-numeric / missing `value` → 422 (pydantic validation), never a 500.
- The scaffold's sample endpoint also used `POST /square` but with field `number`;
  it was a throwaway deploy-pipeline check, so the phase endpoint replaces it.

## Failed test cases and what fixed them

-
