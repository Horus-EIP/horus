#!/bin/bash

# We export LLM_AUTOINIT=0 just in case, though knowledge-store might not use it yet.
# It skips loading heavy models in tests if implemented.
export LLM_AUTOINIT=0 && pytest --cov=app --cov-report=html

# Only try to open browser if we have a display
if [ -n "$DISPLAY" ]; then
    python -m webbrowser htmlcov/index.html
fi
