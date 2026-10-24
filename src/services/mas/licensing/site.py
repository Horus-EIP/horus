"""Database helpers for installation-wide licence configuration."""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from licensing.models import GlobalConfig


def get_or_create_site_id(db: Session) -> str:
    """Return the installation UUID, creating it once and committing it.

    The singleton primary key and the unique ``site_id`` constraint make this
    safe when two application workers initialize the configuration together.
    If another worker wins the insert race, read and return its persisted value.
    """
    config = db.query(GlobalConfig).filter_by(id=1).first()
    if config is not None:
        return config.site_id

    site_id = str(uuid.uuid4())
    db.add(GlobalConfig(id=1, site_id=site_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        config = db.query(GlobalConfig).filter_by(id=1).first()
        if config is None:
            raise
        return config.site_id
    return site_id
