import os
import threading
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from core.config import settings
from core.logger import get_logger

logger = get_logger("llm_setup")

os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True,max_split_size_mb:64"
)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
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


_configure_llm_cpu_threads()

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"
MODEL_DIR = BASE_DIR / "models/Qwen3_instruct_4B"
OFFLOAD_DIR = BASE_DIR / "offload"
OFFLOAD_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_FILES = [
    "config.json",
    "generation_config.json",
    "tokenizer.json",
    "model.safetensors.index.json",
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
        logger.info("Loading LLM on CPU (no GPU or LLM_FORCE_CPU=1).")
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
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


def _ensure_llm_loaded() -> None:
    """Load the model on first use so Uvicorn can bind and pass Docker healthchecks quickly."""
    global tokenizer, model
    if os.environ.get("TEST_MODE") == "1":
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


def ask_llm(messages: list, max_new_tokens: int = 256):
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
        max_length=1024,
        add_special_tokens=True,
    )
    device = _model_device(model)
    input_ids = enc["input_ids"].to(device)
    attn_mask = enc.get("attention_mask")
    if attn_mask is not None:
        attn_mask = attn_mask.to(device)

    logger.info(f"Starting generation with max_new_tokens={max_new_tokens}...")
    import time

    start_time = time.time()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    with torch.no_grad():
        out = model.generate(
            input_ids=input_ids,
            attention_mask=attn_mask,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            return_dict_in_generate=True,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    logger.info(f"Generation finished in {time.time() - start_time:.2f}s")

    seq = out.sequences[0]
    gen_only = seq[input_ids.size(1) :]
    text = tokenizer.decode(
        gen_only, skip_special_tokens=True, clean_up_tokenization_spaces=False
    ).strip()

    return text
