from __future__ import annotations

from pathlib import Path

from core import version

REPO_VERSION_FILE = Path(__file__).resolve().parents[3] / "VERSION"


class TestResolveVersion:
    def test_the_declared_environment_value_wins(self, tmp_path):
        (tmp_path / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        start = tmp_path / "service" / "core" / "version.py"

        assert version.resolve_version({"HORUS_VERSION": " 2.3.4 "}, start) == "2.3.4"

    def test_falls_back_to_the_nearest_version_file_above_the_module(self, tmp_path):
        (tmp_path / "VERSION").write_text("1.2.3\r\n", encoding="utf-8")
        start = tmp_path / "service" / "core" / "version.py"

        assert version.resolve_version({"HORUS_VERSION": ""}, start) == "1.2.3"

    def test_reports_unknown_without_environment_or_file(self, tmp_path):
        start = tmp_path / "service" / "core" / "version.py"

        assert version.resolve_version({}, start) == version.UNKNOWN_VERSION

    def test_an_empty_version_file_reads_as_unknown(self, tmp_path):
        (tmp_path / "VERSION").write_text("\n", encoding="utf-8")
        start = tmp_path / "service" / "core" / "version.py"

        assert version.resolve_version({}, start) == version.UNKNOWN_VERSION

    def test_the_service_reports_the_repository_version_file(self, monkeypatch):
        monkeypatch.delenv("HORUS_VERSION", raising=False)

        expected = REPO_VERSION_FILE.read_text(encoding="utf-8").strip()
        assert version.resolve_version() == expected
        assert version.HORUS_VERSION == expected
