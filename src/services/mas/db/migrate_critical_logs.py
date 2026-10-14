"""
Migration pour ajouter la table critical_logs
"""

from core.logger import log_db_operation, log_error, log_success
from db.database import engine
from sqlalchemy import text


def create_critical_logs_table():
    """Crée la table critical_logs si elle n'existe pas"""

    create_table_sql = """
    CREATE TABLE IF NOT EXISTS critical_logs (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        level VARCHAR(20) NOT NULL,
        category VARCHAR(20) NOT NULL,
        component VARCHAR(50) NOT NULL,
        user_id INTEGER,
        operation VARCHAR(100) NOT NULL,
        details TEXT,
        ip_address VARCHAR(45),
        user_agent TEXT
    );
    """

    create_indexes_sql = [
        "CREATE INDEX IF NOT EXISTS idx_critical_logs_timestamp ON critical_logs(timestamp);",
        "CREATE INDEX IF NOT EXISTS idx_critical_logs_category ON critical_logs(category);",
        "CREATE INDEX IF NOT EXISTS idx_critical_logs_user ON critical_logs(user_id);",
        "CREATE INDEX IF NOT EXISTS idx_critical_logs_component ON critical_logs(component);",
        "CREATE INDEX IF NOT EXISTS idx_critical_logs_operation ON critical_logs(operation);",
    ]

    try:
        log_db_operation(
            "INIT", "critical_logs", "Creating critical_logs table and indexes"
        )

        with engine.connect() as conn:

            conn.execute(text(create_table_sql))

            for index_sql in create_indexes_sql:
                conn.execute(text(index_sql))

            conn.commit()

        log_success("migration", "critical_logs table and indexes created successfully")
        return True

    except Exception as e:
        log_error(
            "migration",
            f"Failed to create critical_logs table: {str(e)}",
            exc_info=True,
        )
        return False


if __name__ == "__main__":
    from core.logger import get_logger

    logger = get_logger("migration")

    logger.info("Creating critical_logs table...")
    if create_critical_logs_table():
        logger.info("Migration completed successfully!")
    else:
        logger.error("Migration failed!")
