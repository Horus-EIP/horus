# SPDX-License-Identifier: Apache-2.0
import ast
import json
import re
import sys
from importlib import metadata
from pathlib import Path

import pytest

from horus_bench_kit import __version__

KIT_ROOT = Path(__file__).resolve().parents[1]
SPDX_LINE = "# SPDX-License-Identifier: Apache-2.0"
OPTIONAL_PACKAGES = {"yaml"}
TEST_PACKAGES = {"pytest", "conftest"}


def python_files(*folders):
    return sorted(path for folder in folders for path in (KIT_ROOT / folder).rglob("*.py"))


def imported_packages(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.module.split(".")[0]


@pytest.mark.parametrize("path", python_files("src", "tests", "scripts", "examples"), ids=lambda path: path.name)
def test_every_python_file_starts_with_the_spdx_line(path):
    assert path.read_text(encoding="utf-8").splitlines()[0] == SPDX_LINE


@pytest.mark.parametrize("path", sorted(path for folder in ("src", "scripts", "examples") for path in (KIT_ROOT / folder).rglob("*.sh")), ids=lambda path: path.name)
def test_every_shell_script_has_the_spdx_line_after_its_shebang(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("#!") and lines[1] == SPDX_LINE


@pytest.mark.parametrize("path", python_files("src", "scripts", "examples"), ids=lambda path: path.name)
def test_the_package_imports_only_the_standard_library_itself_and_optional_pyyaml(path):
    allowed = set(sys.stdlib_module_names) | {"horus_bench_kit"} | OPTIONAL_PACKAGES
    assert set(imported_packages(path)) <= allowed


@pytest.mark.parametrize("path", python_files("tests"), ids=lambda path: path.name)
def test_the_tests_need_only_pytest_besides_the_package(path):
    allowed = set(sys.stdlib_module_names) | {"horus_bench_kit"} | OPTIONAL_PACKAGES | TEST_PACKAGES
    assert set(imported_packages(path)) <= allowed


def test_the_version_is_the_same_in_the_package_and_pyproject():
    pyproject = (KIT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE).group(1) == __version__


def test_the_package_has_no_required_dependency():
    pyproject = (KIT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r"^dependencies = \[\]$", pyproject, re.MULTILINE)
    assert 'license = "Apache-2.0"' in pyproject


def test_licence_and_notice_name_the_copyright_holders():
    licence = (KIT_ROOT / "LICENSE").read_text(encoding="utf-8").splitlines()
    assert licence[0] == "Copyright 2025-2026 Loup Marquez-Luttringer, Noah Gibelli, Matheus Lopez"
    assert licence[3].strip() == "Apache License"
    assert "END OF TERMS AND CONDITIONS" in [line.strip() for line in licence]
    notice = (KIT_ROOT / "NOTICE").read_text(encoding="utf-8").splitlines()
    assert len(notice) == 1 and notice[0].endswith("licensed under the Apache License 2.0.")


def test_every_tool_is_a_console_script():
    pyproject = (KIT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for name, module in (
        ("hbk-eval", "eval"),
        ("hbk-llama-bench", "llama_bench"),
        ("hbk-compare", "compare"),
        ("hbk-model-candidates", "candidates"),
        ("hbk-contract-probe", "contract_probe"),
    ):
        assert f'{name} = "horus_bench_kit.cli.{module}:main"' in pyproject
        assert (KIT_ROOT / "src" / "horus_bench_kit" / "cli" / f"{module}.py").is_file()
    assert 'horus_bench_kit = ["data/*.sh"]' in pyproject


def editable(distribution):
    direct_url = json.loads(distribution.read_text("direct_url.json") or "{}")
    return bool((direct_url.get("dir_info") or {}).get("editable"))


def test_an_installed_copy_ships_the_fetch_script_and_the_tools():
    try:
        distribution = metadata.distribution("horus-bench-kit")
    except metadata.PackageNotFoundError:
        pytest.skip("horus-bench-kit is not installed")
    if Path(distribution.locate_file("")).resolve() == (KIT_ROOT / "src").resolve() or editable(distribution):
        pytest.skip("the metadata found is this source tree's, not an installed copy's")
    if not distribution.files:
        pytest.skip("horus-bench-kit is installed without a file list")
    assert "horus_bench_kit/data/fetch-model.sh" in {file.as_posix() for file in distribution.files}
    scripts = {entry.name for entry in distribution.entry_points if entry.group == "console_scripts"}
    assert {"hbk-eval", "hbk-llama-bench", "hbk-compare", "hbk-model-candidates", "hbk-contract-probe"} <= scripts
