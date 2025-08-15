"""
settings.py
------------
This module defines configuration settings for the MAS Orchestrator integration.
"""
import os

# When running in Docker, set ORCHESTRATOR_URL to http://mas:8000
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
