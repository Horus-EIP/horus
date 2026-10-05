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

_N_RESULTS = Setting(
    "10", MEASURED,
    "Retrieval breadth. Raising 4 -> 10 is what stopped the worker inventing "
    "figures on the demo corpus; it quoted the real number instead. That was "
    "measured with whole documents; results are now passages of at most 1,000 "
    "characters, and ten of them, about 10,600 characters with their source "
    "lines, fit whole under the agent's 12,000-character context cap.",
)

_SERVED_NAME = "qwen3-4b"

GPU_MODEL_SERVER = "vllm"

CPU_MODEL_SERVER = "llm"

CPU_MODEL_SERVER_PORT = 8080

CPU_MODEL_SERVER_URL = f"http://{CPU_MODEL_SERVER}:{CPU_MODEL_SERVER_PORT}/v1"

CPU_CONTEXT_TOKENS = 8192

GGUF_BYTES = 2_497_281_120

_KNOWLEDGE_STORE_MEMORY = "6g"

_CPU_MAS_MEMORY = "3g"

_CPU_AGENT_MEMORY = "4g"

_CPU_MODEL_SERVER_MEMORY = "6g"

def _no_swap_why(swap_key: str) -> str:
    return (
        f"Compose gives the swap limit the same value unless {swap_key} is "
        "set, so the container never swaps: past its limit it is killed and "
        "restarted instead of pushing the whole host into swap."
    )

def _memory_settings() -> dict[str, Setting]:
    return {
        "MAS_MEM_LIMIT": Setting(
            _CPU_MAS_MEMORY, DERIVED,
            "MAS holds no model on the CPU: routing and aggregation run in "
            "llama-server. What is left is Python, torch, transformers and the "
            "90 MB MiniLM skill embedder, about 1 to 1.5 GB by estimate, so 3g "
            "is about twice that. MAS logs its peak RSS on every 'Completed "
            "task' line; read it before going lower. "
            + _no_swap_why("MAS_MEMSWAP_LIMIT"),
        ),
        "AGENT_MEM_LIMIT": Setting(
            _CPU_AGENT_MEMORY, DERIVED,
            "The agent holds no decision model on the CPU: it calls "
            "llama-server. Python, torch, transformers and spaCy "
            "en_core_web_sm come to about 1 to 1.5 GB by estimate. The ReAct "
            "summarize tool, which chat does not use, would load "
            "distilbart-cnn-12-6 (about 1.2 GB in fp32) on first use, and 4g "
            "holds both. The agent logs its peak RSS on every 'Task processed' "
            "line. " + _no_swap_why("AGENT_MEMSWAP_LIMIT"),
        ),
        "KNOWLEDGE_STORE_MEM_LIMIT": Setting(
            _KNOWLEDGE_STORE_MEMORY, DERIVED,
            "The knowledge store holds the BGE base embedder, spaCy "
            "en_core_web_trf, t5-small and distilbart-cnn-6-6 in fp32, about "
            "2.1 GB of weights, plus torch, Chroma and the working set of an "
            "ingestion. Sized from those weights, not measured. "
            + _no_swap_why("KNOWLEDGE_STORE_MEMSWAP_LIMIT"),
        ),
        "LLM_SERVER_MEM_LIMIT": Setting(
            _CPU_MODEL_SERVER_MEMORY, DERIVED,
            f"llama-server holds the Q4_K_M weights ({GGUF_BYTES:,} bytes, "
            "2.3 GiB, memory-mapped), the KV cache of 8,192 tokens in f16 (36 "
            "layers x 8 KV heads x 128 x 2 for K and V x 2 bytes x 8,192 = "
            "1.1 GiB) and a few hundred MB of compute buffers: about 4 GiB. "
            "--cache-ram lets its prompt cache take up to 1 GiB more, which "
            "leaves about 1 GiB of margin under 6g. Arithmetic, not a "
            "measurement. " + _no_swap_why("LLM_SERVER_MEMSWAP_LIMIT"),
        ),
    }

THREAD_KEYS: tuple[str, ...] = (
    "LLM_SERVER_THREADS", "LLM_TORCH_INTRAOP_THREADS", "AGENT_TORCH_INTRAOP_THREADS",
)

TORCH_THREADS_WITHOUT_A_MODEL = 1

PHYSICAL_CORES_FALLBACK = 4

def physical_cores(probe: dict | None) -> tuple[int, str]:
    cpu = (probe or {}).get("cpu") or {}
    count = cpu.get("physical_cores")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return PHYSICAL_CORES_FALLBACK, (
            f"the core count could not be read, so {PHYSICAL_CORES_FALLBACK} "
            "physical cores are assumed"
        )
    if cpu.get("count_is_logical_fallback"):
        return max(1, count // 2), (
            f"only the logical count ({count}) could be read, so half of it is "
            "assumed to be physical"
        )
    return count, f"{count} physical cores detected"

def _thread_settings(probe: dict | None) -> dict[str, Setting]:
    cores, basis = physical_cores(probe)
    return {
        "LLM_SERVER_THREADS": Setting(
            str(cores), DERIVED,
            f"llama-server's generation threads: all {cores} physical cores "
            f"({basis}). It is the only process that generates on this "
            "machine: MAS and the agent wait on its HTTP answer, and the "
            "knowledge store embeds the question before generation starts. "
            "Generation is bound by memory bandwidth, so hyperthreads add "
            "nothing to it and stay free for the MAS event loop, the knowledge "
            "store and the databases. llama.cpp's own default is the physical "
            "core count too. Not benchmarked; B-91 compares thread counts.",
        ),
        "LLM_TORCH_INTRAOP_THREADS": Setting(
            str(TORCH_THREADS_WITHOUT_A_MODEL), DERIVED,
            "MAS loads no model in-process on the CPU. Its torch only runs the "
            "small MiniLM skill embedder on short texts, outside generation, "
            "so one thread is enough and never competes with llama-server.",
        ),
        "AGENT_TORCH_INTRAOP_THREADS": Setting(
            str(TORCH_THREADS_WITHOUT_A_MODEL), DERIVED,
            "The agent loads no decision model on the CPU, so its torch has "
            "no generation to run. One thread, so nothing it does competes "
            "with llama-server.",
        ),
    }

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
            "vllm", DERIVED,
            "The OpenAI-compatible client mode of MAS and the agent; 'vllm' is "
            "its historical name. On the CPU the server behind it is "
            "llama-server in the llm container, one process for the router "
            "and every agent, so neither service loads or downloads a model "
            "of its own. There is no fallback: if llm is down, chat fails.",
        ),
        "LLM_VLLM_URL": Setting(
            CPU_MODEL_SERVER_URL, DERIVED,
            "In-network address of the llm service. Its port is not published "
            "to the host: only the containers on horus-net reach it, which is "
            "why it runs without an API key.",
        ),
        "LLM_VLLM_MODEL": Setting(
            _SERVED_NAME, DERIVED,
            "The name llama-server answers to. Compose passes this same value "
            "to its --alias, so the two cannot drift apart.",
        ),
        "LLM_VLLM_MAX_MODEL_LEN": Setting(
            str(CPU_CONTEXT_TOKENS), DERIVED,
            "The context both clients fit their prompt and answer into. "
            "Compose passes the same value to llama-server's --ctx-size, which "
            "otherwise takes the model's own 262,144 tokens and a KV cache far "
            "larger than this machine's RAM.",
        ),
        "LLM_VLLM_TIMEOUT": Setting(
            "900", DERIVED,
            "Seconds MAS and the agent wait on one call to llama-server. It "
            "answers one request at a time and queues the others, so a call "
            "can wait behind a whole answer before its own prompt is read. The "
            "GPU profiles keep the code default of 120. Not timed on a "
            "CPU-only host.",
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
        "KNOWLEDGE_STORE_N_RESULTS": Setting(
            "5", DERIVED,
            "Each result is a passage of at most 1,000 characters, shown with a "
            "source line of its document title: about 1,060 characters each. "
            "Five is the most that fit whole under AGENT_MAX_CONTEXT_CHARS=6000 "
            "(about 5,300 characters), so the prompt keeps the size B-89 chose "
            "while it draws on up to five places, often in different documents, "
            "instead of the first two whole documents. Six would have the cap cut "
            "the last one. Check answer quality on the test set before trusting "
            "this value.",
        ),
        "AGENT_MAX_CONTEXT_CHARS": Setting(
            "6000", DERIVED,
            "Half the 12,000-character default: about 1,500 to 2,000 tokens of "
            "retrieved text instead of 3,000 to 4,000. On a CPU the whole "
            "prompt is read before the first word of the answer, so this "
            "halves the retrieved part of that wait. It holds the five passages "
            "of KNOWLEDGE_STORE_N_RESULTS whole and only cuts when long titles "
            "make their source lines longer. Not measured yet.",
        ),
        "AGENT_STREAM_TOKENS": Setting(
            "1", DERIVED,
            "Shows the answer in the chat while it is written, so a CPU answer "
            "that takes minutes shows text long before it ends. The first 500 "
            "characters are held back and checked for a self-correction "
            "spiral before anything is shown. The chat's live preview has "
            "unit tests but has not been watched in a browser on a CPU host.",
        ),
        **_memory_settings(),
    }

PROFILES: dict[str, Profile] = {}

def _add(p: Profile) -> None:
    PROFILES[p.name] = p

_CPU_MEMORY_NOTE = (
    "The memory ceilings (MAS 3g, agent 4g, knowledge store 6g, llm 6g) are "
    "ceilings, not a budget: they add up to more than 16 GB. They stop one "
    "runaway container from pushing the host into swap. Expected use is lower: "
    "about 4 GiB for llm, 2 to 3 GB for the knowledge store and 1 to 1.5 GB "
    "each for MAS and the agent, by estimate."
)

_add(Profile(
    name="cpu-lean",
    trigger=f"No CUDA usable from Docker, under about 16 GB of RAM "
            f"(threshold {CPU_RAM_SPLIT_GIB:.1f} GiB reported).",
    runs_vllm=False,
    summary="The cpu-standard model server on a smaller machine. Untested.",
    settings=_cpu_common(),
    notes=(
        "Runs what cpu-standard runs: one llama-server (the llm service) with "
        "Qwen3-4B-Instruct-2507 Q4_K_M, about 4 GiB resident. That is less "
        "than the two 1.5B models this profile used to load in-process (6.2 GB "
        "of bf16 weights), and answers come from the 4B model again.",
        "Whether it fits next to the rest of the stack on a machine this size "
        "has not been measured. Machines under 16 GB get a smaller GGUF or a "
        "'not supported' screen once the CPU benchmark (B-91) has run.",
        "No CPU-only machine has been benchmarked with llama-server. The "
        "timeouts, threads and memory ceilings are reasoned, not measured - if "
        "this profile behaves oddly, suspect those numbers before you suspect "
        "a bug.",
        _CPU_MEMORY_NOTE,
    ),
))

_add(Profile(
    name="cpu-standard",
    trigger=f"No CUDA usable from Docker, about 16 GB of RAM or more "
            f"(threshold {CPU_RAM_SPLIT_GIB:.1f} GiB reported).",
    runs_vllm=False,
    summary="Qwen3-4B Q4_K_M on llama-server: one model for MAS and every agent.",
    settings=_cpu_common(),
    notes=(
        "One llama-server process (the llm service) serves "
        "Qwen3-4B-Instruct-2507 Q4_K_M to MAS and every agent. MAS and the "
        "agent load no model in-process and download none.",
        "Before llama-server, this profile ran a 1.5B router in MAS and the 4B "
        "worker in bf16 in the agent, both with Transformers. MEASURED "
        "2026-09-01 that way, on a 12-core laptop CPU with 64 GB of RAM: one "
        "grounded question took 14m 14s end to end and the answer was WRONG - "
        "the anti-spiral guard fired instead of an answer. Retrieval was fine "
        "and everything else passed. The same machine answers in about 4 "
        "seconds on its GPU.",
        "llama-server has not been timed on a CPU-only machine yet; the "
        "100-question test set (B-91) does that.",
        "The timeouts are still DERIVED, not fitted - but the 1800s ReAct "
        "budget was at least shown to be generous rather than tight: the slow "
        "run finished well inside it and was not truncated.",
        _CPU_MEMORY_NOTE,
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
    {"COMPOSE_FILE", *THREAD_KEYS} | {k for p in PROFILES.values() for k in p.settings}
))

PROFILE_ORDER: tuple[str, ...] = (
    "cpu-lean", "cpu-standard", "gpu-8g", "gpu-16g", "gpu-24g", "gpu-large",
)

def is_cpu_profile(name: str) -> bool:
    return str(name).startswith("cpu")

def model_server(name: str) -> str:
    return GPU_MODEL_SERVER if get(name).runs_vllm else CPU_MODEL_SERVER

def model_server_for_compose_file(compose_file: str) -> str:
    return CPU_MODEL_SERVER if CPU_OVERLAY in compose_file else GPU_MODEL_SERVER


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
            "Total RAM could not be measured, so the low-RAM profile is "
            "chosen. It runs the same llama-server model as cpu-standard."
        )
    if ram_gib < CPU_RAM_SPLIT_GIB:
        return "cpu-lean", (
            f"{ram_gib:.1f} GiB RAM is under the {CPU_RAM_SPLIT_GIB:.0f} GiB "
            "line. For now this profile runs the same llama-server model as "
            "cpu-standard; what machines this size get is decided after the "
            "CPU benchmark (B-91)."
        )
    return "cpu-standard", (
        f"{ram_gib:.1f} GiB RAM holds the llama-server 4B model (about 4 GiB) "
        "next to the rest of the stack."
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

def settings_for(profile_name: str, probe: dict | None = None) -> dict[str, Setting]:
    profile = get(profile_name)
    settings = dict(profile.settings)
    if is_cpu_profile(profile.name):
        settings.update(_thread_settings(probe))
    return settings

def env_for(profile_name: str, probe: dict | None = None) -> dict[str, str]:
    profile = get(profile_name)
    env = {k: s.value for k, s in settings_for(profile_name, probe).items()}
    env["COMPOSE_FILE"] = _compose_file_value(profile.runs_vllm, probe)
    return env

def provenance_for(profile_name: str,
                   probe: dict | None = None) -> dict[str, dict[str, str]]:
    profile = get(profile_name)
    out: dict[str, dict[str, str]] = {
        key: {"value": s.value, "provenance": s.provenance, "why": s.why}
        for key, s in settings_for(profile_name, probe).items()
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

def describe(profile_name: str, probe: dict | None = None) -> str:
    p = get(profile_name)
    env = env_for(profile_name, probe)
    settings = settings_for(profile_name, probe)

    lines = [
        f"Profile: {p.name}",
        f"  {p.summary}",
        "",
        f"  Selected when:  {p.trigger}",
        f"  Model server:   {'vllm (GPU inference)' if p.runs_vllm else 'llm (llama-server on the CPU)'}",
        f"  Confidence:     {'measured - this exact config has been run' if p.confidence == MEASURED else 'derived - reasoned from the measured gpu-8g config, NOT benchmarked'}",
        "",
        "  Writes to src/infra/.env:",
    ]

    width = max(len(k) for k in env)
    for key, value in env.items():
        setting = settings.get(key)
        tag = f"[{setting.provenance}]" if setting else f"[{MEASURED}]"
        lines.append(f"    {key:<{width}} = {value}   {tag}")

    lines.append("")
    lines.append("  Why those numbers:")
    for key in env:
        setting = settings.get(key)
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
