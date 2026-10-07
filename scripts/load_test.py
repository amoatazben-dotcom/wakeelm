"""Isolated load drill: PostgreSQL + Redis + real routing/accounting; controlled provider."""

import asyncio
import json
import os
import resource
import time
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import Settings
from app.core.limits import Limits
from app.core.security import SecretManager
from app.db.base import Base
from app.db.models import Model, Provider, User
from app.db.session import database
from app.services.model_service import ModelService
from app.services.provider_service import ProviderService


class ControlledProvider:
    async def request(self, method, url, headers, payload=None):
        await asyncio.sleep(0.005)
        return {
            "choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


async def run(settings, requests=100, concurrency=10):
    # Refuse application databases: caller must create a dedicated load fixture database.
    if "load_" not in settings.database_url.get_secret_value().rsplit("/", 1)[-1]:
        raise RuntimeError("Load drill requires an isolated load_ database")
    engine, sessions = database(settings.async_database_url)
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    crypto = SecretManager(settings.master_encryption_key.get_secret_value())
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    ids = []
    async with sessions() as session:
        for index in range(concurrency):
            user = User(telegram_user_id=880000 + index)
            session.add(user)
            await session.flush()
            provider = Provider(
                user_id=user.id,
                name="Controlled",
                provider_type="CUSTOM_OPENAI_COMPATIBLE",
                base_url="https://example.com/v1",
                api_base_url="https://example.com/v1",
                encrypted_api_token=crypto.encrypt("test-only"),
                extra_headers_encrypted=crypto.encrypt_headers({}),
                token_hint="***",
                status="ONLINE",
            )
            session.add(provider)
            await session.flush()
            model = Model(
                provider_id=provider.id,
                external_model_id="controlled",
                display_name="Controlled",
                pricing_json={"classification": "FREE_VERIFIED"},
                capabilities_json={"chat": {"state": "SUPPORTED", "source": "TESTED"}},
                metadata_json={},
            )
            session.add(model)
            await session.flush()
            ids.append((user.id, model.id))
        await session.commit()
    latencies, failures, queue_delays = [], [], []
    semaphore = asyncio.Semaphore(concurrency)
    started = time.monotonic()
    cpu_started = time.process_time()

    async def one(index):
        queued = time.monotonic()
        async with semaphore:
            queue_delays.append(time.monotonic() - queued)
            user_id, model_id = ids[index % concurrency]
            stamp = time.monotonic()
            try:
                async with sessions() as session:
                    service = ModelService(
                        ProviderService(
                            session, user_id, crypto, ControlledProvider(), Limits(redis)
                        ),
                        settings,
                    )
                    model = await service.owned.model(model_id)
                    assert (await service.completion(model, "load request"))[0] == "OK"
                    await session.commit()
            except Exception as exc:
                failures.append(getattr(exc, "code", type(exc).__name__))
            latencies.append((time.monotonic() - stamp) * 1000)

    await asyncio.gather(*(one(i) for i in range(requests)))
    ordered = sorted(latencies)

    def percentile(values, p):
        values = sorted(values)
        return round(values[min(len(values) - 1, int((len(values) - 1) * p))], 3)

    async with engine.connect() as connection:
        ledger = await connection.scalar(
            text("SELECT count(*) FROM usage_entries WHERE status='COMPLETED'")
        )
        tokens = await connection.scalar(
            text("SELECT sum(input_tokens+output_tokens) FROM usage_entries")
        )
    redis_info = await redis.info("memory")
    result = {
        "scenario": "isolated multi-tenant model routing + SQL quota reservations + shared Redis circuit",
        "requests": requests,
        "concurrency": concurrency,
        "duration_seconds": round(time.monotonic() - started, 3),
        "p50_ms": percentile(ordered, 0.5),
        "p95_ms": percentile(ordered, 0.95),
        "p99_ms": percentile(ordered, 0.99),
        "error_count": len(failures),
        "error_rate": len(failures) / requests,
        "failures": failures[:10],
        "queue_delay_p95_ms": round(percentile(queue_delays, 0.95) * 1000, 3),
        "cpu_seconds": round(time.process_time() - cpu_started, 3),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "db_pool_checked_out": engine.sync_engine.pool.checkedout(),
        "redis_used_memory_bytes": redis_info["used_memory"],
        "completed_usage_entries": ledger,
        "accounted_tokens": tokens,
        "provider": "controlled 5ms mock; no billable external calls",
        "production_capacity_claim": False,
    }
    await redis.aclose()
    await engine.dispose()
    return result


if __name__ == "__main__":
    result = asyncio.run(run(Settings()))
    destination = Path(os.environ.get("LOAD_REPORT_PATH", "docs/release-evidence/stage8-load.json"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
