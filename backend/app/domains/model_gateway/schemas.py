from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelDefinitionPublic(BaseModel):
    id: str
    name: str
    role: str
    environment: str
    version: str
    status: str
    provider: str
    deployment_region: str = ""
    permitted_data_classes: list[str] = Field(default_factory=lambda: ["PUBLIC"])
    supported_task_types: list[str] = Field(default_factory=lambda: ["general_question"])
    allowed_tools: list[str] = Field(default_factory=list)
    retention_policy: str = "UNREVIEWED"
    training_opt_out: bool = False
    evaluation_manifest_id: str | None = None
    policy_version: str = "f7.1"
    priority: int = 100
    enabled: bool = False
    submitted_by: str | None = None
    approved_by: str | None = None

    model_config = {"from_attributes": True}


class PromptTemplatePublic(BaseModel):
    id: str
    name: str
    version: str
    status: str
    mode: str
    submitted_by: str
    approved_by: str | None

    model_config = {"from_attributes": True}


class TestRunRequest(BaseModel):
    prompt_id: str
    input_text: str


class TestRunResponse(BaseModel):
    prompt_id: str
    prompt_name: str
    output_text: str


class ModelDefinitionCreate(BaseModel):
    name: str
    role: str = "answer"
    environment: str = "Staging"
    version: str = "v1"
    provider: Literal["gemini", "google", "groq", "openai", "mock"]
    deployment_region: str = ""
    permitted_data_classes: list[str] = Field(default_factory=lambda: ["PUBLIC"])
    supported_task_types: list[str] = Field(default_factory=lambda: ["general_question"])
    allowed_tools: list[str] = Field(default_factory=list)
    retention_policy: str
    training_opt_out: bool
    evaluation_manifest_id: str
    priority: int = Field(default=100, ge=1, le=10_000)


class ModelDefinitionUpdate(BaseModel):
    deployment_region: str | None = None
    permitted_data_classes: list[str] | None = None
    supported_task_types: list[str] | None = None
    allowed_tools: list[str] | None = None
    retention_policy: str | None = None
    training_opt_out: bool | None = None
    evaluation_manifest_id: str | None = None
    priority: int | None = Field(default=None, ge=1, le=10_000)


class GatewayContext(BaseModel):
    """Server-resolved inputs used to decide whether a deployment is eligible."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    actor_id: str | None = None
    correlation_id: str
    task_type: str
    data_classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    processing_region: str = ""
    jurisdiction: str | None = None
    requested_tools: list[str] = Field(default_factory=list)
    model_transmission_allowed: bool = True
    retrieval_version: str | None = None
    tool_versions: dict[str, str] = Field(default_factory=dict)


class GatewayAttempt(BaseModel):
    deployment_id: str
    provider: str
    model_id: str
    outcome: Literal["completed", "failed"]
    reason_code: str | None = None
    retryable: bool = False


class GatewayResult(BaseModel):
    output_text: str
    run_id: str
    deployment_id: str
    provider: str
    model_id: str
    policy_version: str
    attempts: list[GatewayAttempt]


class ModelRunPublic(BaseModel):
    id: str
    correlation_id: str
    deployment_id: str | None
    provider: str | None
    model_id: str | None
    task_type: str
    data_classification: str
    processing_region: str
    prompt_id: str
    prompt_version: str
    policy_version: str
    retrieval_version: str | None
    tool_versions: dict
    requested_tools: list[str]
    attempts: list[dict]
    status: str
    reason_code: str | None
    output_hash: str | None

    model_config = {"from_attributes": True}
