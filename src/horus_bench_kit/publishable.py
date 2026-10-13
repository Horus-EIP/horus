# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import ast
import hashlib
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath

SPDX_LINE = "# SPDX-License-Identifier: Apache-2.0"
REQUIRED_FILES = ("LICENSE", "NOTICE", "README.md")
HEADER_SUFFIXES = frozenset({".py", ".sh"})
TEXT_SUFFIXES = frozenset({".py", ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".cfg", ".sh"})
TEXT_NAMES = frozenset({"LICENSE", "NOTICE", ".gitignore"})
SKIPPED_FOLDERS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "build",
        "dist",
        "results",
        "out",
    }
)
SKIPPED_SUFFIXES = frozenset({".pyc", ".pyo", ".part", ".zip"})
ALLOWED_IMPORTS = frozenset({"horus_bench_kit", "yaml", "pytest"})
TEST_IMPORTS = frozenset({"conftest"})
ALLOWED_DEPENDENCIES = {"pyyaml": "MIT", "pytest": "MIT", "setuptools": "MIT"}
DEPENDENCY_KEYS = {("build-system", "requires"), ("project", "dependencies")}
OPTIONAL_TABLE = "project.optional-dependencies"
PLACEHOLDER_USERS = frozenset({"someone", "example", "user"})

_TOKEN = re.compile(r"[a-z0-9_./@-]+")
_WORD = re.compile(r"[a-z0-9]+")
_TABLE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_ARRAY = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*\[")
_QUOTED = re.compile(r"\"([^\"]*)\"|'([^']*)'")
_REQUIREMENT = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_VERSION = re.compile(r"^version\s*=\s*\"([^\"]+)\"\s*$", re.MULTILINE)
_HOME_FOLDER = re.compile(r"/(?:users|home)/+([a-z0-9._-]+)/")


@dataclass(frozen=True)
class Forbidden:
    label: str
    sha256: str
    size: int
    words: bool = False
    allowed_in: frozenset[str] = frozenset()


FORBIDDEN = (
    Forbidden("a product source path", "5c06cdf845c9f116b645eae3b6de0d31f723a0c9598c614c86a60b32e8e59ad8", 12),
    Forbidden("a private registry", "ee91dfadf795111bd5180b8075b8af974036ed66d6772ae3e11b38ce1dfb6d8a", 24),
    Forbidden("closed licence wording", "9049697da52b7e0efb06ef942d752352a8336c4cc657b095b882a63495d75d51", 11),
    Forbidden(
        "a maintainer email domain",
        "a459ebb6e7f7f9e932cb840f11bb99418a9947842ef57a97e6fae8932139bc25",
        11,
        allowed_in=frozenset({"LICENSE", "NOTICE", "CODE_OF_CONDUCT.md"}),
    ),
    Forbidden("a product container path", "8f446954d61fc9b34bd1e9235dcb9a1fd431c26ac4c08a4c9e0a9b05121e5b87", 10),
    Forbidden("a product setting", "230922a8bc86275ec43c08794f5a7e248def15d202f5cada9b9e667d27b6ae13", 20),
    Forbidden("a product network name", "f246f2a4eb9f70fc7831ced2639ef7f012a6bca88cef6d40fc4fad1489ec6b92", 9),
    Forbidden(
        "a product prompt", "779c331b2f5f237d228b76ebdf152973cbeb35d9c2827742a2e62c7f803e2aa3", 9, words=True
    ),
)


def forbidden_string(label: str, text: str, allowed_in: Iterable[str] = ()) -> Forbidden:
    normalized = normalized_text(text).strip()
    if " " not in normalized:
        return Forbidden(label, digest(normalized), len(normalized), False, frozenset(allowed_in))
    words = _WORD.findall(normalized)
    return Forbidden(label, digest(" ".join(words)), len(words), True, frozenset(allowed_in))


def is_packaged(relative: PurePosixPath) -> bool:
    folders = relative.parts[:-1]
    if any(folder in SKIPPED_FOLDERS or folder.endswith(".egg-info") for folder in folders):
        return False
    return relative.suffix not in SKIPPED_SUFFIXES


def packaged_files(root: Path) -> list[PurePosixPath]:
    relative = (PurePosixPath(path.relative_to(root).as_posix()) for path in root.rglob("*") if path.is_file())
    return sorted(path for path in relative if is_packaged(path))


def is_text(relative: PurePosixPath) -> bool:
    return relative.suffix in TEXT_SUFFIXES or relative.name in TEXT_NAMES


def read_text(root: Path, relative: PurePosixPath) -> str:
    return (root / relative).read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")


def required_problems(root: Path) -> list[str]:
    problems = []
    for name in REQUIRED_FILES:
        path = root / name
        if not path.is_file():
            problems.append(f"{name} is missing")
        elif not path.read_text(encoding="utf-8", errors="replace").strip():
            problems.append(f"{name} is empty")
    return problems


def has_header(text: str) -> bool:
    lines = text.splitlines()
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    return bool(lines) and lines[0] == SPDX_LINE


def header_problems(root: Path, files: Sequence[PurePosixPath]) -> list[str]:
    return [
        f"{relative}: the first line is not {SPDX_LINE!r}"
        for relative in files
        if relative.suffix in HEADER_SUFFIXES and not has_header(read_text(root, relative))
    ]


def imported_modules(source: str) -> list[str]:
    modules = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module.split(".")[0])
    return modules


def import_problems(root: Path, files: Sequence[PurePosixPath]) -> list[str]:
    problems = []
    for relative in files:
        if relative.suffix != ".py":
            continue
        allowed = set(sys.stdlib_module_names) | ALLOWED_IMPORTS
        if relative.parts[0] == "tests":
            allowed |= TEST_IMPORTS
        try:
            modules = imported_modules(read_text(root, relative))
        except SyntaxError as exc:
            problems.append(f"{relative}: does not parse: {exc}")
            continue
        for module in sorted(set(modules) - allowed):
            problems.append(f"{relative}: imports {module}, which is neither the standard library nor allowed")
    return problems


def normalized_text(text: str) -> str:
    return text.lower().replace("\\", "/")


@lru_cache(maxsize=None)
def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def windows(text: str, size: int, words: bool) -> set[str]:
    if words:
        found = _WORD.findall(text)
        return {" ".join(found[index : index + size]) for index in range(len(found) - size + 1)}
    return {
        token[index : index + size]
        for token in set(_TOKEN.findall(text))
        if len(token) >= size
        for index in range(len(token) - size + 1)
    }


def found_in(text: str, forbidden: Forbidden) -> bool:
    return any(digest(window) == forbidden.sha256 for window in windows(text, forbidden.size, forbidden.words))


def forbidden_problems(
    root: Path, files: Sequence[PurePosixPath], forbidden: Sequence[Forbidden] = FORBIDDEN
) -> list[str]:
    problems = []
    for relative in files:
        if not is_text(relative):
            continue
        text = normalized_text(read_text(root, relative))
        for rule in forbidden:
            if relative.as_posix() not in rule.allowed_in and found_in(text, rule):
                problems.append(f"{relative}: holds {rule.label}")
    return problems


def personal_folders(text: str) -> set[str]:
    return {name for name in _HOME_FOLDER.findall(normalized_text(text)) if len(name) > 2 and name not in PLACEHOLDER_USERS}


def home_folder_problems(root: Path, files: Sequence[PurePosixPath]) -> list[str]:
    return [
        f"{relative}: holds a path inside a personal home folder"
        for relative in files
        if is_text(relative) and personal_folders(read_text(root, relative))
    ]


def array_strings(text: str, start: int) -> list[str]:
    depth, quote, index = 0, None, start
    while index < len(text):
        char = text[index]
        if quote:
            quote = None if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                break
        index += 1
    return [double or single for double, single in _QUOTED.findall(text[start : index + 1])]


def declared_dependencies(pyproject: str) -> list[str]:
    found = []
    table = None
    offset = 0
    for line in pyproject.splitlines(keepends=True):
        header = _TABLE.match(line)
        if header:
            table = header.group(1).strip()
        else:
            array = _ARRAY.match(line)
            if array and (table == OPTIONAL_TABLE or (table, array.group(1)) in DEPENDENCY_KEYS):
                found.extend(array_strings(pyproject, offset + line.index("[")))
        offset += len(line)
    return found


def requirement_name(requirement: str) -> str:
    match = _REQUIREMENT.match(requirement)
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else requirement.strip().lower()


def dependency_problems(pyproject: str, allowed: dict[str, str] | None = None) -> list[str]:
    allowed = ALLOWED_DEPENDENCIES if allowed is None else allowed
    return [
        f"pyproject.toml: {requirement!r} is not in the allowlist of permissive dependencies "
        f"({', '.join(sorted(allowed))})"
        for requirement in declared_dependencies(pyproject)
        if requirement_name(requirement) not in allowed
    ]


def pyproject_version(pyproject: str) -> str:
    match = _VERSION.search(pyproject)
    if not match:
        raise ValueError("pyproject.toml has no version")
    return match.group(1)


def problems(root: Path | str, *, forbidden: Sequence[Forbidden] = FORBIDDEN) -> list[str]:
    root = Path(root)
    found = required_problems(root)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        found += dependency_problems(pyproject.read_text(encoding="utf-8"))
    else:
        found.append("pyproject.toml is missing")
    files = packaged_files(root)
    return (
        found
        + header_problems(root, files)
        + import_problems(root, files)
        + forbidden_problems(root, files, forbidden)
        + home_folder_problems(root, files)
    )
