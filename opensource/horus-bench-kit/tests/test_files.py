# SPDX-License-Identifier: Apache-2.0
import json
import re
from datetime import date

import pytest

from horus_bench_kit.files import (
    TIMESTAMP_FORMAT,
    check_report,
    is_sha256,
    now_utc,
    read_json,
    report_path,
    safe_label,
    write_json,
)


class TestReportPath:
    def test_path_is_label_and_date(self, tmp_path):
        assert (
            report_path(tmp_path, "laptop-q4", date(2026, 10, 5))
            == tmp_path / "laptop-q4-2026-10-05.json"
        )

    def test_existing_report_is_never_overwritten(self, tmp_path):
        (tmp_path / "gpu8-2026-10-05.json").write_text("{}")
        (tmp_path / "gpu8-2026-10-05-2.json").write_text("{}")
        assert report_path(tmp_path, "gpu8", date(2026, 10, 5)).name == "gpu8-2026-10-05-3.json"

    def test_label_is_made_safe_for_a_file_name(self):
        assert safe_label(" laptop / q8_0 kv ") == "laptop-q8_0-kv"
        with pytest.raises(ValueError):
            safe_label("///")


class TestSha256:
    def test_accepts_64_hex_characters_in_any_case(self):
        assert is_sha256("A" * 64)
        assert is_sha256("0123456789abcdef" * 4)

    def test_rejects_other_values(self):
        assert not is_sha256("abc")
        assert not is_sha256("g" * 64)
        assert not is_sha256(None)


class TestJson:
    def test_json_is_written_whole_and_no_part_file_is_left(self, tmp_path):
        path = tmp_path / "nested" / "laptop-2026-10-05.json"
        write_json(path, {"kind": "horus-bench-kit-eval", "label": "café"})
        assert read_json(path) == {"kind": "horus-bench-kit-eval", "label": "café"}
        assert list(path.parent.iterdir()) == [path]

    def test_json_keeps_key_order_two_space_indent_utf8_and_a_final_newline(self, tmp_path):
        path = tmp_path / "r.json"
        write_json(path, {"b": 1, "a": "é"})
        text = path.read_text(encoding="utf-8")
        assert text == json.dumps({"b": 1, "a": "é"}, indent=2, ensure_ascii=False) + "\n"

    def test_now_utc_is_an_iso_timestamp_in_utc(self):
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", now_utc())
        assert TIMESTAMP_FORMAT == "%Y-%m-%dT%H:%M:%SZ"


class TestCheckReport:
    def test_the_right_kind_at_the_same_or_an_older_version_passes(self):
        check_report({"kind": "x-eval", "schema_version": 2}, "x-eval", 2)
        check_report({"kind": "x-eval", "schema_version": 1}, "x-eval", 2)
        check_report({"kind": "x-eval"}, "x-eval", 2)

    def test_another_kind_is_refused(self):
        with pytest.raises(ValueError, match=r"^not a x-eval report \(kind='y-eval'\)$"):
            check_report({"kind": "y-eval"}, "x-eval", 1)
        with pytest.raises(ValueError, match=r"kind=None"):
            check_report([], "x-eval", 1)

    def test_a_newer_schema_version_is_refused(self):
        with pytest.raises(ValueError, match="schema_version 3 is newer than the 2"):
            check_report({"kind": "x-eval", "schema_version": 3}, "x-eval", 2)
