from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from horus_bench_kit import fetch  # noqa: E402
from horus_bench_kit import llama_bench as kit  # noqa: E402
from horus_bench_kit.llama_bench import (  # noqa: E402, F401
    CONTAINER_MODELS_DIR,
    DEFAULT_REPETITIONS,
    MODELS_DIR_PLACEHOLDER,
    REPORT_KIND,
    SCHEMA_VERSION,
    BenchMatrix,
    KnownModel,
    bench_command,
    bench_test_name,
    build_report,
    checksum_command,
    container_path,
    file_name,
    image_build,
    listing_command,
    llama_cpp_section,
    model_files_in,
    models_mount,
    parse_bench_output,
    parse_checksums,
    parse_listing,
    recorded_command,
    recorded_model_path,
    split_values,
    summary_lines,
    summary_rows,
)
from horus_bench_kit.llama_bench import DEFAULT_CACHE_TYPES as PLAN_CACHE_TYPES  # noqa: E402, F401
from horus_bench_kit.llama_bench import DEFAULT_DEPTHS as PLAN_DEPTHS  # noqa: E402, F401
from horus_bench_kit.llama_bench import DEFAULT_GENERATIONS as PLAN_GENERATIONS  # noqa: E402, F401
from horus_bench_kit.llama_bench import DEFAULT_PROMPTS as PLAN_PROMPTS  # noqa: E402, F401
from horus_bench_kit.llama_bench import DEFAULT_THREADS as PLAN_THREADS  # noqa: E402, F401
from horus_profile import (  # noqa: E402, F401
    BENCH_IMAGE,
    CONTAINER_FETCH_SCRIPT,
    DEFAULT_MODEL_FILES,
    FETCH_IMAGE,
    KNOWN_MODELS,
    UNSLOTH_FILES_URL,
)


def fetch_command(image: str, source: str, script: str, model: KnownModel) -> list[str]:
    return fetch.fetch_command(image, source, script, model, container_script=CONTAINER_FETCH_SCRIPT)


def model_records(
    files: list[str], sizes: dict[str, int], checksums: dict[str, str]
) -> list[dict[str, Any]]:
    return kit.model_records(files, sizes, checksums, KNOWN_MODELS)
