from pydantic import Field, field_validator

from app.agent.schemas import StrictModel
from app.git.runtime import ref
from app.storage.paths import safe_relative


class BranchInput(StrictModel):
    branch: str = Field(min_length=1, max_length=201)

    @field_validator("branch")
    @classmethod
    def valid(cls, value):
        return ref(value)


class PathsInput(StrictModel):
    paths: list[str] = Field(min_length=1, max_length=100)

    @field_validator("paths")
    @classmethod
    def valid(cls, value):
        return [safe_relative(p) for p in value]


class GitCommitInput(StrictModel):
    message: str = Field(min_length=1, max_length=200)
    expected_files: list[str] = Field(min_length=1, max_length=100)

    @field_validator("expected_files")
    @classmethod
    def valid(cls, value):
        return [safe_relative(p) for p in value]


class PushInput(BranchInput):
    expected_head: str = Field(pattern=r"^(?:[a-f0-9]{40,64}|\$last_commit)$")


class NumberInput(StrictModel):
    number: int = Field(ge=1)


class PageInput(StrictModel):
    page: int = Field(default=1, ge=1, le=1000)


class CompareInput(StrictModel):
    base: str = Field(min_length=1, max_length=200)
    head: str = Field(min_length=1, max_length=200)

    @field_validator("base", "head")
    @classmethod
    def valid(cls, value):
        return ref(value)


class SHAInput(StrictModel):
    sha: str = Field(pattern=r"^[a-f0-9]{40,64}$")


class MCPResourceInput(StrictModel):
    server_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    uri: str = Field(min_length=1, max_length=2048)


class MCPPromptInput(StrictModel):
    server_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    name: str = Field(min_length=1, max_length=255)
    arguments: dict[str, str] = Field(default_factory=dict)
