# SPDX-License-Identifier: Apache-2.0
import asyncio
import json
import os
from pathlib import Path

import pytest

from horus_bench_kit.report import question_record
from horus_bench_kit.target import (
    Target,
    absolute_on_another_os,
    observed_values,
    progress_line,
    run_items,
    shown_path,
)
from horus_bench_kit.target import testset_info as describe_testset
from horus_bench_kit.testset import file_sha256


class ScriptedTarget:
    name = "scripted"

    def __init__(self, answers, events=None):
        self.answers = answers
        self.events = events if events is not None else []
        self.asked = []

    async def ask(self, question, *, item_id, files=()):
        self.events.append(f"ask:{item_id}")
        self.asked.append((question, item_id, list(files)))
        return {"mode": "chat", "status": "ok", "answer": self.answers[item_id], "total_s": 1.5}


class RecordingHooks:
    def __init__(self, events):
        self.events = events

    async def start(self):
        self.events.append("start")

    async def before(self):
        self.events.append("before")

    async def after(self, outcome):
        self.events.append("after")
        outcome["models"] = ["seen-by-hook"]


@pytest.fixture
def items(make_item):
    return [
        make_item(id="t-01"),
        make_item(id="t-02", question="Who is the harbour master?", answer_patterns=["Brandt"]),
    ]


class TestTargetProtocol:
    def test_anything_with_a_name_and_an_ask_coroutine_is_a_target(self):
        assert isinstance(ScriptedTarget({}), Target)
        assert not isinstance(object(), Target)


class TestRunItems:
    def test_every_item_is_asked_recorded_and_saved_in_order(self, items):
        target = ScriptedTarget({"t-01": "Fourteen.", "t-02": "Someone else."})
        saved, lines = [], []
        records = asyncio.run(
            run_items(
                target,
                items,
                record=question_record,
                on_record=lambda records: saved.append([r["id"] for r in records]),
                progress=lines.append,
            )
        )
        assert [r["id"] for r in records] == ["t-01", "t-02"]
        assert [r["answer_correct_auto"] for r in records] == [True, False]
        assert saved == [["t-01"], ["t-01", "t-02"]]
        assert lines[0].startswith("[  1/2] t-01")
        assert target.asked[1] == ("Who is the harbour master?", "t-02", [])

    def test_hooks_run_around_each_question_and_may_add_outcome_fields(self, items):
        events = []
        target = ScriptedTarget({"t-01": "14", "t-02": "Brandt"}, events)
        records = asyncio.run(
            run_items(target, items, record=question_record, hooks=RecordingHooks(events), progress=lambda _: None)
        )
        assert events == ["start", "before", "ask:t-01", "after", "before", "ask:t-02", "after"]
        assert records[0]["models"] == ["seen-by-hook"]

    def test_files_for_chooses_the_files_of_each_item(self, items, tmp_path):
        context = tmp_path / "t-01.txt"
        target = ScriptedTarget({"t-01": "14", "t-02": "Brandt"})
        asyncio.run(
            run_items(
                target,
                items,
                record=question_record,
                files_for=lambda item: [context] if item["id"] == "t-01" else [],
                progress=lambda _: None,
            )
        )
        assert [asked[2] for asked in target.asked] == [[context], []]

    def test_the_outcome_returned_by_the_target_is_not_changed(self, items):
        shared = {"mode": "chat", "status": "ok", "answer": "14"}

        class SharedTarget:
            name = "shared"

            async def ask(self, question, *, item_id, files=()):
                return shared

        asyncio.run(
            run_items(SharedTarget(), items[:1], record=question_record, hooks=RecordingHooks([]), progress=lambda _: None)
        )
        assert "models" not in shared


class TestProgressLine:
    def test_line_shows_status_time_and_flags(self):
        record = {
            "id": "pier-01",
            "status": "ok",
            "total_s": 12.5,
            "answer_correct_auto": True,
            "source_correct_auto": False,
            "route_correct": None,
            "error": None,
        }
        assert progress_line(1, 100, record) == (
            "[  1/100] pier-01    ok         12.50s  answer=yes source=no route=-"
        )

    def test_unknown_time_and_errors_are_shown(self):
        record = {"id": "pier-02", "status": "error", "total_s": None, "error": "HTTP 500: boom"}
        line = progress_line(2, 2, record)
        assert "       ?s" in line
        assert line.endswith("route=-  (HTTP 500: boom)")


class TestTestsetInfo:
    def test_a_test_set_inside_the_root_is_recorded_relative_to_it(self, tmp_path):
        path = tmp_path / "sets" / "harbour.json"
        path.parent.mkdir()
        path.write_text("{}", encoding="utf-8")
        testset = {"version": 1.0, "corpus": {"north-pier.md": "0" * 64}, "items": [{}, {}]}
        filters = {"ids": None, "categories": ["lookup"], "limit": 1}
        assert describe_testset(path, testset, [{}], filters, root=tmp_path) == {
            "path": "sets/harbour.json",
            "version": "1.0",
            "sha256": file_sha256(path),
            "corpus": {"north-pier.md": "0" * 64},
            "items_total": 2,
            "items_run": 1,
            "filters": {"ids": None, "categories": ["lookup"], "limit": 1},
        }

    def test_a_test_set_outside_the_root_keeps_no_part_of_its_folder(self, host_folder, host_folder_leaks):
        testset = {"version": "1.0.0", "corpus": {}, "items": []}
        info = describe_testset(f"{host_folder}/own-testset.json", testset, [], {}, root="/srv/elsewhere", sha256="0" * 64)
        assert info["path"] == "own-testset.json"
        assert host_folder_leaks(json.dumps(info)) == []

    def test_without_a_root_only_the_file_name_is_kept(self, tmp_path):
        assert shown_path(tmp_path / "deep" / "harbour.yaml") == "harbour.yaml"
        assert shown_path(Path("harbour.yaml"), root=Path.cwd()) == "harbour.yaml"

    def test_an_absolute_path_of_either_os_is_outside_a_root_that_is_the_working_folder(
        self, host_folder, host_folder_leaks, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        shown = shown_path(f"{host_folder}/own-testset.json", root=tmp_path)
        assert shown == "own-testset.json"
        assert host_folder_leaks(shown) == []


    def test_a_path_rooted_with_a_slash_inside_the_root_keeps_its_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rooted = "/" + tmp_path.relative_to(tmp_path.anchor).as_posix() + "/sets/own.json"
        assert shown_path(rooted, root=tmp_path) == "sets/own.json"


@pytest.mark.parametrize(
    ("path", "from_another_os_outside_windows"),
    [
        ("C:\\Users\\someone\\x\\own.json", True),
        ("C:/Users/someone/x/own.json", True),
        ("\\\\server\\share\\x\\own.json", True),
        ("//server/share/x/own.json", False),
        ("/home/someone/x/own.json", False),
        ("sets/own.json", False),
        ("sets\\own.json", False),
    ],
)
def test_only_a_drive_or_unc_path_read_outside_windows_comes_from_another_os(path, from_another_os_outside_windows):
    assert absolute_on_another_os(path) == (os.name != "nt" and from_another_os_outside_windows)


class TestObservedValues:
    def test_values_are_listed_once_in_first_seen_order(self):
        records = [{"models": ["b", "a"]}, {"models": None}, {"models": ["a", "c"]}, {}]
        assert observed_values(records, "models") == ["b", "a", "c"]
