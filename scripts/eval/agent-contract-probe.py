from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

AGENT_APP_DIR = "/app"
ERROR_STAGE_RETRIEVAL = "retrieval"
ERROR_STAGE_LLM = "llm"
ERROR_BODY_CHARS = 300


@dataclass
class PreparedRequest:
    payload: dict[str, Any]
    url: str
    timeout: float
    labels: list[str]
    sources_by_label: dict[str, dict[str, Any]]
    schema: dict[str, Any]
    retrieved_titles: list[str]


def completion_payload(
    model: str, system: str, user: str, max_tokens: int, response_format: dict[str, Any]
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
        "response_format": response_format,
    }


def reply_from_response(body: dict[str, Any], wall_s: float) -> dict[str, Any]:
    choices = body.get("choices") if isinstance(body, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    return {
        "content": message.get("content"),
        "reasoning_content": message.get("reasoning_content"),
        "finish_reason": choice.get("finish_reason"),
        "usage": body.get("usage"),
        "timings": body.get("timings"),
        "wall_s": round(wall_s, 3),
    }


def distinct_titles(passages: Any) -> list[str]:
    titles: list[str] = []
    for passage in passages if isinstance(passages, list) else []:
        title = passage.get("title") if isinstance(passage, dict) else None
        if isinstance(title, str) and title and title not in titles:
            titles.append(title)
    return titles


class AgentContract:
    def __init__(self, contract: Any, agent: Any, store_client: Any) -> None:
        self.contract = contract
        self.agent = agent
        self.store_client = store_client

    async def retrieve(self, question: str) -> dict[str, Any]:
        data = await self.store_client(question)
        return data if isinstance(data, dict) else {}

    def retrieval_error(self, data: dict[str, Any]) -> str | None:
        if data.get("passages"):
            return None
        error = data.get("error")
        return str(error) if error else None

    def prepare(self, question: str, data: dict[str, Any]) -> PreparedRequest:
        passages = data.get("passages") if isinstance(data.get("passages"), list) else []
        catalog = self.contract.SourceCatalog()
        if passages:
            context = catalog.format_passages(passages, self.agent._max_context_chars())
        else:
            context = data.get("data", "")
        system, user = self.contract.answer_prompt(question, context, catalog.labels)
        user, max_tokens = self.agent._fit_vllm_prompt(system, user)
        response_format = self.contract.answer_response_format(catalog.labels)
        labels = list(catalog.labels)
        return PreparedRequest(
            payload=completion_payload(
                self.agent._vllm_model_name(), system, user, max_tokens, response_format
            ),
            url=self.agent._vllm_base_url().rstrip("/") + "/chat/completions",
            timeout=self.agent._vllm_timeout(),
            labels=labels,
            sources_by_label=dict(zip(labels, catalog.cite(labels), strict=True)),
            schema=response_format["json_schema"]["schema"],
            retrieved_titles=distinct_titles(passages),
        )


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:ERROR_BODY_CHARS]
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


async def probe_item(
    item: dict[str, Any],
    contract: AgentContract,
    post: Callable[[str, dict[str, Any], float], dict[str, Any]] = post_json,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    record: dict[str, Any] = {"id": item["id"]}
    try:
        data = await contract.retrieve(item["question"])
    except Exception as exc:  # noqa: BLE001
        return {
            **record,
            "error_stage": ERROR_STAGE_RETRIEVAL,
            "error": f"{type(exc).__name__}: {exc}",
        }
    error = contract.retrieval_error(data)
    if error:
        return {**record, "error_stage": ERROR_STAGE_RETRIEVAL, "error": error}
    prepared = contract.prepare(item["question"], data)
    record.update(
        labels=prepared.labels,
        sources_by_label=prepared.sources_by_label,
        schema=prepared.schema,
        retrieved_titles=prepared.retrieved_titles,
        max_tokens=prepared.payload["max_tokens"],
    )
    started = clock()
    try:
        body = post(prepared.url, prepared.payload, prepared.timeout)
    except Exception as exc:  # noqa: BLE001
        return {
            **record,
            "error_stage": ERROR_STAGE_LLM,
            "error": f"{type(exc).__name__}: {exc}",
            "wall_s": round(clock() - started, 3),
        }
    return {**record, **reply_from_response(body, clock() - started)}


async def run_probe(
    job: dict[str, Any],
    contract: AgentContract,
    emit: Callable[[dict[str, Any]], None],
    post: Callable[[str, dict[str, Any], float], dict[str, Any]] = post_json,
    progress: Callable[[str], None] = lambda _line: None,
) -> int:
    warmup = job.get("warmup")
    if warmup:
        progress(f"[info] warmup (not scored): {warmup}")
        await probe_item({"id": "warmup", "question": warmup}, contract, post)
    items = job.get("items") or []
    for index, item in enumerate(items, 1):
        record = await probe_item(item, contract, post)
        emit(record)
        progress(
            f"[{index:3}/{len(items)}] {item['id']} {record.get('error') or record.get('finish_reason')}"
        )
    return len(items)


def load_agent_contract(app_dir: str) -> AgentContract:
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    contract = importlib.import_module("ai_agents.answer_contract")
    agent = importlib.import_module("ai_agents.decision_making_agent")
    store = importlib.import_module("ai_agents.knowledge_store_client")
    return AgentContract(contract, agent, store.KnowledgeStoreClient())


def main() -> int:
    job = json.loads(sys.stdin.read() or "{}")
    contract = load_agent_contract(os.environ.get("HORUS_AGENT_APP_DIR", AGENT_APP_DIR))

    def emit(record: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def progress(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    asyncio.run(run_probe(job, contract, emit, post=post_json, progress=progress))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
