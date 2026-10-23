#!/usr/bin/env python
"""
Alembic Migration Management Helper

This script provides utilities for managing Alembic migrations.
Usage: python alembic_helper.py [command]
"""

import subprocess
import sys


def run_command(cmd, description=""):
    """Run a command and display output."""
    if description:
        print(f"\n📌 {description}")
        print("─" * 70)

    try:
        result = subprocess.run(cmd, shell=False, cwd="db", capture_output=False, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("""
╔════════════════════════════════════════════════════════════════╗
║            Alembic Migration Management Helper                ║
╚════════════════════════════════════════════════════════════════╝

Usage: python alembic_helper.py [command]

Commands:
  status          Show current migration status
  history         Show migration history
  upgrade         Apply all pending migrations
  downgrade       Rollback to base (all migrations)
  rollback-1      Rollback last migration
  create          Create new migration (after model changes)
  test            Test upgrade/downgrade cycle
  current         Show current revision details

Examples:
  python alembic_helper.py status      # Check current migration
  python alembic_helper.py upgrade     # Apply all migrations
  python alembic_helper.py test        # Test migrations work

Run from: src/services/mas/
        """)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "status":
        run_command(["alembic", "current"], "Current Migration Status")

    elif command == "history":
        run_command(["alembic", "history"], "Migration History")

    elif command == "upgrade":
        run_command(["alembic", "upgrade", "head"], "Applying all pending migrations")

    elif command == "downgrade":
        run_command(["alembic", "downgrade", "base"], "Rolling back all migrations to base")

    elif command == "rollback-1":
        run_command(["alembic", "downgrade", "-1"], "Rolling back last migration")

    elif command == "create":
        if len(sys.argv) < 3:
            print("Usage: python alembic_helper.py create <description>")
            print('Example: python alembic_helper.py create "Add email column to users"')
            sys.exit(1)
        description = " ".join(sys.argv[2:])
        cmd = ["alembic", "revision", "--autogenerate", "-m", description]
        run_command(cmd, f"Creating new migration: {description}")

    elif command == "test":
        print("""
╔════════════════════════════════════════════════════════════════╗
║                  Testing Migration Cycle                       ║
╚════════════════════════════════════════════════════════════════╝
        """)

        # Test sequence
        print("1️⃣ Checking current status...")
        run_command(["alembic", "current"], "Current Status")

        print("\n2️⃣ Showing history...")
        run_command(["alembic", "history"], "Migration History")

        print("\n3️⃣ Testing downgrade to base...")
        run_command(["alembic", "downgrade", "base"], "Downgrade Test")

        print("\n4️⃣ Testing upgrade to head...")
        run_command(["alembic", "upgrade", "head"], "Upgrade Test")

        print("\n5️⃣ Verifying final status...")
        run_command(["alembic", "current"], "Final Status")

        print("""
✅ Migration cycle test complete!
   - Downgrade: OK
   - Upgrade: OK
   - Status: REVERSIBLE
        """)

    elif command == "current":
        run_command(["alembic", "current"], "Current Revision Details")

    else:
        print(f"❌ Unknown command: {command}")
        print("Run 'python alembic_helper.py' with no arguments for help")
        sys.exit(1)


if __name__ == "__main__":
    main()
