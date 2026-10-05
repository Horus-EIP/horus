from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE_LABEL_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_label(label: str) -> str:
    cleaned = _UNSAFE_LABEL_CHARS.sub("-", label.strip()).strip("-.")
    if not cleaned:
        raise ValueError("label must contain at least one letter or digit")
    return cleaned


def report_path(out_dir: Path | str, label: str, run_date: date) -> Path:
    stem = f"{safe_label(label)}-{run_date.isoformat()}"
    candidate = Path(out_dir) / f"{stem}.json"
    suffix = 2
    while candidate.exists():
        candidate = Path(out_dir) / f"{stem}-{suffix}.json"
        suffix += 1
    return candidate


def is_sha256(value: str | None) -> bool:
    return bool(value) and bool(_SHA256.match(value.strip().lower()))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
