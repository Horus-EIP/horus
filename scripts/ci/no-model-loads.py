from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Line:
    pattern: str
    source: str
    literal: str


LOADS = (
    Line(
        r"Loading sentence-embedding model",
        "src/services/mas/core/embedding_setup.py",
        "Loading sentence-embedding model %s with FastEmbed",
    ),
    Line(
        r"Sentence-embedding model ready",
        "src/services/mas/core/embedding_setup.py",
        "Sentence-embedding model ready: dim=%d",
    ),
    Line(r"Loading LLM on CPU", "src/services/mas/core/llm_setup.py", "Loading LLM on CPU"),
    Line(r"Loading LLM \(lazy", "src/services/mas/core/llm_setup.py", "Loading LLM (lazy"),
    Line(
        r"LLM load with(?:out VRAM cap| max_memory)",
        "src/services/mas/core/llm_setup.py",
        "LLM load without VRAM cap",
    ),
    Line(
        r"LLM load with(?:out VRAM cap| max_memory)",
        "src/services/agent/app/ai_agents/decision_making_agent.py",
        "Agent LLM load with max_memory=%s",
    ),
    Line(
        r"Orchestrator LLM ready", "src/services/mas/core/llm_setup.py", "Orchestrator LLM ready:"
    ),
    Line(
        r"BGE embedder \S+ loaded",
        "src/services/knowledge-store/app/chroma_db/setup.py",
        "BGE embedder %s loaded with",
    ),
    Line(
        r"spaCy model \S+ loaded successfully",
        "src/services/knowledge-store/app/services/content_analyzer.py",
        "spaCy model %s loaded successfully",
    ),
    Line(
        r"pipeline initialized \(",
        "src/services/knowledge-store/app/services/content_analyzer.py",
        "pipeline initialized (%s)",
    ),
    Line(
        r"AGENT_SPACY_PREFER_SM: loading",
        "src/services/agent/app/ai_agents/data_extractor_tool.py",
        "AGENT_SPACY_PREFER_SM: loading en_core_web_sm",
    ),
    Line(
        r"Loading spacy model",
        "src/services/agent/app/ai_agents/data_extractor_tool.py",
        "Loading spacy model en_core_web_trf",
    ),
    Line(
        r"Spacy model loaded successfully",
        "src/services/agent/app/ai_agents/data_extractor_tool.py",
        "Spacy model loaded successfully",
    ),
    Line(
        r"Trying 'en_core_web_sm'",
        "src/services/agent/app/ai_agents/data_extractor_tool.py",
        "Trying 'en_core_web_sm'",
    ),
    Line(
        r"Loading agent decision LLM",
        "src/services/agent/app/ai_agents/decision_making_agent.py",
        "Loading agent decision LLM on CPU",
    ),
    Line(
        r"DecisionMakingAgent model '",
        "src/services/agent/app/ai_agents/decision_making_agent.py",
        "DecisionMakingAgent model '%s' ready",
    ),
    Line(
        r"\[bootstrap_llm\] downloading",
        "src/services/mas/bootstrap_llm.py",
        "[bootstrap_llm] downloading",
    ),
    Line(
        r"\[bootstrap_llm\] downloading",
        "src/services/agent/app/bootstrap_llm.py",
        "[bootstrap_llm] downloading",
    ),
    Line(r"Could not (?:download model|find model in cache_dir)", "", ""),
    Line(r"Fetching \d+ files", "", ""),
)

NO_MODEL = {
    "mas": (
        Line(
            "no embedding model is loaded in MAS",
            "src/services/mas/core/embedding_setup.py",
            "no embedding model is loaded in MAS",
        ),
    ),
    "knowledge_store": (
        Line(
            "no embedding model is loaded in this service",
            "src/services/knowledge-store/app/chroma_db/setup.py",
            "no embedding model is loaded in this service",
        ),
        Line(
            "spaCy is off",
            "src/services/knowledge-store/app/services/content_analyzer.py",
            "spaCy is off (%s=%s)",
        ),
    ),
    "agent": (
        Line(
            "spaCy is off",
            "src/services/agent/app/ai_agents/data_extractor_tool.py",
            "spaCy is off (%s=%s)",
        ),
    ),
}


def problems(logs: Path) -> list[str]:
    found = []
    for service, expected in NO_MODEL.items():
        log = logs / f"{service}.log"
        if not log.is_file():
            found.append(f"{log} is missing")
            continue
        text = log.read_text(encoding="utf-8", errors="replace")
        found += [
            f"{service} never logged '{line.pattern}'"
            for line in expected
            if not re.search(re.escape(line.pattern), text)
        ]
    for log in sorted(logs.glob("*.log")):
        for number, text in enumerate(
            log.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if any(re.search(line.pattern, text) for line in LOADS):
                found.append(f"{log.stem} loaded a model, line {number}: {text.strip()[:200]}")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: no-model-loads.py LOG_FOLDER (one SERVICE.log per service)", file=sys.stderr)
        return 2
    found = problems(Path(argv[0]))
    for problem in found:
        print(f"::error::{problem}")
    if not found:
        print(
            "No service loaded a model; MAS and the knowledge store embed through a server, "
            "and spaCy is off in the knowledge store and the agent."
        )
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
