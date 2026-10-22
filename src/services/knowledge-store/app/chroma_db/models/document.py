from datetime import datetime

from pydantic import BaseModel, Field


class EntityModel(BaseModel):
    people: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    amounts: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)


class DocumentModel(BaseModel):
    id: str
    title: str
    content: str
    size: int
    auto_category: str = ""
    auto_type: str = ""
    auto_summary: str = ""
    entities: EntityModel = Field(default_factory=EntityModel)
    topics: list[str] = Field(default_factory=list)
    confidence_score: float = 0.0
    analyzed_at: datetime | None = None
    user_category: str | None = None
    user_tags: list[str] = Field(default_factory=list)
    chunk_count: int = 0
    is_chunk: bool = False
    parent_id: str | None = None
    chunk_index: int | None = None
