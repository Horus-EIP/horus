from __future__ import annotations

from collections.abc import Sequence

SEARCH_KNOWLEDGE = "search_knowledge"
EXTRACT_DATA = "extract_data"
ANALYZE_PAYMENTS = "analyze_payments"
CALC = "calc"
DELEGATE = "delegate"

MAX_TOOLS_PER_IDENTITY = 5

TOOL_DEFINITIONS: dict[str, str] = {
    SEARCH_KNOWLEDGE: (
        "search_knowledge(query) – Search the knowledge store for relevant "
        "information. If the user names a file (e.g. report.pdf, notes.txt), include "
        "that exact filename in the query so the store can resolve it by name. "
        "Returns contextual text."
    ),
    EXTRACT_DATA: (
        "extract_data(file_url_or_content, file_type) – Parse and extract data "
        "from a file (PDF, CSV, TXT). Returns extracted text."
    ),
    ANALYZE_PAYMENTS: (
        "analyze_payments(query) – Analyze payment data from the knowledge store. "
        "Returns payment insights and statistics."
    ),
    CALC: (
        "calc(expression) – Evaluate a safe mathematical expression. "
        "Supports +, -, *, /, sqrt, sin, cos, log, etc."
    ),
    DELEGATE: (
        "delegate(to_agent_type, request) – Delegate a sub-task to another "
        "agent type (e.g., 'analyst', 'researcher'). The target agent will "
        "process the request and return a result. Use when a task requires "
        "capabilities outside your expertise."
    ),
}

TOOL_NAMES: tuple[str, ...] = tuple(TOOL_DEFINITIONS)


def tool_definitions_block(names: Sequence[str]) -> str:
    return "\n".join(f"  - {TOOL_DEFINITIONS[name]}" for name in names)


def invalid_tool_selection(names: Sequence[str]) -> str | None:
    unknown = [name for name in names if name not in TOOL_DEFINITIONS]
    if unknown:
        return f"unknown tools {unknown}; the tools are {list(TOOL_NAMES)}"
    repeated = sorted({name for name in names if list(names).count(name) > 1})
    if repeated:
        return f"{repeated} more than once in its tools"
    if len(names) > MAX_TOOLS_PER_IDENTITY:
        return f"{len(names)} tools, more than the {MAX_TOOLS_PER_IDENTITY} an identity may have"
    return None
