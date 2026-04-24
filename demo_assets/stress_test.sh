#!/usr/bin/env bash
# ============================================================================
# Horus Live Demo — Stress Test (Step 9, 18:00-20:00)
# Fires 10 tasks concurrently at the FinCorp-Analyst agent.
#
# Usage:
#   1. Edit BASE_URL and TOKEN below.
#   2. chmod +x stress_test.sh
#   3. ./stress_test.sh
#
# Get your JWT token from the browser (DevTools > Application > Local Storage)
# or from the login API response, then paste it as TOKEN below.
# ============================================================================

set -e

BASE_URL="${BASE_URL:-http://localhost:8000}"
TOKEN="${TOKEN:-5ffd1ba3ec16e2f2712968dbb0fe628b505fbe75fbb99be8fcefbd05f28f9e95E}"
SKILL="financial_analysis"

PROMPTS=(
  "Summarize the key financial risks from the Q4 2025 report."
  "List all reimbursable expense categories over 500 dollars."
  "What is our SOX compliance audit schedule?"
  "Who is the designated Data Protection Officer?"
  "What are the maximum vacation days per year?"
  "Explain our incident response SLA."
  "What is the minimum password length required?"
  "Summarize Q4 2025 operating expenses."
  "Who approves expense reports over 5000 dollars?"
  "What is the notice period for terminating an employee?"
)

echo "Firing ${#PROMPTS[@]} tasks at $BASE_URL ..."
echo ""

for i in "${!PROMPTS[@]}"; do
  n=$((i + 1))
  prompt="${PROMPTS[$i]}"
  (
    curl -sS -X POST "$BASE_URL/api/tasks" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"skill\":\"$SKILL\",\"demand\":\"$prompt\"}" \
      | sed "s/^/[task $n] /"
    echo ""
  ) &
done

wait
echo ""
echo "All ${#PROMPTS[@]} tasks submitted. Watch the Tasks page + Grafana for flow."
