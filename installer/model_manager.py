from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from common import (
    EXIT_DISK_SPACE,
    EXIT_MODEL_DOWNLOAD_FAILED,
    EXIT_MODEL_HASH_MISMATCH,
    EXIT_MODEL_MANIFEST_INVALID,
    VERSION,
    InstallError,
    Log,
    elapsed,
    human_bytes,
)

MANIFEST_SCHEMA = 1
MANIFEST_RELATIVE_PATH = Path("models") / "manifest.json"
MODELS_RELATIVE_DIR = Path("models")
COMPOSE_DEFAULT_MODELS_DIR = "../../models"

MODEL_ENV_KEYS: tuple[str, ...] = (
    "HORUS_MODELS_DIR", "LLM_GGUF_FILE", "LLM_GGUF_URL", "LLM_GGUF_SHA256", "LLM_GGUF_SIZE",
)

REQUIRED_FIELDS = (
    "id", "version", "file", "size_bytes", "sha256", "min_ram_gb", "profiles", "mirrors",
)

PARTIAL_SUFFIX = ".part"
VERIFIED_SUFFIX = ".sha256"

FAILURES_BEFORE_NEXT_MIRROR = 3
FAILURES_ON_THE_LAST_MIRROR = 6
BACKOFF_SECONDS = 10
CHUNK_BYTES = 1024 * 1024
READ_TIMEOUT_SECONDS = 60
EVENT_EVERY_SECONDS = 0.5
LINE_EVERY_SECONDS = 15.0
SPEED_WINDOW_SECONDS = 10.0
DISK_HEADROOM_BYTES = 1024 ** 3
TOKEN_HOSTS = ("huggingface.co",)
RETRYABLE_CLIENT_ERRORS = frozenset({408, 425, 429})

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+|\*)$")

@dataclass(frozen=True)
class ModelEntry:
    id: str
    version: str
    file: str
    size_bytes: int
    sha256: str
    min_ram_gb: float
    profiles: tuple[str, ...]
    mirrors: tuple[str, ...]
    licence: str = ""
    source: str = ""

@dataclass(frozen=True)
class Manifest:
    path: Path
    models: tuple[ModelEntry, ...]
    defaults: dict[str, str]
    mirror_bases: tuple[str, ...] = ()

    def by_id(self, model_id: str) -> ModelEntry | None:
        return next((entry for entry in self.models if entry.id == model_id), None)

    def by_sha256(self, digest: str) -> ModelEntry | None:
        return next((entry for entry in self.models if entry.sha256 == digest), None)

    def default_for(self, profile: str) -> ModelEntry | None:
        model_id = self.defaults.get(profile)
        return self.by_id(model_id) if model_id else None

    def mirrors_for(self, entry: ModelEntry) -> tuple[str, ...]:
        from_bases = [base.rstrip("/") + "/" + entry.file for base in self.mirror_bases]
        return tuple(dict.fromkeys([*entry.mirrors, *from_bases]))

def _invalid(path: Path, problem: str) -> InstallError:
    return InstallError(
        EXIT_MODEL_MANIFEST_INVALID,
        "The model manifest is not valid.",
        f"{path}\n{problem}",
        "The manifest ships with Horus. If it was edited by accident, extract\n"
        "it again from the ZIP; otherwise fix the entry named above.",
    )

def _is_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parts = urllib.parse.urlparse(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc)

def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

def _is_bare_file_name(value: object) -> bool:
    return (isinstance(value, str) and bool(value) and value not in (".", "..")
            and not value.startswith(".") and "/" not in value and "\\" not in value)

def _entry(item: object, index: int, path: Path) -> ModelEntry:
    if not isinstance(item, dict):
        raise _invalid(path, f"models[{index}] must be an object")
    where = f"models[{index}] ({item.get('id') or 'no id'})"
    missing = [name for name in REQUIRED_FIELDS if name not in item]
    if missing:
        raise _invalid(path, f"{where} lacks {', '.join(missing)}")
    for name in ("id", "version"):
        if not isinstance(item[name], str) or not item[name].strip():
            raise _invalid(path, f"{where}: {name} must be a non-empty string")
    if not _is_bare_file_name(item["file"]):
        raise _invalid(path, f"{where}: file must be a plain file name, found {item['file']!r}")
    size = item["size_bytes"]
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise _invalid(path, f"{where}: size_bytes must be a positive whole number")
    if not isinstance(item["sha256"], str) or not SHA256_HEX.match(item["sha256"]):
        raise _invalid(path, f"{where}: sha256 must be 64 lower-case hexadecimal characters")
    if not _is_number(item["min_ram_gb"]) or item["min_ram_gb"] < 0:
        raise _invalid(path, f"{where}: min_ram_gb must be a number")
    profiles = item["profiles"]
    if not isinstance(profiles, list) or not all(isinstance(p, str) and p for p in profiles):
        raise _invalid(path, f"{where}: profiles must be a list of profile names")
    mirrors = item["mirrors"]
    if not isinstance(mirrors, list) or not all(_is_url(url) for url in mirrors):
        raise _invalid(path, f"{where}: mirrors must be a list of http(s) URLs")
    return ModelEntry(
        id=item["id"], version=item["version"], file=item["file"], size_bytes=size,
        sha256=item["sha256"], min_ram_gb=item["min_ram_gb"], profiles=tuple(profiles),
        mirrors=tuple(mirrors), licence=str(item.get("licence", "")),
        source=str(item.get("source", "")),
    )

def parse_manifest(document: object, path: Path) -> Manifest:
    if not isinstance(document, dict):
        raise _invalid(path, "the top level must be an object")
    if document.get("schema") != MANIFEST_SCHEMA:
        raise _invalid(path, f"schema must be {MANIFEST_SCHEMA}, found {document.get('schema')!r}")
    raw_models = document.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise _invalid(path, "models must be a non-empty list")
    models = tuple(_entry(item, index, path) for index, item in enumerate(raw_models))
    ids = [entry.id for entry in models]
    repeated = sorted({model_id for model_id in ids if ids.count(model_id) > 1})
    if repeated:
        raise _invalid(path, f"model ids must be unique: {', '.join(repeated)}")
    bases = document.get("mirror_bases", [])
    if not isinstance(bases, list) or not all(_is_url(base) for base in bases):
        raise _invalid(path, "mirror_bases must be a list of http(s) URLs")
    defaults = document.get("defaults", {})
    if not isinstance(defaults, dict):
        raise _invalid(path, "defaults must map a profile name to a model id")
    manifest = Manifest(path=path, models=models, defaults=dict(defaults),
                        mirror_bases=tuple(bases))
    for profile, model_id in defaults.items():
        entry = manifest.by_id(model_id) if isinstance(model_id, str) else None
        if entry is None:
            raise _invalid(path, f"defaults: {profile} names {model_id!r}, which is not in models")
        if profile not in entry.profiles:
            raise _invalid(path, f"defaults: {profile} names {model_id}, whose profiles "
                                 f"do not include {profile}")
    for entry in models:
        if not manifest.mirrors_for(entry):
            raise _invalid(path, f"{entry.id} has no mirror to download it from")
    return manifest

def load_manifest(path: Path) -> Manifest:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise _invalid(path, f"it could not be read: {exc}") from exc
    except ValueError as exc:
        raise _invalid(path, f"it is not valid JSON: {exc}") from exc
    return parse_manifest(document, path)

def manifest_path(repo: Path) -> Path:
    return repo / MANIFEST_RELATIVE_PATH

def default_models_dir(repo: Path) -> Path:
    return repo / MODELS_RELATIVE_DIR

def compose_models_dir(models_dir: Path, repo: Path) -> str:
    if models_dir.resolve() == default_models_dir(repo).resolve():
        return COMPOSE_DEFAULT_MODELS_DIR
    return str(models_dir.resolve()).replace("\\", "/")

def models_dir_from_env(value: str | None, infra: Path) -> Path:
    path = Path(value or COMPOSE_DEFAULT_MODELS_DIR)
    return path if path.is_absolute() else (infra / path).resolve()

def verified_marker(target: Path) -> Path:
    return target.with_name(target.name + VERIFIED_SUFFIX)

def partial_file(target: Path) -> Path:
    return target.with_name(target.name + PARTIAL_SUFFIX)

def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0

def is_verified(entry: ModelEntry, target: Path) -> bool:
    try:
        recorded = verified_marker(target).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return recorded == entry.sha256 and target.is_file() and _size(target) == entry.size_bytes

def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()

def _write_marker(entry: ModelEntry, target: Path) -> None:
    marker = verified_marker(target)
    staging = marker.with_name(marker.name + ".tmp")
    staging.write_bytes((entry.sha256 + "\n").encode("ascii"))
    os.replace(staging, marker)

def _host(url: str) -> str:
    return urllib.parse.urlparse(url).hostname or url

def build_request(url: str, have: int, token: str | None) -> urllib.request.Request:
    request = urllib.request.Request(url, headers={"User-Agent": f"horus-installer/{VERSION}"})
    if have:
        request.add_header("Range", f"bytes={have}-")
    if token and _host(url) in TOKEN_HOSTS:
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    return request

def _reason(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return f"no data for {READ_TIMEOUT_SECONDS}s"
    if isinstance(exc, urllib.error.URLError):
        return f"cannot reach it ({exc.reason})"
    return str(exc) or type(exc).__name__

def _tried(host: str, reason: str, attempts: int) -> str:
    return f"{host}, {attempts} attempt{'' if attempts == 1 else 's'}: {reason}"

class Progress:

    def __init__(self, log: Log, entry: ModelEntry,
                 clock: Callable[[], float] = time.monotonic):
        self.log = log
        self.entry = entry
        self.clock = clock
        self.samples: deque[tuple[float, int]] = deque()
        self.mirror = ""
        self.resumed_from = 0
        self.last_event = 0.0
        self.last_line = 0.0

    def begin(self, done: int, mirror: str) -> None:
        now = self.clock()
        self.mirror = mirror
        self.resumed_from = done
        self.samples.clear()
        self.samples.append((now, done))
        self.last_line = now
        self._emit(done, now)

    def advance(self, done: int) -> None:
        now = self.clock()
        self.samples.append((now, done))
        while len(self.samples) > 2 and now - self.samples[0][0] > SPEED_WINDOW_SECONDS:
            self.samples.popleft()
        finished = done >= self.entry.size_bytes
        if finished or now - self.last_event >= EVENT_EVERY_SECONDS:
            self._emit(done, now)
        if finished or now - self.last_line >= LINE_EVERY_SECONDS:
            self.last_line = now
            self.log.say("   " + self.describe(done))

    def bytes_per_second(self) -> float:
        (first_time, first_done), (last_time, last_done) = self.samples[0], self.samples[-1]
        if last_time <= first_time:
            return 0.0
        return (last_done - first_done) / (last_time - first_time)

    def seconds_left(self, done: int) -> float | None:
        speed = self.bytes_per_second()
        if speed <= 0:
            return None
        return max(0.0, (self.entry.size_bytes - done) / speed)

    def describe(self, done: int) -> str:
        total = self.entry.size_bytes
        parts = [f"{human_bytes(done)} of {human_bytes(total)} ({100 * done / total:.0f}%)"]
        speed = self.bytes_per_second()
        if speed <= 0:
            parts.append("measuring the speed")
        else:
            parts.append(f"{human_bytes(speed)}/s")
            left = self.seconds_left(done)
            if done < total and left is not None:
                parts.append(f"about {elapsed(left)} left")
        return ", ".join(parts)

    def phase(self, phase: str, text: str, done: int | None = None) -> None:
        total = self.entry.size_bytes
        reached = total if done is None else done
        self.log.events.emit(
            "download", model=self.entry.id, file=self.entry.file, phase=phase,
            done_bytes=reached, total_bytes=total, percent=round(100 * reached / total, 1),
            bytes_per_second=0, seconds_left=None, mirror=self.mirror,
            resumed_from_bytes=self.resumed_from, text=text,
        )

    def _emit(self, done: int, now: float) -> None:
        self.last_event = now
        left = self.seconds_left(done)
        self.log.events.emit(
            "download", model=self.entry.id, file=self.entry.file, phase="downloading",
            done_bytes=done, total_bytes=self.entry.size_bytes,
            percent=round(100 * done / self.entry.size_bytes, 1),
            bytes_per_second=int(self.bytes_per_second()),
            seconds_left=None if left is None else int(left),
            mirror=self.mirror, resumed_from_bytes=self.resumed_from,
            text=self.describe(done),
        )

class _TryAgain(Exception):

    def __init__(self, reason: str, received: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.received = received

class _NextMirror(Exception):
    pass

class ModelDownload:

    def __init__(self, log: Log, entry: ModelEntry, models_dir: Path, mirrors, *,
                 token: str | None = None, opener=None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.log = log
        self.entry = entry
        self.target = Path(models_dir) / entry.file
        self.part = partial_file(self.target)
        self.mirrors = list(dict.fromkeys(mirrors))
        self.token = token or None
        self.opener = opener or urllib.request.build_opener()
        self.sleep = sleep
        self.progress = Progress(log, entry, clock)
        self.resumed = False
        self.mismatch: str | None = None

    def run(self) -> Path:
        entry = self.entry
        if is_verified(entry, self.target):
            self.log.ok(f"{entry.file} is in place and was verified before")
            self.progress.phase("verified", f"{entry.file} is in place")
            return self.target
        try:
            self.target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise self._file_error(exc, self.target.parent) from exc
        if self.target.is_file() and self._adopt_existing():
            return self.target
        self._check_disk()

        problems: list[str] = []
        damaged_last = False
        for index, url in enumerate(self.mirrors):
            outcome = self._from_mirror(url, last=index == len(self.mirrors) - 1)
            if outcome is None:
                return self.target
            problem, damaged_last = outcome
            problems.append(problem)
        raise self._give_up(problems, damaged_last)

    def _from_mirror(self, url: str, last: bool) -> tuple[str, bool] | None:
        host = _host(url)
        allowed = FAILURES_ON_THE_LAST_MIRROR if last else FAILURES_BEFORE_NEXT_MIRROR
        moving_on = "No other mirror is listed." if last else "Trying the next mirror."
        attempts = 0
        failures = 0
        restarted_after_mismatch = False
        while True:
            attempts += 1
            try:
                self._fetch(url)
            except _NextMirror as exc:
                self.log.warn(f"{host}: {exc}. {moving_on}")
                return _tried(host, str(exc), attempts), False
            except _TryAgain as exc:
                failures = 1 if exc.received else failures + 1
                if failures >= allowed:
                    self.log.warn(f"{host}: {exc.reason}. That is {failures} failures in a "
                                  f"row. {moving_on}")
                    return _tried(host, exc.reason, attempts), False
                pause = BACKOFF_SECONDS * failures
                self.log.warn(f"{host}: {exc.reason}. Trying again in {pause}s, from "
                              f"{human_bytes(_size(self.part))}.")
                self.sleep(pause)
                continue
            resumed = self.resumed
            if self._verify():
                return None
            if resumed and not restarted_after_mismatch:
                restarted_after_mismatch = True
                self.log.say("   It was put together from more than one download, so it "
                             "is downloaded once more from the start.")
                continue
            return _tried(host, "the file it serves does not have the expected SHA-256",
                          attempts), True

    def _fetch(self, url: str) -> None:
        size = self.entry.size_bytes
        have = _size(self.part)
        if have > size:
            self._discard_partial()
            have = 0
        if have == size:
            self.resumed = True
            return
        try:
            response = self.opener.open(build_request(url, have, self.token),
                                        timeout=READ_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code == 416:
                self._discard_partial()
                raise _TryAgain("it would not resume this file (HTTP 416), so the "
                                "download starts again") from exc
            if 400 <= exc.code < 500 and exc.code not in RETRYABLE_CLIENT_ERRORS:
                raise _NextMirror(f"HTTP {exc.code} {exc.reason}") from exc
            raise _TryAgain(f"HTTP {exc.code} {exc.reason}") from exc
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
            raise _TryAgain(_reason(exc)) from exc
        with response:
            start = self._start_offset(response, have, _host(url))
            self.progress.begin(start, _host(url))
            if start:
                self.log.say(f"   resuming at {human_bytes(start)} of {human_bytes(size)}")
            self._receive(response, start)

    def _start_offset(self, response, have: int, host: str) -> int:
        size = self.entry.size_bytes
        status = response.status
        if status == 206 and have:
            match = CONTENT_RANGE.match((response.headers.get("Content-Range") or "").strip())
            if match is None:
                raise _TryAgain("it answered a resume without a Content-Range")
            start, total = int(match.group(1)), match.group(3)
            if total != "*" and int(total) != size:
                raise _NextMirror(f"it serves a file of {int(total):,} bytes, the manifest "
                                  f"expects {size:,}")
            if start != have:
                self._discard_partial()
                raise _TryAgain(f"it resumed at byte {start:,} instead of {have:,}, so the "
                                "download starts again")
            self.resumed = True
            return have
        if status == 200:
            length = (response.headers.get("Content-Length") or "").strip()
            if length.isdigit() and int(length) != size:
                raise _NextMirror(f"it serves a file of {int(length):,} bytes, the manifest "
                                  f"expects {size:,}")
            if have:
                self.log.warn(f"{host} cannot resume a download, so it starts again from "
                              "the beginning")
            self._discard_partial()
            return 0
        raise _TryAgain(f"unexpected HTTP {status}")

    def _receive(self, response, start: int) -> None:
        size = self.entry.size_bytes
        done = start
        try:
            handle = open(self.part, "ab")
        except OSError as exc:
            raise self._file_error(exc, self.part) from exc
        with handle:
            while done < size:
                try:
                    block = response.read(min(CHUNK_BYTES, size - done))
                except (OSError, http.client.HTTPException, ValueError) as exc:
                    raise _TryAgain(_reason(exc), done - start) from exc
                if not block:
                    break
                try:
                    handle.write(block)
                except OSError as exc:
                    raise self._file_error(exc, self.part) from exc
                done += len(block)
                self.progress.advance(done)
        if done < size:
            raise _TryAgain(f"the connection closed at {human_bytes(done)} of "
                            f"{human_bytes(size)}", done - start)

    def _verify(self) -> bool:
        entry = self.entry
        self.log.say(f"   checking the SHA-256 of the {human_bytes(entry.size_bytes)} file")
        self.progress.phase("verifying", f"Checking the SHA-256 of {entry.file}")
        actual = sha256_of(self.part)
        if actual == entry.sha256:
            try:
                os.replace(self.part, self.target)
                _write_marker(entry, self.target)
            except OSError as exc:
                raise self._file_error(exc, self.target) from exc
            self.log.ok(f"{entry.file} downloaded, SHA-256 checked")
            self.progress.phase("verified", f"{entry.file} downloaded and checked")
            return True
        self._discard_partial()
        self.mismatch = actual
        self.log.warn(f"The downloaded {entry.file} is damaged: its SHA-256 is {actual}, "
                      f"expected {entry.sha256}. The file was deleted.")
        self.progress.phase("failed", f"The downloaded {entry.file} was damaged and was deleted",
                            done=0)
        return False

    def _adopt_existing(self) -> bool:
        entry = self.entry
        self.log.say(f"   checking the {entry.file} already in {self.target.parent}")
        self.progress.phase("verifying", f"Checking the {entry.file} already here")
        try:
            if _size(self.target) == entry.size_bytes and sha256_of(self.target) == entry.sha256:
                _write_marker(entry, self.target)
                self.log.ok(f"{entry.file} was already here and has the expected SHA-256")
                self.progress.phase("verified", f"{entry.file} is in place")
                return True
            self.log.warn(f"The {entry.file} already in {self.target.parent} is not the "
                          "expected file. It is deleted and downloaded again.")
            self.target.unlink()
            verified_marker(self.target).unlink(missing_ok=True)
        except OSError as exc:
            raise self._file_error(exc, self.target) from exc
        return False

    def _discard_partial(self) -> None:
        self.resumed = False
        try:
            self.part.unlink(missing_ok=True)
        except OSError as exc:
            raise self._file_error(exc, self.part) from exc

    def _check_disk(self) -> None:
        missing = self.entry.size_bytes - min(_size(self.part), self.entry.size_bytes)
        try:
            free = shutil.disk_usage(self.target.parent).free
        except OSError:
            return
        if free >= missing + DISK_HEADROOM_BYTES:
            return
        raise InstallError(
            EXIT_DISK_SPACE,
            "Not enough free disk for the language model.",
            f"{self.entry.file} needs {human_bytes(missing)} more in {self.target.parent},\n"
            f"plus {human_bytes(DISK_HEADROOM_BYTES)} to spare. {human_bytes(free)} is free there.",
            "Free some space and run this again: what was already downloaded is\n"
            "kept. Or keep the model on another disk:\n"
            "  START-HERE (your platform) --models-dir <folder on that disk>\n"
            "Later runs keep using that folder without the option.",
        )

    def _file_error(self, exc: OSError, path: Path) -> InstallError:
        return InstallError(
            EXIT_MODEL_DOWNLOAD_FAILED,
            "The language model file could not be written.",
            f"{path}: {exc}",
            "Check that the folder is writable and the disk is not full, then run\n"
            "this again: what was already downloaded is kept. A file left by the\n"
            "llm-model container on Linux belongs to root; remove it with sudo.\n"
            "To keep the model elsewhere, pass  --models-dir <folder>.",
        )

    def _give_up(self, problems: list[str], damaged_last: bool) -> InstallError:
        entry = self.entry
        tried = "\n  ".join(problems) or "no mirror is listed for it"
        if damaged_last and self.mismatch is not None:
            return InstallError(
                EXIT_MODEL_HASH_MISMATCH,
                "The downloaded language model was damaged, so it was deleted.",
                f"{entry.file}\n  SHA-256 received  {self.mismatch}\n"
                f"  SHA-256 expected  {entry.sha256}\n"
                f"Mirrors tried:\n  {tried}\n"
                "A damaged model would make llama-server fail to start or answer\n"
                "wrongly, so nothing was kept.",
                "Run your START-HERE file again to download it again. If it is\n"
                "damaged twice, the mirror serves a different file than the one\n"
                "Horus expects: send us install-log.txt.",
            )
        have = _size(self.part)
        kept = (f"What arrived is kept in {self.part} ({human_bytes(have)} of "
                f"{human_bytes(entry.size_bytes)}), and the next run resumes from it."
                if have else "Nothing arrived.")
        return InstallError(
            EXIT_MODEL_DOWNLOAD_FAILED,
            "The language model could not be downloaded.",
            f"{entry.file} ({human_bytes(entry.size_bytes)}) was tried from "
            f"{len(problems)} mirror(s):\n  {tried}\n" + kept,
            "This is almost always the network. Check the connection, and the\n"
            "proxy or VPN if you use one (set HTTPS_PROXY before running), then\n"
            "run your START-HERE file again: the download resumes where it stopped.",
        )

@dataclass(frozen=True)
class ModelPlan:
    entry: ModelEntry
    models_dir: Path
    mirrors: tuple[str, ...]

    @property
    def target(self) -> Path:
        return self.models_dir / self.entry.file

    def env(self, repo: Path) -> dict[str, str]:
        return {
            "HORUS_MODELS_DIR": compose_models_dir(self.models_dir, repo),
            "LLM_GGUF_FILE": self.entry.file,
            "LLM_GGUF_URL": self.mirrors[0],
            "LLM_GGUF_SHA256": self.entry.sha256,
            "LLM_GGUF_SIZE": str(self.entry.size_bytes),
        }

    def ensure(self, log: Log, **options) -> Path:
        return ModelDownload(log, self.entry, self.models_dir, self.mirrors, **options).run()

def plan_for_profile(repo: Path, profile: str, models_dir: str | Path | None = None,
                     manifest: Manifest | None = None) -> ModelPlan | None:
    manifest = manifest or load_manifest(manifest_path(repo))
    entry = manifest.default_for(profile)
    if entry is None:
        return None
    folder = Path(models_dir).expanduser().resolve() if models_dir else default_models_dir(repo)
    return ModelPlan(entry, folder, manifest.mirrors_for(entry))

def plan_from_env(values: dict[str, str], infra: Path,
                  manifest: Manifest | None) -> ModelPlan | None:
    file = values.get("LLM_GGUF_FILE", "")
    digest = values.get("LLM_GGUF_SHA256", "").lower()
    size = values.get("LLM_GGUF_SIZE", "")
    url = values.get("LLM_GGUF_URL", "")
    if not _is_bare_file_name(file) or not SHA256_HEX.match(digest) or not size.isdigit():
        return None
    from_env = [url] if _is_url(url) else []
    known = manifest.by_sha256(digest) if manifest else None
    if known is not None and known.file == file and known.size_bytes == int(size):
        entry, mirrors = known, (*from_env, *manifest.mirrors_for(known))
    else:
        entry = ModelEntry(id=file, version="", file=file, size_bytes=int(size), sha256=digest,
                           min_ram_gb=0, profiles=(), mirrors=tuple(from_env))
        mirrors = entry.mirrors
    folder = models_dir_from_env(values.get("HORUS_MODELS_DIR"), infra)
    return ModelPlan(entry, folder, tuple(dict.fromkeys(mirrors)))
