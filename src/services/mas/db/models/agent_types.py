"""Enum of recognized agent types."""

from enum import Enum


class AgentTypes(str, Enum):
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    WRITER = "writer"
    GENERAL = "general"
    # First-class orchestrator agent. Only one MANAGER row exists in the
    # directory — its job is to plan multi-step work, dispatch each step to a
    # specialist, and review each result to decide whether to continue, insert
    # an extra step, or finish. Has no worker process: planning/review happens
    # server-side in MAS with a distinct system prompt that frames the LLM as
    # the orchestrator.
    MANAGER = "manager"
