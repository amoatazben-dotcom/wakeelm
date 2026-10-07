import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.exceptions import SafeError

FULL_NAME = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}$")


def full_name(value):
    if not FULL_NAME.fullmatch(value) or value.split("/")[1] in {".", ".."}:
        raise SafeError("INVALID_REPOSITORY")
    return value


class RepositoryMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    full_name: str
    default_branch: str
    private: bool = False
    archived: bool = False
    disabled: bool = False
    permissions: dict = Field(default_factory=dict)

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, value):
        return full_name(value)


class PullRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    draft: bool = True


class CommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=5000)
