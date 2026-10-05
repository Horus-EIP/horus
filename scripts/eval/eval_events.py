from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MANAGER_SKILLS = frozenset({"planning", "review", "orchestration"})
ANSWER_EVENT_TYPES = frozenset({"task_complete", "agent"})


@dataclass
class Observation:
    events: int = 0
    first_event_s: float | None = None
    retrieval_s: float | None = None
    reasoning_start_s: float | None = None
    ttft_s: float | None = None
    total_s: float | None = None
    answer: str | None = None
    answered_by: str | None = None
    retrieval_steps: int = 0
    untitled_retrieval_steps: int = 0
    rankings: list[list[str]] = field(default_factory=list)
    cited_sources: list[str] | None = None
    models: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    done: bool = False

    @property
    def retrieved_sources(self) -> list[list[str]] | None:
        if self.untitled_retrieval_steps:
            return None
        return [list(ranking) for ranking in self.rankings]


def is_final_answer(event: dict[str, Any]) -> bool:
    return event.get("type") in ANSWER_EVENT_TYPES and event.get("skill_used") not in MANAGER_SKILLS


def _add_unique(values: list[str], value: Any) -> None:
    if isinstance(value, str) and value and value not in values:
        values.append(value)


def _source_titles(entries: Any) -> list[str]:
    titles: list[str] = []
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict):
            title = entry.get("title") or entry.get("filename") or entry.get("source")
        else:
            title = entry
        _add_unique(titles, title)
    return titles


def _record_retrieval(observation: Observation, metadata: dict[str, Any]) -> None:
    observation.retrieval_steps += 1
    titles = _source_titles(metadata.get("chunks"))
    if titles or metadata.get("chunk_count") == 0:
        observation.rankings.append(titles)
    else:
        observation.untitled_retrieval_steps += 1


def apply_event(observation: Observation, event: dict[str, Any], offset_s: float) -> Observation:
    observation.events += 1
    if observation.first_event_s is None:
        observation.first_event_s = offset_s
    if event.get("type") == "task_step":
        step = event.get("step_type")
        metadata = event.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        if step == "retrieval.results":
            if observation.retrieval_s is None:
                observation.retrieval_s = offset_s
            _record_retrieval(observation, metadata)
        elif step == "reasoning.start":
            if observation.reasoning_start_s is None:
                observation.reasoning_start_s = offset_s
            _add_unique(observation.models, metadata.get("model"))
            _add_unique(observation.devices, metadata.get("device"))
        elif step == "reasoning.delta" and observation.ttft_s is None and not observation.done:
            observation.ttft_s = offset_s
        return observation
    if is_final_answer(event) and not observation.done:
        observation.answer = event.get("content") or ""
        observation.answered_by = event.get("agent_name")
        observation.total_s = offset_s
        observation.done = True
        if isinstance(event.get("sources"), list):
            observation.cited_sources = _source_titles(event["sources"])
    return observation


def fold_events(timed_events: list[tuple[float, dict[str, Any]]]) -> Observation:
    observation = Observation()
    for offset_s, event in timed_events:
        apply_event(observation, event, offset_s)
    return observation
