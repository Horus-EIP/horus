import os
import time

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.logger import get_logger, log_error, log_success
from db.pool_monitor import attach_pool_monitor

logger = get_logger("database")

DB_HOST = settings.db_host
DB_NAME = settings.postgres_db
DB_USER = settings.postgres_user
DB_PASSWORD = settings.postgres_password
DB_PORT = settings.db_port

URL_DATABASE = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Allow override for testing via environment variable
if os.getenv("TEST_MODE") == "1":
    URL_DATABASE = "sqlite:///:memory:"
    try:
        engine = create_engine(
            URL_DATABASE,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        log_success("database", "Database engine initialized successfully (in-memory)")
    except Exception as e:
        log_error(
            "database",
            f"Failed to initialize in-memory database engine: {str(e)}",
            exc_info=True,
        )
        raise
else:
    try:
        engine = create_engine(
            URL_DATABASE,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
        )
        log_success(
            "database", f"Database engine initialized successfully for {DB_NAME}"
        )
    except Exception as e:
        log_error(
            "database",
            f"Failed to initialize database engine for {DB_NAME}: {str(e)}",
            exc_info=True,
        )
        raise

# attach_pool_monitor(engine) - skipped for sqlite/testing or add condition
if os.getenv("TEST_MODE") != "1":
    attach_pool_monitor(engine)

# In test mode, we might want to skip these listeners or adapt them
if os.getenv("TEST_MODE") != "1":

    @event.listens_for(engine, "before_cursor_execute")
    def receive_before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        conn.info.setdefault("query_start_time", []).append(time.time())

    @event.listens_for(engine, "after_cursor_execute")
    def receive_after_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        start_time = conn.info["query_start_time"].pop(-1)
        total = time.time() - start_time

        if total > 0.5:
            logger.warning(f"Slow Query ({total:.4f}s): {statement[:100]}...")
        else:
            logger.debug(f"Query executed in {total:.4f}s")


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    logger.debug("Database session created")
    try:
        yield db
        logger.debug("Database session completed successfully")
    except Exception as e:
        logger.error(f"Database session error: {str(e)}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()
        logger.debug("Database session closed")
