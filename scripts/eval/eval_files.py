from __future__ import annotations

import sys
from pathlib import Path

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from horus_bench_kit.files import is_sha256, report_path, safe_label, write_json  # noqa: E402, F401
