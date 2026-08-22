import importlib
import os
import pkgutil

from fastapi import FastAPI

from app import routers
from app.reqlog import RequestLogMiddleware

app = FastAPI(title="UBS GCC 2026", version="0.1.0")
app.add_middleware(RequestLogMiddleware)

# Phase routers are auto-discovered: any app/routers/*.py exposing `router` is
# mounted. Keeps main.py conflict-free when phases are developed on branches.
for mod_info in sorted(pkgutil.iter_modules(routers.__path__), key=lambda m: m.name):
    module = importlib.import_module(f"{routers.__name__}.{mod_info.name}")
    if hasattr(module, "router"):
        app.include_router(module.router)


def _commit() -> str:
    # Render injects the deployed commit; lets us confirm which version is live
    return os.environ.get("RENDER_GIT_COMMIT", "local")[:12]


@app.get("/")
async def root():
    return {"service": "ubs-gcc-2026", "commit": _commit()}


@app.get("/health")
async def health():
    return {"status": "ok", "commit": _commit()}
