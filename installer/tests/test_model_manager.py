from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import itertools
import json
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import horus_install  # noqa: E402
import model_manager  # noqa: E402
import profiles  # noqa: E402
from common import (  # noqa: E402
    EVENT_PREFIX,
    EXIT_DISK_SPACE,
    EXIT_MODEL_DOWNLOAD_FAILED,
    EXIT_MODEL_HASH_MISMATCH,
    EXIT_MODEL_MANIFEST_INVALID,
    Events,
    InstallError,
    Log,
)

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "models" / "manifest.json"
MODELS_README = REPO / "scripts" / "models" / "README.md"

UNSLOTH_SIZE = 2497281120
UNSLOTH_SHA256 = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
PINNED_HF_RESOLVE = re.compile(r"^https://huggingface\.co/[^/]+/[^/]+/resolve/[0-9a-f]{40}/")

PAYLOAD_SIZE = 3 * 1024 * 1024 + 123
TEST_CHUNK = 64 * 1024
RANGE_REQUEST = re.compile(r"^bytes=(\d+)-$")
SERVE = "serve"
BUILD_OPENER = urllib.request.build_opener

def payload_of(size: int) -> bytes:
    blocks = (hashlib.sha256(index.to_bytes(4, "big")).digest() for index in range(size // 32 + 1))
    return b"".join(blocks)[:size]

def damaged(data: bytes) -> bytes:
    middle = len(data) // 2
    return data[:middle] + bytes([data[middle] ^ 0xFF]) + data[middle + 1:]

def cut_at(offset: int) -> tuple[str, int]:
    return ("cut", offset)

class MirrorScript:

    def __init__(self, body: bytes):
        self.body = body
        self.plan: list = []
        self.afterwards = SERVE
        self.honours_range = True
        self.ranges: list[str | None] = []
        self.authorizations: list[str | None] = []
        self.served = 0

    @property
    def requests(self) -> int:
        return len(self.ranges)

    def next_step(self):
        return self.plan.pop(0) if self.plan else self.afterwards

class ScriptedHandler(BaseHTTPRequestHandler):

    def log_message(self, *args) -> None:
        pass

    def reply_empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        script = self.server.scripts.get(self.path)
        if script is None:
            self.reply_empty(404)
            return
        asked = self.headers.get("Range")
        script.ranges.append(asked)
        script.authorizations.append(self.headers.get("Authorization"))
        step = script.next_step()
        if isinstance(step, int):
            self.reply_empty(step)
            return
        body = script.body
        start = 0
        match = RANGE_REQUEST.match(asked or "")
        if match and script.honours_range:
            start = int(match.group(1))
            if start >= len(body):
                self.reply_empty(416)
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body) - start))
        self.end_headers()
        end = step[1] if isinstance(step, tuple) else len(body)
        sent = body[start:max(start, end)]
        try:
            self.wfile.write(sent)
            self.wfile.flush()
        except OSError:
            return
        script.served += len(sent)

class LocalMirrors:

    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedHandler)
        self.server.daemon_threads = True
        self.server.scripts = {}
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/{name}/model.gguf"

    def add(self, name: str, body: bytes) -> tuple[MirrorScript, str]:
        script = MirrorScript(body)
        self.server.scripts[f"/{name}/model.gguf"] = script
        return script, self.url(name)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

def direct_opener() -> urllib.request.OpenerDirector:
    return BUILD_OPENER(urllib.request.ProxyHandler({}))

def entry_for(payload: bytes, *mirrors: str, min_ram_gb: float = 16) -> model_manager.ModelEntry:
    return model_manager.ModelEntry(
        id="test-model", version="1.0.0", file="model.gguf", size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(), min_ram_gb=min_ram_gb,
        profiles=("cpu-standard",), mirrors=tuple(mirrors),
    )

def read_events(stream: io.StringIO, name: str = "download") -> list[dict]:
    events = []
    for line in stream.getvalue().splitlines():
        if line.startswith(EVENT_PREFIX):
            data = json.loads(line[len(EVENT_PREFIX):])
            if data.get("event") == name:
                events.append(data)
    return events

def shipped_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))

class DownloadCase(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.models = self.tmp / "models"
        self.events = io.StringIO()
        self.log = Log(self.tmp / "install-log.txt", events=Events(True, stream=self.events))
        self.addCleanup(self.log.close, 0)
        self.mirrors = LocalMirrors()
        self.addCleanup(self.mirrors.close)
        self.pauses: list[float] = []
        chunk = mock.patch.object(model_manager, "CHUNK_BYTES", TEST_CHUNK)
        chunk.start()
        self.addCleanup(chunk.stop)
        self.payload = payload_of(PAYLOAD_SIZE)
        self.half = PAYLOAD_SIZE // 2

    @property
    def target(self) -> Path:
        return self.models / "model.gguf"

    @property
    def part(self) -> Path:
        return self.models / "model.gguf.part"

    @property
    def marker(self) -> Path:
        return self.models / "model.gguf.sha256"

    def download(self, entry: model_manager.ModelEntry, clock=None,
                 token: str | None = None) -> tuple[str, InstallError | None]:
        options = {"opener": direct_opener(), "sleep": self.pauses.append, "token": token}
        if clock is not None:
            options["clock"] = clock
        job = model_manager.ModelDownload(self.log, entry, self.models, entry.mirrors, **options)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                job.run()
                raised = None
            except InstallError as exc:
                raised = exc
        return out.getvalue(), raised

    def assert_in_place(self) -> None:
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(self.marker.read_bytes(),
                         (hashlib.sha256(self.payload).hexdigest() + "\n").encode("ascii"))
        self.assertFalse(self.part.exists())

class Downloads(DownloadCase):

    def test_a_fresh_download_is_verified_then_renamed_in_one_step(self):
        script, url = self.mirrors.add("a", self.payload)
        _out, raised = self.download(entry_for(self.payload, url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(script.ranges, [None])

    def test_a_connection_cut_at_half_resumes_from_half(self):
        script, url = self.mirrors.add("a", self.payload)
        script.plan = [cut_at(self.half)]
        out, raised = self.download(entry_for(self.payload, url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(script.ranges, [None, f"bytes={self.half}-"])
        self.assertEqual(script.served, PAYLOAD_SIZE)
        self.assertEqual(self.pauses, [model_manager.BACKOFF_SECONDS])
        self.assertIn("resuming at", out)

    def test_restarting_after_the_network_dropped_at_half_resumes_from_half(self):
        script, url = self.mirrors.add("a", self.payload)
        script.plan = [cut_at(self.half)]
        script.afterwards = 503
        entry = entry_for(self.payload, url)

        _out, raised = self.download(entry)
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_MODEL_DOWNLOAD_FAILED)
        self.assertEqual(script.requests, model_manager.FAILURES_ON_THE_LAST_MIRROR)
        self.assertEqual(self.part.stat().st_size, self.half)
        self.assertFalse(self.target.exists())
        self.assertIn("the next run resumes from it", raised.detail)
        self.assertIn("START-HERE", raised.fix)

        script.afterwards = SERVE
        served_before = script.served
        _out, raised = self.download(entry)
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(script.ranges[-1], f"bytes={self.half}-")
        self.assertEqual(script.served - served_before, PAYLOAD_SIZE - self.half)

    def test_a_connection_that_keeps_delivering_is_never_given_up(self):
        script, url = self.mirrors.add("a", self.payload)
        steps = range(1, 2 * model_manager.FAILURES_BEFORE_NEXT_MIRROR + 1)
        script.plan = [cut_at(n * PAYLOAD_SIZE // 8) for n in steps]
        _out, raised = self.download(entry_for(self.payload, url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(script.served, PAYLOAD_SIZE)

    def test_a_corrupted_file_is_deleted_and_the_install_says_so(self):
        script, url = self.mirrors.add("a", damaged(self.payload))
        out, raised = self.download(entry_for(self.payload, url))
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_MODEL_HASH_MISMATCH)
        self.assertIn("damaged", raised.headline)
        self.assertIn("deleted", raised.headline)
        self.assertIn(hashlib.sha256(damaged(self.payload)).hexdigest(), raised.detail)
        self.assertIn(hashlib.sha256(self.payload).hexdigest(), raised.detail)
        self.assertIn("The file was deleted", out)
        for path in (self.target, self.part, self.marker):
            self.assertFalse(path.exists(), path)
        self.assertEqual(script.requests, 1)
        phases = [event["phase"] for event in read_events(self.events)]
        self.assertEqual(phases[-2:], ["verifying", "failed"])

    def test_a_corrupted_mirror_is_left_for_the_next_one(self):
        bad, bad_url = self.mirrors.add("bad", damaged(self.payload))
        good, good_url = self.mirrors.add("good", self.payload)
        out, raised = self.download(entry_for(self.payload, bad_url, good_url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual((bad.requests, good.requests), (1, 1))
        self.assertIn("damaged", out)

    def test_three_failures_in_a_row_switch_to_the_next_mirror(self):
        down, down_url = self.mirrors.add("down", self.payload)
        down.afterwards = 503
        good, good_url = self.mirrors.add("good", self.payload)
        out, raised = self.download(entry_for(self.payload, down_url, good_url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(down.requests, model_manager.FAILURES_BEFORE_NEXT_MIRROR)
        self.assertEqual(good.requests, 1)
        self.assertEqual(self.pauses, [model_manager.BACKOFF_SECONDS,
                                       2 * model_manager.BACKOFF_SECONDS])
        self.assertIn("next mirror", out)

    def test_the_last_mirror_rides_out_a_short_network_drop_before_the_install_gives_up(self):
        script, url = self.mirrors.add("only", self.payload)
        script.afterwards = 503
        out, raised = self.download(entry_for(self.payload, url))
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_MODEL_DOWNLOAD_FAILED)
        budget = model_manager.FAILURES_ON_THE_LAST_MIRROR
        self.assertGreater(budget, model_manager.FAILURES_BEFORE_NEXT_MIRROR)
        self.assertEqual(script.requests, budget)
        self.assertEqual(self.pauses,
                         [model_manager.BACKOFF_SECONDS * n for n in range(1, budget)])
        self.assertGreaterEqual(sum(self.pauses), 120)
        self.assertNotIn("Trying the next mirror", out)
        self.assertIn("No other mirror is listed", out)

    def test_the_give_up_message_counts_the_attempts_each_mirror_really_had(self):
        missing_url = self.mirrors.url("gone")
        down, down_url = self.mirrors.add("down", self.payload)
        down.afterwards = 503
        _out, raised = self.download(entry_for(self.payload, missing_url, down_url))
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_MODEL_DOWNLOAD_FAILED)
        self.assertIn("from 2 mirror(s)", raised.detail)
        self.assertIn("1 attempt: HTTP 404", raised.detail)
        self.assertIn(f"{model_manager.FAILURES_ON_THE_LAST_MIRROR} attempts: HTTP 503",
                      raised.detail)
        self.assertNotIn("times each", raised.detail)

    def test_the_next_mirror_resumes_what_the_first_one_delivered(self):
        flaky, flaky_url = self.mirrors.add("flaky", self.payload)
        flaky.plan = [cut_at(self.half)]
        flaky.afterwards = 503
        good, good_url = self.mirrors.add("good", self.payload)
        _out, raised = self.download(entry_for(self.payload, flaky_url, good_url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(good.ranges, [f"bytes={self.half}-"])

    def test_a_missing_file_leaves_the_mirror_at_once(self):
        missing_url = self.mirrors.url("gone")
        good, good_url = self.mirrors.add("good", self.payload)
        out, raised = self.download(entry_for(self.payload, missing_url, good_url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(self.pauses, [])
        self.assertIn("HTTP 404", out)

    def test_a_mirror_serving_another_size_is_left_before_anything_is_written(self):
        wrong, wrong_url = self.mirrors.add("wrong", self.payload + b"extra")
        good, good_url = self.mirrors.add("good", self.payload)
        out, raised = self.download(entry_for(self.payload, wrong_url, good_url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(wrong.requests, 1)
        self.assertEqual(good.ranges, [None])
        self.assertEqual(self.pauses, [])
        self.assertIn(f"{PAYLOAD_SIZE:,}", out)

    def test_a_partial_file_from_another_download_is_fetched_again_from_zero(self):
        self.models.mkdir()
        self.part.write_bytes(damaged(self.payload)[: self.half + 10])
        script, url = self.mirrors.add("a", self.payload)
        out, raised = self.download(entry_for(self.payload, url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(script.ranges, [f"bytes={self.half + 10}-", None])
        self.assertIn("more than one download", out)

    def test_a_mirror_that_ignores_range_starts_again_from_the_beginning(self):
        script, url = self.mirrors.add("a", self.payload)
        script.honours_range = False
        script.plan = [cut_at(self.half)]
        out, raised = self.download(entry_for(self.payload, url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(script.ranges, [None, f"bytes={self.half}-"])
        self.assertIn("cannot resume", out)

    def test_a_verified_file_is_not_downloaded_again(self):
        script, url = self.mirrors.add("a", self.payload)
        entry = entry_for(self.payload, url)
        self.assertIsNone(self.download(entry)[1])
        out, raised = self.download(entry)
        self.assertIsNone(raised)
        self.assertEqual(script.requests, 1)
        self.assertIn("verified before", out)

    def test_a_file_copied_by_hand_is_checked_instead_of_downloaded(self):
        self.models.mkdir()
        self.target.write_bytes(self.payload)
        script, url = self.mirrors.add("a", self.payload)
        _out, raised = self.download(entry_for(self.payload, url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(script.requests, 0)

    def test_a_different_file_under_that_name_is_replaced(self):
        self.models.mkdir()
        self.target.write_bytes(damaged(self.payload))
        self.marker.write_text("0" * 64 + "\n", encoding="utf-8")
        script, url = self.mirrors.add("a", self.payload)
        out, raised = self.download(entry_for(self.payload, url))
        self.assertIsNone(raised)
        self.assert_in_place()
        self.assertEqual(script.requests, 1)
        self.assertIn("not the expected file", out)

    def test_too_little_free_disk_stops_before_any_download(self):
        script, url = self.mirrors.add("a", self.payload)
        usage = mock.Mock(free=PAYLOAD_SIZE)
        with mock.patch.object(model_manager.shutil, "disk_usage", return_value=usage):
            _out, raised = self.download(entry_for(self.payload, url))
        self.assertIsNotNone(raised)
        self.assertEqual(raised.code, EXIT_DISK_SPACE)
        self.assertIn("--models-dir", raised.fix)
        self.assertEqual(script.requests, 0)

    def test_the_token_goes_to_hugging_face_only_and_never_through_a_redirect(self):
        hub = model_manager.build_request("https://huggingface.co/a/b/resolve/c/d.gguf", 10, "t0k")
        self.assertEqual(hub.get_header("Range"), "bytes=10-")
        self.assertEqual(hub.unredirected_hdrs.get("Authorization"), "Bearer t0k")
        self.assertNotIn("Authorization", hub.headers)
        other = model_manager.build_request("https://models.example.org/d.gguf", 0, "t0k")
        self.assertIsNone(other.get_header("Authorization"))
        self.assertIsNone(other.get_header("Range"))
        script, url = self.mirrors.add("a", self.payload)
        _out, raised = self.download(entry_for(self.payload, url), token="t0k")
        self.assertIsNone(raised)
        self.assertEqual(script.authorizations, [None])

class ProgressEvents(DownloadCase):

    def download_with_a_steady_clock(self, entry):
        ticks = itertools.count(0.0, 0.25)
        return self.download(entry, clock=lambda: next(ticks))

    def test_progress_events_carry_total_size_speed_and_time_left(self):
        _script, url = self.mirrors.add("a", self.payload)
        _out, raised = self.download_with_a_steady_clock(entry_for(self.payload, url))
        self.assertIsNone(raised)
        events = read_events(self.events)
        downloading = [event for event in events if event["phase"] == "downloading"]
        self.assertGreater(len(downloading), 4)
        for event in downloading:
            self.assertEqual(event["total_bytes"], PAYLOAD_SIZE)
            self.assertEqual(event["model"], "test-model")
            self.assertEqual(event["file"], "model.gguf")
        self.assertEqual(downloading[0]["done_bytes"], 0)
        self.assertEqual(downloading[-1]["done_bytes"], PAYLOAD_SIZE)
        self.assertEqual(downloading[-1]["percent"], 100.0)
        middle = next(event for event in downloading if 0 < event["done_bytes"] < PAYLOAD_SIZE)
        speed = TEST_CHUNK / 0.25
        self.assertEqual(middle["bytes_per_second"], int(speed))
        self.assertEqual(middle["seconds_left"],
                         int((PAYLOAD_SIZE - middle["done_bytes"]) / speed))
        self.assertIn("of 3.0 MB", middle["text"])
        self.assertIn("/s", middle["text"])
        self.assertIn("left", middle["text"])
        self.assertEqual([event["phase"] for event in events[-2:]], ["verifying", "verified"])

    def test_events_are_spaced_out_but_the_end_is_always_reported(self):
        _script, url = self.mirrors.add("a", self.payload)
        self.download_with_a_steady_clock(entry_for(self.payload, url))
        downloading = [event for event in read_events(self.events)
                       if event["phase"] == "downloading"]
        chunks = -(-PAYLOAD_SIZE // TEST_CHUNK)
        self.assertLess(len(downloading), chunks)
        self.assertEqual(downloading[-1]["done_bytes"], PAYLOAD_SIZE)

    def test_a_resumed_download_reports_where_it_started(self):
        script, url = self.mirrors.add("a", self.payload)
        script.plan = [cut_at(self.half)]
        self.download_with_a_steady_clock(entry_for(self.payload, url))
        resumed = [event for event in read_events(self.events)
                   if event["phase"] == "downloading" and event["resumed_from_bytes"]]
        self.assertTrue(resumed)
        self.assertEqual(resumed[0]["resumed_from_bytes"], self.half)
        self.assertEqual(resumed[0]["done_bytes"], self.half)

    def test_the_console_shows_size_speed_and_time_left_while_it_downloads(self):
        _script, url = self.mirrors.add("a", self.payload)
        with mock.patch.object(model_manager, "LINE_EVERY_SECONDS", 1.0):
            out, _raised = self.download_with_a_steady_clock(entry_for(self.payload, url))
        lines = [line for line in out.splitlines() if " of 3.0 MB (" in line]
        self.assertGreater(len(lines), 2)
        self.assertTrue(any("left" in line for line in lines))
        self.assertIn("(100%)", lines[-1])

    def test_the_desktop_app_renders_every_field_it_reads_from_these_events(self):
        app_js = REPO / "desktop" / "ui" / "app.js"
        if not app_js.is_file():
            self.skipTest("desktop/ is not present")
        source = app_js.read_text(encoding="utf-8")
        self.assertIn('case "download":', source)
        body = source[source.index("function renderDownload"):]
        body = body[:body.index("\n}\n")]
        _script, url = self.mirrors.add("a", self.payload)
        self.download_with_a_steady_clock(entry_for(self.payload, url))
        fields = set(re.findall(r"data\.(\w+)", body))
        self.assertLessEqual({"phase", "percent", "text"}, fields)
        for event in read_events(self.events):
            for field in fields:
                self.assertIn(field, event)
        for phase in ("downloading", "verified", "failed"):
            self.assertIn(f'"{phase}"', body)

class SpeedAndTimeLeft(unittest.TestCase):

    def progress(self, clock) -> model_manager.Progress:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        log = Log(Path(tmp.name) / "install-log.txt")
        self.addCleanup(log.close, 0)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        return model_manager.Progress(log, entry_for(b"x" * 1000), clock=clock)

    def test_speed_is_measured_over_a_recent_window(self):
        times = iter([0.0, 1.0, 2.0, 30.0, 31.0])
        progress = self.progress(lambda: next(times))
        progress.begin(0, "host")
        progress.advance(100)
        progress.advance(200)
        self.assertEqual(progress.bytes_per_second(), 100.0)
        self.assertEqual(progress.seconds_left(200), 8.0)
        progress.advance(210)
        progress.advance(310)
        self.assertEqual(progress.bytes_per_second(), 100.0)

    def test_no_speed_yet_means_no_time_left(self):
        progress = self.progress(lambda: 5.0)
        progress.begin(0, "host")
        self.assertIsNone(progress.seconds_left(0))
        self.assertIn("measuring the speed", progress.describe(0))

class ShippedManifest(unittest.TestCase):

    def setUp(self) -> None:
        self.manifest = model_manager.load_manifest(MANIFEST)

    def test_it_loads(self):
        self.assertEqual(shipped_manifest()["schema"], model_manager.MANIFEST_SCHEMA)
        self.assertTrue(self.manifest.models)

    def test_the_default_cpu_model_is_the_unsloth_q4_k_m_file(self):
        entry = self.manifest.default_for("cpu-standard")
        self.assertEqual(entry.id, "qwen3-4b-q4km")
        self.assertEqual(entry.file, "qwen3-4b-instruct-2507-Q4_K_M.gguf")
        self.assertEqual(entry.size_bytes, UNSLOTH_SIZE)
        self.assertEqual(entry.sha256, UNSLOTH_SHA256)
        self.assertEqual(entry.size_bytes, profiles.GGUF_BYTES)
        self.assertEqual(entry.min_ram_gb, 16)
        self.assertEqual(entry.licence, "Apache-2.0")

    def test_every_cpu_profile_has_a_default_and_no_gpu_profile_does(self):
        for name in profiles.PROFILE_ORDER:
            with self.subTest(name):
                entry = self.manifest.default_for(name)
                if profiles.get(name).runs_vllm:
                    self.assertIsNone(entry)
                else:
                    self.assertIsNotNone(entry)
                    self.assertIn(name, entry.profiles)
        self.assertLessEqual(set(self.manifest.defaults), set(profiles.PROFILES))

    def test_every_mirror_is_https_and_hugging_face_ones_are_pinned_to_a_revision(self):
        for entry in self.manifest.models:
            for url in self.manifest.mirrors_for(entry):
                with self.subTest(url):
                    self.assertTrue(url.startswith("https://"))
                    if "huggingface.co" in url:
                        self.assertRegex(url, PINNED_HF_RESOLVE)

    def test_our_own_storage_has_a_slot_that_adds_a_mirror_per_file(self):
        document = shipped_manifest()
        self.assertIn("mirror_bases", document)
        document["mirror_bases"] = ["https://models.example.org/horus/"]
        manifest = model_manager.parse_manifest(document, MANIFEST)
        entry = manifest.default_for("cpu-standard")
        self.assertEqual(manifest.mirrors_for(entry)[-1],
                         f"https://models.example.org/horus/{entry.file}")
        self.assertEqual(manifest.mirrors_for(entry)[0], entry.mirrors[0])

    def test_the_models_readme_points_at_the_manifest(self):
        readme = MODELS_README.read_text(encoding="utf-8")
        self.assertIn("models/manifest.json", readme)
        self.assertIn(UNSLOTH_SHA256, readme)

    def test_downloaded_files_stay_out_of_git(self):
        ignore = (REPO / "models" / ".gitignore").read_text(encoding="utf-8").split()
        self.assertEqual(ignore[0], "*")
        self.assertIn("!manifest.json", ignore)

class ManifestValidation(unittest.TestCase):

    def assert_rejected(self, change, needle: str) -> None:
        document = copy.deepcopy(shipped_manifest())
        change(document)
        with self.assertRaises(InstallError) as caught:
            model_manager.parse_manifest(document, MANIFEST)
        self.assertEqual(caught.exception.code, EXIT_MODEL_MANIFEST_INVALID)
        self.assertIn(needle, caught.exception.detail)

    def test_an_unknown_schema_is_rejected(self):
        self.assert_rejected(lambda d: d.update(schema=2), "schema")

    def test_a_bad_hash_is_rejected(self):
        self.assert_rejected(lambda d: d["models"][0].update(sha256="ABC"), "sha256")

    def test_a_file_name_cannot_leave_the_models_folder(self):
        self.assert_rejected(lambda d: d["models"][0].update(file="../model.gguf"), "file")

    def test_a_missing_field_is_named(self):
        self.assert_rejected(lambda d: d["models"][0].pop("size_bytes"), "size_bytes")

    def test_a_default_must_name_a_listed_model(self):
        self.assert_rejected(lambda d: d["defaults"].update({"cpu-standard": "nope"}), "nope")

    def test_a_default_must_be_a_model_meant_for_that_profile(self):
        self.assert_rejected(lambda d: d["defaults"].update({"gpu-8g": "qwen3-4b-q4km"}),
                             "gpu-8g")

    def test_a_model_needs_somewhere_to_download_it_from(self):
        self.assert_rejected(lambda d: d["models"][0].update(mirrors=[]), "no mirror")

    def test_mirrors_must_be_urls(self):
        self.assert_rejected(lambda d: d["models"][0].update(mirrors=["ftp://x/y"]), "mirrors")

    def test_ids_must_be_unique(self):
        self.assert_rejected(lambda d: d["models"].append(dict(d["models"][0])), "unique")

    def test_a_file_that_is_not_json_is_reported(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "manifest.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(InstallError) as caught:
                model_manager.load_manifest(path)
        self.assertEqual(caught.exception.code, EXIT_MODEL_MANIFEST_INVALID)
        self.assertIn("not valid JSON", caught.exception.detail)

class Plans(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self.infra = self.repo / "src" / "infra"
        self.infra.mkdir(parents=True)
        (self.repo / "models").mkdir()
        shutil.copy(MANIFEST, self.repo / "models" / "manifest.json")

    def test_a_cpu_profile_downloads_its_default_into_the_models_folder(self):
        plan = model_manager.plan_for_profile(self.repo, "cpu-standard")
        self.assertEqual(plan.models_dir, self.repo / "models")
        env = plan.env(self.repo)
        self.assertEqual(env["HORUS_MODELS_DIR"], "../../models")
        self.assertEqual(env["LLM_GGUF_FILE"], "qwen3-4b-instruct-2507-Q4_K_M.gguf")
        self.assertEqual(env["LLM_GGUF_SHA256"], UNSLOTH_SHA256)
        self.assertEqual(env["LLM_GGUF_SIZE"], str(UNSLOTH_SIZE))
        self.assertEqual(env["LLM_GGUF_URL"], plan.mirrors[0])
        self.assertEqual(set(env), set(model_manager.MODEL_ENV_KEYS))
        self.assertEqual((self.infra / env["HORUS_MODELS_DIR"]).resolve(),
                         plan.models_dir.resolve())

    def test_another_models_folder_is_written_as_an_absolute_path(self):
        elsewhere = self.repo / "elsewhere"
        plan = model_manager.plan_for_profile(self.repo, "cpu-lean", elsewhere)
        written = plan.env(self.repo)["HORUS_MODELS_DIR"]
        self.assertNotIn("\\", written)
        self.assertEqual(Path(written), elsewhere.resolve())

    def test_a_gpu_profile_has_no_model_file(self):
        self.assertIsNone(model_manager.plan_for_profile(self.repo, "gpu-8g"))

    def test_the_model_keys_are_managed_so_a_gpu_reinstall_deactivates_them(self):
        self.assertLessEqual(set(model_manager.MODEL_ENV_KEYS), set(profiles.MANAGED_KEYS))

    def test_an_installed_stack_downloads_what_its_env_names(self):
        manifest = model_manager.load_manifest(self.repo / "models" / "manifest.json")
        values = model_manager.plan_for_profile(self.repo, "cpu-standard").env(self.repo)
        values["LLM_GGUF_URL"] = "https://models.example.org/q.gguf"
        plan = model_manager.plan_from_env(values, self.infra, manifest)
        self.assertEqual(plan.entry.id, "qwen3-4b-q4km")
        self.assertEqual(plan.mirrors[0], "https://models.example.org/q.gguf")
        self.assertIn(manifest.default_for("cpu-standard").mirrors[0], plan.mirrors)
        self.assertEqual(plan.models_dir, (self.repo / "models").resolve())

    def test_a_file_the_manifest_does_not_know_uses_the_env_url_only(self):
        elsewhere = (self.repo / "elsewhere").resolve()
        values = {"LLM_GGUF_FILE": "own.gguf", "LLM_GGUF_SHA256": "a" * 64,
                  "LLM_GGUF_SIZE": "42", "LLM_GGUF_URL": "https://models.example.org/own.gguf",
                  "HORUS_MODELS_DIR": elsewhere.as_posix()}
        plan = model_manager.plan_from_env(values, self.infra, None)
        self.assertEqual(plan.entry.file, "own.gguf")
        self.assertEqual(plan.mirrors, ("https://models.example.org/own.gguf",))
        self.assertEqual(plan.models_dir, elsewhere)

    def test_an_env_without_a_usable_model_names_none(self):
        self.assertIsNone(model_manager.plan_from_env({}, self.infra, None))
        values = {"LLM_GGUF_FILE": "../x.gguf", "LLM_GGUF_SHA256": "a" * 64,
                  "LLM_GGUF_SIZE": "42"}
        self.assertIsNone(model_manager.plan_from_env(values, self.infra, None))

    def dry_run(self, *argv: str) -> str:
        args = horus_install.build_parser().parse_args(["--dry-run", *argv])
        log = Log(self.repo / "install-log.txt")
        self.addCleanup(log.close, 0)
        out = io.StringIO()
        with mock.patch.object(horus_install, "find_repo", return_value=self.repo), \
                contextlib.redirect_stdout(out):
            self.assertEqual(horus_install._dispatch(log, args), horus_install.EXIT_OK)
        return out.getvalue()

    def test_the_dry_run_names_the_model_of_a_cpu_machine(self):
        out = self.dry_run("--simulate", "linux-cpu-16gb")
        self.assertIn("model    : qwen3-4b-q4km, 2.3 GB", out)
        self.assertIn(f"LLM_GGUF_SHA256={UNSLOTH_SHA256}", out)
        self.assertIn("HORUS_MODELS_DIR=../../models", out)

    def test_the_dry_run_of_a_machine_too_small_names_no_model(self):
        out = self.dry_run("--simulate", "linux-cpu-8gb")
        self.assertIn("not supported", out)
        self.assertNotIn("model    :", out)
        self.assertNotIn("LLM_GGUF_", out)

    def test_a_forced_profile_on_a_small_machine_is_warned_but_still_gets_its_model(self):
        out = self.dry_run("--simulate", "linux-cpu-8gb", "--profile", "cpu-lean")
        self.assertIn("forces a profile this machine is not supported for", out)
        self.assertIn("model    : qwen3-4b-q4km, 2.3 GB", out)

    def test_the_dry_run_keeps_the_models_folder_an_earlier_install_chose(self):
        elsewhere = (self.repo / "elsewhere").resolve()
        (self.infra / ".env").write_text(f"HORUS_MODELS_DIR={elsewhere.as_posix()}\n",
                                         encoding="utf-8")
        out = self.dry_run("--simulate", "linux-cpu-16gb")
        self.assertIn(f"Keeping the models folder chosen before: {elsewhere}", out)
        self.assertIn(f"HORUS_MODELS_DIR={elsewhere.as_posix()}", out)
        self.assertIn(f"into {elsewhere}", out)

    def test_a_models_folder_set_aside_by_a_gpu_install_is_not_reused(self):
        elsewhere = (self.repo / "elsewhere").resolve()
        (self.infra / ".env").write_text(
            f"{horus_install.UNSET_MARKER}HORUS_MODELS_DIR={elsewhere.as_posix()}\n",
            encoding="utf-8")
        out = self.dry_run("--simulate", "linux-cpu-16gb")
        self.assertIn("HORUS_MODELS_DIR=../../models", out)
        self.assertNotIn("Keeping the models folder", out)

    def test_the_dry_run_of_a_gpu_profile_names_no_model_file(self):
        out = self.dry_run("--simulate", "nvidia-8gb")
        self.assertNotIn("model    :", out)
        self.assertNotIn("LLM_GGUF_", out)

    def test_both_cpu_profiles_download_the_same_model(self):
        manifest = model_manager.load_manifest(MANIFEST)
        self.assertEqual(manifest.default_for("cpu-lean"), manifest.default_for("cpu-standard"))

class InstalledStackChecksItsModel(DownloadCase):

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.tmp / "repo"
        self.infra = self.repo / "src" / "infra"
        self.infra.mkdir(parents=True)
        opener = mock.patch.object(model_manager.urllib.request, "build_opener",
                                   side_effect=lambda *handlers: direct_opener())
        opener.start()
        self.addCleanup(opener.stop)

    def write_env(self, compose_file: str, url: str) -> None:
        entry = entry_for(self.payload, url)
        lines = [
            f"COMPOSE_FILE={compose_file}",
            f"HORUS_MODELS_DIR={self.models.as_posix()}",
            f"LLM_GGUF_FILE={entry.file}",
            f"LLM_GGUF_URL={url}",
            f"LLM_GGUF_SHA256={entry.sha256}",
            f"LLM_GGUF_SIZE={entry.size_bytes}",
        ]
        (self.infra / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def check(self) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            horus_install.ensure_installed_model(self.log, self.infra)
        return out.getvalue()

    def test_a_cpu_stack_fetches_a_missing_model_before_it_starts(self):
        script, url = self.mirrors.add("a", self.payload)
        self.write_env(f"docker-compose.yml:{profiles.CPU_OVERLAY}", url)
        out = self.check()
        self.assert_in_place()
        self.assertEqual(script.requests, 1)
        self.assertIn("Checking the language model", out)
        self.assertTrue(read_events(self.events))

    def test_a_cpu_stack_resumes_a_download_the_install_left_half_done(self):
        script, url = self.mirrors.add("a", self.payload)
        self.write_env(f"docker-compose.yml:{profiles.CPU_OVERLAY}", url)
        self.models.mkdir()
        self.part.write_bytes(self.payload[: self.half])
        self.check()
        self.assert_in_place()
        self.assertEqual(script.ranges, [f"bytes={self.half}-"])

    def test_a_gpu_stack_downloads_nothing(self):
        script, url = self.mirrors.add("a", self.payload)
        self.write_env("docker-compose.yml", url)
        self.check()
        self.assertEqual(script.requests, 0)
        self.assertFalse(self.models.exists())

    def test_start_checks_the_model_before_docker_starts_anything(self):
        order: list[str] = []
        (self.infra / ".env").write_text("COMPOSE_FILE=docker-compose.yml\n", encoding="utf-8")
        with contextlib.ExitStack() as stack:
            patch = stack.enter_context
            patch(mock.patch.object(horus_install, "_require_docker"))
            patch(mock.patch.object(horus_install, "wait_for_health"))
            patch(mock.patch.object(horus_install, "ensure_installed_model",
                                    side_effect=lambda *a: order.append("model")))
            patch(mock.patch.object(horus_install, "_stream",
                                    side_effect=lambda cmd, *a, **k: order.append(cmd[2]) or 0))
            patch(contextlib.redirect_stdout(io.StringIO()))
            code = horus_install.do_start(self.log, self.infra, timeout=60)
        self.assertEqual(code, horus_install.EXIT_OK)
        self.assertEqual(order, ["model", "up"])

    def test_llm_is_stopped_before_a_model_file_it_may_hold_open_is_replaced(self):
        script, url = self.mirrors.add("a", self.payload)
        self.write_env(f"docker-compose.yml:{profiles.CPU_OVERLAY}", url)
        self.models.mkdir()
        self.target.write_bytes(damaged(self.payload))
        calls: list[tuple[str, bool]] = []

        def docker(cmd, *args, **kwargs) -> int:
            calls.append((" ".join(cmd[2:]), self.target.read_bytes() == self.payload))
            return 0

        with contextlib.ExitStack() as stack:
            patch = stack.enter_context
            patch(mock.patch.object(horus_install, "_require_docker"))
            patch(mock.patch.object(horus_install, "wait_for_health"))
            patch(mock.patch.object(horus_install, "_stream", side_effect=docker))
            patch(contextlib.redirect_stdout(io.StringIO()))
            code = horus_install.do_restart(self.log, self.infra, timeout=60)
        self.assertEqual(code, horus_install.EXIT_OK)
        self.assertEqual(calls, [(f"stop {profiles.CPU_MODEL_SERVER}", False), ("restart", True)])
        self.assert_in_place()
        self.assertEqual(script.requests, 1)

    def test_a_missing_or_checked_model_leaves_llm_running(self):
        script, url = self.mirrors.add("a", self.payload)
        self.write_env(f"docker-compose.yml:{profiles.CPU_OVERLAY}", url)
        with mock.patch.object(horus_install, "_stream") as docker:
            self.check()
            self.check()
        docker.assert_not_called()
        self.assert_in_place()
        self.assertEqual(script.requests, 1)

    def serve_the_manifest_model(self, url: str) -> str:
        (self.repo / "models").mkdir(exist_ok=True)
        document = shipped_manifest()
        document["models"][0].update(size_bytes=len(self.payload), mirrors=[url],
                                     sha256=hashlib.sha256(self.payload).hexdigest())
        (self.repo / "models" / "manifest.json").write_text(json.dumps(document),
                                                            encoding="utf-8")
        return document["models"][0]["file"]

    def run_installer(self, *argv: str) -> str:
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            patch = stack.enter_context
            patch(mock.patch.object(horus_install, "find_repo", return_value=self.repo))
            patch(mock.patch.object(horus_install, "banner"))
            patch(mock.patch.object(horus_install, "preflight"))
            consent = patch(mock.patch.object(horus_install, "consent"))
            consent.choose.return_value = {"corpus_dir": "../../demo_assets"}
            hardware = patch(mock.patch.object(horus_install, "hardware"))
            hardware.probe.return_value = dict(horus_install.SIMULATIONS["nvidia-16gb"])
            patch(mock.patch.object(
                horus_install, "pull_and_build",
                side_effect=lambda *args, before_start=None, **kwargs: before_start()))
            patch(mock.patch.object(horus_install, "wait_for_health"))
            patch(mock.patch.object(horus_install, "wait_for_reindex"))
            patch(mock.patch.object(horus_install, "_success"))
            patch(contextlib.redirect_stdout(out))
            code = horus_install._dispatch(self.log, horus_install.build_parser().parse_args(
                list(argv)))
        self.assertEqual(code, horus_install.EXIT_OK)
        return out.getvalue()

    def installed_env(self) -> dict[str, str]:
        return horus_install.smoke.read_env(self.infra / ".env")

    def test_a_reinstall_without_the_option_keeps_the_models_folder_chosen_before(self):
        script, url = self.mirrors.add("a", self.payload)
        file = self.serve_the_manifest_model(url)
        (self.infra / ".env").write_text("JWT_SECRET_KEY=test\n", encoding="utf-8")
        install = ["--profile", "cpu-standard", "--non-interactive", "--skip-smoke"]

        self.run_installer(*install, "--models-dir", str(self.models))
        chosen = self.installed_env()["HORUS_MODELS_DIR"]
        self.assertEqual(chosen, self.models.resolve().as_posix())
        self.assertEqual((self.models / file).read_bytes(), self.payload)

        out = self.run_installer(*install)
        self.assertIn(f"Keeping the models folder chosen before: {self.models.resolve()}", out)
        self.assertEqual(self.installed_env()["HORUS_MODELS_DIR"], chosen)
        self.assertIn("verified before", out)
        self.assertEqual(script.requests, 1)
        self.assertEqual(sorted(path.name for path in (self.repo / "models").iterdir()),
                         ["manifest.json"])

    def test_the_command_line_fetches_the_model_into_the_folder_the_stack_mounts(self):
        _script, url = self.mirrors.add("a", self.payload)
        file = self.serve_the_manifest_model(url)
        (self.infra / ".env").write_text(f"HORUS_MODELS_DIR={self.models.as_posix()}\n",
                                         encoding="utf-8")
        self.run_installer("--download-model")
        self.assertEqual((self.models / file).read_bytes(), self.payload)
        self.assertFalse((self.repo / "models" / file).exists())

    def test_the_command_line_can_fetch_the_model_alone(self):
        _script, url = self.mirrors.add("a", self.payload)
        file = self.serve_the_manifest_model(url)
        args = horus_install.build_parser().parse_args(
            ["--download-model", "--models-dir", str(self.models)])
        with mock.patch.object(horus_install, "find_repo", return_value=self.repo), \
                contextlib.redirect_stdout(io.StringIO()):
            code = horus_install._dispatch(self.log, args)
        self.assertEqual(code, horus_install.EXIT_OK)
        downloaded = self.models / file
        self.assertEqual(downloaded.read_bytes(), self.payload)

if __name__ == "__main__":
    unittest.main()
