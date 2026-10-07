from app.db.models import AuditLog


def audit(session, user_id, action, entity_type=None, entity_id=None, **metadata):
    safe = {
        k: v
        for k, v in metadata.items()
        if k
        in {
            "risk",
            "integration",
            "job_id",
            "risk",
            "integration",
            "job_id",
            "status",
            "count",
            "language",
            "routing_policy_version",
            "reason",
            "confidence",
            "fallback_chain",
            "required_capabilities",
            "task_type",
            "classifier_version",
        }
    }
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            metadata_json=safe,
        )
    )
