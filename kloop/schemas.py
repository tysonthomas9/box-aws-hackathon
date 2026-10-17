"""Canonical persisted and API data contracts, independent of service SDKs."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Identifier = Annotated[str, Field(min_length=1)]
QuestionKind = Literal["fact", "two_fact", "procedure", "untold", "unrelated"]
Split = Literal["train", "dev", "hidden"]
AskMode = Literal["without", "with", "search"]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Document(Schema):
    file_id: Identifier
    version_id: Identifier
    name: Identifier
    text: str


class Item(Schema):
    id: Identifier
    kind: Literal["fact", "procedure"]
    subject: Identifier
    statement: Identifier
    trigger_conditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list, description="Steps in execution order")
    supporting_quote: Identifier
    source_file_id: Identifier
    source_version_id: Identifier
    extractor: Identifier
    status: Literal["proposed", "approved", "flagged", "retired"] = "proposed"
    flag_reasons: list[str] = Field(default_factory=list)


class Question(Schema):
    id: Identifier
    question: Identifier
    expected_answer: str
    kind: QuestionKind
    split: Split
    source_item_ids: list[str] = Field(default_factory=list)


class ModelVersion(Schema):
    id: Identifier
    import_arn: str | None = None
    status: Literal[
        "pending",
        "training",
        "importing",
        "evaluating",
        "ready",
        "promoted",
        "rejected",
        "failed",
        "deleted",
    ] = "pending"
    manifest: dict[str, JsonValue] = Field(default_factory=dict)
    scores: dict[str, float] = Field(default_factory=dict)


class AskJob(Schema):
    id: Identifier
    question: Identifier
    mode: AskMode
    model_version_id: str | None = None
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    answer: str | None = None
    latency_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    error: str | None = None


class EvalResult(Schema):
    question_id: Identifier
    kind: QuestionKind
    mode: AskMode
    answer: str
    passed: bool
    score: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    reasons: list[str] = Field(default_factory=list)


class EvalReport(Schema):
    id: Identifier
    model_version_id: Identifier
    split: Split
    question_set_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    results: list[EvalResult] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
