from pydantic import BaseModel, Field


class ChunkCorrection(BaseModel):
    chunk_id: str
    corrected_content: str = Field(min_length=1, max_length=20_000)
    reason: str = Field(min_length=1, max_length=500)


class DocumentReviewRequest(BaseModel):
    approve: bool
    reason: str = Field(min_length=1, max_length=500)
    corrections: list[ChunkCorrection] = Field(default_factory=list, max_length=500)
