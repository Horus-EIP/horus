# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

GIB = 1024**3
WINDOWS_AVX2_FEATURE = 40
SMBIOS_MEMORY_TYPES = {
    18: "DDR",
    19: "DDR2",
    24: "DDR3",
    26: "DDR4",
    27: "LPDDR",
    28: "LPDDR2",
    29: "LPDDR3",
    30: "LPDDR4",
    34: "DDR5",
    35: "LPDDR5",
}
WINDOWS_CPU_QUERY = (
    "Get-CimInstance Win32_Processor | "
    "Select-Object Name, NumberOfCores, NumberOfLogicalProcessors | ConvertTo-Json -Compress"
)
WINDOWS_MEMORY_QUERY = (
    "Get-CimInstance Win32_PhysicalMemory | "
    "Select-Object Capacity, Speed, ConfiguredClockSpeed, SMBIOSMemoryType | "
    "ConvertTo-Json -Compress"
)
WINDOWS_TOTAL_MEMORY_QUERY = "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"
WINDOWS_DISK_QUERY = (
    "$number = (Get-Partition -DriveLetter {letter} | Get-Disk).Number; "
    "Get-PhysicalDisk | Where-Object {{ $_.DeviceId -eq [string]$number }} | "
    "Select-Object FriendlyName, MediaType, BusType | ConvertTo-Json -Compress"
)
OVERRIDABLE = ("cpu_model", "ram", "ram_speed", "disk_type")
MISSING_HINTS = {
    "cpu_model": "--cpu-model",
    "ram": "--ram",
    "ram_speed": "--ram-speed (on Linux, dmidecode needs root: sudo dmidecode -t memory)",
    "disk_type": "--disk-type",
}


def run_text(argv: list[str], timeout: float = 60.0) -> str | None:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def powershell(command: str) -> str | None:
    return run_text(["powershell", "-NoProfile", "-NonInteractive", "-Command", command])


def json_rows(text: str | None) -> list[dict[str, Any]]:
    try:
        data = json.loads(text or "")
    except ValueError:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _joined(values: list[str]) -> str | None:
    ordered = [value for value, _count in Counter(values).most_common()]
    return ", ".join(ordered) if ordered else None


def parse_cpuinfo(text: str | None) -> dict[str, Any]:
    model = None
    flags: set[str] | None = None
    cores: set[tuple[str, str]] = set()
    physical_id = core_id = None
    for line in [*(text or "").splitlines(), ""]:
        key, separator, value = line.partition(":")
        if not separator:
            if physical_id is not None and core_id is not None:
                cores.add((physical_id, core_id))
            physical_id = core_id = None
            continue
        key, value = key.strip(), value.strip()
        if key == "model name" and model is None:
            model = value
        elif key == "flags" and flags is None:
            flags = set(value.split())
        elif key == "physical id":
            physical_id = value
        elif key == "core id":
            core_id = value
    return {
        "cpu_model": model,
        "physical_cores": len(cores) or None,
        "avx2": None if flags is None else "avx2" in flags,
    }


def parse_meminfo_total(text: str | None) -> int | None:
    for line in (text or "").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if key.strip() == "MemTotal" and parts and parts[0].isdigit():
            return int(parts[0]) * 1024
    return None


def _dmidecode_size(text: str) -> int | None:
    match = re.match(r"^(\d+)\s*(MB|GB|TB)$", text.strip())
    if not match:
        return None
    return int(match.group(1)) * {"MB": 2**20, "GB": GIB, "TB": 2**40}[match.group(2)]


def parse_dmidecode_memory(text: str | None) -> dict[str, Any]:
    speeds: list[str] = []
    types: list[str] = []
    installed = 0
    modules = 0
    for block in re.split(r"\n\s*\n", text or ""):
        if "Memory Device" not in block:
            continue
        fields = {}
        for line in block.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                fields[key.strip()] = value.strip()
        size = _dmidecode_size(fields.get("Size", ""))
        if size is None:
            continue
        modules += 1
        installed += size
        speed = fields.get("Configured Memory Speed") or fields.get("Speed") or ""
        if speed[:1].isdigit():
            speeds.append(speed.replace("MHz", "MT/s"))
        if fields.get("Type") and fields["Type"] not in ("Unknown", "Other"):
            types.append(fields["Type"])
    return {
        "ram_installed_bytes": installed or None,
        "ram_speed": _joined(speeds),
        "ram_type": _joined(types),
        "ram_modules": modules or None,
    }


def parse_windows_cpu(text: str | None) -> dict[str, Any]:
    rows = json_rows(text)
    if not rows:
        return {}
    name = rows[0].get("Name")
    cores = sum(int(row.get("NumberOfCores") or 0) for row in rows)
    return {
        "cpu_model": name.strip() if isinstance(name, str) and name.strip() else None,
        "physical_cores": cores or None,
    }


def parse_windows_memory(text: str | None) -> dict[str, Any]:
    rows = json_rows(text)
    speeds = [
        f"{int(row.get('ConfiguredClockSpeed') or row.get('Speed'))} MT/s"
        for row in rows
        if row.get("ConfiguredClockSpeed") or row.get("Speed")
    ]
    types = [
        SMBIOS_MEMORY_TYPES[row.get("SMBIOSMemoryType")]
        for row in rows
        if row.get("SMBIOSMemoryType") in SMBIOS_MEMORY_TYPES
    ]
    installed = sum(int(row.get("Capacity") or 0) for row in rows)
    return {
        "ram_installed_bytes": installed or None,
        "ram_speed": _joined(speeds),
        "ram_type": _joined(types),
        "ram_modules": len(rows) or None,
    }


def disk_label(
    *,
    transport: str | None = None,
    rotational: bool | None = None,
    media: str | None = None,
) -> str | None:
    bus = (transport or "").strip().lower()
    media_name = (media or "").strip().upper()
    if bus == "nvme":
        return "NVMe SSD"
    if media_name == "HDD" or rotational is True:
        kind = "HDD"
    elif media_name in ("SSD", "SCM") or rotational is False:
        kind = "SSD"
    else:
        return None
    if bus in ("sata", "sas", "usb"):
        return f"{bus.upper()} {kind}"
    return kind


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if str(value) in ("1", "true"):
        return True
    if str(value) in ("0", "false"):
        return False
    return None


def _first_disk(devices: list[Any]) -> dict[str, Any] | None:
    for device in devices:
        if not isinstance(device, dict):
            continue
        if device.get("type") == "disk":
            return device
        found = _first_disk(device.get("children") or [])
        if found:
            return found
    return None


def parse_lsblk_disk(text: str | None) -> dict[str, Any]:
    try:
        tree = json.loads(text or "")
    except ValueError:
        return {}
    disk = _first_disk(tree.get("blockdevices") or []) if isinstance(tree, dict) else None
    if not disk:
        return {}
    model = (disk.get("model") or "").strip() or None
    return {
        "disk_type": disk_label(transport=disk.get("tran"), rotational=_as_bool(disk.get("rota"))),
        "disk_model": model,
    }


def parse_windows_disk(text: str | None) -> dict[str, Any]:
    rows = json_rows(text)
    if not rows:
        return {}
    row = rows[0]
    model = (row.get("FriendlyName") or "").strip() or None
    return {
        "disk_type": disk_label(transport=str(row.get("BusType") or ""), media=str(row.get("MediaType") or "")),
        "disk_model": model,
    }


def parse_macos_memory(text: str | None) -> dict[str, Any]:
    speeds = re.findall(r"^\s*Speed:\s*(\d+\s*MT/s|\d+\s*MHz)\s*$", text or "", re.MULTILINE)
    types = re.findall(r"^\s*Type:\s*(\S+)\s*$", text or "", re.MULTILINE)
    return {
        "ram_speed": _joined([speed.replace("MHz", "MT/s") for speed in speeds]),
        "ram_type": _joined(types),
    }


def parse_diskutil(text: str | None) -> dict[str, Any]:
    fields = {}
    for line in (text or "").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    solid = fields.get("Solid State")
    rotational = None if solid is None else solid.lower() != "yes"
    protocol = fields.get("Protocol", "")
    transport = "nvme" if "pci" in protocol.lower() or "fabric" in protocol.lower() else protocol
    return {
        "disk_type": disk_label(transport=transport, rotational=rotational),
        "disk_model": fields.get("Device / Media Name") or None,
    }


def parse_docker_info(text: str | None) -> dict[str, Any] | None:
    try:
        info = json.loads(text or "")
    except ValueError:
        return None
    if not isinstance(info, dict) or not info.get("MemTotal"):
        return None
    return {
        "mem_total_bytes": int(info["MemTotal"]),
        "cpus": info.get("NCPU"),
        "operating_system": info.get("OperatingSystem"),
        "kernel": info.get("KernelVersion"),
        "server_version": info.get("ServerVersion"),
        "cgroup_version": info.get("CgroupVersion"),
        "root_dir": info.get("DockerRootDir"),
    }


def docker_facts() -> dict[str, Any] | None:
    return parse_docker_info(run_text(["docker", "info", "--format", "{{json .}}"]))


def _sourced(facts: dict[str, Any], source: str) -> dict[str, Any]:
    return {key: (value, source) for key, value in facts.items()}


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


def _linux_host(disk_path: Path) -> dict[str, tuple[Any, str]]:
    found = _sourced(parse_cpuinfo(_read("/proc/cpuinfo")), "/proc/cpuinfo")
    found["ram_total_bytes"] = (parse_meminfo_total(_read("/proc/meminfo")), "/proc/meminfo")
    found.update(_sourced(parse_dmidecode_memory(run_text(["dmidecode", "-t", "memory"])), "dmidecode"))
    source = run_text(["findmnt", "-n", "-o", "SOURCE", "--target", str(disk_path)])
    if source:
        device = source.strip().split("[")[0]
        tree = run_text(["lsblk", "-J", "-s", "-o", "NAME,TYPE,ROTA,TRAN,MODEL", device])
        found.update(_sourced(parse_lsblk_disk(tree), f"lsblk ({device})"))
    return found


def _windows_avx2() -> bool | None:
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(WINDOWS_AVX2_FEATURE))
    except (AttributeError, OSError):
        return None


def drive_letter(path: Path) -> str:
    text = str(path)
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        return text[0].upper()
    return (os.environ.get("SystemDrive") or "C:")[:1].upper()


def _windows_host(disk_path: Path) -> dict[str, tuple[Any, str]]:
    found = _sourced(parse_windows_cpu(powershell(WINDOWS_CPU_QUERY)), "Win32_Processor")
    found["avx2"] = (_windows_avx2(), "IsProcessorFeaturePresent")
    total = (powershell(WINDOWS_TOTAL_MEMORY_QUERY) or "").strip()
    found["ram_total_bytes"] = (int(total) if total.isdigit() else None, "Win32_ComputerSystem")
    found.update(_sourced(parse_windows_memory(powershell(WINDOWS_MEMORY_QUERY)), "Win32_PhysicalMemory"))
    letter = drive_letter(disk_path)
    disk = parse_windows_disk(powershell(WINDOWS_DISK_QUERY.format(letter=letter)))
    found.update(_sourced(disk, f"Get-PhysicalDisk ({letter}:)"))
    return found


def _macos_host() -> dict[str, tuple[Any, str]]:
    found: dict[str, tuple[Any, str]] = {}
    model = (run_text(["sysctl", "-n", "machdep.cpu.brand_string"]) or "").strip()
    cores = (run_text(["sysctl", "-n", "hw.physicalcpu"]) or "").strip()
    total = (run_text(["sysctl", "-n", "hw.memsize"]) or "").strip()
    features = (run_text(["sysctl", "-n", "machdep.cpu.leaf7_features"]) or "").split()
    found["cpu_model"] = (model or None, "sysctl")
    found["physical_cores"] = (int(cores) if cores.isdigit() else None, "sysctl")
    found["ram_total_bytes"] = (int(total) if total.isdigit() else None, "sysctl")
    found["avx2"] = ("AVX2" in features if features else None, "sysctl")
    found.update(_sourced(parse_macos_memory(run_text(["system_profiler", "SPMemoryDataType"])), "system_profiler"))
    found.update(_sourced(parse_diskutil(run_text(["diskutil", "info", "/"])), "diskutil"))
    return found


def collect_host(
    disk_path: Path | None = None, system: str | None = None
) -> dict[str, tuple[Any, str]]:
    target = Path(disk_path or Path.home())
    system = system or sys.platform
    if system == "win32":
        return _windows_host(target)
    if system == "darwin":
        return _macos_host()
    return _linux_host(target)


def ram_label(total_bytes: int | None, installed_bytes: int | None) -> str | None:
    if installed_bytes:
        label = f"{installed_bytes / GIB:.0f} GiB installed"
        return f"{label}, {total_bytes / GIB:.1f} GiB usable" if total_bytes else label
    return f"{total_bytes / GIB:.1f} GiB usable" if total_bytes else None


def machine_section(
    reference: str | None,
    collected: dict[str, tuple[Any, str]],
    overrides: dict[str, str | None],
    docker: dict[str, Any] | None,
) -> dict[str, Any]:
    values = {key: value for key, (value, _source) in collected.items() if value is not None}
    sources = {key: source for key, (value, source) in collected.items() if value is not None}
    values["ram"] = ram_label(values.get("ram_total_bytes"), values.get("ram_installed_bytes"))
    if values["ram"]:
        sources["ram"] = sources.get("ram_installed_bytes") or sources.get("ram_total_bytes")
    for key in OVERRIDABLE:
        if overrides.get(key):
            values[key] = overrides[key]
            sources[key] = "given"
    return {
        "reference": reference,
        "cpu_model": values.get("cpu_model"),
        "physical_cores": values.get("physical_cores"),
        "logical_cpus": os.cpu_count(),
        "avx2": values.get("avx2"),
        "ram": values.get("ram"),
        "ram_total_bytes": values.get("ram_total_bytes"),
        "ram_installed_bytes": values.get("ram_installed_bytes"),
        "ram_modules": values.get("ram_modules"),
        "ram_type": values.get("ram_type"),
        "ram_speed": values.get("ram_speed"),
        "disk_type": values.get("disk_type"),
        "disk_model": values.get("disk_model"),
        "os": platform.platform(),
        "docker": docker,
        "sources": dict(sorted(sources.items())),
    }


def missing_fields(machine: dict[str, Any]) -> list[str]:
    return [f"{key}: pass {hint}" for key, hint in MISSING_HINTS.items() if not machine.get(key)]


def docker_data_path(docker: dict[str, Any] | None) -> Path:
    if sys.platform.startswith("linux") and docker and docker.get("root_dir"):
        return Path(docker["root_dir"])
    return Path(os.environ.get("LOCALAPPDATA") or Path.home())
