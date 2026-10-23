from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MAS_LAUNCHERS = [
    REPO / "src" / "services" / "mas" / "entrypoint.sh",
    REPO / "scripts" / "dev" / "run-mas.sh",
    REPO / "src" / "services" / "mas" / "README.md",
]


def _uvicorn_commands(path: Path) -> list[list[str]]:
    commands = []
    for line in path.read_text(encoding="utf-8").splitlines():
        tokens = line.split()
        if "uvicorn" in tokens and "main:app" in tokens:
            commands.append(tokens[tokens.index("uvicorn") :])
    return commands


def _option(tokens: list[str], name: str) -> str | None:
    if name not in tokens:
        return None
    return tokens[tokens.index(name) + 1]


@pytest.mark.parametrize("launcher", MAS_LAUNCHERS, ids=lambda p: p.name)
def test_mas_uvicorn_tolerates_a_slow_websocket_pong(launcher):
    commands = _uvicorn_commands(launcher)

    assert commands, f"{launcher} no longer starts uvicorn main:app"
    for tokens in commands:
        assert _option(tokens, "--ws-ping-interval") == "20"
        assert _option(tokens, "--ws-ping-timeout") == "120"
