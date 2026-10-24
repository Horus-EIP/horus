from fastapi import APIRouter
from pydantic import BaseModel

from core import ai_mode

router = APIRouter(prefix="/system", tags=["System"])


class AiModeOut(BaseModel):
    mode: str
    model: str | None
    server: str | None
    simulated: bool
    embeddings: str | None
    spacy: str
    monitoring: str

@router.get(
    "/ai",
    response_model=AiModeOut,
    summary="Which AI answers: a language model or the mock",
    description=(
        "Unauthenticated. mode is mock when the model server is llm-mock (its /v1/models "
        "says owned_by horus-mock), local for a real model server, unknown when it could "
        "not be asked. model is the name the server gives, server its owner. embeddings is "
        "mock when MAS's embeddings server is llm-mock, otherwise MAS's embedding model, and "
        "null when that server cannot be asked. spacy and monitoring are on or off, from "
        "HORUS_SPACY and HORUS_MONITORING. No secrets."
    ),
)
def get_ai_mode() -> AiModeOut:
    return AiModeOut(**ai_mode.current().as_dict(), **ai_mode.models_in_use())
