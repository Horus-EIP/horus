from __future__ import annotations

import os
import threading
from enum import Enum
from pathlib import Path

try:
    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)
except ImportError:
    torch = None
    AutoModelForCausalLM = None
    AutoTokenizer = None
    BitsAndBytesConfig = None

from core.config import settings
from core.logger import get_logger
from core.metrics import observe_prompt_tokens

logger = get_logger("llm_setup")

DEFAULT_PROMPT_TOKEN_BUDGET = 4096
CONSERVATIVE_CHARS_PER_TOKEN = 3
UNLABELLED_CALL = "other"
PURPOSE_HEADER = "X-Horus-Purpose"


class PromptTokenSource(str, Enum):
    USAGE = "usage"
    TOKENIZER = "tokenizer"
    ESTIMATE = "estimate"


def prompt_token_budget() -> int:
    raw = os.getenv("LLM_PROMPT_TOKEN_BUDGET", "").strip()
    try:
        budget = int(raw)
    except ValueError:
        return DEFAULT_PROMPT_TOKEN_BUDGET
    return budget if budget > 0 else DEFAULT_PROMPT_TOKEN_BUDGET


def estimate_prompt_tokens(messages: list) -> int:
    characters = sum(len(str(message.get("content", ""))) for message in messages)
    return -(-characters // CONSERVATIVE_CHARS_PER_TOKEN)


def record_prompt_tokens(call: str, tokens: int, source: PromptTokenSource) -> None:
    budget = prompt_token_budget()
    over_budget = observe_prompt_tokens(call, source.value, tokens, budget)
    logger.info(
        "LLM prompt tokens",
        call=call,
        prompt_tokens=tokens,
        source=source.value,
        budget=budget,
    )
    if over_budget:
        logger.warning(
            "LLM prompt over its token budget",
            call=call,
            prompt_tokens=tokens,
            budget=budget,
        )


def _served_prompt_tokens(data: dict, messages: list) -> tuple[int, PromptTokenSource]:
    usage = data.get("usage") if isinstance(data, dict) else None
    tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    if isinstance(tokens, int) and not isinstance(tokens, bool):
        return tokens, PromptTokenSource.USAGE
    return estimate_prompt_tokens(messages), PromptTokenSource.ESTIMATE


IN_PROCESS_STACK_MISSING = (
    "The in-process router LLM needs torch and transformers, which this image does not "
    "ship: CPU images leave them out. Set LLM_BACKEND=vllm and LLM_VLLM_URL to use "
    "llama-server or vLLM, or run the GPU image."
)

os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True,max_split_size_mb:64"
)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
if torch is not None:
    torch.backends.cuda.matmul.allow_tf32 = True


def _configure_llm_cpu_threads() -> None:
    """Use more CPU cores when the orchestrator runs on CPU (default was 1 thread = very slow)."""
    raw = os.getenv("LLM_TORCH_INTRAOP_THREADS", "").strip()
    if raw:
        try:
            n = max(1, int(raw))
        except ValueError:
            n = max(1, min(8, (os.cpu_count() or 4)))
    else:
        n = max(1, min(8, (os.cpu_count() or 4)))
    os.environ.setdefault("OMP_NUM_THREADS", str(n))
    torch.set_num_threads(n)
    logger.info("LLM CPU thread budget: OMP/torch intra-op=%s", n)


if torch is not None:
    _configure_llm_cpu_threads()


def _require_in_process_stack() -> None:
    if torch is None or AutoModelForCausalLM is None or AutoTokenizer is None:
        raise RuntimeError(IN_PROCESS_STACK_MISSING)


def _cpu_dtype() -> torch.dtype:
    """Weight dtype for a CPU load.

    float16 is the wrong default on CPU: many PyTorch CPU kernels have no fp16
    path, so generation is either pathologically slow or raises outright. Prefer
    bfloat16 (same 2 bytes per weight, widely supported) and fall back to
    float32, which always works but doubles resident memory. Override with
    LLM_CPU_DTYPE=bfloat16|float32|float16.
    """
    aliases = {
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float32": torch.float32,
        "fp32": torch.float32,
        "float16": torch.float16,
        "fp16": torch.float16,
    }
    override = os.getenv("LLM_CPU_DTYPE", "").strip().lower()
    if override:
        if override in aliases:
            return aliases[override]
        logger.warning("Ignoring unknown LLM_CPU_DTYPE=%r", override)
    try:
        probe = torch.zeros(2, 2, dtype=torch.bfloat16)
        _ = probe @ probe
        return torch.bfloat16
    except Exception:
        return torch.float32


BASE_DIR = Path(__file__).resolve().parent.parent
# MAS is a thin router/classifier — it picks an agent, sometimes decomposes a
# task into subtasks, and otherwise gets out of the way. That work doesn't
# need a big model, so we default to Qwen2.5-1.5B-Instruct (~3 GB, Apache 2.0,
# no Hub gating). The agent worker keeps the full 4B model for actual task
# execution (RAG synthesis, answer generation). Override LLM_MODEL_ID if you
# want a different MAS-side model (e.g. bump to 4B if decomposition quality
# matters more than orchestrator latency).
MODEL_ID = os.environ.get("LLM_MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct").strip()


def _resolve_model_dir() -> Path:
    explicit = os.environ.get("LLM_MODEL_DIR", "").strip()
    if explicit:
        return Path(explicit)
    leaf = MODEL_ID.split("/")[-1] or "model"
    return BASE_DIR / "models" / leaf


MODEL_DIR = _resolve_model_dir()
OFFLOAD_DIR = BASE_DIR / "offload"
OFFLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Minimum files we expect after a successful snapshot_download. ``tokenizer.json``
# is universal across HF causal-LM repos; ``config.json`` is required to load
# the model. The old list expected sharded weights which only exist on >2 GB
# checkpoints — 1.5B models ship a single ``model.safetensors`` instead.
REQUIRED_FILES = [
    "config.json",
    "tokenizer.json",
]


def is_model_dir_exists():
    if not os.path.exists(MODEL_DIR):
        return False
    missing = [f for f in REQUIRED_FILES if not (MODEL_DIR / f).exists()]
    if missing:
        logger.warning(f"Model files missing in folder {MODEL_DIR}: {missing}")
        return False
    return True


def _accelerate_max_memory() -> dict | None:
    """
    If LLM_GPU_MEMORY_CAP is unset, return None so Accelerate uses all visible VRAM
    (avoids the old 3.2GiB cap that forced heavy CPU offload).
    Set e.g. LLM_GPU_MEMORY_CAP=6GiB and LLM_CPU_OFFLOAD_CAP=16GiB to limit/split.
    """
    cap = os.getenv("LLM_GPU_MEMORY_CAP", "").strip()
    if not cap:
        return None
    cpu = os.getenv("LLM_CPU_OFFLOAD_CAP", "8GiB").strip() or "8GiB"
    return {0: cap, "cpu": cpu}


def _llm_use_gpu() -> bool:
    if getattr(settings, "llm_force_cpu", None) == 1:
        return False
    if os.environ.get("LLM_FORCE_CPU", "").strip().lower() in ("1", "true", "yes"):
        return False
    return torch.cuda.is_available()


def _bnb4bit():
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=(
            torch.bfloat16
            if (torch.cuda.is_available() and torch.cuda.is_bf16_supported())
            else torch.float16
        ),
    )


def _model_device(model: torch.nn.Module) -> torch.device:
    try:
        return next(model.parameters()).device
    except (StopIteration, AttributeError):
        pass
    dev = getattr(model, "device", None)
    if dev is not None:
        return dev if isinstance(dev, torch.device) else torch.device(str(dev))
    return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


def get_llm():
    _require_in_process_stack()
    use_gpu = _llm_use_gpu()

    if is_model_dir_exists():
        model_path = MODEL_DIR
    else:
        model_path = MODEL_ID

    tokenizer = AutoTokenizer.from_pretrained(
        model_path, use_fast=True, trust_remote_code=True
    )

    if use_gpu:
        max_memory = _accelerate_max_memory()
        gpu_kw: dict = {
            "quantization_config": _bnb4bit(),
            "device_map": "auto",
            "low_cpu_mem_usage": True,
            "attn_implementation": "sdpa",
            "trust_remote_code": True,
        }
        if max_memory is not None:
            gpu_kw["max_memory"] = max_memory
            gpu_kw["offload_folder"] = str(OFFLOAD_DIR)
            logger.info("LLM load with max_memory=%s", max_memory)
        else:
            logger.info("LLM load without VRAM cap (uses full GPU when possible).")
        model = AutoModelForCausalLM.from_pretrained(model_path, **gpu_kw)
    else:
        cpu_dtype = _cpu_dtype()
        logger.info(
            "Loading LLM on CPU (no GPU or LLM_FORCE_CPU=1), dtype=%s.", cpu_dtype
        )
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=cpu_dtype,
            device_map={"": "cpu"},
            low_cpu_mem_usage=True,
            attn_implementation="sdpa",
            trust_remote_code=True,
        )

    model.eval()
    dev = _model_device(model)
    logger.info(
        "Orchestrator LLM ready: parameter_device=%s torch.cuda.is_available()=%s "
        "torch.version.cuda=%s (if CUDA is False, stack runs on CPU — high RAM, no GPU utilization)",
        dev,
        torch.cuda.is_available(),
        getattr(torch.version, "cuda", None),
    )
    return tokenizer, model


tokenizer = None
model = None
_llm_load_lock = threading.Lock()
_generation_lock = threading.Lock()


def _ensure_llm_loaded() -> None:
    """Load the model on first use so Uvicorn can bind and pass Docker healthchecks quickly."""
    global tokenizer, model
    if os.environ.get("TEST_MODE") == "1":
        return
    if _llm_backend() == "vllm":
        # No in-process router under vLLM — ask_llm routes to the server.
        return
    if getattr(settings, "llm_autoinit", 0) != 1:
        return
    if tokenizer is not None and model is not None:
        return
    with _llm_load_lock:
        if tokenizer is not None and model is not None:
            return
        logger.info("Loading LLM (lazy, first request or background use)...")
        tokenizer, model = get_llm()


def start_llm_preload_background_thread() -> None:
    """
    When LLM_AUTOINIT=1, load the model in a daemon thread after HTTP is up.
    Avoids blocking the first /tasks/new_task on a multi‑minute HF download + CPU load
    (which also starves the single Uvicorn worker and breaks the RabbitMQ healthcheck).
    """
    if os.environ.get("TEST_MODE") == "1":
        return
    if getattr(settings, "llm_autoinit", 0) != 1:
        return

    def _worker() -> None:
        try:
            logger.info("Background thread: preloading orchestrator LLM...")
            _ensure_llm_loaded()
            logger.info("Background thread: orchestrator LLM preload finished.")
        except Exception:
            logger.exception(
                "Background LLM preload failed; first ask_llm will retry loading."
            )

    threading.Thread(target=_worker, name="mas-llm-preload", daemon=True).start()


def _llm_backend() -> str:
    """Orchestrator LLM backend (Phase 4 Lever #3): 'transformers' (in-process
    1.5B router, default) or 'vllm' (call the external vLLM server). Under 'vllm'
    MAS does NOT load a local model and every ask_llm goes to vLLM — fixing the
    multi-agent aggregation latency (the CPU router was the e2e killer)."""
    return os.getenv("LLM_BACKEND", "transformers").strip().lower()


def _vllm_base_url() -> str:
    return os.getenv("LLM_VLLM_URL", "http://host.docker.internal:18000/v1")


def _vllm_model_name() -> str:
    return os.getenv("LLM_VLLM_MODEL", "qwen3-4b")


def _vllm_timeout() -> float:
    try:
        return float(os.getenv("LLM_VLLM_TIMEOUT", "120"))
    except ValueError:
        return 120.0


def llm_server_backend() -> bool:
    return _llm_backend() == "vllm"


def _post_chat_completion(body: dict, call: str) -> str:
    import json
    import urllib.request

    url = _vllm_base_url().rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        json.dumps(body).encode("utf-8"),
        {"Content-Type": "application/json", PURPOSE_HEADER: call},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_vllm_timeout()) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = (data["choices"][0]["message"].get("content") or "").strip()
    record_prompt_tokens(call, *_served_prompt_tokens(data, body["messages"]))
    return content


def ask_llm_with_json_schema(
    messages: list, schema_name: str, schema: dict, max_tokens: int
) -> str:
    if not llm_server_backend():
        raise RuntimeError(
            "Constrained JSON output needs the OpenAI-compatible server backend (LLM_BACKEND=vllm)."
        )
    return _post_chat_completion(
        {
            "model": _vllm_model_name(),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        },
        schema_name,
    )


def _ask_vllm(messages: list, max_new_tokens: int, call: str) -> str:
    """Run an orchestration LLM call against the external vLLM server. Greedy to
    match the in-process path; vLLM applies the chat template server-side. Uses
    stdlib urllib so no new MAS dependency / image rebuild is needed for deps."""
    # Budget max_tokens to the room left under max_model_len so a big prompt
    # (e.g. the aggregation step's full chain history) neither 400s nor silently
    # truncates. Estimate prompt tokens from chars (~chars/3, conservative).
    try:
        max_model_len = max(512, int(os.getenv("LLM_VLLM_MAX_MODEL_LEN", "8192")))
    except ValueError:
        max_model_len = 8192
    est_prompt = estimate_prompt_tokens(messages)
    safe_max = max(256, min(int(max_new_tokens), max_model_len - est_prompt - 256))
    return _post_chat_completion(
        {
            "model": _vllm_model_name(),
            "messages": messages,
            "max_tokens": safe_max,
            "temperature": 0.0,
            "stream": False,
        },
        call,
    )


def ask_llm(messages: list, max_new_tokens: int = 256, call: str = UNLABELLED_CALL):
    if _llm_backend() == "vllm":
        return _ask_vllm(messages, max_new_tokens, call)
    _require_in_process_stack()
    logger.info("Entering ask_llm, checking model...")
    _ensure_llm_loaded()
    if tokenizer is None or model is None:
        raise RuntimeError(
            "LLM is not loaded. Set LLM_AUTOINIT=1, ensure the model is available "
            "(local files under models/ or Hugging Face download), and check container "
            "memory / logs."
        )

    logger.info("Tokenizing prompt...")
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    enc = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=4096,
        add_special_tokens=True,
    )
    device = _model_device(model)
    input_ids = enc["input_ids"].to(device)
    attn_mask = enc.get("attention_mask")
    if attn_mask is not None:
        attn_mask = attn_mask.to(device)

    logger.info(f"Starting generation with max_new_tokens={max_new_tokens}...")
    import time

    queued_at = time.time()
    with _generation_lock:
        start_time = time.time()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        with torch.no_grad():
            out = model.generate(
                input_ids=input_ids,
                attention_mask=attn_mask,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                repetition_penalty=1.3,
                return_dict_in_generate=True,
                pad_token_id=tokenizer.eos_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
    logger.info(
        f"Generation finished in {time.time() - start_time:.2f}s "
        f"after waiting {start_time - queued_at:.2f}s for the previous one"
    )

    prompt_length = input_ids.size(1)
    record_prompt_tokens(call, int(prompt_length), PromptTokenSource.TOKENIZER)
    seq = out.sequences[0]
    gen_only = seq[prompt_length:]
    text = tokenizer.decode(
        gen_only, skip_special_tokens=True, clean_up_tokenization_spaces=False
    ).strip()

    return text
