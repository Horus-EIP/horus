from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.embedding_setup import EMBED_MODEL_ID

MAS_DIR = Path(__file__).resolve().parents[3] / "src" / "services" / "mas"
REPORT_TIMEOUT_SECONDS = 900


def minilm_on_disk() -> bool:
    if importlib.util.find_spec("fastembed") is None:
        return False
    from fastembed import TextEmbedding
    from fastembed.common.utils import define_cache_dir
    from huggingface_hub import try_to_load_from_cache

    described = next(
        (model for model in TextEmbedding.list_supported_models()
         if model["model"] == EMBED_MODEL_ID),
        None,
    )
    if described is None or not described["sources"].get("hf"):
        return False
    found = try_to_load_from_cache(
        described["sources"]["hf"], described["model_file"], cache_dir=str(define_cache_dir())
    )
    return isinstance(found, str)


pytestmark = [
    pytest.mark.requires_model,
    pytest.mark.skipif(not minilm_on_disk(), reason=f"{EMBED_MODEL_ID} is not on disk"),
]


def test_router_report_on_the_test_set_with_the_fastembed_minilm_embedder(tmp_path):
    report_path = tmp_path / "router-report.json"
    env = {name: value for name, value in os.environ.items() if name != "TEST_MODE"}
    env.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        OTEL_SDK_DISABLED="true",
        LLM_BACKEND="transformers",
    )

    completed = subprocess.run(
        [sys.executable, "-m", "tasks.router_eval", "--json", str(report_path)],
        cwd=MAS_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=REPORT_TIMEOUT_SECONDS,
        check=False,
    )

    report_start = completed.stdout.find("Router report:")
    print(completed.stdout[report_start:] if report_start >= 0 else completed.stdout)
    assert completed.returncode == 0, completed.stderr[-4000:]
    summary = json.loads(report_path.read_text(encoding="utf-8"))
    assert summary["questions"] >= 100
    assert summary["methods"]["rules"]["accuracy"] == 1.0
    assert summary["accuracy_without_llm"] >= 0.95
    assert summary["fallback_rate"] <= 0.45
