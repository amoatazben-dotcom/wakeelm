"""Shared Android conversation cache."""

import sqlalchemy as sa

from alembic import op

revision = "c091d2a30101"
down_revision = "b86da35fba71"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "client_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_client_conversations_user_id", "client_conversations", ["user_id"])
    op.create_table(
        "client_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("client_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "request_id", "role"),
    )
    op.create_index("ix_client_messages_conversation_id", "client_messages", ["conversation_id"])


def downgrade():
    op.drop_table("client_messages")
    op.drop_table("client_conversations")
