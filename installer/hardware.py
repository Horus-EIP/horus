from __future__ import annotations

import datetime
import json
import os
import platform
import shutil
import sys
from pathlib import Path

from common import VERSION, Log, human_bytes, run

GPU_TEST_IMAGE = "nvidia/cuda:12.4.0-base-ubuntu22.04"

GPU_TEST_TIMEOUT = 420

UNSUPPORTED_VENDORS = ("amd", "intel", "apple")

VENDOR_HINTS = (
    ("nvidia", ("nvidia", "geforce", "quadro", "rtx ", "gtx ", "tesla", "titan")),
    ("amd", ("amd", "radeon", "ati ", "firepro")),
    ("intel", ("intel", "iris", "uhd graphics", "hd graphics", "arc ")),
    ("apple", ("apple m1", "apple m2", "apple m3", "apple m4", "apple silicon")),
)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _vendor_of(name: str) -> str:
    low = (name or "").lower()
    for vendor, needles in VENDOR_HINTS:
        if any(n in low for n in needles):
            return vendor
    return "unknown"


def _is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(errors="replace").lower()
    except OSError:
        return False


def detect_os(log: Log) -> dict:
    info = {
        "platform": sys.platform,
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor_id": platform.processor(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "is_wsl": _is_wsl(),
        "is_64bit": sys.maxsize > 2**32,
    }
    log.info(
        f"os: {info['system']} {info['release']} ({info['machine']})"
        + ("  [running inside WSL]" if info["is_wsl"] else "")
    )
    return info


def _cpu_windows(log: Log) -> tuple[str | None, int | None, str]:
    if shutil.which("wmic"):
        name = run(["wmic", "cpu", "get", "Name", "/value"], log, timeout=30)
        cores = run(["wmic", "cpu", "get", "NumberOfCores", "/value"], log, timeout=30)
        model = _kv_value(name.out, "Name")
        count = _sum_kv_ints(cores.out, "NumberOfCores")
        if model or count:
            return model, count, "wmic"
        log.debug("wmic returned nothing usable for CPU; falling back to CIM")

    ps = run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$c = Get-CimInstance Win32_Processor; "
            "($c | Select-Object -First 1 -ExpandProperty Name); "
            "(($c | Measure-Object -Property NumberOfCores -Sum).Sum)",
        ],
        log,
        timeout=60,
    )
    if ps.ok:
        lines = [ln.strip() for ln in ps.out.splitlines() if ln.strip()]
        model = lines[0] if lines else None
        count = None
        for ln in reversed(lines):
            if ln.isdigit():
                count = int(ln)
                break
        return model, count, "powershell-cim"
    return None, None, "unavailable"


def _kv_value(text: str, key: str) -> str | None:
    for line in (text or "").splitlines():
        if line.strip().startswith(key + "="):
            val = line.split("=", 1)[1].strip()
            return val or None
    return None


def _sum_kv_ints(text: str, key: str) -> int | None:
    total = 0
    found = False
    for line in (text or "").splitlines():
        if line.strip().startswith(key + "="):
            raw = line.split("=", 1)[1].strip()
            if raw.isdigit():
                total += int(raw)
                found = True
    return total if found else None


LINUX_CPUINFO = Path("/proc/cpuinfo")

LINUX_CPU_SYSFS = Path("/sys/devices/system/cpu")


def _cores_from_sysfs(root: Path) -> int | None:
    siblings: set[str] = set()
    for path in root.glob("cpu[0-9]*/topology/thread_siblings_list"):
        try:
            siblings.add(path.read_text(errors="replace").strip())
        except OSError:
            continue
    siblings.discard("")
    return len(siblings) or None


def _cpu_linux(
    log: Log, cpuinfo: Path = LINUX_CPUINFO, sysfs: Path = LINUX_CPU_SYSFS
) -> tuple[str | None, int | None, str]:
    model, count, source = _cpu_from_cpuinfo(log, cpuinfo)
    if count is not None:
        return model, count, source
    from_sysfs = _cores_from_sysfs(sysfs)
    if from_sysfs is not None:
        return model, from_sysfs, f"{sysfs.as_posix()} thread siblings"
    return model, None, source


def _cpu_from_cpuinfo(log: Log, cpuinfo: Path) -> tuple[str | None, int | None, str]:
    try:
        text = cpuinfo.read_text(errors="replace")
    except OSError as exc:
        log.debug(f"{cpuinfo.as_posix()} unreadable: {exc}")
        return None, None, "unavailable"

    model = None
    pairs: set[tuple[str, str]] = set()
    phys = core = None
    for line in text.splitlines():
        if ":" not in line:
            if phys is not None and core is not None:
                pairs.add((phys, core))
            phys = core = None
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key == "model name" and model is None:
            model = val
        elif key == "physical id":
            phys = val
        elif key == "core id":
            core = val
    if phys is not None and core is not None:
        pairs.add((phys, core))

    if pairs:
        return model, len(pairs), "/proc/cpuinfo"
    log.debug("/proc/cpuinfo has no physical id/core id pairs")
    return model, None, "/proc/cpuinfo (no topology)"


def _cpu_macos(log: Log) -> tuple[str | None, int | None, str]:
    model = run(["sysctl", "-n", "machdep.cpu.brand_string"], log, timeout=20)
    cores = run(["sysctl", "-n", "hw.physicalcpu"], log, timeout=20)
    name = model.out.strip() if model.ok and model.out.strip() else None
    count = int(cores.out.strip()) if cores.ok and cores.out.strip().isdigit() else None
    return name, count, "sysctl"


PF_AVX2_INSTRUCTIONS_AVAILABLE = 40

X86_MACHINES = frozenset({"x86_64", "amd64", "x64", "i386", "i686", "x86"})

APPLE_SILICON = "Apple Silicon: an ARM processor, which has no AVX2 and does not need it"


def _avx2_in_cpuinfo(cpuinfo: Path) -> tuple[bool | None, str]:
    try:
        text = cpuinfo.read_text(errors="replace")
    except OSError as exc:
        return None, f"{cpuinfo.as_posix()} unreadable: {exc}"
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "flags":
            return "avx2" in value.split(), f"{cpuinfo.as_posix()} flags"
    return None, f"{cpuinfo.as_posix()} lists no flags"


def _avx2_windows(kernel32=None) -> tuple[bool | None, str]:
    source = f"IsProcessorFeaturePresent({PF_AVX2_INSTRUCTIONS_AVAILABLE})"
    try:
        if kernel32 is None:
            import ctypes

            kernel32 = ctypes.windll.kernel32
        present = kernel32.IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE)
    except (AttributeError, ImportError, OSError) as exc:
        return None, f"{source} failed: {exc}"
    return bool(present), source


def _avx2_macos(log: Log) -> tuple[bool | None, str]:
    arm = run(["sysctl", "-n", "hw.optional.arm64"], log, timeout=20)
    if arm.ok and arm.out.strip() == "1":
        return None, APPLE_SILICON
    res = run(["sysctl", "-n", "hw.optional.avx2_0"], log, timeout=20)
    value = res.out.strip() if res.ok else ""
    if value in ("0", "1"):
        return value == "1", "sysctl hw.optional.avx2_0"
    return None, "sysctl hw.optional.avx2_0 gave no answer"


def detect_avx2(log: Log, osinfo: dict, cpuinfo: Path = LINUX_CPUINFO, kernel32=None) -> dict:
    machine = str(osinfo.get("machine") or "").lower()
    if machine and machine not in X86_MACHINES:
        found, source = None, f"{machine} processor: AVX2 is an x86 feature it does not need"
    elif sys.platform == "win32":
        found, source = _avx2_windows(kernel32)
    elif sys.platform == "darwin":
        found, source = _avx2_macos(log)
    else:
        found, source = _avx2_in_cpuinfo(cpuinfo)
    label = {True: "yes", False: "NO", None: "not checked"}[found]
    log.info(f"avx2: {label} ({source})")
    return {"avx2": found, "avx2_source": source}


def detect_cpu(log: Log) -> dict:
    if sys.platform == "win32":
        model, physical, source = _cpu_windows(log)
    elif sys.platform == "darwin":
        model, physical, source = _cpu_macos(log)
    else:
        model, physical, source = _cpu_linux(log)

    logical = os.cpu_count()
    fallback = False
    if physical is None:
        physical = logical
        fallback = True
        source = f"{source} -> os.cpu_count() (LOGICAL cores, not physical)"

    info = {
        "model": model,
        "physical_cores": physical,
        "logical_cores": logical,
        "count_is_logical_fallback": fallback,
        "source": source,
    }
    label = model or "unknown CPU"
    if fallback:
        log.info(f"cpu: {label}  {physical} logical cores (physical count unavailable)")
    else:
        log.info(f"cpu: {label}  {physical} physical / {logical} logical cores")
    return info


def detect_memory(log: Log) -> dict:
    total: int | None = None
    source = "unavailable"
    detail = ""

    if sys.platform == "win32":
        ps = run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
            ],
            log,
            timeout=60,
        )
        raw = ps.out.strip() if ps.ok else ""
        if raw.isdigit():
            total, source = int(raw), "Win32_ComputerSystem.TotalPhysicalMemory"
        else:
            detail = ps.first_line() or "PowerShell CIM query returned nothing"
    elif sys.platform == "darwin":
        res = run(["sysctl", "-n", "hw.memsize"], log, timeout=20)
        raw = res.out.strip() if res.ok else ""
        if raw.isdigit():
            total, source = int(raw), "sysctl hw.memsize"
        else:
            detail = res.first_line() or "sysctl returned nothing"
    else:
        try:
            for line in Path("/proc/meminfo").read_text(errors="replace").splitlines():
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        total = int(parts[1]) * 1024
                        source = "/proc/meminfo MemTotal"
                    break
        except OSError as exc:
            detail = str(exc)

    if total is None:
        log.warn(
            f"Could not read total RAM ({detail or 'no method succeeded'}). "
            "Assuming the smaller-model profile."
        )
    else:
        log.info(f"ram: {human_bytes(total)} ({source})")

    return {
        "total_bytes": total,
        "total_gib": round(total / 1024**3, 2) if total else None,
        "source": source,
        "detail": detail,
    }


def detect_docker_memory(log: Log) -> dict:
    res = run(["docker", "info", "--format", "{{.MemTotal}}"], log, timeout=45)
    raw = res.out.strip() if res.ok else ""
    if raw.isdigit() and int(raw) > 0:
        total = int(raw)
        log.info(f"docker memory: {human_bytes(total)} (docker info MemTotal)")
        return {
            "mem_total_bytes": total,
            "mem_total_gib": round(total / 1024**3, 2),
            "source": "docker info MemTotal",
            "detail": "",
        }
    detail = res.first_line() or "docker info returned nothing"
    log.info(f"docker memory: unknown ({detail})")
    return {
        "mem_total_bytes": None,
        "mem_total_gib": None,
        "source": "unavailable",
        "detail": detail,
    }


def detect_disk(log: Log, path: Path | None = None) -> dict:
    target = path
    try:
        if target is None:
            target = Path.home()
        usage = shutil.disk_usage(str(target))
    except (OSError, RuntimeError) as exc:
        log.debug(f"disk_usage({target if target is not None else 'home'}) failed: {exc}")
        return {
            "path": str(target) if target is not None else None,
            "free_bytes": None,
            "total_bytes": None,
            "detail": str(exc),
        }
    log.info(f"disk: {human_bytes(usage.free)} free of {human_bytes(usage.total)} at {target}")
    return {"path": str(target), "free_bytes": usage.free, "total_bytes": usage.total, "detail": ""}


def _parse_nvidia_smi(out: str) -> list[dict]:
    gpus = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        name, _, mem = line.rpartition(",")
        name, mem = name.strip(), mem.strip()
        if not name:
            continue
        vram = None
        digits = "".join(c for c in mem if c.isdigit())
        if digits:
            mib = int(digits)
            unit = mem.lower()
            vram = mib * 1024**3 if "gib" in unit or " gb" in unit else mib * 1024**2
        gpus.append({"name": name, "vram_bytes": vram, "vram_label": mem})
    return gpus


def _video_adapters_windows(log: Log) -> list[str]:
    ps = run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }",
        ],
        log,
        timeout=60,
    )
    if not ps.ok:
        return []
    return [ln.strip() for ln in ps.out.splitlines() if ln.strip()]


def _video_adapters_linux(log: Log) -> list[str]:
    if not shutil.which("lspci"):
        return []
    res = run(["lspci"], log, timeout=30)
    if not res.ok:
        return []
    names = []
    for line in res.out.splitlines():
        low = line.lower()
        if "vga compatible controller" in low or "3d controller" in low:
            names.append(line.split(":", 2)[-1].strip())
    return names


def detect_gpu_host(log: Log, osinfo: dict) -> dict:
    info: dict = {
        "vendor": "none",
        "name": None,
        "vram_bytes": None,
        "count": 0,
        "gpus": [],
        "adapters": [],
        "source": "none",
        "detail": "",
        "driver_version": None,
    }

    if osinfo.get("system") == "Darwin":
        info.update(
            {
                "vendor": "apple",
                "name": f"Apple {osinfo.get('machine', '')} integrated GPU".strip(),
                "source": "platform (macOS)",
                "detail": "Not probed: no GPU on macOS can run this stack (see notes).",
            }
        )
        return info

    if shutil.which("nvidia-smi"):
        res = run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            log,
            timeout=60,
        )
        if res.ok and res.out.strip():
            gpus = _parse_nvidia_smi(res.out)
            if gpus:
                largest = max(gpus, key=lambda g: g["vram_bytes"] or 0)
                info.update(
                    {
                        "vendor": "nvidia",
                        "name": largest["name"],
                        "vram_bytes": largest["vram_bytes"],
                        "count": len(gpus),
                        "gpus": gpus,
                        "source": "nvidia-smi",
                    }
                )
                drv = run(
                    ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                    log,
                    timeout=30,
                )
                if drv.ok and drv.out.strip():
                    info["driver_version"] = drv.out.strip().splitlines()[0].strip()
                vram = (
                    human_bytes(largest["vram_bytes"]) if largest["vram_bytes"] else "unknown VRAM"
                )
                log.info(
                    f"gpu (host): {largest['name']}  {vram}"
                    + (f"  driver {info['driver_version']}" if info["driver_version"] else "")
                    + (f"  ({len(gpus)} devices)" if len(gpus) > 1 else "")
                )
                return info
        info["detail"] = res.first_line() or "nvidia-smi produced no output"
        log.debug(f"nvidia-smi present but unusable: {info['detail']}")

    adapters = (
        _video_adapters_windows(log) if sys.platform == "win32" else _video_adapters_linux(log)
    )
    info["adapters"] = adapters
    if adapters:
        chosen = adapters[0]
        for adapter in adapters:
            if _vendor_of(adapter) in ("nvidia", "amd"):
                chosen = adapter
                break
        info.update(
            {
                "vendor": _vendor_of(chosen),
                "name": chosen,
                "count": len(adapters),
                "source": "Win32_VideoController" if sys.platform == "win32" else "lspci",
            }
        )
        log.info(f"gpu (host): {chosen}  [vendor={info['vendor']}, no NVIDIA driver found]")
    else:
        info["detail"] = info["detail"] or "no video adapters enumerated"
        log.info("gpu (host): none detected")
    return info


def _wsl_status(log: Log) -> dict:
    status = {"present": False, "default_version": None, "detail": ""}
    if not shutil.which("wsl"):
        status["detail"] = "wsl.exe not found on PATH"
        return status

    res = run(["wsl", "--status"], log, timeout=45)
    blob = ((res.out or "") + "\n" + (res.err or "")).replace("\x00", "")
    status["present"] = bool(blob.strip()) and res.code in (0, 1)
    low = blob.lower()
    if "default version: 2" in low or "version par défaut : 2" in low:
        status["default_version"] = 2
    elif "default version: 1" in low:
        status["default_version"] = 1
    status["detail"] = " / ".join(ln.strip() for ln in blob.splitlines() if ln.strip())[:400]
    return status


def _skip_reason(osinfo: dict, gpu: dict, allow: bool) -> str | None:
    if not allow:
        return "skipped by request (--no-gpu-test or a CPU profile was forced)"
    if osinfo.get("system") == "Darwin":
        return (
            "macOS. Docker Desktop cannot pass a GPU through to a Linux "
            "container, and vllm/vllm-openai is a CUDA image with no ARM build. "
            "There is nothing this test could discover."
        )
    vendor = gpu.get("vendor")
    if vendor in UNSUPPORTED_VENDORS:
        return (
            f"the only GPU found is {gpu.get('name') or vendor} ({vendor}). The "
            "pinned vLLM image is CUDA-only, so an AMD or Intel card cannot run "
            "this stack whatever Docker reports."
        )
    if vendor == "none" and not gpu.get("adapters"):
        return "no GPU of any kind was detected on the host"
    return None


def docker_gpu_test(log: Log, osinfo: dict, gpu: dict, allow: bool = True) -> dict:
    outcome: dict = {
        "attempted": False,
        "usable": None,
        "image": GPU_TEST_IMAGE,
        "command": None,
        "skipped_reason": None,
        "detail": "",
        "wsl": None,
    }

    if sys.platform == "win32":
        outcome["wsl"] = _wsl_status(log)

    skip = _skip_reason(osinfo, gpu, allow)
    if skip:
        outcome["skipped_reason"] = skip
        log.info(f"docker gpu test: skipped - {skip}")
        return outcome

    if shutil.which("docker") is None:
        outcome["skipped_reason"] = "docker executable not found on PATH"
        log.warn("Cannot test GPU access: docker is not on PATH.")
        return outcome

    ping = run(["docker", "version", "--format", "{{.Server.Version}}"], log, timeout=45)
    if not ping.ok:
        outcome["skipped_reason"] = "the Docker daemon did not answer"
        outcome["detail"] = ping.first_line()
        log.warn("Cannot test GPU access: the Docker daemon is not running.")
        return outcome

    cmd = ["docker", "run", "--rm", "--gpus", "all", GPU_TEST_IMAGE, "nvidia-smi"]
    outcome["command"] = " ".join(cmd)
    outcome["attempted"] = True

    log.say("")
    log.say("  Checking whether Docker can use your GPU.")
    log.say("  This runs nvidia-smi inside a container, which is the only test that")
    log.say("  matters: a card the host can see but a container cannot is no use to")
    log.say("  Horus. It downloads a small NVIDIA image (about 250 MB) to do it.")
    log.say(f"  Image: {GPU_TEST_IMAGE}")
    log.say("  This can take a few minutes on a slow connection. Nothing is installed")
    log.say("  on your machine; the container is deleted as soon as it exits.")

    res = run(cmd, log, timeout=GPU_TEST_TIMEOUT)
    if res.ok:
        outcome["usable"] = True
        outcome["detail"] = res.first_line()
        log.ok("Docker can use the GPU.")
        return outcome

    outcome["usable"] = False
    outcome["detail"] = (res.err or res.out or "").strip()[:1500]
    if res.timed_out:
        outcome["detail"] = f"timed out after {GPU_TEST_TIMEOUT}s (image pull or driver init)"
    log.warn("Docker could not use the GPU - Horus will run on the CPU.")
    for line in _gpu_failure_advice(osinfo, gpu, outcome):
        log.say("    " + line)
    return outcome


def _gpu_failure_advice(osinfo: dict, gpu: dict, outcome: dict) -> list[str]:
    lines = [
        f"Reason: {outcome['detail'].splitlines()[0][:160]}"
        if outcome["detail"]
        else "Reason: the container could not open a CUDA device."
    ]

    if osinfo.get("system") == "Windows":
        wsl = outcome.get("wsl") or {}
        if not wsl.get("present"):
            lines += [
                "WSL2 was not found. Docker Desktop needs the WSL2 backend to pass",
                "an NVIDIA GPU to a container. In an admin PowerShell:",
                "    wsl --install",
                "then reboot, and in Docker Desktop > Settings > General tick",
                "'Use the WSL 2 based engine'.",
            ]
        elif wsl.get("default_version") == 1:
            lines += [
                "WSL is set to version 1, which cannot pass a GPU through. Run:",
                "    wsl --set-default-version 2",
                "and convert your distro, then restart Docker Desktop.",
            ]
        else:
            lines += [
                "WSL2 is present, so the missing piece is usually the driver or",
                "the Docker setting:",
                "  1. Install the NVIDIA driver FOR WINDOWS (not one inside WSL):",
                "     https://www.nvidia.com/Download/index.aspx",
                "  2. Docker Desktop > Settings > Resources > WSL Integration:",
                "     enable your default distro.",
                "  3. Restart Docker Desktop and run this installer again.",
            ]
    elif osinfo.get("system") == "Linux":
        lines += [
            "On Linux the container runtime hook is a separate package:",
            "    sudo apt-get install -y nvidia-container-toolkit",
            "    sudo nvidia-ctk runtime configure --runtime=docker",
            "    sudo systemctl restart docker",
            "then run this installer again.",
        ]

    if gpu.get("vendor") == "nvidia":
        lines.append("Your host does have an NVIDIA card, so this is worth fixing:")
        lines.append("the GPU stack answers in seconds where the CPU one takes minutes.")
    lines.append("You can continue on the CPU now and re-run the installer later.")
    return lines


def _partial_probe(reason: str) -> dict:
    return {
        "installer_version": VERSION,
        "timestamp_utc": _now(),
        "os": {"platform": sys.platform, "system": platform.system()},
        "cpu": {},
        "memory": {
            "total_bytes": None,
            "total_gib": None,
            "source": "unavailable",
            "detail": reason,
        },
        "docker": {
            "mem_total_bytes": None,
            "mem_total_gib": None,
            "source": "unavailable",
            "detail": reason,
        },
        "disk": {"path": None, "free_bytes": None, "total_bytes": None, "detail": reason},
        "gpu": {
            "vendor": "unknown",
            "name": None,
            "vram_bytes": None,
            "count": 0,
            "gpus": [],
            "adapters": [],
            "source": "none",
            "detail": reason,
            "driver_version": None,
        },
        "docker_gpu_test": {
            "attempted": False,
            "usable": None,
            "image": GPU_TEST_IMAGE,
            "command": None,
            "skipped_reason": "the hardware probe failed before the test could run",
            "detail": reason,
            "wsl": None,
        },
        "cuda_usable_in_docker": False,
        "gpu_test_ran": False,
        "probe_failed": True,
        "notes": [
            f"The hardware probe did not complete: {reason}",
            "Everything below is unknown, so the cautious CPU profile was "
            "chosen. Please send this file - a probe that cannot finish is a "
            "bug in the installer, not in your machine.",
        ],
    }


def _mib(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return int(value) // 1024**2


def fingerprint(probe_data: dict) -> dict:
    memory = probe_data.get("memory") or {}
    docker = probe_data.get("docker") or {}
    gpu = probe_data.get("gpu") or {}
    cards = [
        f"{card.get('name')} {_mib(card.get('vram_bytes'))} MiB"
        for card in gpu.get("gpus") or []
        if isinstance(card, dict)
    ]
    return {
        "ram_mib": _mib(memory.get("total_bytes")),
        "docker_memory_mib": _mib(docker.get("mem_total_bytes")),
        "gpus": sorted(str(name) for name in [*cards, *(gpu.get("adapters") or [])]),
    }


def reusable_gpu_test(previous: dict | None, current: dict) -> dict | None:
    if not isinstance(previous, dict) or previous.get("hardware_fingerprint") != current:
        return None
    recorded = previous.get("hardware")
    test = recorded.get("docker_gpu_test") if isinstance(recorded, dict) else None
    if not isinstance(test, dict) or test.get("usable") is not True:
        return None
    return {**test, "reused_from": str(previous.get("generated_utc") or "an earlier run")}


def probe(log: Log, allow_docker_gpu_test: bool = True, previous: dict | None = None) -> dict:
    try:
        return _probe_machine(log, allow_docker_gpu_test, previous)
    except Exception as exc:  # noqa: BLE001 - the promise is the point
        reason = f"{type(exc).__name__}: {exc}"
        log.debug(f"hardware probe raised: {reason}")
        log.warn(
            f"The hardware probe failed ({reason}). Continuing with "
            "unknown hardware and the cautious CPU profile."
        )
        return _partial_probe(reason)


def _probe_machine(log: Log, allow_docker_gpu_test: bool, previous: dict | None) -> dict:
    log.step("Hardware")

    osinfo = detect_os(log)
    cpu = detect_cpu(log)
    cpu.update(detect_avx2(log, osinfo))
    memory = detect_memory(log)
    disk = detect_disk(log)
    gpu = detect_gpu_host(log, osinfo)
    docker = detect_docker_memory(log)
    current = fingerprint({"memory": memory, "docker": docker, "gpu": gpu})
    reused = reusable_gpu_test(previous, current) if allow_docker_gpu_test else None
    if reused is not None:
        gpu_test = reused
        log.ok(
            f"Same RAM, Docker memory and GPUs as on {reused['reused_from']}, when "
            "Docker could use the GPU: the GPU test is not run again."
        )
    else:
        gpu_test = docker_gpu_test(log, osinfo, gpu, allow=allow_docker_gpu_test)

    notes: list[str] = []
    if osinfo.get("system") == "Darwin":
        notes.append(
            "macOS always runs Horus on the CPU. Docker Desktop for Mac cannot "
            "pass the GPU (Apple Silicon or otherwise) to a Linux container, and "
            "the vLLM image the stack pins is CUDA-only with no ARM build. This "
            "is not a limitation the installer can work around."
        )
    if gpu.get("vendor") in ("amd", "intel"):
        notes.append(
            f"A {gpu['vendor'].upper()} GPU was found. The stack's vLLM image is "
            "CUDA-only; ROCm and oneAPI are out of scope for the beta, so this "
            "card will not be used."
        )
    if cpu.get("count_is_logical_fallback"):
        notes.append(
            "The physical core count could not be read, so the number recorded "
            "is the LOGICAL count (hyperthreads included). On CPU inference the "
            "real figure is typically half of it."
        )
    if memory.get("total_bytes") is None:
        notes.append("Total RAM could not be measured; the cautious profile was chosen.")
    if docker.get("mem_total_bytes") is None:
        notes.append(
            f"The memory Docker can use was not read ({docker.get('detail')}). "
            "The RAM of the machine stood in for it, which overstates it on "
            "Windows and macOS, where Docker runs in a virtual machine."
        )
    if cpu.get("avx2") is False:
        notes.append(
            "The processor has no AVX2. llama-server still runs, because the "
            "official llama.cpp build picks the code the processor supports when "
            "it starts, but generation on the CPU is much slower."
        )
    if gpu_test.get("reused_from"):
        notes.append(
            f"The Docker GPU test was not run again: RAM, Docker memory and GPUs "
            f"are the same as on {gpu_test['reused_from']}, when it passed."
        )
    if gpu_test.get("usable") is False:
        notes.append(
            "A GPU exists on the host but Docker could not use it. "
            "See docker_gpu_test.advice in this file."
        )
    if gpu_test.get("usable") is None and gpu_test.get("skipped_reason"):
        notes.append(f"The Docker GPU test did not run: {gpu_test['skipped_reason']}")

    if gpu_test.get("usable") is False:
        gpu_test["advice"] = _gpu_failure_advice(osinfo, gpu, gpu_test)

    result = {
        "installer_version": VERSION,
        "timestamp_utc": _now(),
        "os": osinfo,
        "cpu": cpu,
        "memory": memory,
        "docker": docker,
        "disk": disk,
        "gpu": gpu,
        "docker_gpu_test": gpu_test,
        "cuda_usable_in_docker": gpu_test.get("usable") is True,
        "gpu_test_ran": bool(gpu_test.get("attempted", False)) and not gpu_test.get("reused_from"),
        "hardware_fingerprint": current,
        "notes": notes,
    }
    log.info(f"cuda usable in docker: {result['cuda_usable_in_docker']}")
    return result


_SECRET_HINTS = ("PASSWORD", "SECRET", "TOKEN", "KEY", "CREDENTIAL")


def _redact(env: dict) -> dict:
    out = {}
    for key, value in env.items():
        if any(h in key.upper() for h in _SECRET_HINTS):
            out[key] = "<redacted>"
        else:
            out[key] = value
    return out


def read_profile_json(path: Path) -> dict | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _profile_facts(profile_name: str, probe_data: dict) -> tuple:
    import profiles

    try:
        prof = profiles.get(profile_name)
        return (
            profiles.provenance_for(profile_name, probe_data),
            prof.runs_vllm,
            profiles.model_server(profile_name),
            prof.confidence,
            prof.trigger,
            list(prof.notes),
        )
    except Exception as exc:  # noqa: BLE001 - a bad name must not lose the probe
        return {}, None, None, "unknown", "", [f"profile lookup failed: {exc}"]


def write_profile_json(
    path: Path,
    probe_data: dict,
    profile_name: str,
    env: dict,
    reasons: list[str],
    log: Log | None = None,
    refusal: dict | None = None,
) -> None:
    import profiles

    if refusal is None:
        provenance, runs_vllm, model_server, confidence, trigger, notes = _profile_facts(
            profile_name, probe_data
        )
    else:
        provenance, runs_vllm, model_server, confidence = {}, None, None, "unknown"
        trigger, notes = "", []

    derived = sorted(k for k, v in provenance.items() if v.get("provenance") == profiles.DERIVED)

    document = {
        "schema": "horus-profile/1",
        "installer_version": VERSION,
        "generated_utc": _now(),
        "hardware": probe_data,
        "hardware_fingerprint": probe_data.get("hardware_fingerprint") or fingerprint(probe_data),
        "memory_decision": profiles.memory_decision(probe_data),
        "profile": {
            "name": profile_name,
            "trigger": trigger,
            "runs_vllm": runs_vllm,
            "model_server": model_server,
            "confidence": confidence,
            "reasons": list(reasons),
            "notes": notes,
        },
        "env_written": _redact(env),
        "tuning_provenance": provenance,
        "derived_settings": derived,
        "how_to_read_this": [
            "'measured' means this exact value is part of a configuration that "
            "has really been run and behaved as described.",
            "'derived' means it was reasoned out from the measured 8 GB "
            "configuration - scaled, or argued for - and has NOT been "
            "benchmarked. Suspect these first. Both CPU profiles are derived: "
            "no CPU-only machine has been timed.",
            "cuda_usable_in_docker is the field that decided GPU vs CPU. It is "
            "the result of running nvidia-smi inside a container, not of asking "
            "the host what hardware it has.",
            "memory_decision is what decided between the CPU profiles: the memory "
            "Docker can use (docker info), or the RAM of the machine when Docker "
            "could not say, against the thresholds of ADR-006.",
            "hardware_fingerprint is the RAM, the Docker memory and the GPU list. "
            "The next run compares it: when nothing changed and Docker could use "
            "the GPU, the Docker GPU test is not run again.",
            "Send this file with any performance report; it is the first thing we ask for.",
        ],
    }
    if refusal is not None:
        document["refusal"] = refusal

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        if log is None:
            raise
        log.warn(f"Could not write {path}: {exc}")
        if refusal is None:
            log.warn(
                "The install continues, but please quote install-log.txt "
                "instead of horus-profile.json if you report a problem."
            )
        return
    if log:
        log.ok(f"Hardware profile written to {path}")
