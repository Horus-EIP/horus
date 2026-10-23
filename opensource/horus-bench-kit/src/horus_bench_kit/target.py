# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PureWindowsPath
from typing import Any, Protocol, TypedDict, runtime_checkable

from horus_bench_kit.testset import file_sha256

MODE_CHAT = "chat"
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"


class Outcome(TypedDict, total=False):
    mode: str
    status: str
    error: str | None
    answer: str | None
    cited_sources: list[str] | None
    retrieved_sources: list[list[str]] | None
    retrieval_steps: int | None
    observed_route: str | None
    timing_source: str | None
    ttft_s: float | None
    total_s: float | None
    models: list[str]
    usage: dict[str, Any] | None


@runtime_checkable
class Target(Protocol):
    name: str

    async def ask(self, question: str, *, item_id: str, files: Sequence[Path] = ()) -> Outcome: ...


class Hooks(Protocol):
    async def start(self) -> None: ...

    async def before(self) -> None: ...

    async def after(self, outcome: dict[str, Any]) -> None: ...


def progress_line(index: int, total: int, record: dict[str, Any]) -> str:
    def flag(value: bool | None) -> str:
        return "-" if value is None else ("yes" if value else "no")

    seconds = record.get("total_s")
    shown = f"{seconds:8.2f}s" if isinstance(seconds, (int, float)) else "       ?s"
    return (
        f"[{index:3}/{total}] {record['id']:10} {record['status']:7} {shown}  "
        f"answer={flag(record.get('answer_correct_auto'))} "
        f"source={flag(record.get('source_correct_auto'))} "
        f"route={flag(record.get('route_correct'))}"
        + (f"  ({record['error']})" if record.get("error") else "")
    )


def no_files(_item: dict[str, Any]) -> Sequence[Path]:
    return ()


def ignore_records(_records: list[dict[str, Any]]) -> None:
    return None


async def run_items(
    target: Target,
    items: list[dict[str, Any]],
    *,
    record: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    on_record: Callable[[list[dict[str, Any]]], None] = ignore_records,
    hooks: Hooks | None = None,
    files_for: Callable[[dict[str, Any]], Sequence[Path]] = no_files,
    progress: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if hooks:
        await hooks.start()
    for index, item in enumerate(items, 1):
        if hooks:
            await hooks.before()
        outcome = dict(
            await target.ask(item["question"], item_id=item["id"], files=files_for(item))
        )
        if hooks:
            await hooks.after(outcome)
        records.append(record(item, outcome))
        progress(progress_line(index, len(items), records[-1]))
        on_record(records)
    return records


def absolute_on_another_os(path: str) -> bool:
    return PureWindowsPath(path).is_absolute() and not Path(path).is_absolute()


def shown_path(path: Path | str, root: Path | str | None = None) -> str:
    if absolute_on_another_os(str(path)):
        return PureWindowsPath(str(path)).name
    resolved = Path(path).resolve()
    if root is not None:
        try:
            return resolved.relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass
    return resolved.name


def testset_info(
    path: Path | str,
    testset: dict[str, Any],
    items: list[dict[str, Any]],
    filters: Mapping[str, Any],
    *,
    root: Path | str | None = None,
    sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "path": shown_path(path, root),
        "version": str(testset["version"]),
        "sha256": sha256 if sha256 is not None else file_sha256(Path(path).resolve()),
        "corpus": testset["corpus"],
        "items_total": len(testset["items"]),
        "items_run": len(items),
        "filters": dict(filters),
    }


def observed_values(records: list[dict[str, Any]], field: str) -> list[str]:
    values: list[str] = []
    for record in records:
        for value in record.get(field) or []:
            if value not in values:
                values.append(value)
    return values
