"""
decision_making_agent.py
-------------------------
Loads a Hugging Face causal instruct model (default Qwen3-4B-Instruct) for RAG / ReAct answers
and writer prompts. Same family as the MAS orchestrator LLM; uses chat template + generate.
GPU uses 4-bit quantization when available unless forced to CPU; model can load lazily on first call.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import logging

logger = logging.getLogger(__name__)

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    _TRANSFORMERS_AVAILABLE = True
except Exception:
    torch = None  # type: ignore
    AutoModelForCausalLM = None  # type: ignore
    AutoTokenizer = None  # type: ignore
    BitsAndBytesConfig = None  # type: ignore
    _TRANSFORMERS_AVAILABLE = False

try:
    import torch as _torch_check

    _TORCH_AVAILABLE = _torch_check is not None
except Exception:
    _TORCH_AVAILABLE = False


def _configure_agent_torch_threads() -> None:
    if not _TORCH_AVAILABLE or torch is None:
        return
    raw = (
        os.getenv("AGENT_TORCH_INTRAOP_THREADS", "").strip()
        or os.getenv("LLM_TORCH_INTRAOP_THREADS", "").strip()
    )
    if raw:
        try:
            n = max(1, int(raw))
        except ValueError:
            n = max(1, min(8, (os.cpu_count() or 4)))
    else:
        n = max(1, min(8, (os.cpu_count() or 4)))
    os.environ.setdefault("OMP_NUM_THREADS", str(n))
    torch.set_num_threads(n)
    logger.info("Agent decision LLM CPU thread budget: torch intra-op=%s", n)


if _TRANSFORMERS_AVAILABLE:
    _configure_agent_torch_threads()

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"
LOCAL_MODEL_DIR = APP_DIR / "models" / "Qwen3_instruct_4B"
OFFLOAD_DIR = APP_DIR / "offload"
REQUIRED_LOCAL_FILES = [
    "config.json",
    "generation_config.json",
    "tokenizer.json",
    "model.safetensors.index.json",
]

def _agent_accelerate_max_memory() -> Optional[dict]:
    """
    Unset caps → use all VRAM. Set AGENT_GPU_MEMORY_CAP or LLM_GPU_MEMORY_CAP to limit/split.
    """
    cap = os.getenv("AGENT_GPU_MEMORY_CAP", "").strip() or os.getenv(
        "LLM_GPU_MEMORY_CAP", ""
    ).strip()
    if not cap:
        return None
    cpu = (
        os.getenv("AGENT_CPU_OFFLOAD_CAP", "").strip()
        or os.getenv("LLM_CPU_OFFLOAD_CAP", "8GiB").strip()
        or "8GiB"
    )
    return {0: cap, "cpu": cpu}


def _local_model_ready() -> bool:
    if not LOCAL_MODEL_DIR.is_dir():
        return False
    missing = [f for f in REQUIRED_LOCAL_FILES if not (LOCAL_MODEL_DIR / f).exists()]
    if missing:
        logger.warning("Agent LLM: missing files in %s: %s", LOCAL_MODEL_DIR, missing)
        return False
    return True


def detect_device(device_preference: str = "auto") -> str:
    if device_preference.lower() == "auto":
        if _TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
            device = "cuda"
            logger.info(
                "GPU detected: %s (CUDA %s)",
                torch.cuda.get_device_name(0),
                torch.version.cuda,
            )
            return device
        device = "cpu"
        if not _TORCH_AVAILABLE:
            logger.info("PyTorch not available, using CPU")
        else:
            logger.info("No GPU available, using CPU")
        return device
    if device_preference.startswith("cuda") and _TORCH_AVAILABLE and torch is not None:
        if not torch.cuda.is_available():
            logger.warning("CUDA requested but not available, falling back to CPU")
            return "cpu"
    return device_preference


def _lazy_model_enabled() -> bool:
    v = os.getenv("AGENT_LAZY_DECISION_MODEL", "0").strip().lower()
    return v in ("1", "true", "yes")


def _agent_force_cpu() -> bool:
    return os.getenv("AGENT_FORCE_CPU", "").strip().lower() in ("1", "true", "yes")


def _max_new_tokens() -> int:
    raw = os.getenv("AGENT_MAX_NEW_TOKENS", "256").strip()
    try:
        return max(8, int(raw))
    except ValueError:
        return 256


def _bnb4bit():
    assert BitsAndBytesConfig is not None
    assert torch is not None
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


def _model_device(model: Any) -> Any:
    try:
        return next(model.parameters()).device
    except (StopIteration, AttributeError):
        pass
    dev = getattr(model, "device", None)
    if dev is not None:
        return dev if isinstance(dev, torch.device) else torch.device(str(dev))
    assert torch is not None
    return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


class DecisionMakingAgent:
    def __init__(
        self,
        decision_model: Optional[Callable[..., Any]] = None,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.model_name = model_name or DEFAULT_MODEL_ID
        self.device = detect_device(device) if device else detect_device("auto")
        self.decision_model: Optional[Callable[..., Any]] = decision_model
        self._lazy = decision_model is None and _lazy_model_enabled()
        self._causal_tokenizer = None
        self._causal_model = None
        self._load_lock = threading.Lock()

        if decision_model is not None:
            logger.info(
                "DecisionMakingAgent initialized with injected model on device: %s",
                self.device,
            )
            return

        if not _TRANSFORMERS_AVAILABLE:
            raise RuntimeError(
                "transformers/torch are required for DecisionMakingAgent. "
                "Install dependencies and rebuild the agent image."
            )

        OFFLOAD_DIR.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault(
            "PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True,max_split_size_mb:64"
        )
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        if torch is not None:
            torch.set_num_threads(1)
            torch.backends.cuda.matmul.allow_tf32 = True

        if self._lazy:
            logger.info(
                "Decision model will load on first use (AGENT_LAZY_DECISION_MODEL=1)."
            )
            return

        self._load_causal_model()

    def _resolve_model_path(self) -> str:
        if _local_model_ready():
            return str(LOCAL_MODEL_DIR)
        return self.model_name

    def _use_gpu_for_load(self) -> bool:
        if _agent_force_cpu():
            return False
        return bool(
            self.device.startswith("cuda")
            and torch is not None
            and torch.cuda.is_available()
        )

    def _load_causal_model(self) -> None:
        assert AutoTokenizer is not None and AutoModelForCausalLM is not None
        with self._load_lock:
            if self._causal_model is not None and self._causal_tokenizer is not None:
                return

            model_path = self._resolve_model_path()
            tokenizer = AutoTokenizer.from_pretrained(
                model_path, use_fast=True, trust_remote_code=True
            )

            use_gpu = self._use_gpu_for_load()
            try:
                if use_gpu:
                    max_memory = _agent_accelerate_max_memory()
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
                        logger.info(
                            "Agent LLM load with max_memory=%s", max_memory
                        )
                    else:
                        logger.info(
                            "Agent LLM load without VRAM cap (full GPU when possible)."
                        )
                    model = AutoModelForCausalLM.from_pretrained(
                        model_path,
                        **gpu_kw,
                    )
                else:
                    logger.info("Loading agent decision LLM on CPU.")
                    model = AutoModelForCausalLM.from_pretrained(
                        model_path,
                        torch_dtype=torch.float16,
                        device_map={"": "cpu"},
                        low_cpu_mem_usage=True,
                        attn_implementation="sdpa",
                        trust_remote_code=True,
                    )
            except Exception as e:
                if use_gpu:
                    logger.warning(
                        "Agent LLM GPU load failed (%s), retrying on CPU.", e
                    )
                    self.device = "cpu"
                    model = AutoModelForCausalLM.from_pretrained(
                        model_path,
                        torch_dtype=torch.float16,
                        device_map={"": "cpu"},
                        low_cpu_mem_usage=True,
                        attn_implementation="sdpa",
                        trust_remote_code=True,
                    )
                else:
                    logger.exception("Failed to load agent decision LLM on CPU")
                    raise RuntimeError(
                        "Could not load the Hugging Face decision model "
                        "(check memory, disk, and network). "
                        f"Original error: {e}"
                    ) from e

            model.eval()
            self._causal_tokenizer = tokenizer
            self._causal_model = model
            p_dev = _model_device(model)
            logger.info(
                "DecisionMakingAgent model '%s' ready: param_device=%s preference=%s "
                "torch.cuda.is_available()=%s",
                model_path,
                p_dev,
                self.device,
                torch.cuda.is_available() if torch is not None else False,
            )

    def _ensure_causal_loaded(self) -> None:
        if self.decision_model is not None:
            return
        if self._causal_model is not None:
            return
        self._load_causal_model()

    @staticmethod
    def _coerce_callable_output(result: Any) -> str:
        if (
            isinstance(result, list)
            and result
            and isinstance(result[0], dict)
            and "generated_text" in result[0]
        ):
            return str(result[0]["generated_text"]).strip()
        return str(result).strip()

    def _generate_causal(self, user_content: str, system_content: str) -> str:
        assert self._causal_tokenizer is not None and self._causal_model is not None
        tok = self._causal_tokenizer
        model = self._causal_model

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
        prompt = tok.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        enc = tok(
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

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        max_new = _max_new_tokens()
        with torch.no_grad():
            out = model.generate(
                input_ids=input_ids,
                attention_mask=attn_mask,
                max_new_tokens=max_new,
                do_sample=False,
                return_dict_in_generate=True,
                pad_token_id=tok.eos_token_id,
                eos_token_id=tok.eos_token_id,
            )

        seq = out.sequences[0]
        gen_only = seq[input_ids.size(1) :]
        return tok.decode(
            gen_only,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        ).strip()

    def decide(self, query: str, context: Optional[str] = None) -> str:
        """
        Run inference. If ``context`` is None, ``query`` is treated as the full user message
        (used by WriterAgent). Otherwise the usual grounded QA instruction is applied.
        """
        self._ensure_causal_loaded()

        try:
            from core.metrics import (
                model_inference_duration,
                model_inference_total,
            )

            _METRICS_AVAILABLE = True
        except ImportError:
            _METRICS_AVAILABLE = False

        if context is None:
            user_content = query
            system_content = (
                "You are a helpful assistant. Follow the user's instructions concisely."
            )
        else:
            user_content = (
                "The following content was retrieved from the knowledge base for this task. "
                "Use ONLY this retrieved content to complete the task. "
                "If summarizing, be thorough but structured. "
                "If the retrieved content does not contain enough information, say so.\n\n"
                f"Retrieved Content:\n{context}\n\nTask: {query}"
            )
            system_content = (
                "You are a helpful assistant. Use only the retrieved content to complete the task. "
                "Format every answer in Markdown: start with a brief ## heading when the answer "
                "has multiple parts, use **bold** for important labels, use bullet lists for "
                "enumerations, and keep paragraphs short so the reply is easy to scan."
            )

        logger.debug(
            "Decision inference model=%s device=%s", self.model_name, self.device
        )
        start_time = time.time()

        try:
            if self.decision_model is not None:
                prompt = (
                    f"{system_content}\n\n{user_content}"
                    if context is None
                else (
                    "You are a helpful assistant. Answer using ONLY the provided context. "
                    "Format the answer in Markdown (## heading when helpful, **bold** labels, "
                    "bullet lists for multiple items, short paragraphs). "
                    "If the user asked for a summary, cover the main points without inventing facts. "
                    "If the answer is not present in the context, say: "
                    "'I don't have that information yet.'\n\n"
                    f"Context:\n{context}\n\nQuestion: {query}\nAnswer:"
                )
                )
                result = self.decision_model(prompt)
                text = self._coerce_callable_output(result)
            else:
                text = self._generate_causal(user_content, system_content)

            inference_duration = time.time() - start_time
            if _METRICS_AVAILABLE:
                model_inference_duration.labels(
                    model_name=self.model_name,
                    device=self.device,
                ).observe(inference_duration)
                model_inference_total.labels(
                    model_name=self.model_name,
                    device=self.device,
                    status="success",
                ).inc()
            return text
        except Exception as e:
            inference_duration = time.time() - start_time
            if _METRICS_AVAILABLE:
                model_inference_duration.labels(
                    model_name=self.model_name,
                    device=self.device,
                ).observe(inference_duration)
                model_inference_total.labels(
                    model_name=self.model_name,
                    device=self.device,
                    status="error",
                ).inc()
            logger.error(
                "Model inference failed: error=%s duration=%.3fs device=%s model=%s",
                str(e),
                inference_duration,
                self.device,
                self.model_name,
                exc_info=True,
            )
            raise
