# SPDX-License-Identifier: Apache-2.0
import importlib.util
import shutil
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from horus_bench_kit import __version__

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make-zip.py"


@pytest.fixture(scope="module")
def make_zip():
    spec = importlib.util.spec_from_file_location("make_zip", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSelection:
    @pytest.mark.parametrize(
        "path",
        [
            "src/horus_bench_kit/__pycache__/files.cpython-310.pyc",
            "src/horus_bench_kit.egg-info/PKG-INFO",
            "build/lib/horus_bench_kit/files.py",
            "dist/horus-bench-kit-0.1.0.zip",
            "results/run-2026-10-08.json",
            "results/run-2026-10-08.json.part",
            ".venv/pyvenv.cfg",
        ],
    )
    def test_build_output_caches_and_results_are_left_out(self, make_zip, path):
        assert not make_zip.is_packaged(PurePosixPath(path))

    @pytest.mark.parametrize("path", ["LICENSE", "src/horus_bench_kit/files.py", "examples/corpus/plot-fees.txt"])
    def test_sources_docs_and_examples_are_kept(self, make_zip, path):
        assert make_zip.is_packaged(PurePosixPath(path))

    def test_the_version_comes_from_the_package(self, make_zip):
        assert make_zip.kit_version() == __version__


class TestArchive:
    def test_the_archive_holds_the_kit_under_one_folder_with_lf_text(self, make_zip, tmp_path, capsys):
        assert make_zip.main(["--out-dir", str(tmp_path)]) == 0
        archive = tmp_path / f"horus-bench-kit-{__version__}.zip"
        assert capsys.readouterr().out.startswith(f"[done] wrote {archive} (")
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            licence = bundle.read(f"horus-bench-kit-{__version__}/LICENSE")
        prefix = f"horus-bench-kit-{__version__}/"
        assert all(name.startswith(prefix) for name in names)
        for required in ("LICENSE", "NOTICE", "README.md", "pyproject.toml", "src/horus_bench_kit/__init__.py"):
            assert prefix + required in names
        assert not any("__pycache__" in name or ".egg-info" in name for name in names)
        assert b"\r\n" not in licence

    def test_two_builds_give_the_same_bytes(self, make_zip, tmp_path):
        first, _ = make_zip.build_zip(tmp_path / "one")
        second, _ = make_zip.build_zip(tmp_path / "two")
        assert first.read_bytes() == second.read_bytes()


class TestChecks:
    @pytest.fixture
    def kit_copy(self, tmp_path):
        target = tmp_path / "kit"
        ignored = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache", "dist", "build", "*.egg-info")
        shutil.copytree(SCRIPT.parents[1], target, ignore=ignored)
        return target

    def test_a_kit_with_problems_is_not_zipped(self, make_zip, kit_copy, tmp_path, capsys):
        (kit_copy / "src" / "horus_bench_kit" / "extra.py").write_text("import requests\n", encoding="utf-8")
        (kit_copy / "NOTICE").unlink()
        assert make_zip.main(["--out", str(tmp_path / "zips")], root=kit_copy) == 1
        lines = capsys.readouterr().out.splitlines()
        assert lines == [
            "[error] NOTICE is missing",
            "[error] src/horus_bench_kit/extra.py: the first line is not '# SPDX-License-Identifier: Apache-2.0'",
            "[error] src/horus_bench_kit/extra.py: imports requests, which is neither the standard library nor allowed",
            "[error] the zip was not built: 3 problem(s)",
        ]
        assert not (tmp_path / "zips").exists()

    def test_results_and_output_folders_stay_out_of_the_zip(self, make_zip, kit_copy, tmp_path):
        for relative in ("results/run-2026-10-08.json", "examples/out/report.json", "out/x.json"):
            path = kit_copy / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        assert make_zip.main(["--out", str(kit_copy / "dist")], root=kit_copy) == 0
        archive = kit_copy / "dist" / f"horus-bench-kit-{__version__}.zip"
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            script = bundle.getinfo(f"horus-bench-kit-{__version__}/src/horus_bench_kit/data/fetch-model.sh")
        assert not any("/results/" in name or "/out/" in name or name.endswith(".zip") for name in names)
        assert script.external_attr >> 16 == 0o755
        assert f"horus-bench-kit-{__version__}/examples/probe/command_probe.py" in names
