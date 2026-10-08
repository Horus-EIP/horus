from __future__ import annotations

import posixpath
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICES = REPO / "src" / "services"
IMAGE_SERVICES = ("mas", "agent", "knowledge-store", "web-client")
SERVICE_GITIGNORES = {
    REPO / ".gitignore": "src/services/",
    REPO / "src" / ".gitignore": "services/",
}
PYTHON_CODE = {"mas": "", "agent": "app/", "knowledge-store": "app/"}
PYTHON_LEFTOVERS = (
    "__pycache__/main.cpython-311.pyc",
    "core/__pycache__/config.cpython-311.pyc",
    "core/config.pyc",
    ".pytest_cache/v/cache/nodeids",
    ".venv/bin/python",
    "venv/bin/python",
    "core/debug.log",
    ".env",
)
AGENT_MODEL_FILES = (
    "app/models/Qwen3_instruct_4B/model-00001-of-00003.safetensors",
    "app/models/llm/config.json",
)
LOCAL_FILES = {
    "agent": ("app/offload/layer.dat", "app/qwen3-4b-instruct-q4_k_m.gguf"),
    "mas": ("models/llm/config.json", "logs/mas_20261008.log", "offload/layer.dat",
            "qwen3-4b-instruct-q4_k_m.gguf"),
    "knowledge-store": ("chroma_data/chroma.sqlite3", "chroma_data/0b1c/data_level0.bin",
                        "documents/pdf/report.pdf"),
    "web-client": ("node_modules/next/package.json", ".next/cache/webpack/client.pack",
                   "tsconfig.tsbuildinfo", ".env", ".env.production"),
}
TRACKED_BUT_NOT_BUILT = {"mas": ("logs/", "models/"), "web-client": ("README.md",)}

needs_git = unittest.skipUnless(shutil.which("git") and (REPO / ".git").exists(),
                                "needs the git checkout to list the tracked files")


def read_patterns(text: str) -> list[str]:
    patterns = []
    for raw in text.splitlines():
        if raw.startswith("#") or not raw.strip():
            continue
        line = raw.strip()
        exclusion = line.startswith("!")
        body = posixpath.normpath(line.removeprefix("!").strip()).lstrip("/")
        patterns.append(f"!{body}" if exclusion else body)
    return patterns


def dockerignore(service: str) -> list[str]:
    path = SERVICES / service / ".dockerignore"
    return read_patterns(path.read_text(encoding="utf-8")) if path.is_file() else []


def pattern_regex(pattern: str) -> re.Pattern:
    out, at = "", 0
    while at < len(pattern):
        if pattern.startswith("**/", at):
            out, at = out + "(.*/)?", at + 3
        elif pattern.startswith("**", at):
            out, at = out + ".*", at + 2
        elif pattern[at] == "*":
            out, at = out + "[^/]*", at + 1
        elif pattern[at] == "?":
            out, at = out + "[^/]", at + 1
        elif pattern[at] in "[]":
            out, at = out + pattern[at], at + 1
        else:
            out, at = out + re.escape(pattern[at]), at + 1
    return re.compile(out + r"\Z")


def path_and_parents(path: str) -> list[str]:
    parts = path.split("/")
    return ["/".join(parts[:depth]) for depth in range(1, len(parts) + 1)]


def left_out(patterns: list[str], path: str) -> bool:
    excluded = False
    for pattern in patterns:
        exclusion = pattern.startswith("!")
        if exclusion != excluded:
            continue
        regex = pattern_regex(pattern.removeprefix("!"))
        if any(regex.match(candidate) for candidate in path_and_parents(path)):
            excluded = not exclusion
    return excluded


def copied_sources(service: str) -> list[str]:
    text = re.sub(r"\\\r?\n", " ", (SERVICES / service / "Dockerfile").read_text(encoding="utf-8"))
    sources = []
    for line in text.splitlines():
        words = line.split()
        if words[:1] not in (["COPY"], ["ADD"]):
            continue
        if any(word.startswith("--from=") for word in words):
            continue
        sources += [posixpath.normpath(word) for word in words[1:-1] if not word.startswith("--")]
    return sources


def copied(sources: list[str], path: str) -> bool:
    return any(source == "." or any(pattern_regex(source).match(candidate)
                                    for candidate in path_and_parents(path))
               for source in sources)


def service_gitignore_entries() -> list[tuple[str, str]]:
    entries = []
    for gitignore, prefix in SERVICE_GITIGNORES.items():
        for raw in gitignore.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith(prefix):
                service, _, rest = line.removeprefix(prefix).partition("/")
                entries.append((service, rest))
    return entries


def tracked_files(service: str) -> list[str]:
    listing = subprocess.run(["git", "ls-files", "-z", "--", "."], cwd=SERVICES / service,
                             capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return [path for path in listing.split("\0") if path]


class IgnoreHelper(unittest.TestCase):
    def test_it_reads_the_file_like_docker(self):
        text = "app/models/\r\n# a note\r\n\r\n  !chroma_data/.gitkeep \n/logs\n"
        self.assertEqual(read_patterns(text), ["app/models", "!chroma_data/.gitkeep", "logs"])

    def test_it_matches_like_buildkit(self):
        self.assertTrue(left_out(["__pycache__"], "__pycache__/a.cpython-311.pyc"))
        self.assertFalse(left_out(["__pycache__"], "app/__pycache__/a.cpython-311.pyc"))
        self.assertTrue(left_out(["**/__pycache__"], "app/sub/__pycache__/b.cpython-311.pyc"))
        self.assertTrue(left_out(["app/models"], "app/models/Qwen3_instruct_4B/config.json"))
        self.assertFalse(left_out(["app/models"], "app/models.py"))
        self.assertFalse(left_out(["*.md"], "docs/guide.md"))
        chroma = ["chroma_data/*", "!chroma_data/.gitkeep"]
        self.assertFalse(left_out(chroma, "chroma_data/.gitkeep"))
        self.assertTrue(left_out(chroma, "chroma_data/chroma.sqlite3"))


class BuildContexts(unittest.TestCase):
    def test_every_image_service_has_a_dockerignore(self):
        for service in IMAGE_SERVICES:
            with self.subTest(service):
                self.assertTrue((SERVICES / service / ".dockerignore").is_file())

    def test_the_agent_leaves_its_local_model_snapshots_out(self):
        patterns = dockerignore("agent")
        self.assertEqual([path for path in AGENT_MODEL_FILES if not left_out(patterns, path)], [])

    def test_every_service_folder_the_gitignore_names_stays_out_of_its_image(self):
        entries = service_gitignore_entries()
        self.assertIn(("agent", "app/models/"), entries)
        for service, entry in entries:
            sample = f"{entry.rstrip('/').replace('*', 'local')}/local"
            with self.subTest(f"{service} {entry}"):
                self.assertTrue(left_out(dockerignore(service), sample))

    def test_python_caches_and_environments_stay_out_at_any_depth(self):
        for service, code in PYTHON_CODE.items():
            patterns = dockerignore(service)
            kept = [code + leftover for leftover in PYTHON_LEFTOVERS
                    if not left_out(patterns, code + leftover)]
            with self.subTest(service):
                self.assertEqual(kept, [])

    def test_files_only_a_developer_machine_has_stay_out(self):
        for service, paths in LOCAL_FILES.items():
            patterns = dockerignore(service)
            with self.subTest(service):
                self.assertEqual([path for path in paths if not left_out(patterns, path)], [])

    def test_the_knowledge_store_still_gets_its_empty_chroma_folder(self):
        self.assertFalse(left_out(dockerignore("knowledge-store"), "chroma_data/.gitkeep"))

    def test_every_file_a_dockerfile_names_reaches_the_build(self):
        for service in IMAGE_SERVICES:
            patterns = dockerignore(service)
            named = [source for source in copied_sources(service)
                     if source != "." and "*" not in source and left_out(patterns, source)]
            with self.subTest(service):
                self.assertEqual(named, [])

    @needs_git
    def test_every_tracked_file_a_dockerfile_copies_reaches_the_build(self):
        for service in IMAGE_SERVICES:
            patterns = dockerignore(service)
            sources = copied_sources(service)
            skipped = TRACKED_BUT_NOT_BUILT.get(service, ())
            dropped = [path for path in tracked_files(service)
                       if copied(sources, path) and not path.startswith(skipped)
                       and left_out(patterns, path)]
            with self.subTest(service):
                self.assertEqual(dropped, [])


if __name__ == "__main__":
    unittest.main()
