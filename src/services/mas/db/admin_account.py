import sys

from bcrypt import hashpw, gensalt, checkpw
import hashlib
from auth.permissions import Role
from core.config import settings
from core.hybrid_logging import log_user_action
from core.logger import get_logger, log_error, log_success
from db.database import SessionLocal
from db.models import Users

logger = get_logger("admin_account")

SHIPPED_PASSWORD = "admin"
CREATED = "created"
REPLACED = "replaced"
MATCHES = "matches"
DIFFERS = "differs"
SHIPPED = "shipped"
REFUSED = "refused"
OUTCOME_PREFIX = "admin-account: "
HOW_TO_SET = (
    "Set SUPER_USER_PASSWORD in src/infra/.env to a password of your own "
    "(openssl rand -hex 16 makes one), then run `docker compose up -d mas agent` in src/infra."
)


def usable_password(password: str | None) -> bool:
    return bool(password and password.strip()) and password.strip() != SHIPPED_PASSWORD


def has_password(user: Users, password: str | None) -> bool:
    try:
        password_sha = hashlib.sha256(password.encode('utf-8')).hexdigest()
        return bool(checkpw(password_sha.encode('utf-8') or "", user.hashed_password))
    except (TypeError, ValueError):
        return False


def create_admin(db, username: str, password: str) -> str:
    if not usable_password(password):
        log_error(
            "init_db",
            f"The admin account {username} was not created: SUPER_USER_PASSWORD is empty "
            f"or '{SHIPPED_PASSWORD}'. {HOW_TO_SET}",
        )
        return REFUSED
    
    password_sha = hashlib.sha256(password.encode('utf-8')).hexdigest()
    salt = gensalt()
    admin = Users(
        username=username,
        hashed_password=hashpw(password_sha.encode('utf-8'), salt),
        role=Role.ADMIN.value,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    log_success("init_db", f"Default admin user created: {username}")
    log_user_action(
        "CREATE_ADMIN_USER", user_id=admin.id, details=f"Initial admin user created: {username}"
    )
    return CREATED


def replace_shipped_password(db, admin: Users, password: str) -> str:
    if not usable_password(password):
        log_error(
            "init_db",
            f"The admin account {admin.username} still has the shipped password "
            f"'{SHIPPED_PASSWORD}'. {HOW_TO_SET}",
        )
        return SHIPPED
    
    password_sha = hashlib.sha256(password.encode('utf-8')).hexdigest()
    salt = gensalt()
    admin.hashed_password = hashpw(password_sha.encode('utf-8'), salt)
    db.commit()
    log_success(
        "init_db",
        f"The shipped password of {admin.username} was replaced by SUPER_USER_PASSWORD",
    )
    log_user_action(
        "REPLACE_SHIPPED_ADMIN_PASSWORD",
        user_id=admin.id,
        details=f"The shipped password of {admin.username} was replaced by SUPER_USER_PASSWORD",
    )
    return REPLACED


def ensure_admin_account(db, username: str, password: str) -> str:
    admin = db.query(Users).filter_by(username=username).first()
    if admin is None:
        return create_admin(db, username, password)
    if has_password(admin, SHIPPED_PASSWORD):
        return replace_shipped_password(db, admin, password)
    if has_password(admin, password):
        logger.info(f"Admin user already exists: {username}")
        return MATCHES
    logger.warning(
        f"The password of {username} is not SUPER_USER_PASSWORD from src/infra/.env, so it "
        "was kept. The agent signs in with SUPER_USER_PASSWORD: set it to the password of "
        f"{username}, then run `docker compose up -d agent` in src/infra."
    )
    return DIFFERS


def main() -> int:
    db = SessionLocal()
    try:
        outcome = ensure_admin_account(
            db, settings.super_user_username, settings.super_user_password
        )
    finally:
        db.close()
    print(OUTCOME_PREFIX + outcome, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
