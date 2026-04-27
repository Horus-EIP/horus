#!/usr/bin/env bash
# ============================================================================
# Horus Live Demo - Stress Test
#
# Fires N tasks concurrently against the orchestrator. Tasks are routed
# through the structured `/tasks/new_task/` endpoint with the explicit
# any_with_skill mode (see Update_Greenlight 3.2).
#
# The script logs in for a fresh JWT, creates a dedicated conversation,
# then dispatches every prompt in parallel.
#
# Usage:
#   chmod +x stress_test.sh
#   ./stress_test.sh
#
# Override defaults via env:
#   BASE_URL=http://localhost:8000 \
#   USERNAME=admin PASSWORD=admin \
#   SKILL=financial_analysis \
#   ./stress_test.sh
# ============================================================================

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
USERNAME="${USERNAME:-admin}"
PASSWORD="${PASSWORD:-admin}"
SKILL="${SKILL:-financial_analysis}"
MODE="${MODE:-any_with_skill}"  # auto | any_with_skill | specific_agent
AGENT_ID="${AGENT_ID:-}"        # required when MODE=specific_agent
CONV_NAME="${CONV_NAME:-Stress Test $(date +%Y-%m-%d_%H:%M:%S)}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2; exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required (apt install jq / brew install jq)" >&2; exit 1
fi

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

# 1) Login -> JWT token
echo "[1/3] Logging in as ${USERNAME} -> ${BASE_URL}/auth/token"
TOKEN=$(curl -sS -X POST "${BASE_URL}/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=${USERNAME}&password=${PASSWORD}" \
  | jq -r '.access_token // empty')

if [[ -z "${TOKEN}" || "${TOKEN}" == "null" ]]; then
  echo "Login failed - check USERNAME/PASSWORD or BASE_URL." >&2
  exit 1
fi

# 2) Create a dedicated conversation so the chat UI can group these tasks
echo "[2/3] Creating conversation '${CONV_NAME}'"
CONV_ID=$(curl -sS -X POST "${BASE_URL}/conversations/create-conversation" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg name "${CONV_NAME}" '{name: $name}')" \
  | jq -r '.conversation_id // empty')

if [[ -z "${CONV_ID}" || "${CONV_ID}" == "null" ]]; then
  echo "Conversation creation failed." >&2
  exit 1
fi

# 3) Fan out the prompts in parallel
echo "[3/3] Dispatching ${#PROMPTS[@]} tasks (mode=${MODE}, skill=${SKILL}, conversation_id=${CONV_ID})"
echo ""

build_payload() {
  local prompt="$1"
  jq -n \
    --arg demand "${prompt}" \
    --argjson conv_id "${CONV_ID}" \
    --arg skill "${SKILL}" \
    --arg mode "${MODE}" \
    --arg agent_id "${AGENT_ID}" \
    '{
       demand: $demand,
       conversation_id: $conv_id,
       skills_required: [$skill],
       mode: $mode
     }
     + (if $agent_id == "" then {} else {agent_id: $agent_id} end)'
}

for i in "${!PROMPTS[@]}"; do
  n=$((i + 1))
  prompt="${PROMPTS[$i]}"
  payload="$(build_payload "${prompt}")"
  (
    response=$(curl -sS -w "\n%{http_code}" -X POST \
      "${BASE_URL}/tasks/new_task/" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d "${payload}")
    body=$(echo "${response}" | sed '$d')
    code=$(echo "${response}" | tail -n1)
    echo "[task ${n}] HTTP ${code} -- ${body}"
  ) &
done

wait
echo ""
echo "All ${#PROMPTS[@]} tasks submitted to conversation ${CONV_ID}."
echo "Watch progress at:"
echo "  - UI:      http://localhost:3000/chat?conversation=${CONV_ID}"
echo "  - Grafana: http://localhost:3301"
