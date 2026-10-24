"""Administrative data export routes."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from auth.auth_tool_functions import PermissionChecker
from auth.permissions import Permission
from core.logger import get_logger
from db.database import get_db
from db.models import Conversations

router = APIRouter(prefix="/admin", tags=["Admin"])
logger = get_logger("admin_routes")


@router.get(
    "/export",
    summary="Export conversation data",
    description=(
        "Download all conversations and their messages as JSON. This data export "
        "remains available when the license is restricted."
    ),
    response_class=JSONResponse,
)
def export_data(
    user: Annotated[dict, Depends(PermissionChecker(Permission.EXPORT_DATA))],
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Export conversations without applying the core-feature license gate."""
    try:
        conversations = (
            db.query(Conversations)
            .options(selectinload(Conversations.messages))
            .order_by(Conversations.id.asc())
            .all()
        )
        export: dict[str, Any] = {
            "exported_at": datetime.now(UTC),
            "conversations": [
                {
                    "id": conversation.id,
                    "owner_username": conversation.owner_username,
                    "name": conversation.name,
                    "created_at": conversation.created_at,
                    "modified_at": conversation.modified_at,
                    "messages": [
                        {
                            "id": message.id,
                            "role": message.role,
                            "content": message.content,
                            "created_at": message.created_at,
                            "agent_id": message.agent_id,
                            "agent_name": message.agent_name,
                            "skill_used": message.skill_used,
                            "sources": message.sources,
                            "ai_provider": message.ai_provider,
                        }
                        for message in sorted(
                            conversation.messages,
                            key=lambda item: (item.created_at, item.id),
                        )
                    ],
                }
                for conversation in conversations
            ],
        }
    except SQLAlchemyError as exc:
        logger.error(f"Failed to export conversation data: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Conversation data could not be exported.",
        ) from exc

    logger.info(
        f"Conversation data exported by {user.get('username', 'unknown')} "
        f"({len(conversations)} conversations)"
    )
    return JSONResponse(
        content=jsonable_encoder(export),
        headers={"Content-Disposition": 'attachment; filename="horus-export.json"'},
    )
