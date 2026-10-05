#!/usr/bin/env python3
"""End-to-end LLM chat-pipeline benchmark for Horus MAS.

Unlike ``benchmark-mas.py`` (CRUD endpoints) and ``benchmark-rag.py`` (the
knowledge-store HTTP API), this script drives the *actual* multi-agent LLM
pipeline — the thing whose tokens/sec we care about for the perf / NPU work —
and measures it the way the architecture actually exposes timing.

How it measures (no code changes to the services required)
----------------------------------------------------------
A query is submitted via ``POST /tasks/new_task/`` (``mode=specific_agent`` so
it always lands on the heavy Qwen3-4B worker instead of the 1.5B router's
direct-answer short-circuit). The agent worker emits coarse "thought process"
steps over the chat WebSocket ``/chat/{conversation_id}/``:

    retrieval.start → retrieval.results → reasoning.start → reasoning.done → task_complete

Crucially ``reasoning.start``/``reasoning.done`` bracket the model call, and
``reasoning.done`` carries ``metadata.duration_seconds`` — the agent's *own*
measured inference time (decision_making_agent.py). So we get a clean decode
window without any streaming: decode tok/s = output_tokens / duration_seconds.

Metrics captured per task
-------------------------
- ``submit_http_ms``   — latency of the new_task POST itself.
- ``first_step_s``     — submit → first task_step (time to first activity).
- ``ttft_proxy_s``     — submit → reasoning.start (routing + retrieval + prefill
                         setup; upgrade to true TTFT once Phase 1 streaming lands).
- ``decode_s``         — reported model inference time (reasoning.done duration).
- ``decode_tok_s``     — output_tokens / decode_s.
- ``e2e_s``            — submit → task_complete (full end-to-end latency).
- VRAM / GPU util / power sampled via nvidia-smi for the duration of each scenario.

Scenarios
---------
- ``smoke``       — one task, dump every event + metric (validate against a live stack).
- ``idle``        — sequential single-task runs over the fixed prompt set.
- ``concurrency`` — N tasks fired simultaneously (1/2/4/8 by default); aggregate tok/s + p50/p95.
- ``contention``  — generation tok/s with vs. without a concurrent knowledge-store
                    ingestion load hammering the (unpinned, GPU-resident) BGE embedder.
                    The idle→loaded decode-tok/s drop is the ceiling for the NPU offload.

Usage
-----
    pip install httpx websockets            # tiktoken optional, for better token counts
    python benchmark-pipeline.py --label baseline --scenario all
    python benchmark-pipeline.py --scenario smoke           # quick sanity check first

Results are written to ``results-archive/pipeline-<label>-<timestamp>.{json,md}``.
Generation params are server-side env (AGENT_MAX_NEW_TOKENS, KNOWLEDGE_STORE_N_RESULTS);
both models decode greedily (do_sample=False) so runs are deterministic — no seed needed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

try:
    import websockets
except ImportError:  # pragma: no cover - surfaced at runtime with a clear message
    websockets = None


HERE = Path(__file__).resolve().parent
ASSETS = HERE / "bench_assets"
RESULTS_DIR = HERE / "results-archive"

# The agent CONTAINER loads its generation params from this compose env_file, not
# from the benchmark process's own environment. Resolve the report's "server gen
# params" from here so a baseline records the cap the model actually ran with
# (e.g. AGENT_MAX_NEW_TOKENS=3072), instead of the misleading "256 (default)" the
# benchmark process happens to see when the var isn't exported into its own env.
INFRA_ENV = HERE.parents[1] / "src" / "infra" / ".env"


def _read_dotenv(path: Path) -> dict:
    out: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _server_param(key: str, code_default: str) -> str:
    """Best-effort resolution of a server-side generation param for the report.

    Precedence: an explicit override in the benchmark process's env > the compose
    env_file the agent actually loads (src/infra/.env) > the agent's code default.
    Each return is labelled with its source so the baseline is never silently
    anchored to the wrong cap (the prior baseline mislabelled 3072 as "256").
    """
    v = os.environ.get(key)
    if v:
        return f"{v} (benchmark env)"
    fv = _read_dotenv(INFRA_ENV).get(key)
    if fv:
        return f"{fv} (src/infra/.env)"
    return code_default


# --------------------------------------------------------------------------- #
# small stats helpers
# --------------------------------------------------------------------------- #
def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(int(len(sorted_vals) * p), len(sorted_vals) - 1)
    return sorted_vals[idx]


def summarize(vals: list[float | None]) -> dict:
    clean = [v for v in vals if v is not None]
    if not clean:
        return {"n": 0}
    s = sorted(clean)
    return {
        "n": len(clean),
        "mean": round(statistics.mean(clean), 4),
        "median": round(statistics.median(clean), 4),
        "p25": round(_percentile(s, 0.25), 4),
        "p75": round(_percentile(s, 0.75), 4),
        "p95": round(_percentile(s, 0.95), 4),
        "min": round(min(clean), 4),
        "max": round(max(clean), 4),
        "stdev": round(statistics.stdev(clean), 4) if len(clean) > 1 else 0.0,
    }


def _spiral_split(metrics: list) -> tuple[list, dict]:
    """Partition ok tasks into the spiral-free subset used for headline aggregates.

    A ``suspected_spiral`` task has a contaminated decode_s / decode_tok_s / e2e /
    output (the anti-loop guard fired, or the model produced far more than it
    kept), so averaging it into the medians is exactly the failure this harness
    exists to avoid. We aggregate over the clean subset but keep every per-task
    row plus the counts, so a contaminated run is FLAGGED, not silently averaged.
    Falls back to all-ok only if EVERY ok task spiraled (so a fully-degenerate run
    still reports numbers, with the count making the contamination obvious).
    """
    ok = [m for m in metrics if m.ok]
    clean = [m for m in ok if not m.suspected_spiral]
    chosen = clean if clean else ok
    return chosen, {
        "ok": len(ok),
        "clean": len(clean),
        "suspected_spiral": len(ok) - len(clean),
    }


# The exact phrase the agent substitutes when its anti-loop guard fires
# (decision_making_agent.py _is_degenerate_output). Its presence means the model
# spiraled and the visible answer is a fallback, not a real decode — such tasks
# are flagged ``suspected_spiral`` and excluded from the "clean" aggregates.
GUARD_FALLBACK_MARKER = "couldn't extract a consistent answer from the retrieved"


# --------------------------------------------------------------------------- #
# token counting (pluggable; consistency matters more than absolute accuracy)
# --------------------------------------------------------------------------- #
def make_token_counter(hf_model: str | None):
    if hf_model:
        try:
            from transformers import AutoTokenizer

            tok = AutoTokenizer.from_pretrained(hf_model)
            return (lambda t: len(tok.encode(t or ""))), f"hf:{hf_model}"
        except Exception as e:  # noqa: BLE001
            print(f"[warn] HF tokenizer '{hf_model}' failed to load ({e}); falling back")
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda t: len(enc.encode(t or ""))), "tiktoken:cl100k_base"
    except Exception:  # noqa: BLE001
        pass
    # ~4 chars/token is a decent subword proxy and is perfectly consistent across runs.
    return (lambda t: max(1, round(len(t or "") / 4))), "approx:chars-over-4"


# --------------------------------------------------------------------------- #
# GPU sampler (nvidia-smi background poll)
# --------------------------------------------------------------------------- #
class GpuSampler(threading.Thread):
    """Polls nvidia-smi on an interval; report mean/peak VRAM, util, power."""

    def __init__(self, interval: float = 0.5):
        super().__init__(daemon=True)
        self.interval = interval
        self._stop_requested = threading.Event()
        self.mem: list[float] = []
        self.util: list[float] = []
        self.power: list[float] = []
        self.available = self._probe()

    @staticmethod
    def _probe() -> bool:
        try:
            subprocess.run(
                ["nvidia-smi"], capture_output=True, timeout=10, check=True
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    def run(self) -> None:
        if not self.available:
            return
        while not self._stop_requested.is_set():
            try:
                out = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used,utilization.gpu,power.draw",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout.strip()
                parts = [p.strip() for p in out.splitlines()[0].split(",")]
                self.mem.append(float(parts[0]))
                self.util.append(float(parts[1]))
                try:
                    self.power.append(float(parts[2]))
                except (ValueError, IndexError):
                    pass
            except Exception:  # noqa: BLE001
                pass
            self._stop_requested.wait(self.interval)

    def stop(self) -> dict:
        self._stop_requested.set()
        self.join(timeout=2)
        return self.summary()

    def summary(self) -> dict:
        def stat(v: list[float]) -> dict:
            return {"mean": round(statistics.mean(v), 1), "peak": round(max(v), 1)} if v else {}

        return {
            "available": self.available,
            "samples": len(self.mem),
            "vram_used_mib": stat(self.mem),
            "gpu_util_pct": stat(self.util),
            "power_w": stat(self.power),
        }


def gpu_info() -> dict:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        name, driver, mem = (p.strip() for p in out.splitlines()[0].split(","))
        return {"name": name, "driver": driver, "memory_total": mem}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(HERE),
        ).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# per-task result
# --------------------------------------------------------------------------- #
@dataclass
class TaskMetrics:
    prompt_id: str
    ok: bool = False
    direct: bool = False
    error: str | None = None
    submit_http_ms: float | None = None
    first_step_s: float | None = None
    ttft_proxy_s: float | None = None
    decode_s: float | None = None        # reported model inference time
    decode_wall_s: float | None = None   # reasoning.done - reasoning.start (cross-check)
    e2e_s: float | None = None
    output_chars: int | None = None
    output_tokens: int | None = None       # tokens in the VISIBLE answer (post-guard)
    generated_tokens: int | None = None    # tokens the model ACTUALLY produced (pre-guard) — exact, spiral-proof
    prompt_tokens: int | None = None
    decode_tok_s: float | None = None
    decode_tok_s_basis: str | None = None  # "generated" (exact) or "output" (approx fallback)
    suspected_spiral: bool = False         # anti-loop guard fired / produced far more than it kept
    model: str | None = None
    device: str | None = None
    steps: list = field(default_factory=list)


# --------------------------------------------------------------------------- #
# the benchmark client
# --------------------------------------------------------------------------- #
class PipelineBench:
    def __init__(
        self,
        mas_url: str,
        ks_url: str,
        token_counter,
        token_method: str,
        event_timeout: float,
    ):
        self.mas_url = mas_url.rstrip("/")
        self.ks_url = ks_url.rstrip("/")
        self.ws_base = self.mas_url.replace("https://", "wss://").replace("http://", "ws://")
        self.token: str | None = None
        self.count = token_counter
        self.token_method = token_method
        self.event_timeout = event_timeout

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def authenticate(self, username: str, password: str) -> bool:
        async with httpx.AsyncClient() as c:
            r = await c.post(
                f"{self.mas_url}/auth/token",
                data={"username": username, "password": password, "grant_type": "password"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15.0,
            )
        if r.status_code == 200:
            self.token = r.json().get("access_token")
            return bool(self.token)
        print(f"[error] auth failed: HTTP {r.status_code} — {r.text[:300]}")
        return False

    async def wait_for_agent(self, timeout: float = 120.0) -> tuple[str, str] | None:
        """Poll until a non-Manager agent is registered. Returns (agent_id, skill)."""
        deadline = time.perf_counter() + timeout
        last = None
        while time.perf_counter() < deadline:
            async with httpx.AsyncClient() as c:
                r = await c.get(
                    f"{self.mas_url}/agents/details/", headers=self._headers(), timeout=15.0
                )
            if r.status_code == 200:
                agents = r.json()
                if isinstance(agents, dict):
                    agents = agents.get("agents") or list(agents.values())
                candidates = []
                for a in agents or []:
                    if not isinstance(a, dict):
                        continue
                    name = (a.get("name") or "").strip()
                    if name.lower() == "manager":
                        continue
                    aid = a.get("id") or a.get("agent_id")
                    if not aid:
                        continue
                    status = (a.get("status") or "").lower()
                    skills = a.get("skills") or []
                    candidates.append((status == "active", aid, skills, name))
                # prefer active agents
                candidates.sort(key=lambda x: not x[0])
                if candidates:
                    _active, aid, skills, name = candidates[0]
                    skill = skills[0] if skills else "research"
                    print(f"[info] using agent '{name}' id={aid} skill='{skill}' "
                          f"(active={_active})")
                    return aid, skill
                last = f"{len(agents or [])} agents, none usable yet"
            else:
                last = f"HTTP {r.status_code}"
            await asyncio.sleep(3.0)
        print(f"[error] no usable agent within {timeout:.0f}s ({last})")
        return None

    async def ensure_corpus(self, corpus_path: Path) -> int:
        """Ingest the fixed corpus into the knowledge store (idempotent by id)."""
        if not corpus_path.exists():
            print(f"[warn] corpus file missing: {corpus_path}; skipping ingest")
            return 0
        docs = [json.loads(line) for line in corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        n = 0
        async with httpx.AsyncClient() as c:
            for d in docs:
                doc = {
                    "id": d["id"],
                    "title": d.get("title", d["id"]),
                    "content": d["content"],
                    "size": len(d["content"]),
                }
                try:
                    r = await c.post(f"{self.ks_url}/", json=doc, timeout=60.0)
                    if r.status_code in (200, 201):
                        n += 1
                except Exception as e:  # noqa: BLE001
                    print(f"[warn] corpus ingest failed for {d['id']}: {e}")
        print(f"[info] ingested {n}/{len(docs)} corpus docs into knowledge store")
        return n

    async def create_conversation(self, name: str) -> int | None:
        async with httpx.AsyncClient() as c:
            r = await c.post(
                f"{self.mas_url}/conversations/create-conversation/",
                json={"name": name},
                headers=self._headers(),
                timeout=15.0,
            )
        if r.status_code in (200, 201):
            return r.json().get("conversation_id")
        print(f"[warn] create conversation failed: HTTP {r.status_code} — {r.text[:200]}")
        return None

    async def run_task(
        self, prompt: dict, agent_id: str, skill: str, conv_id: int, verbose: bool = False
    ) -> TaskMetrics:
        m = TaskMetrics(prompt_id=prompt["id"])
        ws_url = f"{self.ws_base}/chat/{conv_id}/?token={self.token}"
        try:
            # Connect the WebSocket BEFORE submitting so we never miss early steps.
            async with websockets.connect(ws_url, max_size=16 * 1024 * 1024, open_timeout=20) as ws:
                t0 = time.perf_counter()
                payload = {
                    "demand": prompt["query"],
                    "conversation_id": conv_id,
                    "skills_required": prompt.get("skills_required") or [skill],
                    "agent_id": agent_id,
                    "mode": "specific_agent",
                }
                async with httpx.AsyncClient() as c:
                    ht0 = time.perf_counter()
                    r = await c.post(
                        f"{self.mas_url}/tasks/new_task/",
                        json=payload,
                        headers=self._headers(),
                        timeout=30.0,
                    )
                    m.submit_http_ms = round((time.perf_counter() - ht0) * 1000, 2)

                if r.status_code != 200:
                    m.error = f"new_task HTTP {r.status_code}: {r.text[:200]}"
                    return m
                body = r.json()
                # Direct router answer (no worker dispatch) — shouldn't happen in
                # specific_agent mode, but handle it so we never hang.
                if body.get("result"):
                    m.direct = True
                    m.ok = True
                    m.e2e_s = round(time.perf_counter() - t0, 4)
                    m.output_chars = len(body["result"])
                    m.output_tokens = self.count(body["result"])
                    return m

                reasoning_start: float | None = None
                deadline = time.perf_counter() + self.event_timeout
                terminal_at: float | None = None  # set when task_complete arrives
                # task_step events are POSTed fire-and-forget on daemon threads in
                # the agent, so reasoning.done can race BEHIND task_complete. After
                # the terminal event we keep draining for `grace` seconds to catch it.
                grace = 3.0
                while True:
                    if terminal_at is not None:
                        remaining = grace - (time.perf_counter() - terminal_at)
                    else:
                        remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        if terminal_at is None:
                            m.error = "timeout waiting for task_complete"
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    except asyncio.TimeoutError:
                        if terminal_at is None:
                            m.error = "timeout waiting for task_complete"
                        break
                    try:
                        ev = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    et = ev.get("type")
                    now = round(time.perf_counter() - t0, 4)
                    if verbose:
                        print(f"    [{now:7.3f}s] {et:14} {ev.get('step_type') or ev.get('skill_used') or ''}")
                    if et == "task_step":
                        st = ev.get("step_type")
                        m.steps.append({"step_type": st, "offset_s": now})
                        if m.first_step_s is None:
                            m.first_step_s = now
                        if st == "reasoning.start":
                            m.ttft_proxy_s = now
                            reasoning_start = now
                            meta = ev.get("metadata") or {}
                            m.model = meta.get("model")
                            m.device = meta.get("device")
                        elif st == "reasoning.done":
                            meta = ev.get("metadata") or {}
                            ds = meta.get("duration_seconds")
                            if isinstance(ds, (int, float)):
                                m.decode_s = float(ds)
                            gt = meta.get("generated_tokens")
                            if isinstance(gt, int):
                                m.generated_tokens = gt
                            pt = meta.get("prompt_tokens")
                            if isinstance(pt, int):
                                m.prompt_tokens = pt
                            if reasoning_start is not None:
                                m.decode_wall_s = round(now - reasoning_start, 4)
                            if terminal_at is not None:
                                break  # got the late step; stop draining early
                    elif et in ("task_complete", "agent"):
                        # Skip the Manager's plan announcement (decompose mode);
                        # in specific_agent mode this is the specialist's answer.
                        if ev.get("skill_used") == "planning":
                            continue
                        if terminal_at is not None:
                            continue
                        content = ev.get("content") or ""
                        m.e2e_s = now
                        m.output_chars = len(content)
                        m.output_tokens = self.count(content)
                        if GUARD_FALLBACK_MARKER in content:
                            m.suspected_spiral = True
                        m.ok = True
                        terminal_at = time.perf_counter()
                        # don't break yet — drain up to `grace`s for a late reasoning.done

                # decode tok/s from the EXACT generated-token count when the agent
                # reports it (spiral-proof); otherwise fall back to counting the
                # visible answer text. Also flag a spiral when the model produced
                # far more than it kept (guard fired but marker text changed).
                if (
                    m.generated_tokens
                    and m.output_tokens
                    and m.generated_tokens > 2 * max(m.output_tokens, 32)
                ):
                    m.suspected_spiral = True
                rate_tokens = m.generated_tokens or m.output_tokens
                if rate_tokens:
                    m.decode_tok_s_basis = "generated" if m.generated_tokens else "output"
                dec = m.decode_s or m.decode_wall_s
                if m.ok and rate_tokens and dec and dec > 0:
                    m.decode_tok_s = round(rate_tokens / dec, 3)
        except Exception as e:  # noqa: BLE001
            m.error = f"{type(e).__name__}: {e}"
        return m

    async def ks_ingest_loop(self, docs: list[dict], workers: int, stop: asyncio.Event) -> int:
        """Continuously POST documents to the KS to keep the BGE embedder busy.

        Ids cycle over a bounded window so the store doesn't grow without bound,
        while each POST still forces a fresh GPU embedding (the contention we want).
        """
        counter = {"n": 0}
        # Unrelated filler — exercises the BGE embedder (GPU contention) WITHOUT
        # polluting the Acme corpus the agent retrieves from (which would change
        # the workload and confound the comparison). `docs` is intentionally unused.
        filler = (
            "Synthetic load document for embedder contention measurement only. "
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
            "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam. "
        )

        async def worker(wid: int) -> None:
            async with httpx.AsyncClient() as c:
                i = 0
                while not stop.is_set():
                    content = f"{filler} (worker {wid}, item {i})"
                    doc = {
                        "id": f"bench-load-{wid}-{i % 64}",
                        "title": f"load-{wid}",
                        "content": content,
                        "size": len(content),
                    }
                    try:
                        await c.post(f"{self.ks_url}/", json=doc, timeout=30.0)
                        counter["n"] += 1
                    except Exception:  # noqa: BLE001
                        pass
                    i += 1

        await asyncio.gather(*(worker(w) for w in range(workers)))
        return counter["n"]


# --------------------------------------------------------------------------- #
# scenarios
# --------------------------------------------------------------------------- #
def _print_task_line(m: TaskMetrics) -> None:
    if not m.ok:
        print(f"  [{m.prompt_id:10}] FAILED — {m.error}")
        return
    print(
        f"  [{m.prompt_id:10}] e2e={m.e2e_s:6.2f}s  ttft~={_fmt(m.ttft_proxy_s)}s  "
        f"decode={_fmt(m.decode_s)}s  tok={m.output_tokens or 0:4}  "
        f"tok/s={_fmt(m.decode_tok_s)}  dev={m.device or '?'}"
    )


def _fmt(v) -> str:
    return f"{v:.2f}" if isinstance(v, (int, float)) else "  ? "


async def scenario_idle(bench: PipelineBench, prompts, agent_id, skill, repeats) -> dict:
    print(f"\n=== idle (sequential single-task) — {repeats} repeat(s) × {len(prompts)} prompts ===")
    sampler = GpuSampler()
    sampler.start()
    results: list[TaskMetrics] = []
    for rep in range(repeats):
        for p in prompts:
            conv = await bench.create_conversation(f"bench-idle-{p['id']}-{rep}")
            if conv is None:
                continue
            m = await bench.run_task(p, agent_id, skill, conv)
            results.append(m)
            _print_task_line(m)
    gpu = sampler.stop()
    base, counts = _spiral_split(results)
    return {
        "results": [asdict(m) for m in results],
        "summary": {
            "ok": counts["ok"],
            "total": len(results),
            "clean": counts["clean"],
            "suspected_spiral": counts["suspected_spiral"],
            "submit_http_ms": summarize([m.submit_http_ms for m in base]),
            "first_step_s": summarize([m.first_step_s for m in base]),
            "ttft_proxy_s": summarize([m.ttft_proxy_s for m in base]),
            "decode_s": summarize([m.decode_s for m in base]),
            "decode_tok_s": summarize([m.decode_tok_s for m in base]),
            "e2e_s": summarize([m.e2e_s for m in base]),
            "output_tokens": summarize([m.output_tokens for m in base]),
        },
        "gpu": gpu,
    }


async def scenario_concurrency(bench: PipelineBench, prompts, agent_id, skill, levels) -> dict:
    print(f"\n=== concurrency — levels {levels} ===")
    out = {}
    for n in levels:
        batch = [prompts[i % len(prompts)] for i in range(n)]
        convs = []
        for i in range(n):
            conv = await bench.create_conversation(f"bench-conc{n}-{i}")
            convs.append(conv)
        sampler = GpuSampler()
        sampler.start()
        wall0 = time.perf_counter()
        tasks = [
            bench.run_task(p, agent_id, skill, c)
            for p, c in zip(batch, convs, strict=False)
            if c is not None
        ]
        ms = await asyncio.gather(*tasks)
        wall = time.perf_counter() - wall0
        gpu = sampler.stop()
        ok = [m for m in ms if m.ok]
        base, counts = _spiral_split(ms)
        agg_tokens = sum(m.output_tokens or 0 for m in ok)
        out[str(n)] = {
            "concurrency": n,
            "ok": len(ok),
            "total": len(ms),
            "clean": counts["clean"],
            "suspected_spiral": counts["suspected_spiral"],
            "wall_s": round(wall, 3),
            # aggregate throughput intentionally counts ALL completed work (incl.
            # spirals) — it's a wall-clock load metric; the per-task decode_tok_s
            # / e2e_s summaries below use the clean subset.
            "aggregate_output_tokens": agg_tokens,
            "aggregate_tok_s": round(agg_tokens / wall, 3) if wall > 0 else 0,
            "e2e_s": summarize([m.e2e_s for m in base]),
            "decode_tok_s": summarize([m.decode_tok_s for m in base]),
            "results": [asdict(m) for m in ms],
            "gpu": gpu,
        }
        print(
            f"  n={n:2}  ok={len(ok)}/{len(ms)}  wall={wall:6.2f}s  "
            f"agg_tok/s={out[str(n)]['aggregate_tok_s']:7.2f}  "
            f"e2e_p95={out[str(n)]['e2e_s'].get('p95', 0):.2f}s"
        )
    return out


async def scenario_contention(bench, prompts, agent_id, skill, gen_count, ks_workers, corpus_docs) -> dict:
    print(f"\n=== contention — {gen_count} gens idle vs. {ks_workers}-worker KS ingestion load ===")

    # Use ONE fixed, stable prompt for every generation so the idle-vs-loaded
    # delta reflects embedder contention, not per-prompt variance. q-risks
    # (last prompt) is the longest stable generation (~400 tokens) — a meaty,
    # repeatable decode window for the contention signal to show up in.
    cprompt = prompts[-1]

    async def measure(label: str) -> list[TaskMetrics]:
        res = []
        for i in range(gen_count):
            conv = await bench.create_conversation(f"bench-cont-{label}-{i}")
            if conv is None:
                continue
            m = await bench.run_task(cprompt, agent_id, skill, conv)
            res.append(m)
            _print_task_line(m)
        return res

    print("  -- baseline (no KS load) --")
    sampler_b = GpuSampler()
    sampler_b.start()
    base = await measure("base")
    gpu_base = sampler_b.stop()

    print("  -- under KS ingestion load --")
    stop = asyncio.Event()
    load = asyncio.create_task(bench.ks_ingest_loop(corpus_docs, ks_workers, stop))
    await asyncio.sleep(2.0)  # let the load ramp
    sampler_l = GpuSampler()
    sampler_l.start()
    loaded = await measure("load")
    gpu_load = sampler_l.stop()
    stop.set()
    docs_ingested = await load

    base_c, base_counts = _spiral_split(base)
    loaded_c, load_counts = _spiral_split(loaded)
    base_tok = summarize([m.decode_tok_s for m in base_c])
    load_tok = summarize([m.decode_tok_s for m in loaded_c])
    base_e2e = summarize([m.e2e_s for m in base_c])
    load_e2e = summarize([m.e2e_s for m in loaded_c])
    drop = None
    if base_tok.get("median") and load_tok.get("median"):
        drop = round((base_tok["median"] - load_tok["median"]) / base_tok["median"] * 100, 1)
    print(
        f"  decode tok/s  idle={base_tok.get('median', 0):.2f}  "
        f"loaded={load_tok.get('median', 0):.2f}  drop={drop}%  "
        f"(docs ingested during load: {docs_ingested})"
    )
    return {
        "gen_count": gen_count,
        "ks_workers": ks_workers,
        "docs_ingested_under_load": docs_ingested,
        "baseline": {
            "decode_tok_s": base_tok,
            "e2e_s": base_e2e,
            "suspected_spiral": base_counts["suspected_spiral"],
            "results": [asdict(m) for m in base],
            "gpu": gpu_base,
        },
        "loaded": {
            "decode_tok_s": load_tok,
            "e2e_s": load_e2e,
            "suspected_spiral": load_counts["suspected_spiral"],
            "results": [asdict(m) for m in loaded],
            "gpu": gpu_load,
        },
        "decode_tok_s_drop_pct": drop,
    }


async def scenario_smoke(bench, prompts, agent_id, skill) -> dict:
    print("\n=== smoke (1 task, verbose event dump) ===")
    conv = await bench.create_conversation("bench-smoke")
    m = await bench.run_task(prompts[0], agent_id, skill, conv, verbose=True)
    print("\n  metrics:")
    for k, v in asdict(m).items():
        if k != "steps":
            print(f"    {k:16} = {v}")
    return {"result": asdict(m)}


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def _md_stat_row(label: str, s: dict) -> str:
    if not s or s.get("n", 0) == 0:
        return f"| {label} | — | — | — | — | — |"
    return (
        f"| {label} | {s.get('median', 0):.3f} | {s.get('mean', 0):.3f} | "
        f"{s.get('p95', 0):.3f} | {s.get('min', 0):.3f} | {s.get('max', 0):.3f} |"
    )


def build_markdown(report: dict) -> str:
    cfg = report["config"]
    lines = [
        f"# Pipeline benchmark — `{report['label']}`",
        "",
        f"- **Timestamp:** {report['timestamp']}",
        f"- **Git commit:** {report.get('git_commit')}",
        f"- **GPU:** {report['machine'].get('name')} (driver {report['machine'].get('driver')}, {report['machine'].get('memory_total')})",
        f"- **MAS:** {cfg['mas_url']}  ·  **KS:** {cfg['ks_url']}",
        f"- **Agent:** `{cfg.get('agent_id')}` · model `{cfg.get('observed_model')}` · device `{cfg.get('observed_device')}`",
        f"- **Token count method:** {cfg['token_method']}",
        f"- **Server gen params (resolved):** AGENT_MAX_NEW_TOKENS={cfg.get('agent_max_new_tokens')}, KNOWLEDGE_STORE_N_RESULTS={cfg.get('knowledge_store_n_results')}",
        "",
        "> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). "
        "`ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. "
        "All times in seconds unless noted.",
        "",
    ]
    sc = report["scenarios"]

    if "idle" in sc:
        s = sc["idle"]["summary"]
        g = sc["idle"]["gpu"]
        lines += [
            "## Idle (single task, sequential)",
            "",
            f"Tasks OK: {s['ok']}/{s['total']}"
            + (
                f" · {s['suspected_spiral']} suspected-spiral excluded from aggregates"
                if s.get("suspected_spiral")
                else ""
            ),
            "",
            "| metric | median | mean | p95 | min | max |",
            "|---|---|---|---|---|---|",
            _md_stat_row("ttft_proxy_s", s["ttft_proxy_s"]),
            _md_stat_row("decode_s", s["decode_s"]),
            _md_stat_row("decode_tok_s", s["decode_tok_s"]),
            _md_stat_row("e2e_s", s["e2e_s"]),
            _md_stat_row("output_tokens", s["output_tokens"]),
            "",
            f"GPU: VRAM peak {g.get('vram_used_mib', {}).get('peak', '?')} MiB · "
            f"util mean {g.get('gpu_util_pct', {}).get('mean', '?')}% · "
            f"power mean {g.get('power_w', {}).get('mean', '?')} W",
            "",
        ]

    if "concurrency" in sc:
        lines += [
            "## Concurrency (N tasks fired simultaneously)",
            "",
            "| N | ok | wall_s | aggregate_tok/s | e2e median | e2e p95 | VRAM peak MiB |",
            "|---|---|---|---|---|---|---|",
        ]
        for n in sorted(sc["concurrency"], key=int):
            c = sc["concurrency"][n]
            lines.append(
                f"| {c['concurrency']} | {c['ok']}/{c['total']} | {c['wall_s']:.2f} | "
                f"{c['aggregate_tok_s']:.2f} | {c['e2e_s'].get('median', 0):.2f} | "
                f"{c['e2e_s'].get('p95', 0):.2f} | {c['gpu'].get('vram_used_mib', {}).get('peak', '?')} |"
            )
        lines.append("")

    if "contention" in sc:
        c = sc["contention"]
        b, loaded = c["baseline"], c["loaded"]
        lines += [
            "## Contention (generation vs. concurrent KS ingestion)",
            "",
            f"KS load: {c['ks_workers']} workers, {c['docs_ingested_under_load']} docs embedded during the loaded run.",
            "",
            "| state | decode_tok/s median | e2e median | VRAM peak MiB | GPU util mean % |",
            "|---|---|---|---|---|",
            f"| idle | {b['decode_tok_s'].get('median', 0):.2f} | {b['e2e_s'].get('median', 0):.2f} | "
            f"{b['gpu'].get('vram_used_mib', {}).get('peak', '?')} | {b['gpu'].get('gpu_util_pct', {}).get('mean', '?')} |",
            f"| under load | {loaded['decode_tok_s'].get('median', 0):.2f} | {loaded['e2e_s'].get('median', 0):.2f} | "
            f"{loaded['gpu'].get('vram_used_mib', {}).get('peak', '?')} | {loaded['gpu'].get('gpu_util_pct', {}).get('mean', '?')} |",
            "",
            f"**Decode tok/s drop under load: {c['decode_tok_s_drop_pct']}%** "
            "— this is the headroom the NPU embedder offload (Phase 6) can recover.",
            "",
        ]

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
async def main() -> int:
    # Windows consoles default to cp1252; our progress output and the rendered
    # markdown contain unicode (e.g. the → in "submit→reasoning.start").
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    parser = argparse.ArgumentParser(description="Horus end-to-end LLM pipeline benchmark")
    parser.add_argument("--mas-url", default=os.environ.get("MAS_URL", "http://localhost:8000"))
    parser.add_argument("--ks-url", default=os.environ.get("KS_URL", "http://localhost:8080"))
    parser.add_argument("--username", default=os.environ.get("SUPER_USER_USERNAME", "admin"))
    parser.add_argument("--password", default=os.environ.get("SUPER_USER_PASSWORD", "secret"))
    parser.add_argument("--token", default=None, help="Bearer JWT (skips /auth/token)")
    parser.add_argument(
        "--scenario",
        default="all",
        choices=["all", "smoke", "idle", "concurrency", "contention"],
    )
    parser.add_argument("--label", default="baseline", help="Result label")
    parser.add_argument("--repeats", type=int, default=2, help="Idle repeats over the prompt set")
    parser.add_argument(
        "--concurrency", default="1,2,4,8", help="Comma-separated concurrency levels"
    )
    parser.add_argument("--gen-count", type=int, default=4, help="Generations per contention phase")
    parser.add_argument("--ks-workers", type=int, default=3, help="KS ingestion load workers")
    parser.add_argument("--event-timeout", type=float, default=240.0, help="Per-task event timeout (s)")
    parser.add_argument("--no-ingest", action="store_true", help="Skip corpus ingestion")
    parser.add_argument("--no-warmup", action="store_true", help="Skip the warmup task")
    parser.add_argument("--hf-tokenizer", default=None, help="HF model id for exact token counts")
    parser.add_argument("--output-dir", default=str(RESULTS_DIR))
    args = parser.parse_args()

    if websockets is None:
        print("[fatal] the 'websockets' package is required: pip install websockets")
        return 2

    counter, token_method = make_token_counter(args.hf_tokenizer)
    bench = PipelineBench(args.mas_url, args.ks_url, counter, token_method, args.event_timeout)

    if args.token:
        bench.token = args.token
        print("[info] using provided --token")
    else:
        print(f"[info] authenticating as {args.username} ...")
        if not await bench.authenticate(args.username, args.password):
            return 1

    prompts = [
        json.loads(line)
        for line in (ASSETS / "prompts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    corpus_docs = [
        json.loads(line)
        for line in (ASSETS / "corpus.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if not args.no_ingest:
        await bench.ensure_corpus(ASSETS / "corpus.jsonl")

    picked = await bench.wait_for_agent()
    if picked is None:
        return 1
    agent_id, skill = picked

    if not args.no_warmup:
        print("[info] warmup task (cold model load / first compile not counted) ...")
        conv = await bench.create_conversation("bench-warmup")
        if conv is not None:
            w = await bench.run_task(prompts[0], agent_id, skill, conv)
            _print_task_line(w)
            if not w.ok:
                print("[warn] warmup task failed — check the stack before trusting results")

    scenarios: dict = {}
    want = args.scenario
    levels = [int(x) for x in args.concurrency.split(",") if x.strip()]

    if want == "smoke":
        scenarios["smoke"] = await scenario_smoke(bench, prompts, agent_id, skill)
    if want in ("all", "idle"):
        scenarios["idle"] = await scenario_idle(bench, prompts, agent_id, skill, args.repeats)
    if want in ("all", "concurrency"):
        scenarios["concurrency"] = await scenario_concurrency(bench, prompts, agent_id, skill, levels)
    if want in ("all", "contention"):
        scenarios["contention"] = await scenario_contention(
            bench, prompts, agent_id, skill, args.gen_count, args.ks_workers, corpus_docs
        )

    # observed model/device from any successful task (walk all scenario results)
    observed_model = observed_device = None

    def _scan(obj):
        nonlocal observed_model, observed_device
        if isinstance(obj, dict):
            if obj.get("model") and not observed_model:
                observed_model = obj.get("model")
            if obj.get("device") and not observed_device:
                observed_device = obj.get("device")
            for v in obj.values():
                _scan(v)
        elif isinstance(obj, list):
            for v in obj:
                _scan(v)

    _scan(scenarios)

    report = {
        "label": args.label,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": git_commit(),
        "machine": gpu_info(),
        "config": {
            "mas_url": args.mas_url,
            "ks_url": args.ks_url,
            "scenario": args.scenario,
            "repeats": args.repeats,
            "concurrency_levels": levels,
            "gen_count": args.gen_count,
            "ks_workers": args.ks_workers,
            "token_method": token_method,
            "agent_id": agent_id,
            "skill": skill,
            "observed_model": observed_model,
            "observed_device": observed_device,
            "agent_max_new_tokens": _server_param("AGENT_MAX_NEW_TOKENS", "256 (agent code default)"),
            "knowledge_store_n_results": _server_param("KNOWLEDGE_STORE_N_RESULTS", "8 (agent settings default)"),
        },
        "scenarios": scenarios,
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    base = out_dir / f"pipeline-{args.label}-{stamp}"
    base.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = build_markdown(report)
    base.with_suffix(".md").write_text(md, encoding="utf-8")
    print(f"\n[done] wrote {base.with_suffix('.json').name} and {base.with_suffix('.md').name}")
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
