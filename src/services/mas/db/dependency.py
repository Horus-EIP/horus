from typing import Annotated

from db.database import SessionLocal, get_db
from fastapi import Depends
from sqlalchemy.orm import Session

db_dependency = Annotated[Session, Depends(get_db)]

__all__ = ["db_dependency", "get_db", "SessionLocal"]
