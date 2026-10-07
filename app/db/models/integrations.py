from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, now


class GitHubConnection(TimestampMixin, Base):
    __tablename__ = "github_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    connection_type: Mapped[str] = mapped_column(String(20))
    github_user_id: Mapped[int | None] = mapped_column(BigInteger)
    github_login: Mapped[str | None] = mapped_column(String(100))
    installation_id: Mapped[int | None] = mapped_column(BigInteger)
    encrypted_token: Mapped[str | None] = mapped_column(Text)
    token_hint: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GitHubRepository(TimestampMixin, Base):
    __tablename__ = "github_repositories"
    __table_args__ = (UniqueConstraint("github_connection_id", "github_repository_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    github_connection_id: Mapped[str] = mapped_column(
        ForeignKey("github_connections.id", ondelete="CASCADE"), index=True
    )
    github_repository_id: Mapped[int] = mapped_column(BigInteger)
    owner: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    full_name: Mapped[str] = mapped_column(String(210))
    default_branch: Mapped[str] = mapped_column(String(255))
    visibility: Mapped[str] = mapped_column(String(20))
    web_url: Mapped[str] = mapped_column(String(512))
    clone_url: Mapped[str] = mapped_column(String(512))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions_json: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RepositoryWorkspace(TimestampMixin, Base):
    __tablename__ = "repository_workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True
    )
    github_repository_id: Mapped[str] = mapped_column(
        ForeignKey("github_repositories.id", ondelete="CASCADE")
    )
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("github_connections.id", ondelete="CASCADE")
    )
    remote_name: Mapped[str] = mapped_column(String(30), default="origin")
    default_branch: Mapped[str] = mapped_column(String(255))
    base_ref: Mapped[str] = mapped_column(String(255))
    working_branch: Mapped[str | None] = mapped_column(String(255))
    base_commit_sha: Mapped[str] = mapped_column(String(64))
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class MCPServer(TimestampMixin, Base):
    __tablename__ = "mcp_servers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    transport: Mapped[str] = mapped_column(String(30), default="streamable_http")
    server_url: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    auth_type: Mapped[str] = mapped_column(String(20), default="NONE")
    encrypted_auth_config: Mapped[str | None] = mapped_column(Text)
    protocol_version: Mapped[str | None] = mapped_column(String(30))
    server_info_json: Mapped[dict] = mapped_column(JSON, default=dict)
    capabilities_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MCPCredential(TimestampMixin, Base):
    __tablename__ = "mcp_credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mcp_server_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), unique=True
    )
    credential_type: Mapped[str] = mapped_column(String(30))
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scopes_json: Mapped[list] = mapped_column(JSON, default=list)
    issuer: Mapped[str] = mapped_column(String(2048))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class MCPTool(TimestampMixin, Base):
    __tablename__ = "mcp_tools"
    __table_args__ = (UniqueConstraint("mcp_server_id", "external_name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mcp_server_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True
    )
    external_name: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema_json: Mapped[dict] = mapped_column(JSON)
    output_schema_json: Mapped[dict | None] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(20), default="HIGH")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MCPResource(Base):
    __tablename__ = "mcp_resources"
    __table_args__ = (UniqueConstraint("mcp_server_id", "uri"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mcp_server_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True
    )
    uri: Mapped[str] = mapped_column(String(2048))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    mime_type: Mapped[str | None] = mapped_column(String(100))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OAuthState(Base):
    __tablename__ = "integration_oauth_states"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # hashed state
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(36))
    nonce_hash: Mapped[str] = mapped_column(String(64))
    payload_encrypted: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
