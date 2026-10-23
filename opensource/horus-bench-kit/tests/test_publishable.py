# SPDX-License-Identifier: Apache-2.0
import re
from pathlib import Path, PurePosixPath

import pytest

from horus_bench_kit import publishable
from horus_bench_kit.publishable import (
    FORBIDDEN,
    declared_dependencies,
    dependency_problems,
    forbidden_problems,
    forbidden_string,
    is_packaged,
    packaged_files,
    problems,
    pyproject_version,
    requirement_name,
)

KIT_ROOT = Path(__file__).resolve().parents[1]
SPDX = "# SPDX-License-Identifier: Apache-2.0\n"
PYPROJECT = """[build-system]
requires = ["setuptools>=77"]

[project]
name = "example-kit"
version = "1.2.3"
dependencies = []

[project.optional-dependencies]
yaml = ["PyYAML>=6"]
test = [
    "pytest>=8",
    'PyYAML>=6',
]
"""


@pytest.fixture
def kit(tmp_path):
    root = tmp_path / "kit"
    (root / "src" / "example").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "LICENSE").write_text("Apache License\n", encoding="utf-8")
    (root / "NOTICE").write_text(
        "example, licensed under the Apache License 2.0.\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# Example\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (root / "src" / "example" / "tool.py").write_text(
        SPDX + "import json\nimport yaml\n", encoding="utf-8"
    )
    (root / "tests" / "test_tool.py").write_text(
        SPDX + "import pytest\nfrom conftest import helper\n", encoding="utf-8"
    )
    return root


def test_the_kit_itself_can_be_published():
    assert problems(KIT_ROOT) == []


def test_a_clean_folder_has_no_problem(kit):
    assert problems(kit) == []


def test_missing_and_empty_licence_files_are_named(kit):
    (kit / "LICENSE").unlink()
    (kit / "NOTICE").write_text("  \n", encoding="utf-8")
    assert problems(kit)[:2] == ["LICENSE is missing", "NOTICE is empty"]
    (kit / "pyproject.toml").unlink()
    assert "pyproject.toml is missing" in problems(kit)


def test_every_python_and_shell_file_starts_with_the_spdx_line(kit):
    (kit / "src" / "example" / "bare.py").write_text("import json\n", encoding="utf-8")
    (kit / "src" / "example" / "run.sh").write_text(
        "#!/bin/sh\n" + SPDX + "echo ok\n", encoding="utf-8"
    )
    (kit / "src" / "example" / "other.sh").write_text(
        "#!/bin/sh\necho no header\n", encoding="utf-8"
    )
    (kit / "src" / "example" / "crlf.py").write_bytes(
        SPDX.replace("\n", "\r\n").encode() + b"import os\r\n"
    )
    assert problems(kit) == [
        "src/example/bare.py: the first line is not '# SPDX-License-Identifier: Apache-2.0'",
        "src/example/other.sh: the first line is not '# SPDX-License-Identifier: Apache-2.0'",
    ]


def test_imports_are_the_standard_library_the_kit_yaml_or_pytest(kit):
    (kit / "src" / "example" / "net.py").write_text(
        SPDX + "import requests\nfrom conftest import x\nfrom . import tool\n", encoding="utf-8"
    )
    (kit / "src" / "example" / "broken.py").write_text(SPDX + "def (:\n", encoding="utf-8")
    found = problems(kit)
    assert (
        "src/example/net.py: imports conftest, which is neither the standard library nor allowed"
        in found
    )
    assert (
        "src/example/net.py: imports requests, which is neither the standard library nor allowed"
        in found
    )
    assert any(problem.startswith("src/example/broken.py: does not parse") for problem in found)
    assert len(found) == 3


def test_forbidden_strings_are_found_without_being_written_in_the_kit(kit):
    rules = (
        forbidden_string("a test network", "widget-net"),
        forbidden_string("a test phrase", "Which Widgets Are In Stock?"),
        forbidden_string("a test domain", "@widgets.test", allowed_in=("NOTICE",)),
    )
    assert [rule.words for rule in rules] == [False, True, False]
    assert rules[1].size == 5
    (kit / "README.md").write_text(
        "# Example\n\nJoin LAB_WIDGET-NET and ask: which widgets\nare in stock?\n", encoding="utf-8"
    )
    (kit / "NOTICE").write_text("Contact admin@widgets.test\n", encoding="utf-8")
    (kit / "src" / "example" / "path.py").write_text(
        SPDX + "PATH = 'C:\\\\data\\\\widget-net'\n", encoding="utf-8"
    )
    files = packaged_files(kit)
    assert forbidden_problems(kit, files, rules) == [
        "README.md: holds a test network",
        "README.md: holds a test phrase",
        "src/example/path.py: holds a test network",
    ]
    (kit / "README.md").write_text("Mail admin@WIDGETS.test\n", encoding="utf-8")
    assert forbidden_problems(kit, packaged_files(kit), rules) == [
        "README.md: holds a test domain",
        "src/example/path.py: holds a test network",
    ]


def test_a_path_inside_a_personal_home_folder_is_refused(kit):
    home, users = "/home/", "C:\\\\Users\\\\"
    (kit / "README.md").write_text(
        f"Models live in {home}odile/models and D:\\work\\x.\n", encoding="utf-8"
    )
    (kit / "src" / "example" / "paths.py").write_text(
        SPDX
        + f"WINDOWS = '{users}Jdoe\\\\gguf'\nFAKE = ['/home/u/models', 'C:/Users/someone/x']\n",
        encoding="utf-8",
    )
    assert problems(kit) == [
        "README.md: holds a path inside a personal home folder",
        "src/example/paths.py: holds a path inside a personal home folder",
    ]
    (kit / "src" / "example" / "paths.py").write_text(
        SPDX + "FAKE = ['/home/u/models']\n", encoding="utf-8"
    )
    (kit / "README.md").write_text("# Example\n", encoding="utf-8")
    assert problems(kit) == []


def test_the_built_in_rules_hold_only_digests():
    assert len(FORBIDDEN) == 8
    assert len({rule.sha256 for rule in FORBIDDEN}) == 8
    assert all(re.fullmatch(r"[0-9a-f]{64}", rule.sha256) for rule in FORBIDDEN)
    assert sum(rule.words for rule in FORBIDDEN) == 1
    assert [rule.allowed_in for rule in FORBIDDEN if rule.allowed_in] == [
        frozenset({"LICENSE", "NOTICE", "CODE_OF_CONDUCT.md"})
    ]


def test_the_checks_module_stands_alone():
    source = Path(publishable.__file__).read_text(encoding="utf-8")
    assert "import horus_bench_kit" not in source and "from horus_bench_kit" not in source


class TestDependencies:
    def test_the_declared_dependencies_are_read_from_every_list(self):
        assert declared_dependencies(PYPROJECT) == [
            "setuptools>=77",
            "PyYAML>=6",
            "pytest>=8",
            "PyYAML>=6",
        ]
        assert dependency_problems(PYPROJECT) == []

    def test_a_dependency_outside_the_allowlist_is_refused(self):
        text = PYPROJECT.replace(
            "dependencies = []", 'dependencies = ["requests>=2", "uvicorn[standard]>=0.30"]'
        )
        assert dependency_problems(text) == [
            "pyproject.toml: 'requests>=2' is not in the allowlist of permissive dependencies (pytest, pyyaml, setuptools)",
            "pyproject.toml: 'uvicorn[standard]>=0.30' is not in the allowlist of permissive dependencies (pytest, pyyaml, setuptools)",
        ]
        assert (
            dependency_problems(text, {"requests": "Apache-2.0", "uvicorn": "BSD-3-Clause"}) != []
        )

    def test_requirement_names_are_normalised(self):
        assert requirement_name("PyYAML>=6") == "pyyaml"
        assert requirement_name("Zope.Interface ; python_version<'4'") == "zope-interface"

    def test_the_version(self):
        assert pyproject_version(PYPROJECT) == "1.2.3"
        with pytest.raises(ValueError):
            pyproject_version("[project]\n")


@pytest.mark.parametrize(
    ("path", "kept"),
    [
        ("src/pkg/__pycache__/a.cpython-310.pyc", False),
        ("src/pkg.egg-info/PKG-INFO", False),
        ("build/lib/pkg/a.py", False),
        ("dist/kit-1.0.0.zip", False),
        ("results/run-2026-10-08.json", False),
        ("examples/out/report.json", False),
        ("kit-1.0.0.zip", False),
        (".venv/pyvenv.cfg", False),
        ("examples/probe/items.json", True),
        ("src/pkg/data/fetch-model.sh", True),
    ],
)
def test_what_a_zip_leaves_out(path, kept):
    assert is_packaged(PurePosixPath(path)) is kept
