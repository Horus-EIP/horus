#!/usr/bin/env python3
"""Quality benchmark for Horus.

Measures *what the system returns*, not just *how fast*. Two assertions per query:

1. **Keyword match** — does the retrieved chunk (or the final agent answer) contain
   the expected keywords for the query?
2. **Output assertion** — does the agent answer satisfy a predicate (e.g. "contains
   a number > 0", "matches regex", "JSON parses").

Produces a JSON file under ``scripts/perf/results-archive/`` named
``quality-<label>-<YYYYMMDD>.json`` so before/after pairs are obvious in git.

Usage::

    python scripts/perf/quality-benchmark.py --label baseline
    python scripts/perf/quality-benchmark.py --label after-chunk-tuning

Both runs hit the same query set; diff the two JSON files for the optimization story.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# --------------------------------------------------------------------------- #
# Query set
# --------------------------------------------------------------------------- #


@dataclass
class QueryCase:
    """One test case: a query + the assertions we run on the response."""

    query: str
    expected_keywords: list[str]
    # Optional: free-form predicate on the final answer string.
    # Receives (answer:str) -> bool. Default = always True (skipped).
    answer_predicate: Callable[[str], bool] = field(default=lambda _a: True)
    answer_predicate_name: str = "none"


# These mirror the mock corpus in ``demo_assets/``. Edit / extend as you add
# canonical questions the team agrees Horus must answer well.
DEFAULT_QUERIES: list[QueryCase] = [
    QueryCase(
        query="What was Q4 2025 revenue?",
        expected_keywords=["revenue", "Q4", "2025"],
        answer_predicate=lambda a: bool(re.search(r"\$?\s?\d", a)),
        answer_predicate_name="answer_contains_number",
    ),
    QueryCase(
        query="What is the expense reimbursement policy for travel?",
        expected_keywords=["expense", "travel", "reimbursement"],
    ),
    QueryCase(
        query="How many vacation days does an employee get per year?",
        expected_keywords=["vacation", "days", "employee"],
        answer_predicate=lambda a: bool(re.search(r"\d+\s*(?:days?|jours?)", a, re.I)),
        answer_predicate_name="answer_contains_day_count",
    ),
    QueryCase(
        query="What are the data retention requirements?",
        expected_keywords=["data", "retention"],
    ),
    QueryCase(
        query="Who is allowed to approve a wire transfer over $50,000?",
        expected_keywords=["approve", "wire", "transfer"],
    ),
    QueryCase(
        query="What security controls protect the production environment?",
        expected_keywords=["security", "production"],
    ),
    QueryCase(
        query="What is the password complexity requirement?",
        expected_keywords=["password", "complexity"],
        answer_predicate=lambda a: bool(
            re.search(r"\d+\s*(?:chars?|characters?|caractères?)", a, re.I)
        ),
        answer_predicate_name="answer_contains_char_count",
    ),
    QueryCase(
        query="Which compliance frameworks apply to customer data?",
        expected_keywords=["compliance", "data"],
    ),
]


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def keyword_match_precision(text: str, keywords: list[str]) -> float:
    """Fraction of expected keywords found in ``text`` (case-insensitive)."""
    if not keywords:
        return 1.0
    needle = text.lower()
    hits = sum(1 for k in keywords if k.lower() in needle)
    return hits / len(keywords)


# --------------------------------------------------------------------------- #
# Backend calls
# --------------------------------------------------------------------------- #


def call_knowledge_store(
    client: httpx.Client,
    ks_url: str,
    query: str,
    top_k: int = 5,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Call the Knowledge Store search endpoint and return the parsed payload.

    The endpoint shape mirrors ``src/services/knowledge-store/app/api/routes/store.py``
    (``GET /`` with query parameters).
    """
    t0 = time.perf_counter()
    resp = client.get(
        ks_url.rstrip("/") + "/",
        params={"query": query, "n_results": top_k},
        timeout=timeout,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    resp.raise_for_status()
    data = resp.json()
    return {"raw": data, "elapsed_ms": elapsed_ms}


def call_mas_chat(
    client: httpx.Client,
    mas_url: str,
    token: str,
    conversation_id: int,
    query: str,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Optionally call MAS to get the full agent answer.

    Skipped when ``--no-chat`` is passed; many benchmark runs only need to exercise
    retrieval (cheap) and skip the LLM (expensive).
    """
    t0 = time.perf_counter()
    resp = client.post(
        mas_url.rstrip("/") + "/tasks/new_task/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conversation_id,
            "content": query,
        },
        timeout=timeout,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    resp.raise_for_status()
    data = resp.json()
    return {"raw": data, "elapsed_ms": elapsed_ms}


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def run(args: argparse.Namespace) -> dict[str, Any]:
    queries = DEFAULT_QUERIES
    results: list[dict[str, Any]] = []
    client = httpx.Client()

    for qc in queries:
        case: dict[str, Any] = {
            "query": qc.query,
            "expected_keywords": qc.expected_keywords,
            "answer_predicate": qc.answer_predicate_name,
        }
        try:
            ks = call_knowledge_store(client, args.ks_url, qc.query, args.top_k)
            retrieved_text = json.dumps(ks["raw"])
            case["retrieval_latency_ms"] = round(ks["elapsed_ms"], 2)
            case["keyword_match_precision_retrieval"] = round(
                keyword_match_precision(retrieved_text, qc.expected_keywords), 4
            )
            case["retrieval_ok"] = True
        except Exception as e:  # noqa: BLE001
            case["retrieval_ok"] = False
            case["retrieval_error"] = repr(e)
            case["keyword_match_precision_retrieval"] = 0.0
            case["retrieval_latency_ms"] = None

        if not args.no_chat and args.token and args.conversation_id:
            try:
                chat = call_mas_chat(
                    client,
                    args.mas_url,
                    args.token,
                    args.conversation_id,
                    qc.query,
                )
                answer = str(chat["raw"].get("response") or chat["raw"])
                case["answer_latency_ms"] = round(chat["elapsed_ms"], 2)
                case["keyword_match_precision_answer"] = round(
                    keyword_match_precision(answer, qc.expected_keywords), 4
                )
                case["answer_predicate_passed"] = bool(qc.answer_predicate(answer))
                case["answer_ok"] = True
                case["answer_snippet"] = answer[:200]
            except Exception as e:  # noqa: BLE001
                case["answer_ok"] = False
                case["answer_error"] = repr(e)
                case["keyword_match_precision_answer"] = 0.0
                case["answer_predicate_passed"] = False
        else:
            case["answer_ok"] = None  # skipped

        results.append(case)

    # Aggregates
    def mean(xs: list[float]) -> float:
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    retrieval_precisions = [c.get("keyword_match_precision_retrieval", 0.0) for c in results]
    answer_precisions = [
        c.get("keyword_match_precision_answer") for c in results if c.get("answer_ok")
    ]
    predicate_pass_rate = (
        sum(1 for c in results if c.get("answer_predicate_passed"))
        / max(1, sum(1 for c in results if c.get("answer_ok")))
        if any(c.get("answer_ok") for c in results)
        else None
    )

    summary = {
        "label": args.label,
        "timestamp": datetime.now(UTC).isoformat(),
        "ks_url": args.ks_url,
        "mas_url": args.mas_url,
        "top_k": args.top_k,
        "num_queries": len(results),
        "metrics": {
            "keyword_match_precision_retrieval_mean": mean(retrieval_precisions),
            "keyword_match_precision_answer_mean": mean(answer_precisions),
            "answer_predicate_pass_rate": predicate_pass_rate,
            "retrieval_latency_ms_mean": mean([c.get("retrieval_latency_ms") for c in results]),
        },
        "cases": results,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ks-url",
        default=os.environ.get("KS_URL", "http://localhost:8080"),
        help="Knowledge Store base URL",
    )
    parser.add_argument(
        "--mas-url", default=os.environ.get("MAS_URL", "http://localhost:8000"), help="MAS base URL"
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("MAS_TOKEN", ""),
        help="JWT bearer token for MAS (skip MAS calls if empty)",
    )
    parser.add_argument(
        "--conversation-id",
        type=int,
        default=int(os.environ.get("CONVERSATION_ID", "0")),
        help="Existing conversation ID for the chat endpoint",
    )
    parser.add_argument(
        "--top-k", type=int, default=5, help="Top-k chunks to retrieve from the Knowledge Store"
    )
    parser.add_argument(
        "--label", required=True, help="Run label, e.g. 'baseline' or 'after-chunk-tuning'"
    )
    parser.add_argument(
        "--no-chat",
        action="store_true",
        help="Skip the MAS chat call; only exercise retrieval (faster)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).parent / "results-archive"),
        help="Directory to write the JSON result into",
    )
    args = parser.parse_args()

    summary = run(args)

    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    out_path = Path(args.out_dir) / f"quality-{args.label}-{stamp}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print(json.dumps(summary["metrics"], indent=2))
    print(f"\nWrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
