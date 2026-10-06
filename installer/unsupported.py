from __future__ import annotations

import math
import textwrap

import profiles
from common import EXIT_HARDWARE_NOT_SUPPORTED, InstallError, Log

EVENT = "unsupported"

HEADLINE = "This machine does not have enough memory for Horus."

NUMBER_KEYS = ("docker_memory_bytes", "ram_bytes", "required_bytes", "os")

VM_REPORTS_LESS_GIB = 0.5

WINDOWS_PRACTICAL_RAM_GB = 24

WRAP = 66

_GIB = 1024 ** 3


def _bullets(items: list[str]) -> list[str]:
    lines: list[str] = []
    for item in items:
        wrapped = textwrap.wrap(item, WRAP, break_on_hyphens=False,
                                break_long_words=False) or [""]
        lines.append("- " + wrapped[0])
        lines.extend("  " + rest for rest in wrapped[1:])
    return lines


class NotSupported(InstallError):

    def __init__(self, have: list[str], need: list[str], alternatives: list[str],
                 numbers: dict, checked_utc: str | None = None):
        self.have = list(have)
        self.need = list(need)
        self.alternatives = list(alternatives)
        self.numbers = {key: numbers.get(key) for key in NUMBER_KEYS}
        self.checked_utc = checked_utc
        super().__init__(EXIT_HARDWARE_NOT_SUPPORTED, HEADLINE, self._detail(),
                         "\n".join(_bullets(self.alternatives)))

    def _detail(self) -> str:
        lines: list[str] = []
        if self.checked_utc:
            lines += [f"Found when START-HERE last ran ({self.checked_utc}).", ""]
        lines += ["This machine:", *_bullets(self.have), "", "Horus needs:",
                  *_bullets(self.need), "",
                  "Nothing was installed and Horus itself was not downloaded."]
        return "\n".join(lines)

    def record(self) -> dict:
        return {"headline": self.headline, "have": self.have, "need": self.need,
                "alternatives": self.alternatives, **self.numbers}

    def report(self, log: Log) -> None:
        log.events.emit(EVENT, checked_utc=self.checked_utc, **self.record())
        super().report(log)


def _gib(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value) / _GIB


def _whole_gb_to_set(need_gib: float) -> int:
    return math.ceil(need_gib + VM_REPORTS_LESS_GIB)


def _gpu_line(probe: dict) -> str:
    gpu = probe.get("gpu") or {}
    test = probe.get("docker_gpu_test") or {}
    vendor = str(gpu.get("vendor") or "").lower()
    name = gpu.get("name") or "The GPU"
    vram = _gib(gpu.get("vram_bytes"))
    if probe.get("cuda_usable_in_docker") is True:
        size = f"{vram:.1f} GiB" if vram is not None else "its"
        return (f"{name}: Docker can use it, but {size} of VRAM is under the "
                f"{profiles.MIN_USABLE_VRAM_GIB:.0f} GiB the GPU profiles need.")
    if vendor == "nvidia":
        if test.get("usable") is False:
            return f"{name}, which Docker could not use."
        return f"{name}; whether Docker can use it was not tested."
    if vendor in ("amd", "intel", "apple"):
        return f"{name}, which Horus cannot use: its GPU profiles need NVIDIA CUDA."
    return "No NVIDIA GPU."


def _gpu_alternative(probe: dict) -> str:
    gpu = probe.get("gpu") or {}
    vendor = str(gpu.get("vendor") or "").lower()
    if probe.get("cuda_usable_in_docker") is True:
        return (f"Use an NVIDIA GPU with {profiles.MIN_USABLE_VRAM_GIB:.0f} GB of VRAM or "
                "more: the model then runs on the card, and this memory check is for "
                "machines that run it on the processor.")
    if vendor == "nvidia":
        return ("Make the NVIDIA GPU usable from Docker (the advice above), then run "
                "START-HERE again: the model then runs on the card, and this memory "
                "check is for machines that run it on the processor.")
    return ("Use a machine with an NVIDIA GPU that Docker can use: the model then runs "
            "on the card, and this memory check is for machines that run it on the "
            "processor.")


def _more_memory_for_docker(system: str, floor: float) -> str | None:
    lean = _whole_gb_to_set(floor)
    standard = _whole_gb_to_set(profiles.CPU_STANDARD_MIN_GIB)
    sizes = (f"{lean} GB" if lean == standard
             else f"{lean} GB (cpu-lean) or {standard} GB (cpu-standard)")
    if system == "Windows":
        settings = (f"memory={lean}GB" if lean == standard
                    else f"memory={lean}GB (cpu-lean) or memory={standard}GB (cpu-standard)")
        return ("Give Docker more memory. Docker Desktop runs in WSL 2, which gets half "
                "of the RAM by default. Open WSL Settings > Memory and processor, or put "
                f"{settings} under [wsl2] in %UserProfile%\\.wslconfig. Then run "
                "wsl --shutdown, start Docker Desktop again and run START-HERE again. "
                "The installer does not change this setting for you. Windows needs "
                f"memory of its own: in practice this takes {WINDOWS_PRACTICAL_RAM_GB} GB "
                "of RAM.")
    if system == "Darwin":
        return ("Give Docker more memory: Docker Desktop > Settings > Resources > Memory "
                f"limit, at least {sizes}, then Apply & restart and run START-HERE "
                "again. macOS needs memory of its own too.")
    return ("Docker runs in a virtual machine here and gets less than the RAM: raise its "
            f"memory to at least {sizes} (Docker Desktop > Settings > Resources), then "
            "run START-HERE again.")


def _more_memory_overall(system: str) -> str:
    if system == "Windows":
        return ("Use a machine with more memory. On Windows Docker runs in WSL 2 and "
                f"Windows needs its own share: in practice {WINDOWS_PRACTICAL_RAM_GB} GB "
                "of RAM.")
    if system == "Darwin":
        return ("Use a machine with more memory. On macOS Docker runs in a virtual "
                "machine and macOS needs its own share, so the Mac needs more RAM than "
                "Docker gets.")
    return ("Use a machine with more memory. On Linux Docker can use all of it, so a "
            "16 GB machine is enough.")


def refusal(probe: dict) -> NotSupported:
    system = str((probe.get("os") or {}).get("system") or "")
    docker = _gib((probe.get("docker") or {}).get("mem_total_bytes"))
    ram = _gib((probe.get("memory") or {}).get("total_bytes"))
    floor = profiles.cpu_floor_gib()

    have = [f"Docker can use {docker:.1f} GiB of memory." if docker is not None
            else "Docker did not say how much memory it can use."]
    if ram is not None:
        have.append(f"The machine has {ram:.1f} GiB of RAM.")
    have.append(_gpu_line(probe))

    if profiles.CPU_LEAN_SUPPORTED:
        profile_needs = (f"cpu-lean, the smaller CPU profile; cpu-standard needs "
                         f"{profiles.CPU_STANDARD_MIN_GIB:.1f} GiB")
    else:
        profile_needs = "cpu-standard, the only CPU profile the installer chooses"
    need = [
        f"{floor:.1f} GiB of memory for Docker on a machine without a usable NVIDIA "
        f"GPU ({profile_needs}).",
        f"These are {profiles.THRESHOLDS_BASIS}.",
    ]

    room_in_the_machine = ram is not None and ram >= floor
    if docker is not None and room_in_the_machine and docker < ram:
        memory = _more_memory_for_docker(system, floor)
    else:
        memory = _more_memory_overall(system)
    has_nvidia = str((probe.get("gpu") or {}).get("vendor") or "").lower() == "nvidia"
    gpu = _gpu_alternative(probe)
    alternatives = [gpu, memory] if has_nvidia else [memory, gpu]
    alternatives.append(
        "Try anyway, unsupported: run START-HERE again with --profile cpu-lean. Expect "
        "containers stopped for lack of memory, or answers that take far longer. If "
        "it works, tell us: these thresholds are still planning figures."
    )

    numbers = {
        "docker_memory_bytes": (probe.get("docker") or {}).get("mem_total_bytes"),
        "ram_bytes": (probe.get("memory") or {}).get("total_bytes"),
        "required_bytes": int(floor * _GIB),
        "os": system,
    }
    return NotSupported(have, need, alternatives, numbers)


def from_record(document: dict | None) -> NotSupported | None:
    if not isinstance(document, dict):
        return None
    refused = document.get("refusal")
    if not isinstance(refused, dict):
        return None

    def strings(key: str) -> list[str]:
        value = refused.get(key)
        return [str(item) for item in value] if isinstance(value, list) else []

    checked = str(document.get("generated_utc") or "") or None
    return NotSupported(strings("have"), strings("need"), strings("alternatives"),
                        {key: refused.get(key) for key in NUMBER_KEYS}, checked)
