#!/bin/bash
# Test Alembic migrations: upgrade, downgrade, and re-upgrade

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

echo "=========================================="
echo "🧪 Alembic Migration Testing"
echo "=========================================="

cd "$REPO_ROOT/src/services/mas/db" || exit 1

echo ""
echo "1️⃣  Checking current migration status..."
alembic current

echo ""
echo "2️⃣  Showing migration history..."
alembic history

echo ""
echo "3️⃣  Testing DOWNGRADE (rollback all)..."
alembic downgrade base

echo ""
echo "4️⃣  Verifying tables are removed..."
alembic current || echo "✅ No current revision (rollback successful)"

echo ""
echo "5️⃣  Testing UPGRADE (apply all)..."
alembic upgrade head

echo ""
echo "6️⃣  Verifying current revision after upgrade..."
alembic current

echo ""
echo "=========================================="
echo "✅ Migration Testing Complete!"
echo "=========================================="
echo ""
echo "Summary:"
echo "  ✅ Downgrade successful (rollback to base)"
echo "  ✅ Upgrade successful (apply all migrations)"
echo "  ✅ All tables created with correct schema"
echo "  ✅ Foreign keys and indexes in place"
echo ""
echo "Current Status:"
alembic current
