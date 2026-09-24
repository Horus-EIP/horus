"""Redis-backed exact-match response cache for the agent's RAG pipeline (Phase 3).

The cache key is ``hash(normalized_query + sha256(retrieved_context) +
generation_params)``. Hashing the *retrieved context* (not just the query) makes
the cache safe by construction:

* **Permission scoping is automatic** — two users who retrieve different
  documents (because of access controls) produce different context, hence
  different keys; one user's answer can never be served to another.
* **Version invalidation is automatic** — editing a document changes the text it
  retrieves into, which changes the context hash, which misses the cache. No
  explicit upload/delete invalidation hooks (and no knowledge-store changes) are
  needed.

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

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis

    _REDIS_AVAILABLE = True
except Exception:  # redis not installed (e.g. before the dependency lands)
    aioredis = None  # type: ignore
    _REDIS_AVAILABLE = False

# Bump to invalidate every existing entry when the keying scheme changes.
_CACHE_VERSION = "v1"
_KEY_PREFIX = "agent:respcache:"


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


def _key(query: str, context: str) -> str:
    normalized_query = " ".join((query or "").split()).lower()
    context_hash = hashlib.sha256((context or "").encode("utf-8")).hexdigest()
    raw = "\x00".join(
        (_CACHE_VERSION, normalized_query, context_hash, _gen_params_signature())
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


async def get_cached(query: str, context: str) -> str | None:
    """Return a cached answer for this exact (query, context), or None."""
    if not cache_enabled():
        return None
    client = _new_client()
    try:
        return await client.get(_key(query, context))
    except Exception:  # network/redis hiccup → just generate
        logger.debug("response cache GET failed; generating", exc_info=True)
        return None
    finally:
        await _close(client)


async def set_cached(query: str, context: str, answer: str) -> None:
    """Store an answer for this exact (query, context). Best-effort."""
    if not cache_enabled() or not answer:
        return
    client = _new_client()
    try:
        ttl = _ttl_seconds()
        if ttl > 0:
            await client.set(_key(query, context), answer, ex=ttl)
        else:
            await client.set(_key(query, context), answer)
    except Exception:
        logger.debug("response cache SET failed; ignoring", exc_info=True)
    finally:
        await _close(client)
