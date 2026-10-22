import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from eval_contract import contract_summary
from eval_report import build_report, question_record, resummarize
from eval_testset import DEFAULT_TESTSET_PATH, file_sha256

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = REPO_ROOT / "benchmarks"
GOLDEN = Path(__file__).resolve().parent / "golden"
SCRIPTS = REPO_ROOT / "scripts" / "benchmarks"
HELP_SCRIPTS = {
    "compare-benchmarks": SCRIPTS / "compare-benchmarks.py",
    "run-eval": REPO_ROOT / "scripts" / "eval" / "run-eval.py",
    "run-llama-bench": SCRIPTS / "run-llama-bench.py",
    "run-model-candidates": SCRIPTS / "run-model-candidates.py",
}
PYTHON = f"py{sys.version_info.major}{sys.version_info.minor}"
COMPENSATED_FLOAT_SUM = sys.version_info >= (3, 12)
SUM_ROUNDING = 0.0011
ITEM_FIELDS = (
    "id",
    "category",
    "difficulty",
    "question",
    "expected_answer",
    "expected_source",
    "expected_route",
)
CANDIDATES_SUMMARY = "model-candidates-2026-10-06"
COMPARISONS = {
    "compare-cpu-laptop.md": ["cpu-laptop-2026-10-06.json"],
    "compare-cpu-transformers-vs-cpu-laptop.md": [
        "--before",
        "cpu-transformers-2026-09-01.json",
        "--after",
        "cpu-laptop-2026-10-06.json",
        "eval-laptop-cpu-standard-2026-10-06.json",
    ],
    "compare-eval-standard.md": ["eval-laptop-cpu-standard-2026-10-06.json"],
    "compare-eval-lean-vs-standard.md": [
        "eval-laptop-cpu-lean-2026-10-06.json",
        "eval-laptop-cpu-standard-2026-10-06.json",
    ],
}


def lf_text(path):
    return path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")


def dumped(payload):
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def committed(kind):
    reports = []
    for path in sorted(BENCHMARKS.rglob("*.json")):
        document = json.loads(lf_text(path))
        if isinstance(document, dict) and document.get("kind") == kind:
            reports.append(path)
    return reports


def shown(path):
    return path.relative_to(BENCHMARKS).as_posix()


def assert_close(produced, committed, key=None):
    if key == "sum" and isinstance(produced, float) and isinstance(committed, float):
        assert abs(produced - committed) <= SUM_ROUNDING, key
    elif isinstance(produced, (list, tuple)) and isinstance(committed, (list, tuple)):
        assert len(produced) == len(committed), key
        if isinstance(produced, tuple):
            assert produced[0] == committed[0]
            assert_close(produced[1], committed[1], produced[0])
        else:
            for left, right in zip(produced, committed):
                assert_close(left, right, key)
    else:
        assert produced == committed, key


def assert_same_report(produced, committed):
    if produced == committed or not COMPENSATED_FLOAT_SUM:
        assert produced == committed
        return
    assert_close(
        json.loads(produced, object_pairs_hook=list), json.loads(committed, object_pairs_hook=list)
    )


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


EVAL_REPORTS = committed("horus-eval")
CONTRACT_REPORTS = committed("horus-contract-probe")


def test_the_committed_reports_are_all_found():
    assert (len(EVAL_REPORTS), len(CONTRACT_REPORTS)) == (10, 7)


@pytest.mark.parametrize("path", EVAL_REPORTS, ids=shown)
def test_resummarize_gives_the_committed_evaluation_report(path):
    assert_same_report(dumped(resummarize(json.loads(lf_text(path)))), lf_text(path))


@pytest.mark.parametrize("path", CONTRACT_REPORTS, ids=shown)
def test_the_contract_summary_gives_the_committed_probe_report(path):
    report = json.loads(lf_text(path))
    assert_same_report(
        dumped({**report, "summary": contract_summary(report["replies"])}), lf_text(path)
    )


@pytest.mark.parametrize("path", EVAL_REPORTS, ids=shown)
def test_a_full_rebuild_gives_the_committed_evaluation_report(path, items):
    stored = json.loads(lf_text(path))
    if stored["testset"]["sha256"] != file_sha256(DEFAULT_TESTSET_PATH):
        pytest.skip("written with another version of the test set")
    by_id = {item["id"]: item for item in items}
    records = []
    for question in stored["questions"]:
        outcome = {key: value for key, value in question.items() if key not in ITEM_FIELDS}
        outcome["mode"] = stored["run"]["mode"]
        record = question_record(by_id[question["id"]], outcome)
        if record["review"] is not None:
            record["review"] = question["review"]
        records.append(record)
    report = build_report(
        label=stored["label"],
        run=stored["run"],
        testset=stored["testset"],
        records=records,
        llama_cpp_build=stored["llama_cpp"]["build"],
        llama_server=stored["llama_cpp"]["server"],
        model=stored["model"],
        machine=stored["machine"],
        resources=stored["resources"],
    )
    assert_same_report(dumped(report), lf_text(path))


def test_resummarize_gives_the_committed_model_candidates_summary(tmp_path, capsys):
    runner = load_script("run_model_candidates", SCRIPTS / "run-model-candidates.py")
    shutil.copytree(BENCHMARKS / CANDIDATES_SUMMARY, tmp_path / CANDIDATES_SUMMARY)
    summary = tmp_path / f"{CANDIDATES_SUMMARY}.json"
    shutil.copy(BENCHMARKS / summary.name, summary)
    assert runner.main(["--resummarize", str(summary)]) == 0
    assert capsys.readouterr().out == f"[done] wrote {summary} and {summary.with_suffix('.md')}\n"
    for suffix in (".json", ".md"):
        assert lf_text(summary.with_suffix(suffix)) == lf_text(
            BENCHMARKS / f"{CANDIDATES_SUMMARY}{suffix}"
        )


@pytest.mark.parametrize("golden", sorted(COMPARISONS))
def test_compare_benchmarks_prints_the_golden_markdown(golden, tmp_path, capsys):
    compare_cli = load_script("compare_benchmarks", SCRIPTS / "compare-benchmarks.py")
    argv = [
        str(BENCHMARKS / part) if part.endswith(".json") else part for part in COMPARISONS[golden]
    ]
    out = tmp_path / golden
    assert compare_cli.main([*argv, "--out", str(out)]) == 0
    expected = lf_text(GOLDEN / golden)
    assert capsys.readouterr().out == expected
    assert lf_text(out) == expected


@pytest.mark.parametrize("name", sorted(HELP_SCRIPTS))
def test_the_help_text_is_the_golden_one(name, tmp_path):
    golden = GOLDEN / "help" / f"{name}-{PYTHON}.txt"
    if not golden.is_file():
        pytest.skip(
            f"argparse wraps usage lines differently from one Python version to another: no golden for {PYTHON}"
        )
    completed = subprocess.run(
        [sys.executable, str(HELP_SCRIPTS[name]), "--help"],
        cwd=tmp_path,
        env={**os.environ, "COLUMNS": "80", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert (completed.returncode, completed.stderr) == (0, "")
    assert completed.stdout == lf_text(golden)
