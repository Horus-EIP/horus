import json
from unittest.mock import patch

import pytest

from core.llm_setup import ask_llm


def test_ask_llm_returns_mock_when_not_initialized():
    """
    Test that ask_llm returns a mock response when tokenizer or model are None.
    """
    # We patch the module-level variables in core.llm_setup
    with patch("core.llm_setup.tokenizer", None), patch("core.llm_setup.model", None):

        messages = [{"role": "user", "content": "Hello"}]
        response = ask_llm(messages)

        # Parse the response to verify it's valid JSON and has expected structure
        data = json.loads(response)

        assert "next_action" in data
        assert data["next_action"] == "run_agents"
        assert "actions" in data
        assert isinstance(data["actions"], list)
        assert len(data["actions"]) > 0
        assert data["actions"][0]["agent"] == "test_agent_math_fixed"
        assert "final_answer" in data


def test_ask_llm_mock_response_structure():
    """
    Verify the exact structure of the mock response matches what is expected by the agent controller.
    """
    with patch("core.llm_setup.tokenizer", None), patch("core.llm_setup.model", None):

        response = ask_llm([])
        data = json.loads(response)

        expected_response = {
            "next_action": "run_agents",
            "actions": [
                {"agent": "test_agent_math_fixed", "input": "Calculate sqrt(16)"}
            ],
            "final_answer": "",
        }

        assert data == expected_response
