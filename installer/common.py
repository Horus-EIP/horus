from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "0.1.0"

EXIT_OK = 0
EXIT_USAGE = 2

EXIT_PYTHON_TOO_OLD = 10
EXIT_DOCKER_NOT_FOUND = 11
EXIT_DOCKER_DAEMON_DOWN = 12
EXIT_COMPOSE_MISSING = 13
EXIT_DISK_SPACE = 14
EXIT_NETWORK = 15
EXIT_PORTS_BUSY = 16
EXIT_REPO_NOT_FOUND = 17
EXIT_NOT_INSTALLED = 18

EXIT_CONSENT_CANCELLED = 20

EXIT_PROFILE_UNKNOWN = 30
EXIT_NO_USABLE_GPU_FOR_PROFILE = 31

EXIT_ENV_WRITE_FAILED = 40
EXIT_COMPOSE_PULL_FAILED = 41
EXIT_COMPOSE_UP_FAILED = 42
EXIT_HEALTH_TIMEOUT = 43

EXIT_SMOKE_FAILED = 50

EXIT_UNINSTALL_FAILED = 60

EXIT_INTERRUPTED = 130

_EXIT_NAMES = {
    v: k for k, v in list(globals().items()) if k.startswith("EXIT_") and isinstance(v, int)
}

def exit_name(code: int) -> str:
    return _EXIT_NAMES.get(code, "EXIT_UNKNOWN")

def _enable_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

_enable_utf8_console()

def _supports_colour() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32" and not os.environ.get("WT_SESSION"):
        return False
    return True

_COLOUR = _supports_colour()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text

def bold(t: str) -> str:
    return _c("1", t)

def green(t: str) -> str:
    return _c("32", t)

def yellow(t: str) -> str:
    return _c("33", t)

def red(t: str) -> str:
    return _c("31", t)

def dim(t: str) -> str:
    return _c("2", t)

def rule(title: str = "") -> str:
    width = 72
    if not title:
        return "-" * width
    return "-- " + title + " " + "-" * max(0, width - len(title) - 4)

EVENT_PREFIX = "@@HORUS "

class Events:

    def __init__(self, enabled: bool = False, stream=None):
        self.enabled = bool(enabled)
        self._stream = stream if stream is not None else sys.stderr

    def emit(self, event: str, **fields) -> None:
        if not self.enabled:
            return
        payload = {"event": event}
        payload.update(fields)
        try:
            line = EVENT_PREFIX + json.dumps(payload, default=str, sort_keys=True)
        except (TypeError, ValueError):  # pragma: no cover - default=str covers it
            return
        try:
            print(line, file=self._stream, flush=True)
        except (OSError, ValueError):
            pass

class Log:

    def __init__(self, path: Path, events: "Events | None" = None):
        self.path = path
        self.events = events if events is not None else Events(False)
        self._fh = None
        self._closed = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a", encoding="utf-8", errors="replace")
        except OSError as exc:  # pragma: no cover - unwritable target dir
            print(f"WARNING: cannot write {self.path}: {exc}", file=sys.stderr)
        self.write_raw("")
        self.write_raw("=" * 72)
        self.info(f"Horus beta installer {VERSION} starting")
        self.info(f"python  {sys.version.split()[0]} ({sys.executable})")
        self.info(f"platform {sys.platform} / {os.name}")
        self.info(f"cwd     {Path.cwd()}")

    @staticmethod
    def _stamp() -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def write_raw(self, line: str) -> None:
        if self._fh:
            try:
                self._fh.write(line + "\n")
                self._fh.flush()
            except (OSError, ValueError):
                pass

    def _log(self, level: str, msg: str) -> None:
        self.write_raw(f"{self._stamp()}  {level:<7} {msg}")

    def debug(self, msg: str) -> None:
        self._log("DEBUG", msg)

    def info(self, msg: str) -> None:
        self._log("INFO", msg)

    def say(self, msg: str = "") -> None:
        print(msg)
        plain = _strip_ansi(msg)
        self._log("INFO", plain)
        self.events.emit("say", text=plain)

    def ok(self, msg: str) -> None:
        print("  " + green("[ok]") + "   " + msg)
        self._log("OK", msg)
        self.events.emit("ok", text=_strip_ansi(msg))

    def warn(self, msg: str) -> None:
        print("  " + yellow("[warn]") + " " + msg)
        self._log("WARN", msg)
        self.events.emit("warn", text=_strip_ansi(msg))

    def fail(self, msg: str) -> None:
        print("  " + red("[FAIL]") + " " + msg)
        self._log("FAIL", msg)
        self.events.emit("fail", text=_strip_ansi(msg))

    def step(self, msg: str) -> None:
        print()
        print(bold(msg))
        self._log("STEP", msg)
        self.events.emit("step", text=_strip_ansi(msg))

    def close(self, code: int) -> None:
        if self._closed:
            return
        self._closed = True
        self._log("EXIT", f"{code} ({exit_name(code)})")
        self.events.emit("exit", code=code, name=exit_name(code))
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

def _strip_ansi(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        if text[i] == "\033":
            j = text.find("m", i)
            if j == -1:
                break
            i = j + 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)

class InstallError(Exception):

    def __init__(self, code: int, headline: str, detail: str = "", fix: str = ""):
        super().__init__(headline)
        self.code = code
        self.headline = headline
        self.detail = detail
        self.fix = fix

    def report(self, log: Log) -> None:
        log.say("")
        log.say(red("=" * 72))
        log.say(red("INSTALL STOPPED: " + self.headline))
        log.say(red("=" * 72))
        if self.detail:
            log.say("")
            for line in self.detail.strip().splitlines():
                log.say("  " + line)
        if self.fix:
            log.say("")
            log.say(bold("  What to do:"))
            for line in self.fix.strip().splitlines():
                log.say("    " + line)
        log.say("")
        log.say(f"  Full log: {log.path}")
        log.say(f"  Exit code {self.code} ({exit_name(self.code)})")
        log.say("")

class Result:
    __slots__ = ("code", "out", "err", "timed_out")

    def __init__(self, code: int, out: str, err: str, timed_out: bool = False):
        self.code = code
        self.out = out
        self.err = err
        self.timed_out = timed_out

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out

    def first_line(self) -> str:
        for chunk in (self.out, self.err):
            for line in chunk.splitlines():
                if line.strip():
                    return line.strip()
        return ""

def run(
    cmd: list[str],
    log: Log,
    timeout: int = 60,
    cwd: Path | None = None,
    env: dict | None = None,
) -> Result:
    log.debug(f"$ {' '.join(cmd)}" + (f"   (cwd={cwd})" if cwd else ""))
    merged = None
    if env:
        merged = os.environ.copy()
        merged.update(env)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            env=merged,
        )
    except FileNotFoundError:
        log.debug(f"  -> executable not found: {cmd[0]}")
        return Result(127, "", f"{cmd[0]}: not found")
    except subprocess.TimeoutExpired:
        log.debug(f"  -> TIMEOUT after {timeout}s")
        return Result(124, "", f"timed out after {timeout}s", timed_out=True)
    except OSError as exc:
        log.debug(f"  -> OSError: {exc}")
        return Result(126, "", str(exc))

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    log.debug(f"  -> exit {proc.returncode}")
    for label, blob in (("stdout", out), ("stderr", err)):
        if blob:
            for line in blob.splitlines()[:20]:
                log.debug(f"  {label}: {line}")
    return Result(proc.returncode, out, err)

def have(executable: str) -> bool:
    return shutil.which(executable) is not None

INSTALLER_DIR = Path(__file__).resolve().parent
BUNDLE_DIR = INSTALLER_DIR.parent

def find_repo(explicit: str | None = None) -> Path:
    marker = Path("src") / "infra" / "docker-compose.yml"
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    candidates.append(BUNDLE_DIR / "horus")
    candidates.append(BUNDLE_DIR)
    here = Path.cwd().resolve()
    candidates.extend([here] + list(here.parents))

    seen = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        if (cand / marker).is_file():
            return cand

    raise InstallError(
        EXIT_REPO_NOT_FOUND,
        "Could not find the Horus source tree.",
        "The installer looks for src/infra/docker-compose.yml next to itself\n"
        "(in a horus/ folder), and then upwards from the current directory.\n"
        f"Searched from: {BUNDLE_DIR}",
        "Re-extract the ZIP without moving files out of it, then run the\n"
        "START-HERE launcher for your platform again.\n"
        "Or pass the path explicitly:  --repo /path/to/horus",
    )

def infra_dir(repo: Path) -> Path:
    return repo / "src" / "infra"

def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"

def elapsed(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
