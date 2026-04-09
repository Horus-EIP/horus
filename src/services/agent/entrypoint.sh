#!/bin/sh
set -eu
# Dev compose bind-mounts host ./app over /app, which hides models baked in the image.
# Keep a copy under /opt/llm-bundle (populated at docker build) and seed the writable tree once.
BUNDLE="/opt/llm-bundle/Qwen3_instruct_4B"
TARGET="/app/models/Qwen3_instruct_4B"
if [ -d "$BUNDLE" ] && [ ! -f "$TARGET/config.json" ]; then
  echo "Seeding decision LLM from image bundle into $TARGET ..."
  mkdir -p /app/models
  cp -a "$BUNDLE" "$TARGET"
fi
exec "$@"
