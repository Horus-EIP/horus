from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from db.database import SessionLocal, get_db

db_dependency = Annotated[Session, Depends(get_db)]

__all__ = ["db_dependency", "get_db", "SessionLocal"]
