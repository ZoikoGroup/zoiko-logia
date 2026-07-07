from pydantic import BaseModel


class ModelDefinitionPublic(BaseModel):
    id: str
    name: str
    role: str
    environment: str
    version: str
    status: str
    provider: str

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
