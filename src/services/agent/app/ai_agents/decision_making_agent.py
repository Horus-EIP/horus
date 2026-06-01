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
from typing import Any

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

        with torch.no_grad():
            out = model.generate(
                input_ids=input_ids,
                attention_mask=attn_mask,
                max_new_tokens=max_new,
                # Greedy decoding on a 4B model with no penalties loops once it
                # hits a repeatable phrase (the "(Duplicate)" failure mode).
                # repetition_penalty discourages echoing tokens already seen;
                # no_repeat_ngram_size hard-bans repeating any 4-gram.
                # bad_words_ids physically prevents the self-correcting loop
                # by blocking the tokens that start it.
                do_sample=False,
                repetition_penalty=1.2,
                no_repeat_ngram_size=4,
                bad_words_ids=bad_words_ids if bad_words_ids else None,
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

    def decide(self, query: str, context: str | None = None) -> str:
        """
        Run inference. If ``context`` is None, ``query`` is treated as the full user message
        (used by WriterAgent). Otherwise the usual grounded QA instruction is applied.

        If a persona is bound on :data:`agent_server.profiles.current_persona`
        (set per-task by the RabbitMQ consumer), it's prepended to the system
        message so the specialist's domain instructions shape the response
        without changing every helper's signature.
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
            # Cap retrieved context BEFORE building the prompt. Knowledge-store
            # retrieval can return multiple full documents (e.g. IT Security
            # Policy + 2026 Budget + Q4 Report) for an underspecified query;
            # if we dump that verbatim into the prompt, tokenizer truncation
            # cuts the ``Task: ...`` line off the end and the model ends up
            # echoing/repeating retrieved chunks instead of answering. ~12k
            # chars (~3k tokens) leaves room for the persona, instructions,
            # and the bracketed task line under the 8192-token prompt budget.
            _MAX_CTX_CHARS = 12000
            ctx = context or ""
            if len(ctx) > _MAX_CTX_CHARS:
                ctx = ctx[:_MAX_CTX_CHARS] + "\n…[retrieved content truncated]"

            # Bracket the task at both ends: even if the middle gets truncated,
            # the instruction at the top and the question at the bottom both
            # survive so the model always sees what it's being asked to do.
            user_content = (
                f"Task: {query}\n\n"
                "RULES (read before answering):\n"
                "1. Use ONLY the retrieved content below. Do NOT invent facts.\n"
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
                "lists. Stop when the question is answered.\n\n"
                f"Retrieved Content:\n{ctx}\n\n"
                f"Now answer the task: {query}"
            )
            system_content = (
                "You are a helpful assistant. Use only the retrieved content to complete the task. "
                "Format every answer in Markdown: start with a brief ## heading when the answer "
                "has multiple parts, use **bold** for important labels, use bullet lists for "
                "enumerations, and keep paragraphs short so the reply is easy to scan. "
                "Never echo or duplicate the retrieved text — synthesise.\n\n"
                "CRITICAL: Once you write a number, fact, or quote, COMMIT TO IT. "
                "Do not revise or second-guess in the same answer. Self-correcting "
                "loops ('wait — no — $265K — actually $263K') destroy the answer's "
                "trustworthiness. Pick the single statement that best fits the "
                "question and stop."
            )

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
                if context is not None
                else "Running the language model on the user's request."
            ),
            model=self.model_name,
            device=self.device,
            query=query_preview,
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
            _emit(
                "reasoning.done",
                "Reasoning complete",
                f"Model returned a response in {inference_duration:.2f}s.",
                duration_seconds=round(inference_duration, 3),
                model=self.model_name,
            )

            # Final guard: if the model produced a self-correction spiral
            # despite the anti-loop prompt + bad_words_ids, replace the
            # output with a clean fallback. The raw text is logged so the
            # task detail page still has it for debugging, but the user
            # never sees pages of "→ no → wait → actually $265K — no" in
            # chat. Detection is a simple density-of-contradiction-markers
            # check; well-formed answers virtually never trip it.
            if _is_degenerate_output(text):
                logger.warning(
                    "Degenerate self-correction loop detected in model output "
                    "(length=%d); replacing with clean fallback. Raw output "
                    "preview: %r",
                    len(text),
                    text[:400],
                )
                text = (
                    "I couldn't extract a consistent answer from the retrieved "
                    "content for this step. The chunks pulled from the knowledge "
                    "store appear fragmented or contradictory, and the model "
                    "spiraled trying to reconcile them. Please rephrase the demand "
                    "to focus on one specific question, or check the task detail "
                    "page for the raw retrieved context."
                )

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
            _emit(
                "error",
                "Reasoning failed",
                str(e),
                phase="reasoning",
                model=self.model_name,
            )
            raise
