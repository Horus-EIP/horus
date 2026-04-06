from pydantic import BaseModel, Field
from typing import Optional, List

class SmartSearchRequest(BaseModel):
    query: str
    n_results: int = Field(default=5, ge=1, le=50)
    categories: Optional[List[str]] = None
    entities: Optional[List[str]] = None
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    entity_type: Optional[str] = None
