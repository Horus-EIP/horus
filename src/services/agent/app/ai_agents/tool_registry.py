"""
tool_registry.py
-----------------
Defines a minimal tool protocol and an in-memory registry to expose utility tools
to the pipeline via a stable `run(name, payload)` API.
"""

from __future__ import annotations

from typing import Dict, Any, Protocol, Optional, Iterable
import logging

logger = logging.getLogger(__name__)


class Tool(Protocol):
    name: str

    def run(self, payload: Dict[str, Any]) -> str:
        ...


class ToolRegistry:
    def __init__(self):
        """Initialize the tool registry."""
        self._tools: Dict[str, Tool] = {}
        self._aliases: Dict[str, str] = {}
        logger.info("ToolRegistry initialized")

    def register(self, tool: Tool, *, aliases: Optional[Iterable[str]] = None) -> None:
        """
        Register a new tool.

        Args:
            tool: The tool instance (must implement Tool protocol).
            aliases: Optional list of alternate names for the tool.
        """
        self._tools[tool.name] = tool
        if aliases:
            for alias in aliases:
                self._aliases[alias] = tool.name
        logger.debug(f"Registered tool '{tool.name}' with aliases={aliases}")

    def get(self, name: str) -> Optional[Tool]:
        """
        Retrieve a tool by name or alias.
        
        Args:
            name: tool name or alias
            
        Returns:
            The tool instance or None.
        """
        if name in self._tools:
            return self._tools[name]
        
        resolved_name = self._aliases.get(name)
        if resolved_name and resolved_name in self._tools:
            return self._tools[resolved_name]
            
        logger.warning(f"Tool '{name}' not found")
        return None

    def resolve(self, name: str) -> Optional[Tool]:
        if name in self._tools:
            return self._tools[name]
        canonical = self._aliases.get(name)
        if canonical:
            return self._tools.get(canonical)
        return None

    def has(self, name: str) -> bool:
        return self.resolve(name) is not None

    def run(self, name: str, payload: Dict[str, Any]) -> str:
        tool = self.resolve(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        return tool.run(payload)


