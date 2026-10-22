"""First-run helper: download the orchestrator LLM into a mounted volume.

The image used to bake the LLM in at build time (~8 GB per image, slow CI).
Now we ship a slim image and pull the model on first container start into a
named docker volume, so subsequent restarts are instant and rebuilding the
image stays cheap.

Behaviour:
- Resolve the target hub id from ``LLM_MODEL_ID`` (default: Qwen2.5-1.5B-Instruct).
- Resolve the on-disk cache dir from ``LLM_MODEL_DIR`` (default under ``models/``).
- If the directory already contains the required model files, no-op.
- Else if ``HF_HUB_OFFLINE=1``, fail loudly with a helpful message.
- Else download via ``huggingface_hub.snapshot_download``.

Exit code is always 0 on success or when the model is already present. Any
non-zero exit aborts the container start so the operator notices.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REQUIRED_FILES = ("config.json", "tokenizer.json")


# Match the model dir name to the trailing path segment of the hub id so a
# user who flips LLM_MODEL_ID also gets a fresh, predictable directory.
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
    # Under the vLLM backend the orchestrator routes all generation to the
    # external vLLM server (see core/llm_setup.py: _ensure_llm_loaded returns
    # early, ask_llm -> _ask_vllm) and never loads a local model — so there is
    # nothing to download. Skip the multi-GB snapshot; otherwise the entrypoint
    # blocks container startup (and the Docker healthcheck) on a large HF
    # download that isn't even used.
    if os.environ.get("LLM_BACKEND", "").strip().lower() == "vllm":
        print("[bootstrap_llm] LLM_BACKEND=vllm -> no local model needed; skipping download.")
        return 0

    here = Path(__file__).resolve().parent
    model_id = os.environ.get("LLM_MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct").strip()
    explicit_dir = os.environ.get("LLM_MODEL_DIR", "").strip()
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
