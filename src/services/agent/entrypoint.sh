#!/bin/sh
set -eu
# Download the decision LLM if missing. No-op when the named-volume cache is
# warm; fails loudly if HF_HUB_OFFLINE=1 and the model isn't present.
echo "Bootstrapping agent decision LLM (if missing)..."
python /app/bootstrap_llm.py || { echo "LLM bootstrap failed"; exit 1; }

exec "$@"
