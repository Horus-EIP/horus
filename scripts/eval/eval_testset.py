from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml
from eval_scoring import answer_correct, compile_pattern, expected_sources

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TESTSET_PATH = REPO_ROOT / "tests" / "eval" / "testset.yaml"

CATEGORIES = ("lookup", "numeric", "multi_hop", "not_in_corpus", "direct")
IN_CORPUS_CATEGORIES = frozenset({"lookup", "numeric", "multi_hop"})
DIFFICULTIES = ("easy", "medium", "hard")
REQUIRED_FIELDS = (
    "id",
    "question",
    "expected_answer",
    "answer_patterns",
    "expected_source",
    "category",
    "difficulty",
)
CANNED_NON_ANSWERS = (
    "The retrieved content does not contain this information.",
    "I don't have that information yet.",
)


def load_testset(path: Path | str = DEFAULT_TESTSET_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def corpus_root(testset: dict[str, Any], testset_path: Path | str) -> Path:
    return (Path(testset_path).resolve().parent / testset["corpus_dir"]).resolve()


def lf_normalized(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def file_sha256(path: Path | str) -> str:
    return hashlib.sha256(lf_normalized(Path(path).read_bytes())).hexdigest()


def read_documents(testset: dict[str, Any], root: Path) -> dict[str, str]:
    return {
        name: lf_normalized((root / name).read_bytes()).decode("utf-8")
        for name in testset.get("corpus", {})
        if (root / name).is_file()
    }


def schema_errors(testset: dict[str, Any]) -> list[str]:
    errors = []
    for key in ("version", "corpus_dir", "corpus", "items"):
        if key not in testset:
            errors.append(f"testset: missing top-level key {key!r}")
    for index, item in enumerate(testset.get("items") or []):
        label = item.get("id") or f"item #{index}"
        for field in REQUIRED_FIELDS:
            if field not in item:
                errors.append(f"{label}: missing field {field!r}")
        for field in ("id", "question", "expected_answer"):
            if field in item and not (isinstance(item[field], str) and item[field].strip()):
                errors.append(f"{label}: {field} must be a non-empty string")
        category = item.get("category")
        if category not in CATEGORIES:
            errors.append(f"{label}: unknown category {category!r}")
        if item.get("difficulty") not in DIFFICULTIES:
            errors.append(f"{label}: unknown difficulty {item.get('difficulty')!r}")
        patterns = item.get("answer_patterns")
        if not (isinstance(patterns, list) and patterns):
            errors.append(f"{label}: answer_patterns must be a non-empty list")
        else:
            errors.extend(_pattern_errors(label, "answer_patterns", patterns))
        if "evidence_patterns" in item:
            errors.extend(_pattern_errors(label, "evidence_patterns", item["evidence_patterns"]))
        errors.extend(_category_errors(label, category, item))
    return errors


def _pattern_errors(label: str, field: str, patterns: Any) -> list[str]:
    if not isinstance(patterns, list) or not patterns:
        return [f"{label}: {field} must be a non-empty list"]
    errors = []
    for pattern in patterns:
        try:
            compile_pattern(pattern)
        except (re.error, TypeError) as exc:
            errors.append(f"{label}: invalid regex {pattern!r} in {field} ({exc})")
    return errors


def _category_errors(label: str, category: str | None, item: dict[str, Any]) -> list[str]:
    errors = []
    sources = item.get("expected_source")
    if category in IN_CORPUS_CATEGORIES:
        if not expected_sources(item) or not all(isinstance(s, str) for s in expected_sources(item)):
            errors.append(f"{label}: an in-corpus item needs expected_source")
        if "absent_terms" in item:
            errors.append(f"{label}: absent_terms is only for not_in_corpus items")
    elif category in ("not_in_corpus", "direct") and sources is not None:
        errors.append(f"{label}: a {category} item must have expected_source: null")
    if category == "not_in_corpus":
        terms = item.get("absent_terms")
        if not (isinstance(terms, list) and terms and all(isinstance(t, str) for t in terms)):
            errors.append(f"{label}: a not_in_corpus item needs a non-empty absent_terms list")
    if "evidence_patterns" in item and category not in ("numeric", "multi_hop"):
        errors.append(f"{label}: evidence_patterns is only for derived numeric or multi_hop answers")
    return errors


def duplicate_errors(testset: dict[str, Any]) -> list[str]:
    errors = []
    for field in ("id", "question"):
        seen: set[str] = set()
        for item in testset.get("items") or []:
            value = str(item.get(field, "")).strip().lower()
            if value in seen:
                errors.append(f"duplicate {field}: {item.get(field)!r}")
            seen.add(value)
    return errors


def corpus_errors(testset: dict[str, Any], root: Path) -> list[str]:
    errors = []
    declared = testset.get("corpus") or {}
    for name, digest in declared.items():
        path = root / name
        if not path.is_file():
            errors.append(f"corpus: {name} does not exist under {root}")
        elif file_sha256(path) != digest:
            errors.append(
                f"corpus: {name} changed (sha256 {file_sha256(path)}); re-verify the answers "
                "that cite it, then update the hash and bump the testset version"
            )
    for item in testset.get("items") or []:
        for source in expected_sources(item):
            if source not in declared:
                errors.append(f"{item.get('id')}: expected_source {source!r} is not in corpus")
    return errors


def grounding_errors(testset: dict[str, Any], documents: dict[str, str]) -> list[str]:
    errors = []
    for item in testset.get("items") or []:
        if item.get("category") not in IN_CORPUS_CATEGORIES:
            continue
        sources = expected_sources(item)
        if not all(source in documents for source in sources):
            continue
        text = "\n".join(documents[source] for source in sources)
        field = "evidence_patterns" if "evidence_patterns" in item else "answer_patterns"
        for pattern in item.get(field) or []:
            if not compile_pattern(pattern).search(text):
                errors.append(
                    f"{item['id']}: {field} {pattern!r} does not match {', '.join(sources)}"
                )
    return errors


def absent_term_errors(testset: dict[str, Any], documents: dict[str, str]) -> list[str]:
    errors = []
    for item in testset.get("items") or []:
        for term in item.get("absent_terms") or []:
            probe = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
            for name, text in documents.items():
                if probe.search(text):
                    errors.append(f"{item['id']}: absent term {term!r} appears in {name}")
    return errors


def self_consistency_errors(testset: dict[str, Any]) -> list[str]:
    errors = []
    for item in testset.get("items") or []:
        if not answer_correct(item, item.get("expected_answer")):
            errors.append(f"{item.get('id')}: expected_answer fails its own answer_patterns")
        if item.get("category") == "not_in_corpus":
            continue
        for canned in CANNED_NON_ANSWERS:
            if answer_correct(item, canned):
                errors.append(f"{item.get('id')}: answer_patterns accept the non-answer {canned!r}")
    return errors


def validate_testset(testset: dict[str, Any], root: Path) -> list[str]:
    schema = schema_errors(testset)
    if schema:
        return schema
    documents = read_documents(testset, root)
    return (
        duplicate_errors(testset)
        + corpus_errors(testset, root)
        + grounding_errors(testset, documents)
        + absent_term_errors(testset, documents)
        + self_consistency_errors(testset)
    )


def corpus_problems(expected_names: list[str], stored_titles: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for title in stored_titles:
        counts[title] = counts.get(title, 0) + 1
    problems = [f"{name} is not in the knowledge store" for name in expected_names if name not in counts]
    problems += [
        f"{name} is stored {counts[name]} times; delete the duplicates so retrieval is not skewed"
        for name in expected_names
        if counts.get(name, 0) > 1
    ]
    return problems


def select_items(
    items: list[dict[str, Any]],
    ids: list[str] | None = None,
    categories: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selected = [
        item
        for item in items
        if (not ids or item["id"] in ids) and (not categories or item["category"] in categories)
    ]
    return selected[:limit] if limit else selected
