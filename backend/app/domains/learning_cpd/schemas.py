from pydantic import BaseModel


class SyllabusPathwayPublic(BaseModel):
    id: str
    body: str
    qualification: str
    module: str
    topic: str
    learning_outcome: str

    model_config = {"from_attributes": True}


class TopicMapNodePublic(BaseModel):
    id: str
    topic: str
    prerequisites: str
    standards_summary: str

    model_config = {"from_attributes": True}
