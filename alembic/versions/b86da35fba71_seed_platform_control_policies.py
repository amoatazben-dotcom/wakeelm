"""Seed explicit operational controls and versioned plan limits."""

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from alembic import op

revision = "b86da35fba71"
down_revision = "771dc45faaa3"
branch_labels = None
depends_on = None


def upgrade():
    stamp = datetime.now(timezone.utc)
    flags = sa.table(
        "feature_flags",
        sa.column("key", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("targets_json", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    plans = sa.table(
        "plan_policies",
        sa.column("name", sa.String()),
        sa.column("limits_json", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    flag_values = {
        "multi_agent": True,
        "deep_mode": True,
        "experimental_router": True,
        "disable_external_writes": False,
        "disable_github_push": False,
        "disable_mcp_writes": False,
        "disable_new_jobs": False,
        "disable_uploads": False,
        "admin_dashboard_feature": True,
    }
    plan_values = {
        "FREE": {
            "messages_day": 50,
            "tokens_day": 100000,
            "jobs_day": 10,
            "concurrent_jobs": 2,
            "storage_bytes": 100000000,
            "repositories": 3,
            "mcp_connections": 3,
            "github_repositories": 5,
            "monthly_spend": 5,
            "daily_spend": 1,
            "max_upload_bytes": 20000000,
        },
        "STANDARD": {
            "messages_day": 500,
            "tokens_day": 1000000,
            "jobs_day": 100,
            "concurrent_jobs": 5,
            "storage_bytes": 1000000000,
            "repositories": 20,
            "mcp_connections": 20,
            "github_repositories": 50,
            "monthly_spend": 50,
            "daily_spend": 10,
            "max_upload_bytes": 20000000,
        },
        "PRO": {
            "messages_day": 2000,
            "tokens_day": 5000000,
            "jobs_day": 500,
            "concurrent_jobs": 10,
            "storage_bytes": 5000000000,
            "repositories": 100,
            "mcp_connections": 100,
            "github_repositories": 200,
            "monthly_spend": 200,
            "daily_spend": 50,
            "max_upload_bytes": 50000000,
        },
        "ADMIN": {
            "messages_day": 2000,
            "tokens_day": 5000000,
            "jobs_day": 500,
            "concurrent_jobs": 10,
            "storage_bytes": 5000000000,
            "repositories": 100,
            "mcp_connections": 100,
            "github_repositories": 200,
            "monthly_spend": 200,
            "daily_spend": 50,
            "max_upload_bytes": 50000000,
        },
    }
    insert = pg_insert if op.get_bind().dialect.name == "postgresql" else sqlite_insert
    op.execute(
        insert(flags)
        .values(
            [
                {
                    "key": key,
                    "enabled": enabled,
                    "targets_json": {},
                    "created_at": stamp,
                    "updated_at": stamp,
                }
                for key, enabled in flag_values.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["key"])
    )
    op.execute(
        insert(plans)
        .values(
            [
                {"name": name, "limits_json": limits, "created_at": stamp, "updated_at": stamp}
                for name, limits in plan_values.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["name"])
    )


def downgrade():
    # Retain operator-modified rows; the earlier table downgrade handles their eventual removal.
    pass
