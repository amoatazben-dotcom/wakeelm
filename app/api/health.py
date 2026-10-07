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
        from app.platform.telemetry import metric

        metric("redis_errors")
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


@router.get("/version")
async def version(request: Request):
    from app.platform.version import metadata

    result = metadata(request.app.state.settings)
    result["schema_version"] = "unavailable"
    try:
        async with asyncio.timeout(3):
            async with request.app.state.engine.connect() as connection:
                result["schema_version"] = await connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
    except Exception:
        pass
    return result
