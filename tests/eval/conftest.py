import re
from pathlib import Path

import pytest
from eval_testset import (
    DEFAULT_TESTSET_PATH,
    corpus_root,
    load_testset,
    read_documents,
)


@pytest.fixture(scope="session")
def testset_path() -> Path:
    return DEFAULT_TESTSET_PATH


@pytest.fixture(scope="session")
def testset(testset_path):
    return load_testset(testset_path)


@pytest.fixture(scope="session")
def corpus(testset, testset_path) -> Path:
    return corpus_root(testset, testset_path)


@pytest.fixture(scope="session")
def documents(testset, corpus):
    return read_documents(testset, corpus)


@pytest.fixture(scope="session")
def items(testset):
    return testset["items"]


@pytest.fixture
def make_item():
    def _factory(**overrides):
        item = {
            "id": "x-01",
            "category": "lookup",
            "difficulty": "easy",
            "question": "What is the hotel limit per night in the US?",
            "expected_answer": "$250 per night.",
            "expected_source": "4_Expense_Policy.md",
            "answer_patterns": [r"\b250\b"],
        }
        item.update(overrides)
        return item

    return _factory


@pytest.fixture
def make_testset(testset):
    def _factory(items):
        return {**testset, "items": items}

    return _factory


@pytest.fixture(params=["C:\\Users\\someone\\x", "/home/someone/x"])
def host_folder(request):
    return request.param


@pytest.fixture
def host_folder_leaks(host_folder):
    parts = [part for part in re.split(r"[\\/:]+", host_folder) if len(part) > 1]

    def leaks(text):
        return [part for part in parts if part in text]

    return leaks
