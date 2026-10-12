"""
decision_making_agent.py
-------------------------
Loads a Hugging Face causal instruct model (default Qwen3-4B-Instruct) for RAG / ReAct answers
and writer prompts. Same family as the MAS orchestrator LLM; uses chat template + generate.
GPU uses 4-bit quantization when available unless forced to CPU; model can load lazily on first call.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ai_agents.generation_stop import GenerationStopped, generation_stop_event
from ai_agents.prompt_tokens import TokenSource, estimate_tokens, record_prompt_tokens

logger = logging.getLogger(__name__)

try:
    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        StoppingCriteria,
        StoppingCriteriaList,
        TextIteratorStreamer,
    )

    _TRANSFORMERS_AVAILABLE = True
except Exception:
    torch = None  # type: ignore
    AutoModelForCausalLM = None  # type: ignore
    AutoTokenizer = None  # type: ignore
    BitsAndBytesConfig = None  # type: ignore
    StoppingCriteria = None  # type: ignore
    StoppingCriteriaList = None  # type: ignore
    TextIteratorStreamer = None  # type: ignore
    _TRANSFORMERS_AVAILABLE = False

try:
    import torch as _torch_check

    _TORCH_AVAILABLE = _torch_check is not None
except Exception:
    _TORCH_AVAILABLE = False


# Spiral / self-correction markers. The 4B worker LLM, when handed retrieved
# context with multiple similar-looking numbers (e.g. "$265K" appearing in
# both a table cell and a variance note), enters a "$265K — no — wait —
# actually $263K — no" loop until it runs out of token budget. The pattern
# is easy to detect by counting contradiction markers. When the density goes
# over a threshold we replace the whole output with a clean fallback so the
# user never sees the loop garbage; the raw output is still logged for debug.
_SPIRAL_MARKERS = (
    "→ no",
    "→ wrong",
    "→ not supported",
    "→ not in text",
    "we surrender",
    "we give up",
    "we settle",
    "we now",
    "wait —",
    "wait,",
    "actually,",
    "but actually",
    "no — wait",
    "we conclude",
    "we believe the actual",
    "but the text says",
    "but the table says",
    "absurd",
    "impossible",
)


def _is_degenerate_output(text: str) -> bool:
    """Return True when ``text`` looks like a self-correcting spiral.

    Counts how many ``_SPIRAL_MARKERS`` substrings appear in a lowercased
    view of the text. > 4 across a single answer is essentially never a
    well-formed response — those phrases only cluster when the model is
    repeatedly contradicting itself. False positives are rare because a real
    answer rarely contains more than one or two contradiction markers.
    """
    if not text or len(text) < 200:
        return False
    lowered = text.lower()
    score = sum(lowered.count(m) for m in _SPIRAL_MARKERS)
    return score >= 5


DEGENERATE_OUTPUT_FALLBACK = (
    "I couldn't extract a consistent answer from the retrieved "
    "content for this step. The chunks pulled from the knowledge "
    "store appear fragmented or contradictory, and the model "
    "spiraled trying to reconcile them. Please rephrase the demand "
    "to focus on one specific question, or check the task detail "
    "page for the raw retrieved context."
)


_FULL_WIDTH_TO_ASCII = str.maketrans(
    {
        **{chr(code): chr(code - 0xFEE0) for code in range(0xFF01, 0xFF5F)},
        "\u3000": " ",
        "。": ".",
        "｡": ".",
    }
)


def _normalize_model_text(text: str) -> str:
    return text.translate(_FULL_WIDTH_TO_ASCII)


def clean_model_text(text: str) -> str:
    text = _normalize_model_text(text)
    if not _is_degenerate_output(text):
        return text
    logger.warning(
        "Degenerate self-correction loop detected in model output (length=%d); replacing "
        "with clean fallback. Raw output preview: %r",
        len(text),
        text[:400],
    )
    return DEGENERATE_OUTPUT_FALLBACK


ANSWER_CALL = "answer"
GROUNDED_CALL = "grounded"
INSTRUCTION_CALL = "instruction"
PURPOSE_HEADER = "X-Horus-Purpose"

INSTRUCTION_SYSTEM_PROMPT = "You are a helpful assistant. Follow the user's instructions concisely."

GROUNDED_SYSTEM_PROMPT = (
    "You are a helpful assistant. Use only the retrieved content to complete the task. "
    "Format every answer in Markdown: start with a brief ## heading when the answer "
    "has multiple parts, use **bold** for important labels, use bullet lists for "
    "enumerations, and keep paragraphs short so the reply is easy to scan. "
    "Never echo or duplicate the retrieved text — synthesise.\n\n"
    "CRITICAL: Once you write a number, fact, or quote, COMMIT TO IT. "
    "Do not revise or second-guess in the same answer. Self-correcting "
    "loops ('wait — no — $265K — actually $263K') destroy the answer's "
    "trustworthiness. Pick the single statement that best fits the "
    "question and stop.\n\n"
    "RULES (read before answering):\n"
    "1. Use ONLY the retrieved content. Do NOT invent facts.\n"
    "2. Pick ONE answer and commit. If the retrieved content has "
    "multiple similar-looking figures, pick the one that matches "
    "the question's exact wording and move on. Do NOT write 'wait', "
    "'no', 'actually', 'correction', 'let me recheck', or any "
    "self-correcting phrase. Do NOT second-guess.\n"
    "3. If the retrieved content genuinely lacks the answer, say "
    "'The retrieved content does not contain this information.' in "
    "ONE sentence and stop. Do NOT keep searching by re-quoting.\n"
    "4. Never quote the retrieved text back to question it. State "
    "facts confidently in your own words.\n"
    "5. Keep the answer concise. Use short paragraphs and bullet "
    "lists. Stop when the question is answered."
)


def _early_stop_enabled() -> bool:
    """Whether to halt generation early when a spiral is detected mid-stream.

    Default ON. The greedy 4B worker, on certain (query, retrieved-context)
    pairs, falls into a self-correction loop and generates tokens all the way to
    AGENT_MAX_NEW_TOKENS (measured: a full 3072-token run ≈ 150s at ~20 tok/s)
    before the post-hoc _is_degenerate_output guard replaces the garbage with a
    clean fallback. The early-stop criterion fires the SAME heuristic during
    generation, so the spiral is cut to a few hundred tokens / a few seconds with
    byte-identical user-visible output. Set AGENT_EARLY_STOP=0 to disable (A/B).
    """
    return os.getenv("AGENT_EARLY_STOP", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


# Re-evaluate the spiral heuristic on the generated tail every
# _EARLY_STOP_INTERVAL new tokens, starting once at least _EARLY_STOP_MIN_TOKENS
# have been produced (so there is enough text for _is_degenerate_output's
# 200-char / 5-marker gate to be meaningful and false positives stay rare).
_EARLY_STOP_MIN_TOKENS = 128
_EARLY_STOP_INTERVAL = 64


def _stream_tokens_enabled() -> bool:
    """Whether to stream generated tokens to the client as ``reasoning.delta``
    steps over the existing step→WebSocket path (Phase 1). Default OFF so the
    blocking path is untouched until streaming is enabled end-to-end.

    "Hold a beat" UX: the streamer buffers ~_STREAM_HOLD_CHARS before emitting
    anything and runs the SAME _is_degenerate_output guard on the buffer, so a
    spiral is caught and suppressed before the user ever sees self-correction
    garbage. Only confirmed-clean output is streamed; the post-hoc guard and the
    final result envelope are unchanged.
    """
    return os.getenv("AGENT_STREAM_TOKENS", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# Buffer this many characters (~125 tokens, aligned with the early-stop's first
# check) before deciding whether the output is a spiral. Short answers under
# this length are emitted in one delta at the end — fine, they are already fast.
_STREAM_HOLD_CHARS = 500
# Coalesce streamed tokens into at most one step every this many seconds so a
# long answer produces ~tens of POSTs to MAS, not one-per-token. Each step is an
# authenticated POST to /tasks/task-step/, so a tight window (0.12s) sustained
# over a whole generation floods MAS with ~8 POSTs/s. 0.5s keeps the typing
# preview smooth while cutting the per-answer POST count ~4x; tune via env.
_STREAM_FLUSH_INTERVAL = float(os.getenv("AGENT_STREAM_FLUSH_INTERVAL", "0.5"))


def _llm_backend() -> str:
    """Generation backend (Phase 4): 'transformers' (in-process, default) or
    'vllm' (call an external vLLM OpenAI-compatible server). Under 'vllm' the
    agent does NOT load the local 4B, freeing the 8GB GPU for the server, and
    decode runs ~3x faster with continuous batching for concurrency."""
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


def _vllm_max_model_len() -> int:
    try:
        return max(512, int(os.getenv("LLM_VLLM_MAX_MODEL_LEN", "8192")))
    except ValueError:
        return 8192


def _fit_vllm_prompt(system_content: str, user_content: str) -> tuple[str, int]:
    """Keep prompt + generation within the vLLM server's max_model_len.

    vLLM rejects with 400 when ``prompt_tokens + max_tokens > max_model_len``.
    A fixed ``max_tokens`` (e.g. 3072) overflows whenever a RAG / multi-agent
    prompt is large, so instead we give the generation whatever room is LEFT.
    The agent can't tokenize here, so estimate tokens from chars (~chars/3 — a
    deliberate OVER-count vs the usual ~chars/4, for safety margin). If the
    prompt alone is too long, truncate ``user_content`` head+tail so a minimum
    generation still fits. Returns ``(maybe-truncated user_content, max_tokens)``.
    """
    max_len = _vllm_max_model_len()
    margin = 256  # chat-template tokens + estimation slack
    # Always leave generous room so answers aren't cut off mid-section; truncate
    # the prompt before the generation budget when context is large.
    min_gen = 1024
    sys_tok = len(system_content) // 3
    max_user_tok = max(0, max_len - sys_tok - margin - min_gen)
    user_tok = len(user_content) // 3
    if user_tok > max_user_tok and max_user_tok > 0:
        keep_chars = max_user_tok * 3
        head = user_content[: (keep_chars * 2) // 3]
        tail = user_content[-(keep_chars // 3) :]
        user_content = (
            head + "\n…[input truncated to fit the context window]…\n" + tail
        )
        user_tok = len(user_content) // 3
    budget = max_len - sys_tok - user_tok - margin
    max_tokens = max(min_gen, min(_max_new_tokens(), budget))
    return user_content, max_tokens


def _generated_tail_spirals(tokenizer: Any, input_ids: Any, prompt_len: int) -> bool:
    gen_len = int(input_ids.shape[1]) - prompt_len
    if gen_len < _EARLY_STOP_MIN_TOKENS or gen_len % _EARLY_STOP_INTERVAL != 0:
        return False
    text = tokenizer.decode(
        input_ids[0, prompt_len:],
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )
    return _is_degenerate_output(_normalize_model_text(text))


if _TRANSFORMERS_AVAILABLE and StoppingCriteria is not None:

    class _SpiralStoppingCriteria(StoppingCriteria):  # type: ignore[misc]
        """Stop greedy generation as soon as the decoded tail looks degenerate.

        Reuses the exact ``_is_degenerate_output`` definition (≥5 contradiction
        markers over ≥200 chars), so it only ever stops outputs the downstream
        guard would discard anyway — it never truncates a well-formed answer.
        Decodes only the generated portion, and only every
        ``_EARLY_STOP_INTERVAL`` tokens, so the cost is negligible vs. the
        generation it short-circuits. Batch size 1 (the agent decodes one
        sequence at a time).
        """

        def __init__(self, tokenizer: Any, prompt_len: int) -> None:
            self._tok = tokenizer
            self._prompt_len = int(prompt_len)
            self.triggered = False

        def __call__(self, input_ids: Any, scores: Any = None, **kwargs: Any) -> bool:
            if _generated_tail_spirals(self._tok, input_ids, self._prompt_len):
                self.triggered = True
                return True
            return False

else:  # transformers unavailable — generation path is never reached in this case
    _SpiralStoppingCriteria = None  # type: ignore


class StreamView(Protocol):
    def feed(self, piece: str) -> str: ...


def _visible_piece(piece: str, stream_view: StreamView | None) -> str:
    if stream_view is None:
        return _normalize_model_text(piece)
    return _normalize_model_text(stream_view.feed(piece))


class _StopRequestedCriteria:
    def __init__(self, stop: threading.Event) -> None:
        self._stop = stop

    def __call__(self, input_ids: Any, scores: Any = None, **kwargs: Any) -> bool:
        return self._stop.is_set()


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


def _cpu_dtype():
    """Weight dtype for a CPU load.

    float16 is the wrong default on CPU: many PyTorch CPU kernels have no fp16
    path, so generation is either pathologically slow or raises outright. Prefer
    bfloat16 (same 2 bytes per weight, widely supported) and fall back to
    float32, which always works but doubles resident memory. Override with
    AGENT_CPU_DTYPE=bfloat16|float32|float16.
    """
    aliases = {
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float32": torch.float32,
        "fp32": torch.float32,
        "float16": torch.float16,
        "fp16": torch.float16,
    }
    override = os.getenv("AGENT_CPU_DTYPE", "").strip().lower()
    if override:
        if override in aliases:
            return aliases[override]
        logger.warning("Ignoring unknown AGENT_CPU_DTYPE=%r", override)
    try:
        probe = torch.zeros(2, 2, dtype=torch.bfloat16)
        _ = probe @ probe
        return torch.bfloat16
    except Exception:
        return torch.float32

APP_DIR = Path(__file__).resolve().parent.parent
# The agent runs the actual task work (RAG, synthesis, generation), so its
# default is the full 4B Qwen. MAS uses the 1.5B variant for routing only —
# see services/mas/core/llm_setup.py.
DEFAULT_MODEL_ID = os.environ.get(
    "MODEL_NAME", "Qwen/Qwen3-4B-Instruct-2507"
).strip()


def _resolve_local_model_dir() -> Path:
    explicit = os.environ.get("MODEL_DIR", "").strip()
    if explicit:
        return Path(explicit)
    leaf = DEFAULT_MODEL_ID.split("/")[-1] or "model"
    return APP_DIR / "models" / leaf


LOCAL_MODEL_DIR = _resolve_local_model_dir()
OFFLOAD_DIR = APP_DIR / "offload"
# Required files post-snapshot_download. A 1.5B model ships a single
# ``model.safetensors`` (no shard index), so we only check for the basics.
REQUIRED_LOCAL_FILES = [
    "config.json",
    "tokenizer.json",
]

def _agent_accelerate_max_memory() -> dict | None:
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


DEFAULT_MAX_CONTEXT_CHARS = 12000


def _max_context_chars() -> int:
    raw = os.getenv("AGENT_MAX_CONTEXT_CHARS", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_CONTEXT_CHARS
    return value if value > 0 else DEFAULT_MAX_CONTEXT_CHARS


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
        decision_model: Callable[..., Any] | None = None,
        model_name: str | None = None,
        device: str | None = None,
    ):
        self.model_name = model_name or DEFAULT_MODEL_ID
        self.device = detect_device(device) if device else detect_device("auto")
        self.decision_model: Callable[..., Any] | None = decision_model
        self._lazy = decision_model is None and _lazy_model_enabled()
        self._causal_tokenizer = None
        self._causal_model = None
        # Last generation's exact token counts, surfaced to the benchmark harness
        # via the reasoning.done step (decode tok/s). Set by _generate_causal;
        # left None on the decision_model callable path.
        self._last_gen_tokens: int | None = None
        self._last_prompt_tokens: int | None = None
        self._load_lock = threading.Lock()

        if decision_model is not None:
            logger.info(
                "DecisionMakingAgent initialized with injected model on device: %s",
                self.device,
            )
            return

        if _llm_backend() == "vllm" and not _TRANSFORMERS_AVAILABLE:
            logger.info(
                "LLM_BACKEND=vllm: generation is served by %s (model=%s); this image has "
                "no in-process model stack.",
                _vllm_base_url(),
                _vllm_model_name(),
            )
            return

        if not _TRANSFORMERS_AVAILABLE:
            raise RuntimeError(
                "The in-process decision model needs transformers/torch, which this image "
                "does not ship: CPU images leave them out. Set LLM_BACKEND=vllm and "
                "LLM_VLLM_URL to use llama-server or vLLM, or run the GPU image."
            )

        OFFLOAD_DIR.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault(
            "PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True,max_split_size_mb:64"
        )
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        if torch is not None:
            # One intra-op thread is right for a GPU load, where the CPU only
            # feeds the device. On a CPU-only worker it throws away every core
            # but one, and _configure_agent_torch_threads() already picked a
            # sensible budget at import, so leave that alone unless CUDA is
            # actually in play.
            if self.device != "cpu" and torch.cuda.is_available():
                torch.set_num_threads(1)
            torch.backends.cuda.matmul.allow_tf32 = True

        if self._lazy:
            logger.info(
                "Decision model will load on first use (AGENT_LAZY_DECISION_MODEL=1)."
            )
            return

        if _llm_backend() == "vllm":
            logger.info(
                "LLM_BACKEND=vllm: skipping in-process model load; generation is "
                "served by %s (model=%s).",
                _vllm_base_url(),
                _vllm_model_name(),
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
                    cpu_dtype = _cpu_dtype()
                    logger.info(
                        "Loading agent decision LLM on CPU, dtype=%s.", cpu_dtype
                    )
                    model = AutoModelForCausalLM.from_pretrained(
                        model_path,
                        torch_dtype=cpu_dtype,
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
                        torch_dtype=_cpu_dtype(),
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

    @property
    def constrains_output(self) -> bool:
        return self.decision_model is None and _llm_backend() == "vllm"

    def _prompt_token_count(self, prompt: str) -> tuple[int, TokenSource]:
        counted = self._last_prompt_tokens
        if self.decision_model is None and isinstance(counted, int) and not isinstance(counted, bool):
            if _llm_backend() == "vllm":
                return counted, TokenSource.USAGE
            return counted, TokenSource.TOKENIZER
        return estimate_tokens(prompt), TokenSource.ESTIMATE

    def _generate_causal(
        self,
        user_content: str,
        system_content: str,
        stream_view: StreamView | None = None,
    ) -> str:
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
            # Raised from 4096 → 8192 so the bracketed task instruction at the
            # end of user_content isn't chopped when the retrieved context is
            # long. Qwen3-4B supports far more than 8K natively.
            max_length=8192,
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
        # Build a bad-words list to physically block the self-correcting loop
        # pattern ("wait — no — $265K — actually $263K …") that the 4B model
        # falls into when retrieved context has multiple similar figures. The
        # tokens are encoded as bad_words_ids and the generator will avoid
        # producing them. Lower-cased and prefixed variants cover both
        # mid-sentence and start-of-sentence occurrences.
        _antiloop_phrases = [
            " wait", " Wait", " No —", " no —",
            " Actually", " actually", " correction", " Correction",
            " let me recheck", " Let me recheck", " let me re-check",
            " No.", " no.", " No,", " no,",
        ]
        bad_words_ids: list[list[int]] = []
        for phrase in _antiloop_phrases:
            ids = tok(phrase, add_special_tokens=False).input_ids
            if ids:
                bad_words_ids.append(ids)

        # Halt the self-correction spiral the moment it is detectable instead of
        # letting it run to max_new_tokens (see _early_stop_enabled / the
        # measured 3072-token, ~150s worst case). No-op for well-formed answers.
        spiral_criteria = None
        criteria: list[Any] = []
        if _early_stop_enabled() and _SpiralStoppingCriteria is not None:
            spiral_criteria = _SpiralStoppingCriteria(tok, input_ids.size(1))
            criteria.append(spiral_criteria)
        stop = generation_stop_event()
        if stop is not None:
            criteria.append(_StopRequestedCriteria(stop))
        stopping = StoppingCriteriaList(criteria) if criteria else None

        # Greedy decoding on a 4B model with no penalties loops once it hits a
        # repeatable phrase (the "(Duplicate)" failure mode). repetition_penalty
        # discourages echoing tokens already seen; no_repeat_ngram_size hard-bans
        # repeating any 4-gram; bad_words_ids physically prevents the
        # self-correcting loop by blocking the tokens that start it.
        gen_kwargs: dict[str, Any] = {
            "input_ids": input_ids,
            "attention_mask": attn_mask,
            "max_new_tokens": max_new,
            "do_sample": False,
            "repetition_penalty": 1.2,
            "no_repeat_ngram_size": 4,
            "bad_words_ids": bad_words_ids if bad_words_ids else None,
            "stopping_criteria": stopping,
            "return_dict_in_generate": True,
            "pad_token_id": tok.eos_token_id,
            "eos_token_id": tok.eos_token_id,
        }

        if _stream_tokens_enabled() and TextIteratorStreamer is not None:
            # Streams confirmed-clean tokens to the client as reasoning.delta
            # steps; returns the same return_dict_in_generate output as below so
            # token telemetry and the degeneracy guard are unchanged.
            out = self._generate_streaming(model, tok, gen_kwargs, stream_view)
        else:
            with torch.no_grad():
                out = model.generate(**gen_kwargs)

        if stop is not None and stop.is_set():
            raise GenerationStopped("Generation stopped by its caller")
        seq = out.sequences[0]
        gen_only = seq[input_ids.size(1) :]
        # Exact token counts for benchmark telemetry. Captured raw — before any
        # degeneracy-guard cleanup of the decoded text — so a spiral is measured
        # as the ~max_new_tokens it actually produced, not the short fallback the
        # guard substitutes downstream.
        self._last_gen_tokens = int(gen_only.shape[0])
        self._last_prompt_tokens = int(input_ids.size(1))
        if spiral_criteria is not None and spiral_criteria.triggered:
            logger.info(
                "Early-stop: spiral detected; halted generation at %d new tokens "
                "(cap %d) — clean fallback substituted downstream.",
                self._last_gen_tokens,
                max_new,
            )
        return tok.decode(
            gen_only,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        ).strip()

    def _generate_streaming(
        self,
        model: Any,
        tok: Any,
        gen_kwargs: dict,
        stream_view: StreamView | None = None,
    ) -> Any:
        """Run ``model.generate`` in a background thread with a
        ``TextIteratorStreamer`` and emit confirmed-clean tokens to the client as
        coalesced ``reasoning.delta`` steps.

        Hold-a-beat: buffer the first ~``_STREAM_HOLD_CHARS`` characters and run
        ``_is_degenerate_output`` on them. If the output is spiralling we suppress
        streaming entirely (the early-stop criterion halts generation and the
        post-hoc guard substitutes the clean fallback, so the user never sees
        self-correction garbage). Otherwise we flush the held text and then stream
        subsequent tokens, coalesced to at most one step per
        ``_STREAM_FLUSH_INTERVAL``. Returns the same ``return_dict_in_generate``
        object as the blocking path so the caller's telemetry/guard are unchanged.
        """
        try:
            from ai_agents.step_emitter import emit_step as _emit
        except Exception:  # pragma: no cover - emitter unbound (e.g. unit tests)
            def _emit(*_a: Any, **_kw: Any) -> None:  # type: ignore[misc]
                return None

        streamer = TextIteratorStreamer(
            tok, skip_prompt=True, skip_special_tokens=True
        )
        holder: dict[str, Any] = {}

        def _run() -> None:
            try:
                with torch.no_grad():
                    holder["out"] = model.generate(**gen_kwargs, streamer=streamer)
            except Exception as exc:  # surfaced to the caller after join
                holder["error"] = exc

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()

        held: list[str] = []
        held_chars = 0
        streaming = False  # have we confirmed clean and started emitting?
        suppressed = False  # spiral detected → never stream
        pending: list[str] = []
        idx = 0
        last_flush = time.monotonic()

        def _flush(force: bool = False) -> None:
            nonlocal pending, last_flush, idx
            if not pending:
                return
            if not force and (time.monotonic() - last_flush) < _STREAM_FLUSH_INTERVAL:
                return
            _emit("reasoning.delta", "", "", chunk="".join(pending), index=idx)
            pending = []
            idx += 1
            last_flush = time.monotonic()

        try:
            for raw_piece in streamer:
                if not raw_piece or suppressed:
                    continue
                piece = _visible_piece(raw_piece, stream_view)
                if not piece:
                    continue
                if streaming:
                    pending.append(piece)
                    _flush()
                    continue
                # hold-a-beat phase: accumulate until we can judge degeneracy
                held.append(piece)
                held_chars += len(piece)
                if held_chars >= _STREAM_HOLD_CHARS:
                    joined = "".join(held)
                    held = []
                    if _is_degenerate_output(joined):
                        suppressed = True
                    else:
                        _emit("reasoning.delta", "", "", chunk=joined, index=idx)
                        idx += 1
                        streaming = True
            # stream ended before crossing the hold threshold (short answer):
            # emit the whole thing once, unless it looks degenerate.
            if not streaming and not suppressed and held:
                joined = "".join(held)
                if not _is_degenerate_output(joined):
                    _emit("reasoning.delta", "", "", chunk=joined, index=idx)
            _flush(force=True)
        except Exception:  # never let streaming break generation
            logger.debug("Token streaming failed; generation continues", exc_info=True)

        worker.join()
        if "error" in holder:
            raise holder["error"]
        return holder["out"]

    def _generate_vllm(
        self,
        user_content: str,
        system_content: str,
        response_format: dict | None = None,
        stream_view: StreamView | None = None,
        call: str = ANSWER_CALL,
    ) -> str:
        """Generate via the external vLLM OpenAI-compatible server (Phase 4).

        Mirrors the local path's contract: returns the answer text and sets
        ``self._last_gen_tokens`` / ``_last_prompt_tokens`` from the API's usage
        block, so the reasoning.done telemetry and the post-hoc degeneracy guard
        are unchanged. The transformers ``StoppingCriteria`` does not apply here
        — spiral control is the prompt RULES + the post-hoc guard + ``max_tokens``.
        (Token streaming is not yet wired for this backend; the answer arrives in
        one block. The transformers backend keeps the Phase-1 reasoning.delta path.)
        """
        import requests

        # Give generation whatever room is left under max_model_len rather than a
        # fixed max_tokens (which 400s when the prompt is large). See _fit_vllm_prompt.
        user_content, max_tokens = _fit_vllm_prompt(system_content, user_content)
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
        if _stream_tokens_enabled() or generation_stop_event() is not None:
            return self._generate_vllm_streaming(
                messages,
                max_tokens,
                emit_tokens=_stream_tokens_enabled(),
                response_format=response_format,
                stream_view=stream_view,
                call=call,
            )

        url = _vllm_base_url().rstrip("/") + "/chat/completions"
        payload = {
            "model": _vllm_model_name(),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": False,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        resp = requests.post(
            url, json=payload, headers={PURPOSE_HEADER: call}, timeout=_vllm_timeout()
        )
        resp.raise_for_status()
        data = resp.json()
        text = (data["choices"][0]["message"].get("content") or "").strip()
        usage = data.get("usage") or {}
        self._last_gen_tokens = usage.get("completion_tokens")
        self._last_prompt_tokens = usage.get("prompt_tokens")
        return text

    def _generate_vllm_streaming(
        self,
        messages: list,
        max_tokens: int,
        emit_tokens: bool = True,
        response_format: dict | None = None,
        stream_view: StreamView | None = None,
        call: str = ANSWER_CALL,
    ) -> str:
        """Stream a vLLM chat completion (SSE) and emit confirmed-clean tokens as
        batched ``reasoning.delta`` steps — the Phase-1 streaming UX on the vLLM
        backend. Same hold-a-beat guard as the transformers path: buffer
        ``_STREAM_HOLD_CHARS``, run ``_is_degenerate_output``, suppress on a
        spiral. ``max_tokens`` is the budgeted remaining room (see
        _fit_vllm_prompt). Token counts come from the final usage chunk."""
        import json as _json

        import requests

        try:
            from ai_agents.step_emitter import emit_step as _emit
        except Exception:  # pragma: no cover

            def _emit(*_a: Any, **_kw: Any) -> None:  # type: ignore[misc]
                return None

        if not emit_tokens:

            def _emit(*_a: Any, **_kw: Any) -> None:  # type: ignore[misc]
                return None

        stop = generation_stop_event()
        url = _vllm_base_url().rstrip("/") + "/chat/completions"
        payload = {
            "model": _vllm_model_name(),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if response_format is not None:
            payload["response_format"] = response_format

        full: list[str] = []
        held: list[str] = []
        held_chars = 0
        streaming = False
        suppressed = False
        pending: list[str] = []
        idx = 0
        last_flush = time.monotonic()

        def _flush(force: bool = False) -> None:
            nonlocal pending, last_flush, idx
            if not pending:
                return
            if not force and (time.monotonic() - last_flush) < _STREAM_FLUSH_INTERVAL:
                return
            _emit("reasoning.delta", "", "", chunk="".join(pending), index=idx)
            pending = []
            idx += 1
            last_flush = time.monotonic()

        with requests.post(
            url,
            json=payload,
            headers={PURPOSE_HEADER: call},
            timeout=_vllm_timeout(),
            stream=True,
        ) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines():
                if stop is not None and stop.is_set():
                    logger.info("Generation stopped by its caller; closing the stream")
                    raise GenerationStopped("Generation stopped by its caller")
                if not raw:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = _json.loads(data)
                except ValueError:
                    continue
                error = chunk.get("error")
                if error:
                    message = error.get("message") if isinstance(error, dict) else error
                    raise RuntimeError(f"LLM server stopped the stream: {message}")
                usage = chunk.get("usage")
                if usage:
                    self._last_gen_tokens = usage.get("completion_tokens")
                    self._last_prompt_tokens = usage.get("prompt_tokens")
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                content = (choices[0].get("delta") or {}).get("content") or ""
                if not content:
                    continue
                piece = _visible_piece(content, stream_view)
                full.append(content if stream_view is not None else piece)
                if suppressed or not piece:
                    continue
                if streaming:
                    pending.append(piece)
                    _flush()
                    continue
                held.append(piece)
                held_chars += len(piece)
                if held_chars >= _STREAM_HOLD_CHARS:
                    joined = "".join(held)
                    held = []
                    if _is_degenerate_output(joined):
                        suppressed = True
                    else:
                        _emit("reasoning.delta", "", "", chunk=joined, index=idx)
                        idx += 1
                        streaming = True

        if not streaming and not suppressed and held:
            joined = "".join(held)
            if not _is_degenerate_output(joined):
                _emit("reasoning.delta", "", "", chunk=joined, index=idx)
        _flush(force=True)
        return "".join(full).strip()

    def decide(self, query: str, context: str | None = None) -> str:
        """
        Run inference. If ``context`` is None, ``query`` is treated as the full user message
        (used by WriterAgent). Otherwise the usual grounded QA instruction is applied.

        If a persona is bound on :data:`agent_server.profiles.current_persona`
        (set per-task by the RabbitMQ consumer), it's prepended to the system
        message so the specialist's domain instructions shape the response
        without changing every helper's signature.
        """
        if context is None:
            return clean_model_text(
                self._infer(
                    query,
                    query,
                    INSTRUCTION_SYSTEM_PROMPT,
                    on_context=False,
                    call=INSTRUCTION_CALL,
                )
            )
        # Cap retrieved context BEFORE building the prompt. Knowledge-store
        # retrieval can return multiple full documents (e.g. IT Security
        # Policy + 2026 Budget + Q4 Report) for an underspecified query;
        # if we dump that verbatim into the prompt, tokenizer truncation
        # cuts the ``Task: ...`` line off the end and the model ends up
        # echoing/repeating retrieved chunks instead of answering. ~12k
        # chars (~3k tokens) leaves room for the persona, instructions,
        # and the task line under the 8192-token prompt budget.
        max_ctx_chars = _max_context_chars()
        ctx = context or ""
        if len(ctx) > max_ctx_chars:
            ctx = ctx[:max_ctx_chars] + "\n…[retrieved content truncated]"
        callable_prompt = (
            "You are a helpful assistant. Answer using ONLY the provided context. "
            "Format the answer in Markdown (## heading when helpful, **bold** labels, "
            "bullet lists for multiple items, short paragraphs). "
            "If the user asked for a summary, cover the main points without inventing facts. "
            "If the answer is not present in the context, say: "
            "'I don't have that information yet.'\n\n"
            f"Context:\n{context}\n\nQuestion: {query}\nAnswer:"
        )
        return clean_model_text(
            self._infer(
                query,
                f"Retrieved Content:\n{ctx}\n\nTask: {query}",
                GROUNDED_SYSTEM_PROMPT,
                on_context=True,
                callable_prompt=callable_prompt,
                call=GROUNDED_CALL,
            )
        )

    def complete(
        self,
        query: str,
        user_content: str,
        system_content: str,
        *,
        response_format: dict | None = None,
        stream_view: StreamView | None = None,
        call: str = ANSWER_CALL,
    ) -> str:
        return self._infer(
            query,
            user_content,
            system_content,
            on_context=True,
            response_format=response_format,
            stream_view=stream_view,
            call=call,
        )

    def reason(self, query: str, user_content: str, system_content: str, *, call: str) -> str:
        return clean_model_text(
            self._infer(query, user_content, system_content, on_context=True, call=call)
        )

    def _infer(
        self,
        query: str,
        user_content: str,
        system_content: str,
        *,
        on_context: bool,
        callable_prompt: str | None = None,
        response_format: dict | None = None,
        stream_view: StreamView | None = None,
        call: str = ANSWER_CALL,
    ) -> str:
        if _llm_backend() != "vllm":
            self._ensure_causal_loaded()

        try:
            from core.metrics import (
                model_inference_duration,
                model_inference_total,
            )

            _METRICS_AVAILABLE = True
        except ImportError:
            _METRICS_AVAILABLE = False

        # Per-task persona override. Set by the consumer thread based on which
        # specialist agent owns this task. Prepended so the specialist's
        # domain instructions take precedence over the generic system message.
        try:
            from agent_server.profiles import current_persona

            persona = current_persona.get()
        except Exception:
            persona = None
        if persona:
            system_content = f"{persona}\n\n---\n\n{system_content}"

        logger.debug(
            "Decision inference model=%s device=%s", self.model_name, self.device
        )

        # Coarse "thought process" boundary — the consumer binds an emitter
        # per-task; nothing happens in unit tests calling decide() directly.
        try:
            from ai_agents.step_emitter import emit_step

            _emit = emit_step
        except Exception:
            def _emit(*_a, **_kw):  # type: ignore[no-redef]
                return None

        query_preview = (query or "").strip()
        if len(query_preview) > 200:
            query_preview = query_preview[:200] + "…"
        _emit(
            "reasoning.start",
            "Reasoning over retrieved content",
            (
                "Running the language model on the retrieved context."
                if on_context
                else "Running the language model on the user's request."
            ),
            model=self.model_name,
            device=self.device,
            query=query_preview,
        )

        start_time = time.time()
        # Reset per-call token telemetry; _generate_causal sets it on the causal
        # path (the decision_model callable path leaves it None → harness falls
        # back to counting the visible answer text).
        self._last_gen_tokens = None
        self._last_prompt_tokens = None

        prompt = f"{system_content}\n\n{user_content}"
        if self.decision_model is not None and callable_prompt:
            prompt = callable_prompt
        try:
            if self.decision_model is not None:
                result = self.decision_model(prompt)
                text = self._coerce_callable_output(result)
            elif _llm_backend() == "vllm":
                text = self._generate_vllm(
                    user_content,
                    system_content,
                    response_format=response_format,
                    stream_view=stream_view,
                    call=call,
                )
            else:
                text = self._generate_causal(
                    user_content, system_content, stream_view=stream_view
                )

            inference_duration = time.time() - start_time
            record_prompt_tokens(call, *self._prompt_token_count(prompt))
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
            _emit(
                "reasoning.done",
                "Reasoning complete",
                f"Model returned a response in {inference_duration:.2f}s.",
                duration_seconds=round(inference_duration, 3),
                generated_tokens=self._last_gen_tokens,
                prompt_tokens=self._last_prompt_tokens,
                model=self.model_name,
            )
            return text
        except GenerationStopped:
            logger.info(
                "Reasoning stopped after %.1fs at its caller's request",
                time.time() - start_time,
            )
            raise
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
            _emit(
                "error",
                "Reasoning failed",
                str(e),
                phase="reasoning",
                model=self.model_name,
            )
            raise
