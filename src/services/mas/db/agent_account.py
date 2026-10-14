import sys

from auth.auth_tool_functions import bcrypt_context
from auth.permissions import Role
from core.config import settings
from core.hybrid_logging import log_user_action
from core.logger import get_logger, log_error, log_success
from db.admin_account import has_password
from db.database import SessionLocal
from db.models import Users

logger = get_logger("agent_account")

SHIPPED_PASSWORD = "agent"
CREATED = "created"
REPLACED = "replaced"
MATCHES = "matches"
DIFFERS = "differs"
SHIPPED = "shipped"
REFUSED = "refused"
OUTCOME_PREFIX = "agent-account: "
HOW_TO_SET = (
    "Set SUPER_AGENT_PASSWORD in src/infra/.env to a password of your own "
    "(openssl rand -hex 16 makes one), then run `docker compose up -d mas agent` in src/infra."
)

def usable_agent_password(password: str | None) -> bool:
    return bool(password and password.strip()) and password.strip() != SHIPPED_PASSWORD

def create_agent(db, username: str, password: str) -> str:
    if not usable_agent_password(password):
        log_error(
            "init_db",
            f"The agent account {username} was not created: SUPER_AGENT_PASSWORD is empty "
            f"or '{SHIPPED_PASSWORD}'. {HOW_TO_SET}",
        )
        return REFUSED
    agent = Users(
        username=username,
        hashed_password=bcrypt_context.hash(password),
        role=Role.AGENT.value,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    log_success("init_db", f"Default agent user created: {username}")
    log_user_action(
        "CREATE_AGENT_USER", user_id=agent.id, details=f"Initial agent user created: {username}"
    )
    return CREATED

def replace_shipped_agent_password(db, agent: Users, password: str) -> str:
    if not usable_agent_password(password):
        log_error(
            "init_db",
            f"The agent account {agent.username} still has the shipped password "
            f"'{SHIPPED_PASSWORD}'. {HOW_TO_SET}",
        )
        return SHIPPED
    agent.hashed_password = bcrypt_context.hash(password)
    db.commit()
    log_success("init_db", f"The shipped password of {agent.username} was replaced")
    log_user_action(
        "REPLACE_SHIPPED_AGENT_PASSWORD",
        user_id=agent.id,
        details=f"The shipped password of {agent.username} was replaced",
    )
    return REPLACED

def ensure_agent_account(db, username: str, password: str) -> str:
    agent = db.query(Users).filter_by(username=username).first()
    if agent is None:
        return create_agent(db, username, password)
    if agent.role != Role.AGENT.value:
        agent.role = Role.AGENT.value
        db.commit()
    if has_password(agent, SHIPPED_PASSWORD):
        return replace_shipped_agent_password(db, agent, password)
    if has_password(agent, password):
        logger.info(f"Agent account already exists: {username}")
        return MATCHES
    logger.warning(
        f"The password of {username} is not SUPER_AGENT_PASSWORD from src/infra/.env, so it "
        "was kept. The agent signs in with SUPER_AGENT_PASSWORD: set it to the password of "
        f"{username}, then run `docker compose up -d agent` in src/infra."
    )
    return DIFFERS

def main() -> int:
    db = SessionLocal()
    try:
        outcome = ensure_agent_account(
            db, settings.super_agent_username, settings.super_agent_password
        )
    finally:
        db.close()
    print(OUTCOME_PREFIX + outcome, flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
