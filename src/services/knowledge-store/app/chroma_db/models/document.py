from pydantic import BaseModel

class DocumentModel(BaseModel):
    id: str
    title: str
    content: str
    size: int