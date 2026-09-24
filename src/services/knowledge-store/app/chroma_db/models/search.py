
from pydantic import BaseModel, Field


class SmartSearchRequest(BaseModel):
    query: str
    n_results: int = Field(default=5, ge=1, le=50)
    categories: list[str] | None = None
    entities: list[str] | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    entity_type: str | None = None
