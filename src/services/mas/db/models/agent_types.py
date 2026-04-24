"""Enum of recognized agent types."""

from enum import Enum


class AgentTypes(str, Enum):
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    WRITER = "writer"
    GENERAL = "general"
