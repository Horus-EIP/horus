from __future__ import annotations

import sys
from pathlib import Path

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from horus_bench_kit.host import (  # noqa: E402, F401
    MISSING_HINTS,
    OVERRIDABLE,
    collect_host,
    disk_label,
    docker_data_path,
    docker_facts,
    machine_section,
    missing_fields,
    parse_cpuinfo,
    parse_diskutil,
    parse_dmidecode_memory,
    parse_docker_info,
    parse_lsblk_disk,
    parse_macos_memory,
    parse_meminfo_total,
    parse_windows_cpu,
    parse_windows_disk,
    parse_windows_memory,
    ram_label,
    run_text,
)
