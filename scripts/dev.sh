#!/usr/bin/env bash
# Run the service locally with hot reload.
cd "$(dirname "$0")/.."
exec .venv/bin/uvicorn app.main:app --reload --port "${PORT:-8000}"
