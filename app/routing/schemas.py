from enum import StrEnum

from pydantic import BaseModel, Field


class RoutingPolicy(StrEnum):
    AUTO = "AUTO"
    PREFER_FREE = "PREFER_FREE"
    PREFER_CHEAP = "PREFER_CHEAP"
    PREFER_FAST = "PREFER_FAST"
    PREFER_STRONGEST = "PREFER_STRONGEST"
    PREFER_LONG_CONTEXT = "PREFER_LONG_CONTEXT"
    PREFER_CODING = "PREFER_CODING"
    MANUAL_ONLY = "MANUAL_ONLY"


class TaskType(StrEnum):
    GENERAL_CHAT = "GENERAL_CHAT"
    CODE_QA = "CODE_QA"
    CODE_EDIT = "CODE_EDIT"
    REPOSITORY_TASK = "REPOSITORY_TASK"
    DEBUGGING = "DEBUGGING"
    REFACTOR = "REFACTOR"
    TESTING = "TESTING"
    DOCUMENT_ANALYSIS = "DOCUMENT_ANALYSIS"
    IMAGE_ANALYSIS = "IMAGE_ANALYSIS"
    DATA_ANALYSIS = "DATA_ANALYSIS"
    PLANNING = "PLANNING"
    SEARCH = "SEARCH"
    MCP_ACTION = "MCP_ACTION"
    GITHUB_ACTION = "GITHUB_ACTION"
    LONG_CONTEXT_REVIEW = "LONG_CONTEXT_REVIEW"


class TaskClassification(BaseModel):
    task_type: TaskType
    complexity: int = Field(default=1, ge=1, le=5)
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    classifier_version: str = "rules-1"


class RoutingRequest(BaseModel):
    task_type: TaskType = TaskType.GENERAL_CHAT
    task_complexity: int = Field(default=1, ge=1, le=5)
    required_capabilities: set[str] = Field(default_factory=set)
    context_size: int = Field(default=0, ge=0)
    policy: RoutingPolicy = RoutingPolicy.AUTO
    manual_model_id: int | None = None
    fallback_enabled: bool = True
    excluded_providers: set[int] = Field(default_factory=set)
    latency_preference: float = Field(default=0.5, ge=0, le=1)
    cost_preference: float = Field(default=0.5, ge=0, le=1)
    workspace_metadata: dict = Field(default_factory=dict)


class RoutingDecision(BaseModel):
    provider_id: int
    model_id: int
    reason: str
    confidence: float
    fallback_chain: list[int]
    estimated_cost_class: str
    required_capabilities: list[str]
    routing_policy_version: str = "router-1"
