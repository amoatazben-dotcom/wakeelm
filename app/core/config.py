from typing import Literal

from cryptography.fernet import Fernet
from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    app_name: str = "Telegram AI Agent"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    telegram_bot_token: SecretStr
    database_url: SecretStr
    redis_url: SecretStr
    master_encryption_key: SecretStr
    bot_mode: Literal["polling", "webhook"] = "polling"
    bot_default_language: Literal["ar", "en"] = "ar"
    log_level: str = "INFO"
    public_base_url: str | None = None
    webhook_secret: SecretStr | None = None
    provider_timeout: float = Field(default=30, gt=0, le=60)
    max_response_bytes: int = Field(default=2_000_000, ge=1024, le=10_000_000)
    max_model_fallbacks: int = Field(default=2, ge=0, le=5)
    max_job_model_calls: int = Field(default=12, ge=1, le=50)
    max_job_tokens: int = Field(default=100000, ge=1000, le=1000000)
    max_job_cost: float = Field(default=1, gt=0, le=100)
    max_models: int = Field(default=1000, ge=1, le=10000)

    workspace_storage_root: str = "storage/workspaces"
    max_upload_size_mb: int = Field(default=20, ge=1, le=100)
    max_archive_size_mb: int = Field(default=20, ge=1, le=100)
    max_extracted_size_mb: int = Field(default=100, ge=1, le=500)
    max_archive_files: int = Field(default=2000, ge=1, le=10000)
    max_single_file_size_mb: int = Field(default=5, ge=1, le=50)
    max_project_files: int = Field(default=2000, ge=1, le=10000)
    context_max_tokens: int = Field(default=6000, ge=256, le=32000)
    context_safety_margin: float = Field(default=0.2, ge=0.1, le=0.5)
    max_agent_steps: int = Field(default=12, ge=1, le=30)
    max_tool_calls: int = Field(default=20, ge=1, le=60)
    max_replans: int = Field(default=2, ge=0, le=5)
    max_repair_attempts: int = Field(default=1, ge=0, le=3)
    max_task_duration: int = Field(default=300, ge=10, le=1800)
    max_command_output_bytes: int = Field(default=32000, ge=1024, le=1000000)
    command_timeout: int = Field(default=60, ge=1, le=300)
    sandbox_backend: Literal["disabled", "docker"] = "disabled"
    sandbox_image: str = "wakeelm-validation:local"
    require_edit_approval: bool = False
    max_patch_files: int = Field(default=10, ge=1, le=30)
    approval_ttl_seconds: int = Field(default=600, ge=30, le=3600)

    github_app_id: int | None = None
    github_app_private_key: SecretStr | None = None
    github_client_id: str | None = None
    github_client_secret: SecretStr | None = None
    github_webhook_secret: SecretStr | None = None
    github_write_enabled: bool = False
    github_push_ci_reviewed: bool = False
    github_comments_enabled: bool = False
    github_bot_name: str = "Wakeelm Agent"
    github_bot_email: str = "wakeelm-agent@users.noreply.github.com"
    git_timeout_seconds: int = Field(default=90, ge=1, le=300)
    git_max_output_bytes: int = Field(default=2000000, ge=1024, le=10000000)
    git_max_repository_bytes: int = Field(default=100000000, ge=1000000, le=500000000)
    git_max_memory_mb: int = Field(default=512, ge=64, le=2048)
    git_require_validation: bool = True
    integrations_callback_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("integrations_callback_base_url", "MCP_CALLBACK_BASE_URL"),
    )
    oauth_state_ttl_seconds: int = Field(default=600, ge=30, le=900)
    mcp_allowed_transports: list[str] = ["streamable_http"]
    mcp_connect_timeout_seconds: int = Field(default=10, ge=1, le=60)
    mcp_call_timeout_seconds: int = Field(default=30, ge=1, le=120)
    mcp_max_response_bytes: int = Field(default=1000000, ge=1024, le=5000000)
    mcp_max_capabilities: int = Field(default=100, ge=1, le=1000)
    mcp_tool_policies: dict = {}  # admin reviewed URL + name + schema fingerprint policies
    mcp_oauth_clients: dict = {}  # admin-provisioned issuer -> public client ID
    integration_jobs_enabled: bool = True

    @field_validator("master_encryption_key")
    @classmethod
    def valid_key(cls, value):
        Fernet(value.get_secret_value().encode())
        return value

    @model_validator(mode="after")
    def webhook_config(self):
        if self.bot_mode == "webhook" and (
            not self.public_base_url
            or not self.public_base_url.startswith("https://")
            or not self.webhook_secret
        ):
            raise ValueError("Webhook requires HTTPS PUBLIC_BASE_URL and WEBHOOK_SECRET")
        if self.webhook_secret:
            import re

            if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", self.webhook_secret.get_secret_value()):
                raise ValueError("Invalid webhook secret format")
        return self

    @property
    def async_database_url(self):
        url = self.database_url.get_secret_value()
        if url.startswith(("postgres://", "postgresql://")):
            return "postgresql+asyncpg://" + url.split("://", 1)[1]
        return url
