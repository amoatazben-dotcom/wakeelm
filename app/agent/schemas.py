from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.storage.paths import safe_relative


class AgentMode(StrEnum):
    READ_ONLY = "READ_ONLY"
    SUGGEST = "SUGGEST"
    WORKSPACE = "WORKSPACE"


class Risk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ToolRequest(StrictModel):
    tool_name: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict)
    reason: str = Field(default="", max_length=500)


class AgentPlan(StrictModel):
    goal: str = Field(min_length=1, max_length=1000)
    steps: list[ToolRequest] = Field(min_length=0, max_length=30)
    risk: Risk = Risk.LOW
    complete: bool = True
    answer: str = Field(default="", max_length=6000)

    @model_validator(mode="after")
    def valid_finish(self):
        if not self.steps and (not self.complete or not self.answer.strip()):
            raise ValueError("Empty unfinished plan")
        return self


class EmptyInput(StrictModel):
    pass


class FileInput(StrictModel):
    path: str = Field(min_length=1, max_length=2048)

    @field_validator("path")
    @classmethod
    def path_valid(cls, value):
        return safe_relative(value)


class ReadInput(FileInput):
    start_line: int = Field(default=1, ge=1, le=1000000)
    end_line: int = Field(default=200, ge=1, le=1000000)


class SearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    glob: str | None = Field(default=None, max_length=2048)
    max_results: int = Field(default=30, ge=1, le=100)


class PatchEdit(FileInput):
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    kind: str = Field(pattern=r"^(exact|lines|unified|full|new|delete)$")
    old_text: str | None = Field(default=None, max_length=200000)
    new_text: str = Field(default="", max_length=200000)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    justification: str = Field(default="", max_length=1000)


class ProposePatchInput(StrictModel):
    edits: list[PatchEdit] = Field(min_length=1, max_length=30)


class ChangeSetInput(StrictModel):
    change_set_id: str = Field(min_length=1, max_length=40)


class ValidationInput(StrictModel):
    command_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,49}$")


class RequestApprovalInput(StrictModel):
    tool_name: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict)


class ToolOutput(StrictModel):
    data: dict = Field(default_factory=dict)
    summary: str = Field(default="", max_length=500)
