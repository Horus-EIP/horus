"""Redis-backed exact-match response cache for the agent's RAG pipeline (Phase 3).

The cache key is ``hash(normalized_query + sha256(retrieved_context) +
corpus_version + generation_params)``. Hashing the *retrieved context* (not just
the query) makes the cache safe by construction:

* **Permission scoping is automatic** — two users who retrieve different
  documents (because of access controls) produce different context, hence
  different keys; one user's answer can never be served to another.

A hit therefore skips only the expensive generation step (seconds), never
retrieval (~0.4s), which is exactly the part we can safely reuse. Disabled
unless ``AGENT_RESPONSE_CACHE`` is truthy and the ``redis`` client is installed;
every Redis call is best-effort and degrades to a normal (uncached) generation
on any error, so the cache can never break the pipeline.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time

import httpx

from ai_agents.decision_making_agent import (
    DEGENERATE_OUTPUT_FALLBACK,
    _is_degenerate_output,
    _normalize_model_text,
)
from config.settings import KNOWLEDGE_STORE_API_PREFIX, KNOWLEDGE_STORE_URL

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis

    _REDIS_AVAILABLE = True
except Exception:  # redis not installed (e.g. before the dependency lands)
    aioredis = None  # type: ignore
    _REDIS_AVAILABLE = False

# Bump to invalidate every existing entry when the keying scheme changes.
_CACHE_VERSION = "v2"
_KEY_PREFIX = "agent:respcache:"
_CORPUS_VERSION_TIMEOUT_SECONDS = 1.0
_REFUSAL = re.compile(
    "|".join(
        (
            r"\b(?:does|do)(?: not|n't) (?:contain|include|have|mention|provide) "
            r"(?:this|that|the requested|any|enough) information\b",
            r"\b(?:is|are)(?: not|n't) covered in the (?:current|retrieved|provided)\b",
            r"\bno (?:relevant )?information (?:about|on|regarding)\b",
            r"\bi(?: cannot| can't| am unable to|'m unable to) (?:answer|find|provide|determine)\b",
            r"^(?:i'm|i am) sorry\b",
        )
    )
)

_corpus_version_memo: tuple[str, float] | None = None


def cache_enabled() -> bool:
    return _REDIS_AVAILABLE and os.getenv(
        "AGENT_RESPONSE_CACHE", "0"
    ).strip().lower() in ("1", "true", "yes", "on")


def _ttl_seconds() -> int:
    try:
        return max(0, int(os.getenv("AGENT_RESPONSE_CACHE_TTL", "3600")))
    except ValueError:
        return 3600


def _gen_params_signature() -> str:
    """Everything besides (query, context) that changes the answer.

    ``KNOWLEDGE_STORE_N_RESULTS`` is intentionally absent — it only affects which
    chunks are retrieved, and that already shows up in the context hash.
    """
    return "|".join(
        (
            # Backend + model: an AWQ vLLM answer differs from a bnb-NF4
            # transformers answer for the same (query, context) — cache apart.
            os.getenv("LLM_BACKEND", "transformers"),
            os.getenv("LLM_VLLM_MODEL", "") if os.getenv("LLM_BACKEND") == "vllm"
            else os.getenv("MODEL_NAME", "Qwen/Qwen3-4B-Instruct-2507"),
            os.getenv("AGENT_MAX_NEW_TOKENS", "256"),
            os.getenv("AGENT_EARLY_STOP", "1"),
        )
    )


def _corpus_version_ttl_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("AGENT_RESPONSE_CACHE_VERSION_TTL", "5")))
    except ValueError:
        return 5.0


def _corpus_version_url() -> str:
    return f"{KNOWLEDGE_STORE_URL.rstrip('/')}{KNOWLEDGE_STORE_API_PREFIX}/corpus-version"


async def _fetch_corpus_version() -> str:
    async with httpx.AsyncClient(timeout=_CORPUS_VERSION_TIMEOUT_SECONDS) as client:
        response = await client.get(_corpus_version_url())
        response.raise_for_status()
        version = response.json()["version"]
    if not isinstance(version, str) or not version:
        raise ValueError(f"unusable corpus version {version!r}")
    return version


async def current_corpus_version() -> str | None:
    global _corpus_version_memo
    if not cache_enabled():
        return None
    now = time.monotonic()
    memo = _corpus_version_memo
    if memo is not None and now - memo[1] < _corpus_version_ttl_seconds():
        return memo[0]
    try:
        version = await _fetch_corpus_version()
    except Exception as exc:
        logger.warning("response cache bypassed: corpus version unavailable (%r)", exc)
        return None
    _corpus_version_memo = (version, now)
    return version


def _looks_like_refusal(text: str) -> bool:
    return _REFUSAL.search(text.lower().replace("\u2019", "'")) is not None


def is_cacheable_answer(answer: str | None) -> bool:
    text = _normalize_model_text(answer or "").strip()
    if not text or text == DEGENERATE_OUTPUT_FALLBACK:
        return False
    return not _is_degenerate_output(text) and not _looks_like_refusal(text)


def _key(query: str, context: str, corpus_version: str) -> str:
    normalized_query = " ".join(_normalize_model_text(query or "").split()).lower()
    context_hash = hashlib.sha256((context or "").encode("utf-8")).hexdigest()
    raw = "\x00".join(
        (
            _CACHE_VERSION,
            corpus_version,
            normalized_query,
            context_hash,
            _gen_params_signature(),
        )
    )
    return _KEY_PREFIX + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_client():
    # Created PER CALL, not cached: the agent consumer runs each task in a fresh
    # event loop (consumers.py: asyncio.new_event_loop), and a redis.asyncio
    # client binds to the loop it was created on — a cached client would raise
    # "attached to a different loop" on every task after the first.
    return aioredis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None,
        socket_timeout=0.5,
        socket_connect_timeout=0.5,
        decode_responses=True,
    )


async def _close(client) -> None:
    try:
        closer = getattr(client, "aclose", None) or getattr(client, "close", None)
        if closer is not None:
            await closer()
    except Exception:
        pass


async def get_cached(query: str, context: str, corpus_version: str | None) -> str | None:
    """Return a cached answer for this exact (query, context), or None."""
    if corpus_version is None or not cache_enabled():
        return None
    client = _new_client()
    try:
        answer = await client.get(_key(query, context, corpus_version))
    except Exception:  # network/redis hiccup → just generate
        logger.debug("response cache GET failed; generating", exc_info=True)
        return None
    finally:
        await _close(client)
    return answer if answer is not None and is_cacheable_answer(answer) else None


async def set_cached(
    query: str, context: str, corpus_version: str | None, answer: str
) -> None:
    """Store an answer for this exact (query, context). Best-effort."""
    if corpus_version is None or not cache_enabled() or not is_cacheable_answer(answer):
        return
    key = _key(query, context, corpus_version)
    answer = _normalize_model_text(answer)
    client = _new_client()
    try:
        ttl = _ttl_seconds()
        if ttl > 0:
            await client.set(key, answer, ex=ttl)
        else:
            await client.set(key, answer)
    except Exception:
        logger.debug("response cache SET failed; ignoring", exc_info=True)
    finally:
        await _close(client)
