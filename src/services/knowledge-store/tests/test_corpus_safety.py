from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

os.environ.setdefault("TEST_MODE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

def _stub(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__spec__ = types.SimpleNamespace(origin="mock", submodule_search_locations=[])
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module

_stub("spacy", load=MagicMock(return_value=MagicMock()), cli=MagicMock())
_stub("spacy.lang")
_stub("spacy.lang.en")
_stub("spacy.lang.en.stop_words", STOP_WORDS={"a", "the", "is", "in"})

_stub("chromadb", PersistentClient=MagicMock())
_stub("chromadb.config", Settings=MagicMock())
_stub("sentence_transformers", SentenceTransformer=MagicMock())

_stub("pdfplumber", open=MagicMock())
_stub("pytesseract", image_to_string=MagicMock(return_value=""))
_stub("docx", Document=MagicMock())
_stub("pdf2image", convert_from_path=MagicMock(return_value=[]))

from app.api.routes import corpus  # noqa: E402

MAX_BYTES = 1024

def _accepted(root: Path) -> set[str]:
    return {
        rel for _p, rel, cand in corpus.walk_corpus(root, MAX_BYTES)
        if cand.reason is None
    }

def _reasons(root: Path) -> dict[str, str]:
    return {
        rel: cand.reason for _p, rel, cand in corpus.walk_corpus(root, MAX_BYTES)
        if cand.reason is not None
    }

def _hard_link(link: Path, target: Path) -> None:
    try:
        os.link(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create hard links in this environment: {exc}")

def _symlink(link: Path, target: Path, is_dir: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks in this environment: {exc}")

@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "report.md").write_text("Q4 2025 revenue was 4.2M.", encoding="utf-8")
    return root

class TestBaseline:
    def test_plain_document_is_accepted(self, corpus_root):
        assert _accepted(corpus_root) == {"report.md"}

    def test_accepted_file_reports_no_reason(self, corpus_root):
        cand = corpus.inspect_candidate(corpus_root / "report.md", corpus_root, MAX_BYTES)

        assert cand.reason is None
        assert cand.resolved == (corpus_root / "report.md").resolve()
        assert cand.size > 0
        assert (cand.dev, cand.ino) != (0, 0)

    def test_reported_path_is_relative_not_absolute(self, corpus_root):
        (corpus_root / "nested").mkdir()
        (corpus_root / "nested" / "memo.txt").write_text("hello", encoding="utf-8")
        rels = _accepted(corpus_root)
        assert "nested/memo.txt" in rels
        assert not any(os.path.isabs(rel) for rel in rels)

class TestAbsoluteEscape:
    def test_path_outside_root_is_rejected(self, tmp_path, corpus_root):
        outside = tmp_path / "secret.txt"
        outside.write_text("token=hunter2", encoding="utf-8")

        cand = corpus.inspect_candidate(outside, corpus_root, MAX_BYTES)

        assert cand.resolved is None
        assert cand.reason == corpus.SKIP_OUTSIDE_ROOT

    def test_dotdot_traversal_is_rejected(self, tmp_path, corpus_root):
        outside = tmp_path / "secret.txt"
        outside.write_text("token=hunter2", encoding="utf-8")

        climbing = corpus_root / ".." / "secret.txt"
        cand = corpus.inspect_candidate(climbing, corpus_root, MAX_BYTES)

        assert cand.resolved is None
        assert cand.reason == corpus.SKIP_OUTSIDE_ROOT

class TestSymlinkedFile:
    def test_symlinked_file_pointing_outside_is_rejected(self, tmp_path, corpus_root):
        outside = tmp_path / "shadow"
        outside.write_text("root:!:19000:0:99999:7:::", encoding="utf-8")
        _symlink(corpus_root / "notes.txt", outside)

        cand = corpus.inspect_candidate(corpus_root / "notes.txt", corpus_root, MAX_BYTES)

        assert cand.resolved is None
        assert cand.reason == corpus.SKIP_SYMLINK

    def test_walker_lists_the_symlink_but_never_accepts_it(self, tmp_path, corpus_root):
        outside = tmp_path / "shadow"
        outside.write_text("root:!:19000:0:99999:7:::", encoding="utf-8")
        _symlink(corpus_root / "notes.txt", outside)

        assert _accepted(corpus_root) == {"report.md"}
        assert _reasons(corpus_root)["notes.txt"] == corpus.SKIP_SYMLINK

    def test_symlink_inside_the_root_is_still_rejected(self, corpus_root):
        _symlink(corpus_root / "alias.md", corpus_root / "report.md")

        cand = corpus.inspect_candidate(corpus_root / "alias.md", corpus_root, MAX_BYTES)
        assert cand.reason == corpus.SKIP_SYMLINK

class TestSymlinkedDirectory:
    def test_symlinked_directory_is_not_descended(self, tmp_path, corpus_root):
        outside_dir = tmp_path / "elsewhere"
        outside_dir.mkdir()
        (outside_dir / "private.md").write_text("confidential", encoding="utf-8")
        _symlink(corpus_root / "linked", outside_dir, is_dir=True)

        rows = corpus.walk_corpus(corpus_root, MAX_BYTES)
        seen = {rel for _p, rel, _cand in rows}

        assert _accepted(corpus_root) == {"report.md"}
        assert not any("private.md" in rel for rel in seen)

    def test_noisy_directories_are_pruned(self, corpus_root):
        for name in (".git", ".ssh", "node_modules", "__pycache__", ".hidden"):
            junk = corpus_root / name
            junk.mkdir()
            (junk / "junk.txt").write_text("x", encoding="utf-8")

        assert _accepted(corpus_root) == {"report.md"}

class TestExtensionAllowlist:
    @pytest.mark.parametrize("name", ["id_rsa.pem", "history.sqlite", "blob.bin", "noext"])
    def test_unsupported_extension_is_rejected(self, corpus_root, name):
        (corpus_root / name).write_text("not a document", encoding="utf-8")

        cand = corpus.inspect_candidate(corpus_root / name, corpus_root, MAX_BYTES)

        assert cand.reason == corpus.SKIP_EXTENSION
        assert name not in _accepted(corpus_root)

    @pytest.mark.parametrize("ext", sorted(corpus.ALLOWED_EXTENSIONS - {".pdf", ".docx"}))
    def test_allowlisted_text_extensions_are_accepted(self, corpus_root, ext):
        (corpus_root / f"doc{ext}").write_text("content", encoding="utf-8")
        assert f"doc{ext}" in _accepted(corpus_root)

    def test_extension_match_is_case_insensitive(self, corpus_root):
        (corpus_root / "SHOUTING.MD").write_text("content", encoding="utf-8")
        assert "SHOUTING.MD" in _accepted(corpus_root)

class TestSizeLimits:
    def test_oversized_file_is_rejected(self, corpus_root):
        (corpus_root / "huge.txt").write_text("x" * (MAX_BYTES + 1), encoding="utf-8")

        cand = corpus.inspect_candidate(corpus_root / "huge.txt", corpus_root, MAX_BYTES)

        assert cand.reason == corpus.SKIP_TOO_LARGE
        assert cand.size == MAX_BYTES + 1
        assert "huge.txt" not in _accepted(corpus_root)

    def test_file_exactly_at_the_cap_is_accepted(self, corpus_root):
        (corpus_root / "edge.txt").write_text("x" * MAX_BYTES, encoding="utf-8")
        assert "edge.txt" in _accepted(corpus_root)

    def test_zero_byte_file_is_rejected(self, corpus_root):
        (corpus_root / "empty.txt").write_text("", encoding="utf-8")

        cand = corpus.inspect_candidate(corpus_root / "empty.txt", corpus_root, MAX_BYTES)

        assert cand.reason == corpus.SKIP_EMPTY

class TestMiscellaneous:
    def test_missing_root_yields_no_rows(self, tmp_path):
        assert corpus.walk_corpus(tmp_path / "not-mounted", MAX_BYTES) == []

    def test_doc_id_is_content_addressed_and_stable(self, corpus_root):
        path = corpus_root / "report.md"
        first = corpus.sha256_of_file(path)
        second = corpus.sha256_of_file(path)

        assert first == second
        assert corpus.doc_id_for(first) == f"corpus-{first[:32]}"
        assert corpus.doc_id_for(first).startswith("corpus-")

    def test_doc_id_changes_when_content_changes(self, corpus_root):
        path = corpus_root / "report.md"
        before = corpus.doc_id_for(corpus.sha256_of_file(path))
        path.write_text("Q4 2025 revenue was 5.0M.", encoding="utf-8")
        after = corpus.doc_id_for(corpus.sha256_of_file(path))

        assert before != after

    def test_every_rejection_carries_a_reason(self, tmp_path, corpus_root):
        (corpus_root / "id_rsa.pem").write_text("key", encoding="utf-8")
        (corpus_root / "empty.txt").write_text("", encoding="utf-8")
        (corpus_root / "huge.txt").write_text("x" * (MAX_BYTES + 1), encoding="utf-8")

        reasons = _reasons(corpus_root)
        assert reasons["id_rsa.pem"] == corpus.SKIP_EXTENSION
        assert reasons["empty.txt"] == corpus.SKIP_EMPTY
        assert reasons["huge.txt"] == corpus.SKIP_TOO_LARGE
        assert all(reason for reason in reasons.values())

class TestHardLink:
    def test_hard_link_to_a_private_key_is_rejected(self, tmp_path, corpus_root):
        key = tmp_path / "id_rsa"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----", encoding="utf-8")
        _hard_link(corpus_root / "notes.txt", key)

        cand = corpus.inspect_candidate(corpus_root / "notes.txt", corpus_root, MAX_BYTES)

        assert cand.resolved is None
        assert cand.reason == corpus.SKIP_HARD_LINK

    def test_walker_refuses_the_hard_link_and_says_why(self, tmp_path, corpus_root):
        key = tmp_path / "id_rsa"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----", encoding="utf-8")
        _hard_link(corpus_root / "notes.txt", key)

        assert _accepted(corpus_root) == {"report.md"}
        assert _reasons(corpus_root)["notes.txt"] == corpus.SKIP_HARD_LINK

    def test_hard_link_defeats_the_ssh_directory_pruning(self, tmp_path, corpus_root):
        hidden = tmp_path / ".ssh"
        hidden.mkdir()
        key = hidden / "id_ed25519"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----", encoding="utf-8")
        _hard_link(corpus_root / "meeting.md", key)

        assert "meeting.md" not in _accepted(corpus_root)
        assert _reasons(corpus_root)["meeting.md"] == corpus.SKIP_HARD_LINK

    def test_ordinary_single_named_file_is_untouched(self, corpus_root):
        cand = corpus.inspect_candidate(corpus_root / "report.md", corpus_root, MAX_BYTES)
        assert cand.reason is None

def _pinned(root: Path, name: str):
    rows = {rel: cand for _p, rel, cand in corpus.walk_corpus(root, MAX_BYTES)}
    return rows[name]

def _ingest(job: dict, root: Path, name: str, cand) -> dict:
    asyncio.run(corpus._ingest_one(job, cand.resolved or (root / name), name, cand))
    return job["files"][-1]

class TestChangedDuringScan:
    def test_file_swapped_after_the_walk_is_not_read(self, tmp_path, corpus_root):
        (corpus_root / "z.txt").write_text("harmless notes", encoding="utf-8")
        cand = _pinned(corpus_root, "z.txt")
        assert cand.reason is None

        secret = tmp_path / "shadow"
        secret.write_text("root:$6$REAL$HASH:19000:0:99999:7:::", encoding="utf-8")
        (corpus_root / "z.txt").unlink()
        _hard_link(corpus_root / "z.txt", secret)

        job = corpus._new_job(dry_run=True)
        entry = _ingest(job, corpus_root, "z.txt", cand)

        assert entry["reason"] == corpus.SKIP_CHANGED_DURING_SCAN
        assert job["totals"]["rejected"] == 1
        assert job["totals"]["would_ingest"] == 0

    def test_file_grown_past_the_cap_after_the_walk_is_not_read(self, corpus_root):
        (corpus_root / "z.txt").write_text("small", encoding="utf-8")
        cand = _pinned(corpus_root, "z.txt")
        (corpus_root / "z.txt").write_text("x" * (MAX_BYTES + 1), encoding="utf-8")

        job = corpus._new_job(dry_run=True)
        entry = _ingest(job, corpus_root, "z.txt", cand)

        assert entry["reason"] == corpus.SKIP_CHANGED_DURING_SCAN
        assert job["totals"]["rejected"] == 1

    def test_untouched_file_still_gets_ingested(self, corpus_root):
        cand = _pinned(corpus_root, "report.md")

        job = corpus._new_job(dry_run=True)
        entry = _ingest(job, corpus_root, "report.md", cand)

        assert entry.get("reason") != corpus.SKIP_CHANGED_DURING_SCAN
        assert job["totals"]["rejected"] == 0
        assert entry["decision"] in {"skipped_unchanged", "would_ingest"}

    def test_still_pinned_tracks_the_inode_not_the_name(self, tmp_path, corpus_root):
        (corpus_root / "z.txt").write_text("harmless notes", encoding="utf-8")
        cand = _pinned(corpus_root, "z.txt")
        assert corpus._still_pinned(corpus_root / "z.txt", cand) is True

        secret = tmp_path / "shadow"
        secret.write_text("root:$6$REAL$HASH:19000:0:99999:7:::", encoding="utf-8")
        (corpus_root / "z.txt").unlink()
        _hard_link(corpus_root / "z.txt", secret)

        assert corpus._still_pinned(corpus_root / "z.txt", cand) is False

    def test_pinned_path_names_the_open_inode_where_proc_exists(
        self, corpus_root, monkeypatch
    ):
        report = corpus_root / "report.md"
        fd = os.open(report, corpus.OPEN_FLAGS)
        try:
            monkeypatch.setattr(corpus, "HAS_PROC_FD", True)
            assert corpus._pinned_path(fd, report) == f"/proc/self/fd/{fd}"

            monkeypatch.setattr(corpus, "HAS_PROC_FD", False)
            assert corpus._pinned_path(fd, report) == str(report)
        finally:
            os.close(fd)

    def test_hash_from_the_descriptor_matches_the_hash_from_the_name(self, corpus_root):
        report = corpus_root / "report.md"
        fd = os.open(report, corpus.OPEN_FLAGS)
        try:
            assert corpus.sha256_of_fd(fd) == corpus.sha256_of_file(report)
        finally:
            os.close(fd)

TOKEN = "s3cret-corpus-token"
UI_ORIGIN = "http://localhost:3000"
DRIVE_BY_ORIGIN = "https://evil.example"

@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(corpus, "CORPUS_ROOT", tmp_path / "not-mounted")
    return TestClient(app)

class TestCorpusTokenGate:
    def test_unset_token_disables_the_routes_rather_than_opening_them(
        self, client, monkeypatch
    ):
        monkeypatch.delenv(corpus.CORPUS_TOKEN_ENV, raising=False)

        assert client.post("/corpus/scan").status_code == 503
        assert client.get("/corpus/status").status_code == 503

    def test_empty_token_also_fails_closed(self, client, monkeypatch):
        monkeypatch.setenv(corpus.CORPUS_TOKEN_ENV, "   ")
        assert client.get("/corpus/status").status_code == 503

    def test_no_header_is_refused(self, client, monkeypatch):
        monkeypatch.setenv(corpus.CORPUS_TOKEN_ENV, TOKEN)

        assert client.post("/corpus/scan").status_code == 403
        assert client.get("/corpus/status").status_code == 403

    def test_wrong_token_is_refused(self, client, monkeypatch):
        monkeypatch.setenv(corpus.CORPUS_TOKEN_ENV, TOKEN)
        headers = {corpus.CORPUS_TOKEN_HEADER: TOKEN + "x"}

        assert client.post("/corpus/scan", headers=headers).status_code == 403
        assert client.get("/corpus/status", headers=headers).status_code == 403

    def test_correct_token_reaches_the_route(self, client, monkeypatch):
        monkeypatch.setenv(corpus.CORPUS_TOKEN_ENV, TOKEN)
        headers = {corpus.CORPUS_TOKEN_HEADER: TOKEN}

        assert client.get("/corpus/status", headers=headers).status_code == 200
        assert client.post("/corpus/scan", headers=headers).status_code == 404

class TestCorsOrigins:
    def test_drive_by_page_cannot_read_the_response(self, client, monkeypatch):
        monkeypatch.setenv(corpus.CORPUS_TOKEN_ENV, TOKEN)

        response = client.get(
            "/corpus/status",
            headers={corpus.CORPUS_TOKEN_HEADER: TOKEN, "Origin": DRIVE_BY_ORIGIN},
        )

        assert "access-control-allow-origin" not in response.headers

    def test_preflight_for_the_token_header_is_refused_cross_origin(
        self, client, monkeypatch
    ):
        monkeypatch.setenv(corpus.CORPUS_TOKEN_ENV, TOKEN)

        preflight = client.options(
            "/corpus/scan",
            headers={
                "Origin": DRIVE_BY_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": corpus.CORPUS_TOKEN_HEADER,
            },
        )

        assert preflight.headers.get("access-control-allow-origin") is None

    def test_the_horus_ui_is_still_allowed(self, client, monkeypatch):
        monkeypatch.setenv(corpus.CORPUS_TOKEN_ENV, TOKEN)

        response = client.get(
            "/corpus/status",
            headers={corpus.CORPUS_TOKEN_HEADER: TOKEN, "Origin": UI_ORIGIN},
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == UI_ORIGIN
