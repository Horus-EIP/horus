from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from common import (
    EXIT_COMPOSE_MISSING,
    EXIT_DISK_SPACE,
    EXIT_DOCKER_DAEMON_DOWN,
    EXIT_DOCKER_NOT_FOUND,
    EXIT_NETWORK,
    EXIT_PORTS_BUSY,
    EXIT_PYTHON_TOO_OLD,
    InstallError,
    Log,
    human_bytes,
    run,
)

MIN_PYTHON = (3, 11)
REQUIRED_FREE_BYTES = 150 * 1024**3
GPU_FREE_BYTES = 125 * 1024**3

DOCKER_DOWNLOAD = {
    "win32": "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe",
    "darwin": "https://www.docker.com/products/docker-desktop/",
    "linux": "https://docs.docker.com/engine/install/",
}

RUNTIME_HOSTS = [
    ("Docker registry", "https://registry-1.docker.io/v2/"),
    ("Docker auth", "https://auth.docker.io/token?service=registry.docker.io"),
    ("Hugging Face (model weights)", "https://huggingface.co/"),
]

SOURCE_BUILD_HOSTS = [
    ("PyPI (Python deps)", "https://pypi.org/simple/"),
    ("PyPI files", "https://files.pythonhosted.org/"),
    ("npm (web client deps)", "https://registry.npmjs.org/"),
    ("Debian apt (image packages)", "https://deb.debian.org/"),
]

REGISTRIES = RUNTIME_HOSTS + SOURCE_BUILD_HOSTS

LAYER_HOSTS = {"ghcr.io": "https://pkg-containers.githubusercontent.com/"}

MODEL_SERVER_IMAGE_KEY = "LLM_SERVER_IMAGE"

DEFAULT_MODEL_SERVER_IMAGE = "ghcr.io/ggml-org/llama.cpp"

COMPOSE_FEATURES: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("gpus: all", (2, 33, 0)),
    ("depends_on with required: false", (2, 20, 2)),
    ("the !reset tag", (2, 18, 0)),
    ("${VAR:+...} interpolation", (2, 8, 0)),
)

MIN_COMPOSE_VERSION = max(version for _feature, version in COMPOSE_FEATURES)

VERSION_NUMBER = re.compile(r"(\d+)\.(\d+)\.(\d+)")

def dotted(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)

def compose_version(text: str) -> tuple[int, int, int] | None:
    match = VERSION_NUMBER.search(text or "")
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch

DOCKER_HUB_NAMES = {"docker.io", "index.docker.io", "registry-1.docker.io"}

def registry_host(image: str) -> str | None:
    first, separator, _rest = image.strip().partition("/")
    names_a_registry = "." in first or ":" in first or first == "localhost"
    if separator and names_a_registry and first not in DOCKER_HUB_NAMES:
        return first
    return None

def model_server_hosts(image: str) -> list[tuple[str, str]]:
    host = registry_host(image)
    if host is None:
        return []
    hosts = [("llama.cpp server image", f"https://{host}/v2/")]
    if host in LAYER_HOSTS:
        hosts.append(("llama.cpp server image layers", LAYER_HOSTS[host]))
    return hosts

def _labelled_once(hosts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    labels: dict[str, list[str]] = {}
    for label, url in hosts:
        names = labels.setdefault(url, [])
        if label not in names:
            names.append(label)
    return [(" and ".join(names), url) for url, names in labels.items()]

def network_hosts(image_registry: str | None,
                  model_server_image: str | None = None) -> list[tuple[str, str]]:
    if not image_registry:
        hosts = list(REGISTRIES)
    else:
        host = image_registry.split("/", 1)[0]
        hosts = [*RUNTIME_HOSTS, ("Horus images", f"https://{host}/v2/")]
        if host in LAYER_HOSTS:
            hosts.append(("Horus image layers", LAYER_HOSTS[host]))
    if model_server_image:
        hosts.extend(model_server_hosts(model_server_image))
    return _labelled_once(hosts)

PORTS = [
    (3000, "HTTPS gateway", None),
    (8000, "mas (API)", None),
    (8001, "agent", None),
    (8080, "knowledge_store", None),
    (18000, "vllm", "VLLM_HOST_PORT"),
    (5432, "postgres", "DB_PORT"),
    (6379, "redis", "REDIS_PORT"),
    (5672, "rabbitmq (AMQP)", "RABBITMQ_PORT"),
    (15672, "rabbitmq (management UI)", None),
    (4317, "tempo (OTLP gRPC)", None),
    (4318, "tempo (OTLP HTTP)", None),
]

def check_python(log: Log) -> None:
    log.step("1/6  Python")
    got = sys.version_info[:3]
    if got < MIN_PYTHON:
        raise InstallError(
            EXIT_PYTHON_TOO_OLD,
            f"Python {'.'.join(map(str, MIN_PYTHON))} or newer is required.",
            f"This interpreter is {'.'.join(map(str, got))} at {sys.executable}.",
            "Install Python 3.11+ from https://www.python.org/downloads/\n"
            "On Windows, tick 'Add python.exe to PATH' in the installer.\n"
            "Then run the START-HERE launcher again.",
        )
    log.ok(f"Python {'.'.join(map(str, got))}")

def _docker_missing_error() -> InstallError:
    url = DOCKER_DOWNLOAD.get(sys.platform, DOCKER_DOWNLOAD["linux"])
    if sys.platform == "win32":
        extra = (
            "1. Download and run Docker Desktop:\n"
            f"     {url}\n"
            "2. It needs administrator rights and a reboot. Let it finish.\n"
            "3. Start Docker Desktop and wait for the whale icon in the system\n"
            "   tray to stop animating.\n"
            "4. Run START-HERE-Windows.bat again."
        )
    elif sys.platform == "darwin":
        extra = (
            "1. Download Docker Desktop for Mac (pick the Apple Silicon or\n"
            f"   Intel build to match your machine):  {url}\n"
            "2. Drag it to Applications and open it once to accept the licence.\n"
            "3. Wait for the whale icon in the menu bar to stop animating.\n"
            "4. Run START-HERE-macOS.command again."
        )
    else:
        extra = (
            "1. Install Docker Engine and the Compose plugin:\n"
            f"     {url}\n"
            "2. Add yourself to the docker group so you do not need sudo:\n"
            "     sudo usermod -aG docker $USER\n"
            "   then log out and back in.\n"
            "3. Run START-HERE-Linux.sh again."
        )
    return InstallError(
        EXIT_DOCKER_NOT_FOUND,
        "Docker is not installed (or not on PATH).",
        "Horus runs entirely in containers, so Docker has to be there first.\n"
        "This installer will not install it for you: Docker Desktop needs\n"
        "administrator rights, a licence acceptance, and usually a reboot.\n"
        "Doing that silently would be rude and would probably half-fail.",
        extra,
    )

def check_docker(log: Log) -> str:
    log.step("2/6  Docker Engine")
    if shutil.which("docker") is None:
        log.fail("docker executable not found on PATH")
        raise _docker_missing_error()

    res = run(["docker", "version", "--format", "{{.Server.Version}}"], log, timeout=45)
    if res.ok and res.out.strip():
        version = res.out.strip().splitlines()[0]
        log.ok(f"Docker Engine {version}")
        return version

    hint = (res.err or res.out or "").strip()
    log.fail("Docker CLI is installed but the daemon did not answer")
    if sys.platform == "win32":
        fix = (
            "Start Docker Desktop from the Start menu and wait for the whale\n"
            "icon in the system tray to stop animating, then run this again.\n"
            "If it never settles, open Docker Desktop > Troubleshoot > Restart."
        )
    elif sys.platform == "darwin":
        fix = (
            "Open Docker Desktop from Applications and wait for the whale icon\n"
            "in the menu bar to stop animating, then run this again."
        )
    else:
        fix = (
            "Start the service:   sudo systemctl start docker\n"
            "If you get a permission error, add yourself to the docker group:\n"
            "  sudo usermod -aG docker $USER   (then log out and back in)"
        )
    raise InstallError(
        EXIT_DOCKER_DAEMON_DOWN,
        "Docker is installed but not running.",
        (f"`docker version` reported:\n  {hint[:500]}" if hint else
         "`docker version` could not reach the daemon."),
        fix,
    )

def _compose_too_old(found: tuple[int, int, int]) -> InstallError:
    width = max(len(feature) for feature, _version in COMPOSE_FEATURES)
    return InstallError(
        EXIT_COMPOSE_MISSING,
        f"Docker Compose {dotted(found)} is too old: Horus needs "
        f"{dotted(MIN_COMPOSE_VERSION)} or newer.",
        "The Horus compose files use these features, and an older Compose\n"
        "rejects or misreads them before any container starts:\n\n  "
        + "\n  ".join(f"{feature:<{width}}  since Compose {dotted(version)}"
                      for feature, version in COMPOSE_FEATURES),
        "Update Docker Desktop: it ships Compose.\n"
        "On Linux update the plugin from Docker's own package repository:\n"
        "  sudo apt-get update && sudo apt-get install docker-compose-plugin\n"
        "  (or see https://docs.docker.com/compose/install/linux/)\n"
        f"Then check that  docker compose version  says {dotted(MIN_COMPOSE_VERSION)} "
        "or newer,\nand run this again.",
    )

def check_compose(log: Log) -> str:
    log.step("3/6  Docker Compose")
    res = run(["docker", "compose", "version"], log, timeout=45)
    if not res.ok:
        raise InstallError(
            EXIT_COMPOSE_MISSING,
            "Docker Compose v2 is not available.",
            "`docker compose version` failed. The old standalone `docker-compose`\n"
            "(with a hyphen) is not enough: this stack uses v2 features.",
            "Docker Desktop ships Compose v2 already, so update Docker Desktop.\n"
            "On Linux install the plugin:\n"
            "  sudo apt-get install docker-compose-plugin\n"
            "  (or see https://docs.docker.com/compose/install/linux/)",
        )
    version = res.first_line() or "unknown"
    found = compose_version(version)
    if found is None:
        log.warn(f"Could not read a version number in {version!r}. Horus needs "
                 f"Compose {dotted(MIN_COMPOSE_VERSION)} or newer; if the stack does "
                 "not start, update Docker.")
        return version
    if found < MIN_COMPOSE_VERSION:
        log.fail(f"{version}  (Horus needs {dotted(MIN_COMPOSE_VERSION)} or newer)")
        raise _compose_too_old(found)
    log.ok(version)
    return version

def _docker_root(log: Log) -> str | None:
    res = run(["docker", "info", "--format", "{{.DockerRootDir}}"], log, timeout=45)
    return res.out.strip() if res.ok and res.out.strip() else None

def _desktop_vm_dir() -> Path | None:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            for sub in ("Docker/wsl/disk", "Docker/wsl", "Docker"):
                cand = Path(local) / sub
                if cand.exists():
                    return cand
            return Path(local)
        return None
    if sys.platform == "darwin":
        cand = Path.home() / "Library/Containers/com.docker.docker/Data"
        return cand if cand.exists() else Path.home()
    return None

def check_disk(log: Log, required: int = REQUIRED_FREE_BYTES, mock: bool = False) -> dict:
    log.step("4/6  Disk space")
    root = _docker_root(log)
    log.debug(f"docker info DockerRootDir = {root!r}")

    measured: Path | None = None
    note = ""
    if root:
        cand = Path(root)
        if cand.exists():
            measured = cand
            note = "Docker data root"
    if measured is None:
        vm = _desktop_vm_dir()
        if vm and vm.exists():
            measured = vm
            note = "Docker Desktop VM disk location on the host"
    if measured is None:
        measured = Path.home()
        note = "home directory (could not locate the Docker data root)"

    try:
        usage = shutil.disk_usage(str(measured))
    except OSError as exc:
        log.warn(f"Could not measure free space at {measured}: {exc}")
        log.warn("Skipping the disk check. If the install fails part-way, "
                 "free up space and retry.")
        return {"checked": False, "path": str(measured), "free_bytes": None}

    free = usage.free
    log.info(f"disk: {note} = {measured}  free={human_bytes(free)} "
             f"total={human_bytes(usage.total)}")
    if free < required and mock:
        raise InstallError(
            EXIT_DISK_SPACE,
            f"Mock AI mode needs {human_bytes(required)} free. "
            f"Found {human_bytes(free)} at {measured}.",
            f"{measured} is the {note}.\n\n"
            f"{human_bytes(required)} is what a mock install used when it was\n"
            "measured, with a margin. See docs/mock-ai.md.",
            "Free up space, then run this again. Docker's own build cache\n"
            "is usually the quickest win, and it is safe to delete:\n"
            "  docker builder prune -f\n"
            "To see what else Docker is holding:\n"
            "  docker system df\n"
            "To go ahead anyway, re-run with  --skip-disk-check",
        )
    if free < required:
        raise InstallError(
            EXIT_DISK_SPACE,
            f"Horus needs {human_bytes(required)} free for a CPU install "
            f"({human_bytes(GPU_FREE_BYTES)} for GPU). "
            f"Found {human_bytes(free)} at {measured}.",
            f"{measured} is the {note}.\n\n"
            f"{human_bytes(required)} is the measured peak while the images\n"
            "build, not a safety margin. It settles to about 130 GB (CPU)\n"
            "or 110 GB (GPU) once the build finishes. See README-FIRST.txt.",
            "Free up space, then run this again. Docker's own build cache\n"
            "is usually the quickest win, and it is safe to delete:\n"
            "  docker builder prune -f\n"
            "To see what else Docker is holding:\n"
            "  docker system df\n"
            "Do NOT use `docker system prune --volumes` if Horus is already\n"
            "installed: that deletes your ingested documents and the models\n"
            "it downloaded, along with the space you were trying to free.\n\n"
            f"On the GPU profile {human_bytes(GPU_FREE_BYTES)} is enough. To go\n"
            "ahead anyway, re-run with  --skip-disk-check",
        )
    log.ok(f"{human_bytes(free)} free at {measured}")
    return {"checked": True, "path": str(measured), "free_bytes": free}

def _reachable(url: str, timeout: float = 8.0) -> tuple[bool, str]:
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "horus-installer")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return True, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return False, str(exc.reason)
    except (TimeoutError, socket.timeout):
        return False, "timed out"
    except Exception as exc:  # noqa: BLE001 - report anything else verbatim
        return False, str(exc)

def check_network(log: Log, hosts: list[tuple[str, str]] | None = None) -> dict:
    log.step("5/6  Network")
    hosts = list(REGISTRIES) if hosts is None else hosts
    downloads = ("container images, Python and npm packages,\nand model weights"
                 if any(entry in hosts for entry in SOURCE_BUILD_HOSTS)
                 else "container images and model\nweights")
    results, failed = {}, []
    for label, url in hosts:
        ok, detail = _reachable(url)
        results[label] = {"url": url, "ok": ok, "detail": detail}
        if ok:
            log.ok(f"{label}  ({detail})")
        else:
            log.fail(f"{label}  -> {detail}")
            failed.append(f"{label}  {url}\n    {detail}")

    if failed:
        raise InstallError(
            EXIT_NETWORK,
            f"Cannot reach {len(failed)} of {len(hosts)} required hosts.",
            f"The installer downloads {downloads}. All of these have to be reachable:\n\n  "
            + "\n  ".join(failed),
            "Check your internet connection.\n"
            "On a corporate network you may need a proxy. Set it before running:\n"
            "  Windows:  set HTTPS_PROXY=http://proxy.example:8080\n"
            "  macOS/Linux:  export HTTPS_PROXY=http://proxy.example:8080\n"
            "and configure the same proxy in Docker Desktop > Settings >\n"
            "Resources > Proxies, because Docker pulls images itself.",
        )
    return results

def _read_env_values(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    try:
        text = env_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values

def _read_env_ports(env_path: Path) -> dict[str, str]:
    return {key: value for key, value in _read_env_values(env_path).items()
            if key.endswith("_PORT")}

def model_server_image(infra: Path) -> str:
    return (os.environ.get(MODEL_SERVER_IMAGE_KEY, "").strip()
            or _read_env_values(infra / ".env").get(MODEL_SERVER_IMAGE_KEY, "")
            or DEFAULT_MODEL_SERVER_IMAGE)

def _port_free(port: int) -> bool:
    for family, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.4)
                if sock.connect_ex((addr, port)) == 0:
                    return False
        except OSError:
            continue
    return True

def _holder(port: int) -> str:
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=20,
                errors="replace",
            ).stdout
            pid = None
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3] == "LISTENING":
                    if parts[1].endswith(f":{port}"):
                        pid = parts[4]
                        break
            if not pid:
                return ""
            tl = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=20, errors="replace",
            ).stdout.strip()
            name = tl.split(",")[0].strip('"') if tl and "," in tl else ""
            return f"{name} (PID {pid})" if name else f"PID {pid}"

        if shutil.which("lsof"):
            out = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fcn"],
                capture_output=True, text=True, timeout=20, errors="replace",
            ).stdout
            names = [ln[1:] for ln in out.splitlines() if ln.startswith("c")]
            if names:
                return names[0]
        if shutil.which("ss"):
            out = subprocess.run(
                ["ss", "-lptnH", f"sport = :{port}"],
                capture_output=True, text=True, timeout=20, errors="replace",
            ).stdout
            m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', out)
            if m:
                return f"{m.group(1)} (PID {m.group(2)})"
    except Exception:  # noqa: BLE001 - diagnostics only, never fatal
        pass
    return ""

def _compose_rows(text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        return [row for row in (parsed if isinstance(parsed, list) else [parsed])
                if isinstance(row, dict)]
    except json.JSONDecodeError:
        pass
    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows

def ports_of_this_install(log: Log, infra: Path) -> set[int]:
    if not (infra / ".env").is_file():
        return set()
    res = run(["docker", "compose", "ps", "--format", "json"], log, timeout=60, cwd=infra,
              log_output=False)
    if not res.ok:
        return set()
    published = set()
    for row in _compose_rows(res.out):
        for publisher in row.get("Publishers") or []:
            port = publisher.get("PublishedPort") if isinstance(publisher, dict) else None
            if isinstance(port, int) and port > 0:
                published.add(port)
    return published

def check_ports(log: Log, infra: Path) -> dict:
    log.step("6/6  Ports")
    env_ports = _read_env_ports(infra / ".env")
    if env_ports:
        log.debug(f"port overrides from .env: {env_ports}")
    ours = ports_of_this_install(log, infra)

    busy, report = [], {}
    for default, service, env_key in PORTS:
        port = default
        if env_key and env_ports.get(env_key, "").isdigit():
            port = int(env_ports[env_key])

        free = _port_free(port)
        report[str(port)] = {"service": service, "free": free}
        if free:
            continue
        if port in ours:
            report[str(port)]["held_by_this_install"] = True
            log.ok(f"port {port} ({service}) is this Horus install's own; "
                   "its container is replaced on start")
            continue
        who = _holder(port)
        report[str(port)]["holder"] = who
        label = f"port {port} ({service})" + (f" held by {who}" if who else " is in use")
        log.fail(label)
        busy.append((port, service, who))

    if busy:
        lines = []
        for port, service, who in busy:
            lines.append(f"{port}  needed by {service}"
                         + (f", currently held by {who}" if who else ""))
        raise InstallError(
            EXIT_PORTS_BUSY,
            f"{len(busy)} port(s) already in use.",
            "Horus publishes these on localhost and cannot start without them:\n\n  "
            + "\n  ".join(lines),
            "Stop whatever is using them and run this again.\n"
            "If it is an older Horus stack, shut it down cleanly:\n"
            "  START-HERE (your platform) --stop\n"
            "If it is another project's containers:\n"
            "  docker ps        then    docker stop <name>",
        )
    required = len(PORTS)
    if any(entry.get("held_by_this_install") for entry in report.values()):
        log.ok(f"all {required} required ports are free or this install's own")
    else:
        log.ok(f"all {required} required ports free")
    return report

def run_engine_checks(log: Log) -> dict:
    check_python(log)
    return {"docker_version": check_docker(log), "compose_version": check_compose(log)}

def run_install_checks(log: Log, infra: Path,
                       skip_disk_check: bool = False,
                       image_registry: str | None = None,
                       cpu_profile: bool = False,
                       mock_free_gib: float | None = None) -> dict:
    summary: dict = {}
    if skip_disk_check:
        log.step("4/6  Disk space")
        log.warn("Skipped with --skip-disk-check. If the build runs out of "
                 "space it will fail part-way through.")
        summary["disk"] = {"checked": False, "path": None,
                           "free_bytes": None, "skipped": True}
    elif mock_free_gib is None:
        summary["disk"] = check_disk(log)
    else:
        summary["disk"] = check_disk(log, int(mock_free_gib * 1024**3), mock=True)
    llama_image = model_server_image(infra) if cpu_profile else None
    summary["network"] = check_network(log, network_hosts(image_registry, llama_image))
    summary["ports"] = check_ports(log, infra)
    log.say("")
    log.say("  " + "Preflight passed.")
    return summary
