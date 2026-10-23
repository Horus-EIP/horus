from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from horus_bench_kit import candidates as kit  # noqa: E402
from horus_bench_kit import llama_server  # noqa: E402
from horus_bench_kit.candidates import (  # noqa: E402, F401
    REPORT_KIND,
    SCHEMA_VERSION,
    SERVING_STEPS,
    STEPS,
    SUMMARY_LABEL,
    Variant,
    bench_headline,
    bench_speeds,
    build_number,
    download_url,
    written_report,
)
from horus_bench_kit.llama_bench import (  # noqa: E402, F401
    CONTAINER_MODELS_DIR,
    MODELS_DIR_PLACEHOLDER,
)
from horus_bench_kit.llama_server import (  # noqa: E402, F401
    REASONING_MODES,
    parse_container_env,
    parse_container_inspect,
    parse_memory_limit,
    parse_process_memory,
    server_args,
)
from horus_profile import (  # noqa: E402, F401
    AGENT_CONTAINER,
    CANDIDATE_CONTAINER,
    CANDIDATES,
    CONTRACT_HEADLINE_KEYS,
    DEFAULT_CATALOG,
    ENABLED_SETTING_VALUES,
    LLM_NETWORK_ALIAS,
    NETWORK_SUFFIX,
    RESPONSE_CACHE_SETTING,
    STACK_LLM_CONTAINER,
    eval_headline,
    response_cache_finding,
    setting_enabled,
)


def load_catalog(path: Path | str = DEFAULT_CATALOG) -> dict[str, Any]:
    return kit.load_catalog(path)


def catalog_problems(catalog: Any) -> list[str]:
    return kit.catalog_problems(catalog, CANDIDATES.name_key)


def all_variants(catalog: dict[str, Any]) -> list[Variant]:
    return kit.all_variants(catalog, CANDIDATES.name_key)


def select_variants(
    catalog: dict[str, Any], only: list[str] | None = None, all_quants: bool = False
) -> list[Variant]:
    return kit.select_variants(catalog, only, all_quants, CANDIDATES.name_key)


def variant_gate(variant: Variant, catalog: dict[str, Any]) -> list[str]:
    return kit.variant_gate(variant, catalog, CANDIDATES.gate_build)


def candidate_network(networks: list[str]) -> str | None:
    return llama_server.candidate_network(networks, NETWORK_SUFFIX)


def candidate_run_command(
    *,
    image: str,
    network: str,
    models_dir: str,
    args: list[str],
    memory_bytes: int | None,
    name: str = CANDIDATE_CONTAINER,
    alias: str = LLM_NETWORK_ALIAS,
) -> list[str]:
    return llama_server.candidate_run_command(
        image=image,
        models_dir=models_dir,
        args=args,
        memory_bytes=memory_bytes,
        name=name,
        network=network,
        alias=alias,
    )


def contract_headline(contract_report: dict[str, Any] | None) -> dict[str, Any] | None:
    return kit.contract_headline(contract_report, CONTRACT_HEADLINE_KEYS)


def variant_summary(variant: Variant, **parts: Any) -> dict[str, Any]:
    return kit.variant_summary(variant, profile=CANDIDATES, **parts)


def build_report(
    *,
    run: dict[str, Any],
    catalog: dict[str, Any],
    machine: dict[str, Any] | None,
    variants: list[dict[str, Any]],
) -> dict[str, Any]:
    return kit.build_report(
        run=run, catalog=catalog, machine=machine, variants=variants, profile=CANDIDATES
    )


def markdown_summary(report: dict[str, Any]) -> str:
    return kit.markdown_summary(report, CANDIDATES.markdown)
