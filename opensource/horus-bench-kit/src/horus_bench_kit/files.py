# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
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
    return bool(value) and bool(SHA256_PATTERN.match(value.strip().lower()))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_data(path: Path | str, what: str = "file", *, yaml_only: bool = False) -> Any:
    with open(path, encoding="utf-8") as handle:
        if not yaml_only and Path(path).suffix.lower() == ".json":
            return json.load(handle)
        try:
            import yaml
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                f"a YAML {what} needs PyYAML: pip install 'horus-bench-kit[yaml]', or use a .json {what}"
            ) from exc
        return yaml.safe_load(handle)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)


def check_report(document: Any, kind: str, schema_version: int) -> None:
    found = document.get("kind") if isinstance(document, dict) else None
    if found != kind:
        raise ValueError(f"not a {kind} report (kind={found!r})")
    version = document.get("schema_version")
    if isinstance(version, int) and not isinstance(version, bool) and version > schema_version:
        raise ValueError(
            f"{kind} schema_version {version} is newer than the {schema_version} this "
            "horus-bench-kit reads; update horus-bench-kit"
        )
