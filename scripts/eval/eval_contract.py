from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from horus_bench_kit import probe  # noqa: E402
from horus_bench_kit.contract import (  # noqa: E402, F401
    ANNOTATION_KEYWORDS,
    FAILURE_EMPTY,
    FAILURE_NO_SCHEMA,
    FAILURE_NOT_JSON,
    FAILURE_NOT_OBJECT,
    FAILURE_REQUEST,
    FAILURE_RETRIEVAL,
    FAILURE_SCHEMA,
    FAILURE_TRUNCATED,
    LENGTH_FINISH_REASON,
    SUPPORTED_KEYWORDS,
    THINK_TAG,
    check_reply,
    json_type,
    reply_timings,
    schema_violations,
    thought_first,
)
from horus_eval_profile import CONTRACT_KIND as REPORT_KIND  # noqa: E402, F401
from horus_eval_profile import (  # noqa: E402, F401
    CONTRACT_PROFILE,
    ERROR_STAGE_LLM,
    ERROR_STAGE_RETRIEVAL,
    PROBED_CATEGORIES,
    STATUS_NOT_FOUND,
    STATUS_OK,
    WARMUP_QUESTION,
    cited_titles,
    expected_status,
)
from horus_eval_profile import CONTRACT_SCHEMA_VERSION as SCHEMA_VERSION  # noqa: E402, F401


def reply_record(item: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
    return probe.reply_record(item, reply, CONTRACT_PROFILE)


def contract_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return probe.contract_summary(records, CONTRACT_PROFILE)


def probe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item["category"] in PROBED_CATEGORIES]


def build_contract_report(
    *,
    label: str,
    run: dict[str, Any],
    model: dict[str, Any],
    llama_server: dict[str, Any] | None,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return probe.build_contract_report(
        label=label,
        run=run,
        model=model,
        llama_server=llama_server,
        records=records,
        profile=CONTRACT_PROFILE,
    )
