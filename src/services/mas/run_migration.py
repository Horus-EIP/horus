import os
import sys

from alembic import command
from alembic.config import Config

# Add project root to path so we can import models if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))
# Add src/services/mas to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def run_migrations():
    print(" running migrations...")
    alembic_cfg = Config("db/alembic.ini")
    print(" history:")
    try:
        command.history(alembic_cfg)
    except Exception as e:
        print(f"Error checking history: {e}")

    print(" upgrading head...")
    command.upgrade(alembic_cfg, "head")
    print(" migrations complete!")


if __name__ == "__main__":
    run_migrations()
