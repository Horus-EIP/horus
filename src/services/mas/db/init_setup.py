import os
import subprocess

from auth.auth_tool_functions import bcrypt_context
from auth.permissions import Role
from core.config import settings
from core.hybrid_logging import log_user_action
from core.logger import get_logger, log_db_operation, log_error, log_success
from db.database import Base, SessionLocal, engine
from db.migrate_critical_logs import create_critical_logs_table
from db.models import Users

logger = get_logger("init_db")


def run_migrations():
    """Run Alembic migrations to ensure schema is up-to-date."""
    try:
        # Get the path to the db directory
        db_path = os.path.dirname(os.path.abspath(__file__))

        log_db_operation("MIGRATION", "alembic", "Running Alembic migrations...")

        import sys

        # Run alembic upgrade head from the db directory using the python executable
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=db_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            log_success("migration", "Alembic migrations completed successfully")
            return True
        else:
            log_error("migration", f"Alembic migrations failed: {result.stderr}")
            return False
    except Exception as e:
        log_error("migration", f"Error running migrations: {str(e)}", exc_info=True)
        return False


def init_db():
    """Initialize database with migrations, default admin user and critical_logs table"""
    log_db_operation("INIT", "database", "Starting database initialization...")

    # First, run Alembic migrations to create/update schema
    run_migrations()

    # Check what tables exist
    db = SessionLocal()
    try:
        from sqlalchemy import inspect

        inspector = inspect(engine)
        tables = inspector.get_table_names()
        logger.info(f"Tables found after migration: {tables}")

        # If only alembic_version exists, or no tables, something is wrong if we expect users table
        if "users" not in tables:
            logger.warning(
                "Users table missing after migration! Attempting fallback creation..."
            )
            try:
                Base.metadata.create_all(bind=engine)
                logger.info("Database tables created via SQLAlchemy fallback")
                # Refresh table list
                tables = inspector.get_table_names()
                logger.info(f"Tables after fallback: {tables}")
            except Exception as e:
                log_error(
                    "init_db",
                    f"Failed to create tables via SQLAlchemy: {str(e)}",
                    exc_info=True,
                )
    except Exception as e:
        logger.debug(f"Could not check table status: {str(e)}")
    finally:
        db.close()

    if not create_critical_logs_table():
        log_error("init_db", "Failed to create critical_logs table")

    db = SessionLocal()
    try:
        admin_user = (
            db.query(Users).filter_by(username=settings.super_user_username).first()
        )

        if not admin_user:
            admin_user = Users(
                username=settings.super_user_username,
                hashed_password=bcrypt_context.hash(settings.super_user_password),
                role=Role.ADMIN.value,
            )
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)

            log_success(
                "init_db", f"Default admin user created: {settings.super_user_username}"
            )

            log_user_action(
                "CREATE_ADMIN_USER",
                user_id=admin_user.id,
                details=f"Initial admin user created: {settings.super_user_username}",
            )
        else:
            logger.info(f"Admin user already exists: {admin_user.username}")

        # Default agents are no longer DB-seeded — the agent worker registers
        # them itself at startup as real, heartbeating identities (see
        # services/agent/app/agent_server/profiles.py). Keeping a seed here
        # would just leave inactive placeholders cluttering the UI.

        log_success("init_db", "Database initialization completed successfully")

    except Exception as e:
        log_error("init_db", f"Database initialization failed: {str(e)}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()
