import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request):
    checks = {"configuration": True, "postgresql": False, "redis": False}
    try:
        async with asyncio.timeout(3):
            async with request.app.state.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                checks["postgresql"] = True
    except Exception:
        pass
    try:
        async with asyncio.timeout(3):
            checks["redis"] = bool(await request.app.state.redis.ping())
    except Exception:
        pass
    task = getattr(request.app.state, "polling_task", None)
    if task is not None:
        checks["bot"] = not task.done()
    worker = getattr(request.app.state, "worker_task", None)
    if worker is not None:
        checks["agent_worker"] = not worker.done()
    return JSONResponse(
        {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks},
        status_code=200 if all(checks.values()) else 503,
    )
