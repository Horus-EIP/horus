"""
main.py
-------
Entry point for the agent server application.
Starts the FastAPI server to listen for tasks.
"""

import uvicorn

if __name__ == "__main__":
    # Run the agent server on port 8001 (ensure it doesn't conflict with the orchestrator)
    uvicorn.run("agent_server.server:app", host="0.0.0.0", port=8001, reload=True)
