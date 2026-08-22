# Adaptive API Gateway Challenge (Student Guide)

This brief covers the full challenge: translating a V2-style request into a V1-compatible output and computing SLO-style health metrics from heartbeat data.

## Context

Server A recently moved from Version 1 (V1) to Version 2 (V2). The participant server must preserve compatibility for legacy clients while also reporting service-health metrics based on incoming heartbeat data.

## Goal

Implement `POST /solve` so that it returns a single combined response with both an adapted payload and SLO metrics.

## Required Endpoint

- `POST /solve`

## Request Contract

The endpoint receives:

```json
{
	"payload": "ewoJImFkYXB0SW5wdXQiOiB7CgkJInVzZXIiOiB7CgkJCSJpZCI6ICJVNDIiLAoJCQkiZnVsbE5hbWUiOiAiSmFuZSBEb2UiCgkJfSwKCQkiYWN0aW9uIjogIkNSRUFURSIsCgkJIm1ldGFkYXRhIjogewoJCQkicHJpb3JpdHkiOiAiSElHSCIKCQl9Cgl9LAoJImhlYXJ0YmVhdHMiOiBbCgkJewoJCQkic2VydmljZSI6ICJhdXRoIiwKCQkJInRpbWVzdGFtcCI6IDE3MTAwMDAxMjMsCgkJCSJsYXRlbmN5TXMiOiAxMjAsCgkJCSJzdGF0dXMiOiAiT0siCgkJfSwKCQl7CgkJCSJzZXJ2aWNlIjogImF1dGgiLAoJCQkidGltZXN0YW1wIjogMTcxMDAwMDEyNSwKCQkJImxhdGVuY3lNcyI6IDE4MCwKCQkJInN0YXR1cyI6ICJGQUlMIgoJCX0sCgkJewoJCQkic2VydmljZSI6ICJhdXRoIiwKCQkJInRpbWVzdGFtcCI6IDE3MTAwMDAxMjEsCgkJCSJsYXRlbmN5TXMiOiA5NSwKCQkJInN0YXR1cyI6ICJPSyIKCQl9CgldLAoJInNsb1F1ZXJ5IjogewoJCSJzZXJ2aWNlIjogImF1dGgiLAoJCSJzaW5jZSI6IDE3MTAwMDAxMjMKCX0KfQ=="
}
```

where the payload somehow decodes to this:

```json
{
	"adaptInput": {
		"user": {
			"id": "U42",
			"fullName": "Jane Doe"
		},
		"action": "CREATE",
		"metadata": {
			"priority": "HIGH"
		}
	},
	"heartbeats": [
		{
			"service": "auth",
			"timestamp": 1710000123,
			"latencyMs": 120,
			"status": "OK"
		},
		{
			"service": "auth",
			"timestamp": 1710000125,
			"latencyMs": 180,
			"status": "FAIL"
		},
		{
			"service": "auth",
			"timestamp": 1710000121,
			"latencyMs": 95,
			"status": "OK"
		}
	],
	"sloQuery": {
		"service": "auth",
		"since": 1710000123
	}
}
```

## Response Contract

The server should return:

```json
{
	"adaptOutput": {
		"id": "U42",
		"name": "Jane Doe",
		"action": "create",
		"priority": 3
	},
	"sloOutput": {
		"availability": 0.5,
		"p95LatencyMs": 180
	}
}
```

## Part 1: Adaptation Rules

Build `adaptOutput` from `adaptInput` using these rules:

- `adaptInput.user.id` -> `adaptOutput.id`
- `adaptInput.user.fullName` -> `adaptOutput.name`
- `adaptInput.action` -> lowercase string in `adaptOutput.action`
- `adaptInput.metadata.priority` mapping:
    - `LOW` -> `1`
    - `MEDIUM` -> `2`
    - `HIGH` -> `3`

Robustness expectations:

- Ignore unknown fields.
- If priority is missing or unrecognized, default to `2`.
- The output should be deterministic for the same logical input.

## Part 2: SLO Rules

Build `sloOutput` from `heartbeats` and `sloQuery`.

Filtering rules:

- Keep only heartbeats whose `service` matches `sloQuery.service`.
- If `sloQuery.since` exists, keep only heartbeats where `timestamp >= since`; otherwise keep all.
- Ignore duplicate heartbeats that share the same `(service, timestamp)` pair.
- Handle out-of-order input correctly.

Metrics:

- `availability = OK_count / total_count`
- `p95LatencyMs = nearest-rank p95 latency of the relevant rows`

If no rows remain after filtering, return:

- `availability: 0.0`
- `p95LatencyMs: 0`

## Success Criteria

The evaluator will validate that:

- `POST /solve` exists and responds with HTTP 200,
- the response contains both `adaptOutput` and `sloOutput`,
- the adaptation mapping is correct,
- the priority defaults and lowercasing behave as expected,
- the SLO availability and p95 calculations are correct.
