import importlib
from pathlib import Path

import pytest

llm = importlib.import_module("core.llm_setup")


def test_is_model_dir_exists_returns_false_when_dir_missing(tmp_path, monkeypatch):
    missing_dir = tmp_path / "no-model-here"
    # ensure it does not exist
    if missing_dir.exists():
        for p in missing_dir.iterdir():
            p.unlink()
        missing_dir.rmdir()

    monkeypatch.setattr(llm, "MODEL_DIR", missing_dir)

    assert llm.is_model_dir_exists() is False


def test_is_model_dir_exists_returns_false_when_some_files_missing(
    tmp_path, monkeypatch, caplog
):
    model_dir = tmp_path / "model"
    model_dir.mkdir()

    # create only some of the required files
    for fname in llm.REQUIRED_FILES[:2]:
        (model_dir / fname).write_text("ok")

    monkeypatch.setattr(llm, "MODEL_DIR", model_dir)

    assert llm.is_model_dir_exists() is False

    # optional: ensure message about missing files logged
    assert any("Model files missing" in record.message for record in caplog.records)


def test_is_model_dir_exists_returns_true_when_all_files_present(tmp_path, monkeypatch):
    model_dir = tmp_path / "model-full"
    model_dir.mkdir()

    for fname in llm.REQUIRED_FILES:
        (model_dir / fname).write_text("ok")

    monkeypatch.setattr(llm, "MODEL_DIR", model_dir)

    assert llm.is_model_dir_exists() is True
