"""First-run helper: download the agent decision LLM into a mounted volume.

See ``services/mas/bootstrap_llm.py`` for the full rationale. The agent reads
``MODEL_NAME`` (existing env) for the hub id and ``MODEL_DIR`` to override the
cache location.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REQUIRED_FILES = ("config.json", "tokenizer.json")


def _default_model_dir(base: Path, model_id: str) -> Path:
    leaf = model_id.split("/")[-1] or "model"
    return base / "models" / leaf


def _required_files_present(model_dir: Path) -> bool:
    if not model_dir.is_dir():
        return False
    missing = [f for f in REQUIRED_FILES if not (model_dir / f).exists()]
    if missing:
        print(
            f"[bootstrap_llm] {model_dir} exists but is missing: {missing}",
            file=sys.stderr,
        )
        return False
    return True


def main() -> int:
    here = Path(__file__).resolve().parent
    model_id = os.environ.get("MODEL_NAME", "Qwen/Qwen3-4B-Instruct-2507").strip()
    explicit_dir = os.environ.get("MODEL_DIR", "").strip()
    model_dir = Path(explicit_dir) if explicit_dir else _default_model_dir(here, model_id)

    print(f"[bootstrap_llm] target model={model_id!r} dir={model_dir}")

    if _required_files_present(model_dir):
        print("[bootstrap_llm] already present; skipping download.")
        return 0

    offline = os.environ.get("HF_HUB_OFFLINE", "").strip() in ("1", "true", "yes")
    if offline:
        print(
            "[bootstrap_llm] ERROR: model is not present and HF_HUB_OFFLINE=1.\n"
            f"    Set HF_HUB_OFFLINE=0 for the first run so {model_id} can be downloaded,\n"
            "    or pre-populate the model volume.",
            file=sys.stderr,
        )
        return 1

    print(f"[bootstrap_llm] downloading {model_id} to {model_dir} ...")
    model_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        print(f"[bootstrap_llm] huggingface_hub import failed: {exc}", file=sys.stderr)
        return 2

    try:
        snapshot_download(
            repo_id=model_id,
            local_dir=str(model_dir),
            local_dir_use_symlinks=False,
        )
    except Exception as exc:
        print(f"[bootstrap_llm] download failed: {exc}", file=sys.stderr)
        return 3
    print("[bootstrap_llm] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
