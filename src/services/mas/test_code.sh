#!/bin/bash

export LLM_AUTOINIT=0 && pytest --cov=. --cov-report=html

python -m webbrowser htmlcov/index.html