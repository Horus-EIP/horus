"""
Delegation Handler
------------------
Manages the delegation protocol for ReAct agents. Allows an agent to delegate
part of its work to another agent mid-task, tracking delegation chains to
prevent infinite loops.

Flow:
    1. ReAct agent calls delegate(to_agent_type, request, data)
    2. DelegationHandler builds the delegation request
    3. Request is sent to MAS /rabbitmq/delegate endpoint
    4. MAS routes to target agent and waits for result
    5. Result is returned to the calling ReAct loop
"""

from __future__ import annotations

import logging
import requests
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_DEPTH = 5
DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass
class DelegationRecord:
    """Tracks a single delegation call for audit and debugging."""

    delegation_id: str
    to_agent_type: str
    request: str
    status: str = "pending"
    result: Optional[str] = None
    error: Optional[str] = None
    target_agent_id: Optional[str] = None


@dataclass
class DelegationChainTracker:
    """
    Tracks the delegation chain to enforce depth limits and prevent loops.

    Each agent that participates in a delegation is added to the chain.
    If the same agent appears twice, a loop is detected.
    """

    chain: List[str] = field(default_factory=list)
    max_depth: int = DEFAULT_MAX_DEPTH

    def can_delegate(self) -> bool:
        return len(self.chain) < self.max_depth

    def has_loop(self, agent_id: str) -> bool:
        return agent_id in self.chain

    def add(self, agent_id: str) -> None:
        self.chain.append(agent_id)

    @property
    def depth(self) -> int:
        return len(self.chain)


class DelegationHandler:
    """
    Handles delegation requests from a ReAct agent to other agents via the
    MAS orchestrator.

    Usage in the ReAct loop:
        handler = DelegationHandler(agent_id, orchestrator_url, headers)
        result = handler.delegate("analyst", "Calculate totals", {"data": ...})
    """

    def __init__(
        self,
        agent_id: str,
        orchestrator_url: str,
        auth_headers_fn=None,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.agent_id = agent_id
        self.orchestrator_url = orchestrator_url
        self.auth_headers_fn = auth_headers_fn or (lambda: {})
        self.max_depth = max_depth
        self.timeout_seconds = timeout_seconds
        self.chain_tracker = DelegationChainTracker(max_depth=max_depth)
        self.history: List[DelegationRecord] = []

    def delegate(
        self,
        to_agent_type: str,
        request: str,
        data: Optional[Dict[str, Any]] = None,
        conversation_id: str = "",
        delegation_context: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Delegate work to another agent type.

        Args:
            delegation_context: Accumulated context entries from earlier
                agents in the chain.  Each entry is a dict with keys
                ``agent_id``, ``request``, and ``data``.

        Returns:
            Dict with keys: status, result (or error).
        """
        if not self.chain_tracker.can_delegate():
            error_msg = (
                f"Maximum delegation depth ({self.max_depth}) reached. "
                f"Current chain: {self.chain_tracker.chain}"
            )
            logger.warning(error_msg)
            return {"status": "error", "error": error_msg}

        record = DelegationRecord(
            delegation_id="",
            to_agent_type=to_agent_type,
            request=request,
        )

        context_chain = list(delegation_context or [])
        context_chain.append({
            "agent_id": self.agent_id,
            "request": request,
            "data": data or {},
        })

        url = f"{self.orchestrator_url}/rabbitmq/delegate"
        payload = {
            "sender_agent_id": self.agent_id,
            "to_agent_type": to_agent_type,
            "request": request,
            "data": data or {},
            "conversation_id": conversation_id,
            "delegation_chain": self.chain_tracker.chain,
            "delegation_context": context_chain,
            "timeout_seconds": self.timeout_seconds,
        }

        try:
            headers = self.auth_headers_fn()
            headers["Content-Type"] = "application/json"

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds + 5,
            )

            if response.status_code != 200:
                error_msg = f"Delegation request failed: {response.status_code} - {response.text}"
                logger.error(error_msg)
                record.status = "error"
                record.error = error_msg
                self.history.append(record)
                return {"status": "error", "error": error_msg}

            result_data = response.json()
            record.delegation_id = result_data.get("delegation_id", "")
            record.target_agent_id = result_data.get("agent_id")

            if result_data.get("status") == "completed":
                record.status = "completed"
                record.result = result_data.get("result", "")
                self.chain_tracker.add(self.agent_id)
                self.history.append(record)
                logger.info(
                    f"Delegation to {to_agent_type} completed successfully: "
                    f"{record.result[:100]}..."
                )
                return {
                    "status": "completed",
                    "result": record.result,
                    "agent_id": record.target_agent_id,
                    "delegation_id": record.delegation_id,
                }

            error_msg = result_data.get("error", "Delegation failed")
            record.status = result_data.get("status", "error")
            record.error = error_msg
            self.history.append(record)
            logger.warning(f"Delegation to {to_agent_type} failed: {error_msg}")
            return {"status": record.status, "error": error_msg}

        except requests.Timeout:
            error_msg = f"Delegation to {to_agent_type} timed out after {self.timeout_seconds}s"
            logger.warning(error_msg)
            record.status = "timeout"
            record.error = error_msg
            self.history.append(record)
            return {"status": "timeout", "error": error_msg}

        except Exception as exc:
            error_msg = f"Delegation failed with exception: {exc}"
            logger.error(error_msg, exc_info=True)
            record.status = "error"
            record.error = error_msg
            self.history.append(record)
            return {"status": "error", "error": error_msg}

    def get_history(self) -> List[Dict[str, Any]]:
        return [
            {
                "delegation_id": r.delegation_id,
                "to_agent_type": r.to_agent_type,
                "request": r.request,
                "status": r.status,
                "result": r.result,
                "error": r.error,
                "target_agent_id": r.target_agent_id,
            }
            for r in self.history
        ]

    def reset_chain(self) -> None:
        """Reset the chain tracker for a new top-level task."""
        self.chain_tracker = DelegationChainTracker(max_depth=self.max_depth)
