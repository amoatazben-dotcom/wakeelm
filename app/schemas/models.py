from pydantic import BaseModel, Field

CAPABILITIES = [
    "chat",
    "streaming",
    "tool_calling",
    "vision",
    "reasoning",
    "structured_output",
    "embeddings",
    "audio_input",
    "audio_output",
    "image_generation",
    "coding",
]


class NormalizedModel(BaseModel):
    external_id: str
    display_name: str
    provider: str
    status: str = "UNTESTED"
    capabilities: dict = Field(
        default_factory=lambda: {
            k: {"state": "UNKNOWN", "source": "NOT_TESTED"} for k in CAPABILITIES
        }
    )
    context_length: int | None = None
    pricing: dict = Field(default_factory=lambda: {"classification": "UNKNOWN"})
    metadata: dict = Field(default_factory=dict)
