import os

from fastapi import FastAPI

from app.reqlog import RequestLogMiddleware
from app.routers import debug, phase1, phase2, phase3

app = FastAPI(title="UBS GCC 2026", version="0.1.0")
app.add_middleware(RequestLogMiddleware)

app.include_router(debug.router)
# phase routers get added here as statements are released:
app.include_router(phase1.router)
app.include_router(phase2.router)
app.include_router(phase3.router)


def _commit() -> str:
    # Render injects the deployed commit; lets us confirm which version is live
    return os.environ.get("RENDER_GIT_COMMIT", "local")[:12]


@app.get("/")
async def root():
    return {"service": "ubs-gcc-2026", "commit": _commit()}


@app.get("/health")
async def health():
    return {"status": "ok", "commit": _commit()}
