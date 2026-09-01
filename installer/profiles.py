from __future__ import annotations

import sys
from dataclasses import dataclass, field

from common import EXIT_PROFILE_UNKNOWN, InstallError

MEASURED = "measured"

DERIVED = "derived"

CPU_RAM_SPLIT_GIB = 15.0

MIN_USABLE_VRAM_GIB = 6.0

VRAM_BANDS: tuple[tuple[float, float, str], ...] = (
    (6.0, 10.0, "gpu-8g"),
    (10.0, 17.0, "gpu-16g"),
    (17.0, 25.0, "gpu-24g"),
    (25.0, float("inf"), "gpu-large"),
)

VRAM_HEADROOM_NOTE = (
    "The VRAM band is wider than the card class it is named for on purpose: a "
    "card reports a little less than the number on its box, so each band runs "
    "up to the sticker size of the next class."
)

def _vram_trigger(profile_name: str) -> str:
    for low, high, name in VRAM_BANDS:
        if name != profile_name:
            continue
        if high == float("inf"):
            return f"CUDA usable from Docker, {low:.1f} GiB of VRAM or more."
        return (f"CUDA usable from Docker, at least {low:.1f} GiB and under "
                f"{high:.1f} GiB of VRAM.")
    return "CUDA usable from Docker."

@dataclass(frozen=True)
class Setting:

    value: str
    provenance: str
    why: str

@dataclass(frozen=True)
class Profile:
    name: str
    trigger: str
    runs_vllm: bool
    summary: str
    settings: dict[str, Setting]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def confidence(self) -> str:
        provs = {s.provenance for s in self.settings.values()}
        return MEASURED if provs == {MEASURED} else DERIVED

_ROUTER_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
_WORKER_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
_SMALL_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"

_N_RESULTS = Setting(
    "10", MEASURED,
    "Retrieval breadth. Raising 4 -> 10 is what stopped the worker inventing "
    "figures on the demo corpus; it quoted the real number instead.",
)

_SERVED_NAME = "qwen3-4b"

def _vllm_common() -> dict[str, Setting]:
    return {
        "LLM_BACKEND": Setting(
            "vllm", MEASURED,
            "Generation goes to the vllm container's OpenAI API. There is no "
            "fallback: if vllm is down, chat returns HTTP 500.",
        ),
        "LLM_VLLM_URL": Setting(
            "http://vllm:8000/v1", MEASURED,
            "In-network address of the vllm service. The code default points at "
            "the host instead, which is wrong inside Compose.",
        ),
        "LLM_VLLM_MODEL": Setting(
            _SERVED_NAME, MEASURED,
            "Must equal VLLM_SERVED_MODEL_NAME or MAS requests a model the "
            "server does not host.",
        ),
        "VLLM_SERVED_MODEL_NAME": Setting(
            _SERVED_NAME, MEASURED,
            "The --served-model-name the vllm container advertises.",
        ),
        "LLM_FORCE_CPU": Setting(
            "0", MEASURED, "Let the MAS router use CUDA when the container sees a card.",
        ),
        "MODEL_DEVICE": Setting(
            "auto", MEASURED, "Agent picks CUDA inside the container when it is visible.",
        ),
        "LLM_MODEL_ID": Setting(
            _ROUTER_MODEL, MEASURED,
            "MAS only routes and decomposes, so it keeps the 1.5B model.",
        ),
        "MODEL_NAME": Setting(
            _WORKER_MODEL, MEASURED,
            "Agent worker model. With LLM_BACKEND=vllm this is the in-process "
            "fallback identity; generation itself happens in vllm.",
        ),
        "TASK_TIMEOUT": Setting(
            "1800", MEASURED,
            "Wall-clock cap on a RUNNING task in MAS. Generous; the binding "
            "limit on a single answer is REACT_TIMEOUT_SECONDS below.",
        ),
        "REACT_TIMEOUT_SECONDS": Setting(
            "120", MEASURED,
            "What actually bounds one chat answer. 120s is the code's GPU "
            "default and the value the shipping stack runs with.",
        ),
        "KNOWLEDGE_STORE_N_RESULTS": _N_RESULTS,
    }

def _cpu_common() -> dict[str, Setting]:
    return {
        "LLM_BACKEND": Setting(
            "transformers", MEASURED,
            "In-process HuggingFace inference. The pinned vllm image is CUDA-only "
            "and crash-loops on a CPU host, so it must not be the backend here.",
        ),
        "LLM_FORCE_CPU": Setting(
            "1", MEASURED, "No CUDA to find; say so instead of letting torch probe and fail.",
        ),
        "MODEL_DEVICE": Setting("cpu", MEASURED, "Same, for the agent worker."),
        "KNOWLEDGE_STORE_EMBED_DEVICE": Setting(
            "cpu", MEASURED, "There is no GPU for the BGE embedder either.",
        ),
        "TASK_TIMEOUT": Setting(
            "3600", DERIVED,
            "CPU generation is roughly an order of magnitude slower. At the GPU "
            "default MAS cancels the task mid-answer and chat hangs on 'loading'. "
            "The doubling of the 1800s GPU value is reasoning, not a measured "
            "CPU run - no CPU-only machine has been benchmarked.",
        ),
        "REACT_TIMEOUT_SECONDS": Setting(
            "1800", DERIVED,
            "The real per-answer limit. On expiry the user gets 'The model took "
            "too long to respond.' as a COMPLETED task, so a low value looks "
            "like a bad answer rather than a timeout. 1800s is a guess with a "
            "wide margin: the code's own device-aware CPU default is 900s, and "
            "neither number has been timed on a CPU-only host.",
        ),
        "KNOWLEDGE_STORE_N_RESULTS": _N_RESULTS,
    }

PROFILES: dict[str, Profile] = {}

def _add(p: Profile) -> None:
    PROFILES[p.name] = p

_add(Profile(
    name="cpu-lean",
    trigger=f"No CUDA usable from Docker, under about 16 GB of RAM "
            f"(threshold {CPU_RAM_SPLIT_GIB:.1f} GiB reported).",
    runs_vllm=False,
    summary="Smallest everything. Slow but it finishes.",
    settings={
        **_cpu_common(),
        "LLM_MODEL_ID": Setting(
            _SMALL_MODEL, MEASURED,
            "1.5B router - the shipping default, unchanged.",
        ),
        "MODEL_NAME": Setting(
            _SMALL_MODEL, DERIVED,
            "1.5B worker too. The 4B model needs ~9 GB of resident RAM on top of "
            "twelve containers; on a small machine it swaps and never finishes. "
            "That is the argument for downgrading the worker, not a measurement "
            "of it - the swap has been reasoned about, never timed.",
        ),
    },
    notes=(
        "Answer quality is noticeably below the GPU stack: this is the 1.5B "
        "model doing work the 4B model normally does.",
        "Expect minutes, not seconds, for the first answer of a session.",
        "No CPU-only machine has been benchmarked. The timeouts and the model "
        "downgrade are reasoned, not measured - if this profile behaves oddly, "
        "suspect those numbers before you suspect a bug.",
    ),
))

_add(Profile(
    name="cpu-standard",
    trigger=f"No CUDA usable from Docker, about 16 GB of RAM or more "
            f"(threshold {CPU_RAM_SPLIT_GIB:.1f} GiB reported).",
    runs_vllm=False,
    summary="Today's tiered defaults, forced onto the CPU.",
    settings={
        **_cpu_common(),
        "LLM_MODEL_ID": Setting(
            _ROUTER_MODEL, MEASURED, "1.5B router - the shipping default.",
        ),
        "MODEL_NAME": Setting(
            _WORKER_MODEL, MEASURED, "4B worker - the shipping default.",
        ),
    },
    notes=(
        "This is the shipping model pair; only the device changes.",
        "MEASURED 2026-09-01, on a 14-core laptop CPU with 32 GB of RAM - the "
        "first time this profile has ever been run. One grounded question took "
        "14m 14s end to end, and the answer was WRONG: the agent's anti-spiral "
        "guard fired instead of an answer. Retrieval was fine (the right "
        "document ranked first and contained the figure); generation is what "
        "failed. Everything else passed - auth, RBAC, five agents registering, "
        "ingestion, the chat socket.",
        "So treat this profile as 'the stack comes up and is demonstrably "
        "correct everywhere except the model'. On the same repo a GPU run "
        "answers in about 4 seconds.",
        "The timeouts are still DERIVED, not fitted - but the 1800s ReAct "
        "budget was at least shown to be generous rather than tight: the slow "
        "run finished well inside it and was not truncated.",
    ),
))

_add(Profile(
    name="gpu-8g",
    trigger=_vram_trigger("gpu-8g"),
    runs_vllm=True,
    summary="The tuned 8 GB laptop configuration. The one that has actually been run.",
    settings={
        **_vllm_common(),
        "VLLM_MAX_MODEL_LEN": Setting(
            "8192", MEASURED,
            "Longest context that leaves room for a KV cache on an 8 GB card.",
        ),
        "VLLM_GPU_MEMORY_UTILIZATION": Setting(
            "0.70", MEASURED,
            "0.70, not higher: the other three services also request the card, "
            "and vLLM reserving more triggers OOM at load time.",
        ),
        "KNOWLEDGE_STORE_EMBED_DEVICE": Setting(
            "cpu", MEASURED,
            "Keeps the BGE embedder OFF the shared card. On GPU its ingestion "
            "bursts page out the 4B model and generation stalls afterwards - "
            "this was measured, not assumed.",
        ),
    },
    notes=(
        "Every number here reproduces the configuration the project ships and "
        "runs today. Nothing in this profile is a guess.",
        VRAM_HEADROOM_NOTE,
    ),
))

_add(Profile(
    name="gpu-16g",
    trigger=_vram_trigger("gpu-16g"),
    runs_vllm=True,
    summary="Longer context, embedder back on the card.",
    settings={
        **_vllm_common(),
        "VLLM_MAX_MODEL_LEN": Setting(
            "16384", DERIVED,
            "Doubled from the 8 GB value because roughly twice the VRAM is free "
            "for the KV cache. Not benchmarked.",
        ),
        "VLLM_GPU_MEMORY_UTILIZATION": Setting(
            "0.80", DERIVED,
            "The card has headroom the 8 GB one does not, so vLLM can claim more "
            "and still leave room for the embedder. Not benchmarked.",
        ),
        "KNOWLEDGE_STORE_EMBED_DEVICE": Setting(
            "cuda", DERIVED,
            "The eviction problem that forced the embedder to CPU on 8 GB should "
            "not occur here. Untested: if ingestion makes chat stall, set this "
            "back to cpu.",
        ),
    },
    notes=(
        "Scaled from the 8 GB configuration, not benchmarked. If it misbehaves, "
        "the fastest test is to re-run with --profile gpu-8g.",
        VRAM_HEADROOM_NOTE,
    ),
))

_add(Profile(
    name="gpu-24g",
    trigger=_vram_trigger("gpu-24g"),
    runs_vllm=True,
    summary="Full 32k context.",
    settings={
        **_vllm_common(),
        "VLLM_MAX_MODEL_LEN": Setting(
            "32768", DERIVED,
            "The model's full trained context. Room for it exists at this VRAM "
            "size on paper. Not benchmarked.",
        ),
        "VLLM_GPU_MEMORY_UTILIZATION": Setting(
            "0.85", DERIVED,
            "Higher still, leaving ~15% for the other three GPU services. "
            "Not benchmarked.",
        ),
        "KNOWLEDGE_STORE_EMBED_DEVICE": Setting(
            "cuda", DERIVED, "Plenty of room for the embedder alongside vLLM. Untested.",
        ),
    },
    notes=(
        "Scaled from the 8 GB configuration, not benchmarked.",
        "A 32k context does not make answers better on its own - it mostly "
        "raises the ceiling for long documents.",
        VRAM_HEADROOM_NOTE,
    ),
))

_add(Profile(
    name="gpu-large",
    trigger=_vram_trigger("gpu-large"),
    runs_vllm=True,
    summary="Same as gpu-24g. The card is bigger than anything we have tuned for.",
    settings={
        **_vllm_common(),
        "VLLM_MAX_MODEL_LEN": Setting(
            "32768", DERIVED, "Full trained context of the 4B model; more is not useful.",
        ),
        "VLLM_GPU_MEMORY_UTILIZATION": Setting(
            "0.85", DERIVED,
            "Deliberately NOT raised further: on a large card 0.85 already "
            "reserves far more than the 4B model needs.",
        ),
        "KNOWLEDGE_STORE_EMBED_DEVICE": Setting(
            "cuda", DERIVED, "Ample room for the embedder. Untested.",
        ),
    },
    notes=(
        "This card is under-used. The bottleneck is the model, not the GPU: "
        "the stack serves a 4B AWQ model that fits in 8 GB.",
        "To use the card properly, serve something bigger by hand in "
        "src/infra/.env - for example VLLM_MODEL=Qwen/Qwen3-14B-Instruct or a "
        "larger AWQ build. THREE values must change together or chat 404s:",
        "    VLLM_MODEL, VLLM_SERVED_MODEL_NAME, LLM_VLLM_MODEL",
        "The installer does not do this for you because we have not run it, and "
        "a beta that half-works is worse than one that is merely modest.",
        VRAM_HEADROOM_NOTE,
    ),
))

MANAGED_KEYS: tuple[str, ...] = tuple(sorted(
    {"COMPOSE_FILE"} | {k for p in PROFILES.values() for k in p.settings}
))

PROFILE_ORDER: tuple[str, ...] = (
    "cpu-lean", "cpu-standard", "gpu-8g", "gpu-16g", "gpu-24g", "gpu-large",
)

CPU_OVERLAY = "docker-compose.cpu.yml"
BASE_COMPOSE = "docker-compose.yml"

def get(profile_name: str) -> Profile:
    try:
        return PROFILES[profile_name]
    except KeyError:
        raise InstallError(
            EXIT_PROFILE_UNKNOWN,
            f"Unknown hardware profile: {profile_name!r}",
            "Valid profiles are:\n  " + "\n  ".join(
                f"{n:<13} {PROFILES[n].trigger}" for n in PROFILE_ORDER
            ),
            "Drop --profile to let the installer detect your hardware, or pass\n"
            "one of the names above exactly as written.",
        ) from None

def _gib(n: int | float | None) -> float | None:
    return None if not n else float(n) / (1024.0 ** 3)

def _cpu_profile_for_ram(ram_gib: float | None) -> tuple[str, str]:
    if ram_gib is None:
        return "cpu-lean", (
            "Total RAM could not be measured, so the smaller-model profile "
            "is chosen. It is the one that cannot run out of memory."
        )
    if ram_gib < CPU_RAM_SPLIT_GIB:
        return "cpu-lean", (
            f"{ram_gib:.1f} GiB RAM is under the {CPU_RAM_SPLIT_GIB:.0f} GiB "
            "line, so the 1.5B model is used for both the router and the "
            "worker. The 4B worker would swap on this machine."
        )
    return "cpu-standard", (
        f"{ram_gib:.1f} GiB RAM is enough for the shipping model pair "
        "(1.5B router, 4B worker) held in system memory."
    )

def select_profile(probe: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    gpu = probe.get("gpu") or {}
    mem = probe.get("memory") or {}
    osinfo = probe.get("os") or {}
    gpu_test = probe.get("docker_gpu_test") or {}

    vram_gib = _gib(gpu.get("vram_bytes"))
    ram_gib = _gib(mem.get("total_bytes"))
    usable = probe.get("cuda_usable_in_docker") is True
    outcome = gpu_test.get("usable")

    vendor = (gpu.get("vendor") or "unknown").lower()
    name = gpu.get("name") or "no GPU detected"

    if not usable:
        if osinfo.get("system") == "Darwin":
            reasons.append(
                "macOS: Docker Desktop cannot pass a GPU through to a Linux "
                "container, and the vLLM image is CUDA-only with no ARM build. "
                "Every Mac runs Horus on the CPU."
            )
        elif vendor in ("amd", "intel"):
            reasons.append(
                f"GPU is {name} ({vendor.upper()}). The stack's pinned vLLM image "
                "is CUDA-only; ROCm and oneAPI are out of scope for the beta, so "
                "this card cannot be used."
            )
        elif outcome is False:
            reasons.append(
                "The Docker GPU test failed: a container could not open a CUDA "
                "device. Whatever the host reports, the stack has no GPU."
            )
            if vram_gib is not None and vendor == "nvidia":
                reasons.append(
                    f"The host does have {name} with {vram_gib:.1f} GiB VRAM, so "
                    "this is worth fixing - see the advice in install-log.txt, "
                    "then re-run the installer."
                )
        else:
            skipped = gpu_test.get("skipped_reason") or "it was not attempted"
            reasons.append(
                f"The Docker GPU test did not run ({skipped}), so a working GPU "
                "cannot be assumed. The CPU profile is the only safe answer."
            )
            if vram_gib is not None and vendor == "nvidia":
                reasons.append(
                    f"The host reports {name} with {vram_gib:.1f} GiB VRAM. That "
                    "is a hint, not a verdict: re-run without skipping the GPU "
                    "test to find out whether Docker can actually use it."
                )

        name_cpu, why = _cpu_profile_for_ram(ram_gib)
        reasons.append(why)
        return name_cpu, reasons

    reasons.append(
        "A Docker container successfully ran nvidia-smi and saw a CUDA device. "
        "This is the test that decides, and it passed."
    )
    if vram_gib is None:
        reasons.append(
            f"VRAM on {name} could not be read, so the most conservative GPU "
            "profile is used. It is the one that is known to fit in 8 GB."
        )
        return "gpu-8g", reasons

    if vram_gib < MIN_USABLE_VRAM_GIB:
        reasons.append(
            f"{name} has {vram_gib:.1f} GiB of VRAM, under the "
            f"{MIN_USABLE_VRAM_GIB:.0f} GiB the 4B AWQ weights plus a usable KV "
            "cache need. CUDA works, but the model would not fit, so the CPU "
            "profile is safer than a card that OOMs on every request."
        )
        name_cpu, why = _cpu_profile_for_ram(ram_gib)
        reasons.append(why)
        return name_cpu, reasons

    for low, high, pname in VRAM_BANDS:
        if low <= vram_gib < high:
            reasons.append(f"{name} reports {vram_gib:.1f} GiB VRAM -> {pname}.")
            if pname == "gpu-8g":
                reasons.append(
                    "This is the configuration the project actually runs on. "
                    "Every number in it is measured."
                )
            else:
                reasons.append(
                    "The tuning numbers for this profile are scaled from the "
                    "measured 8 GB configuration and have NOT been benchmarked. "
                    "If something looks wrong, re-run with --profile gpu-8g."
                )
            return pname, reasons

    reasons.append(
        f"{vram_gib:.1f} GiB VRAM did not match any band; falling back to the "
        "profile that is known to work."
    )
    return "gpu-8g", reasons

def _compose_file_value(runs_vllm: bool, probe: dict | None) -> str:
    platform = ""
    if probe:
        platform = str((probe.get("os") or {}).get("platform") or "")
    platform = platform or sys.platform
    sep = ";" if platform.startswith("win") else ":"

    if runs_vllm:
        return BASE_COMPOSE
    return sep.join((BASE_COMPOSE, CPU_OVERLAY))

def env_for(profile_name: str, probe: dict | None = None) -> dict[str, str]:
    profile = get(profile_name)
    env = {k: s.value for k, s in profile.settings.items()}
    env["COMPOSE_FILE"] = _compose_file_value(profile.runs_vllm, probe)
    return env

def provenance_for(profile_name: str) -> dict[str, dict[str, str]]:
    profile = get(profile_name)
    out: dict[str, dict[str, str]] = {
        key: {"value": s.value, "provenance": s.provenance, "why": s.why}
        for key, s in profile.settings.items()
    }
    out["COMPOSE_FILE"] = {
        "value": _compose_file_value(profile.runs_vllm, None),
        "provenance": MEASURED,
        "why": (
            "Selects the CPU overlay. `gpus: []` and `gpus: null` do not work - "
            "Compose appends sequences - so the overlay uses `!reset`."
        ),
    }
    return out

def describe(profile_name: str) -> str:
    p = get(profile_name)
    env = env_for(profile_name)

    lines = [
        f"Profile: {p.name}",
        f"  {p.summary}",
        "",
        f"  Selected when:  {p.trigger}",
        f"  vLLM service:   {'starts (GPU inference)' if p.runs_vllm else 'NOT started'}",
        f"  Confidence:     {'measured - this exact config has been run' if p.confidence == MEASURED else 'derived - reasoned from the measured gpu-8g config, NOT benchmarked'}",
        "",
        "  Writes to src/infra/.env:",
    ]

    width = max(len(k) for k in env)
    for key, value in env.items():
        setting = p.settings.get(key)
        tag = f"[{setting.provenance}]" if setting else f"[{MEASURED}]"
        lines.append(f"    {key:<{width}} = {value}   {tag}")

    lines.append("")
    lines.append("  Why those numbers:")
    for key in env:
        setting = p.settings.get(key)
        why = setting.why if setting else (
            "Activates the CPU Compose overlay (or clears it on a GPU machine)."
        )
        lines.append(f"    {key}:")
        for chunk in _wrap(why, 66):
            lines.append(f"      {chunk}")

    if p.notes:
        lines.append("")
        lines.append("  Notes:")
        for note in p.notes:
            wrapped = _wrap(note, 66)
            lines.append(f"    - {wrapped[0]}")
            lines.extend(f"      {c}" for c in wrapped[1:])

    return "\n".join(lines)

def _wrap(text: str, width: int) -> list[str]:
    if text.startswith("    "):
        return [text]
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out or [""]

def describe_all() -> str:
    return "\n\n".join(describe(n) for n in PROFILE_ORDER)
