#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import consent  # noqa: E402
import hardware  # noqa: E402
import images  # noqa: E402
import model_manager  # noqa: E402
import preflight  # noqa: E402
import profiles  # noqa: E402
import smoke  # noqa: E402
import unsupported  # noqa: E402
from common import (  # noqa: E402
    BUNDLE_DIR,
    EXIT_COMPOSE_PULL_FAILED,
    EXIT_COMPOSE_UP_FAILED,
    EXIT_ENV_WRITE_FAILED,
    EXIT_HEALTH_TIMEOUT,
    EXIT_INTERRUPTED,
    EXIT_MODEL_MANIFEST_INVALID,
    EXIT_NOT_INSTALLED,
    EXIT_OK,
    EXIT_PROFILE_UNKNOWN,
    EXIT_SMOKE_FAILED,
    EXIT_UNINSTALL_FAILED,
    VERSION,
    Events,
    InstallError,
    Log,
    bold,
    dim,
    elapsed,
    find_repo,
    green,
    human_bytes,
    infra_dir,
    red,
    rule,
    run,
    yellow,
)

LOG_PATH = BUNDLE_DIR / "install-log.txt"
PROFILE_JSON = BUNDLE_DIR / "horus-profile.json"

WEB_URL = "http://localhost:3000"

CORE_SERVICES = [
    "postgres", "redis", "rabbitmq", "mas", "agent", "knowledge_store", "web-client",
]

def cpu_overlay_active(infra: Path) -> bool:
    answer = False
    try:
        text = (infra / ".env").read_text(encoding="utf-8")
    except OSError:
        return False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("COMPOSE_FILE="):
            answer = profiles.CPU_OVERLAY in line.split("=", 1)[1]
    return answer

def expected_services(infra: Path) -> list[str]:
    server = profiles.CPU_MODEL_SERVER if cpu_overlay_active(infra) else profiles.GPU_MODEL_SERVER
    return [*CORE_SERVICES, server]

_GIB = 1024 ** 3

def _simulated(system: str, machine: str, cpu_model: str, physical: int,
               logical: int, ram_gib: float, *, gpu_vendor: str | None = None,
               gpu_name: str | None = None, vram_gib: float | None = None,
               docker_gpu: bool = False, wsl: bool = False,
               avx2: bool | None = True) -> dict:
    has_gpu = gpu_name is not None
    docker_gib = ram_gib if system == "Linux" else ram_gib / 2
    return {
        "installer_version": VERSION,
        "timestamp_utc": "simulated",
        "simulated": True,
        "os": {"system": system, "machine": machine, "release": "",
               "platform": system.lower(), "is_wsl": wsl, "is_64bit": True},
        "cpu": {"model": cpu_model, "physical_cores": physical,
                "logical_cores": logical, "count_is_logical_fallback": False,
                "source": "simulated", "avx2": avx2, "avx2_source": "simulated"},
        "memory": {"total_bytes": int(ram_gib * _GIB), "total_gib": float(ram_gib),
                   "source": "simulated"},
        "docker": {"mem_total_bytes": int(docker_gib * _GIB),
                   "mem_total_gib": round(docker_gib, 2), "source": "simulated"},
        "disk": {"path": "(simulated)", "free_bytes": 500 * _GIB,
                 "total_bytes": 1000 * _GIB},
        "gpu": {"vendor": gpu_vendor, "name": gpu_name,
                "vram_bytes": int(vram_gib * _GIB) if vram_gib else None,
                "count": 1 if has_gpu else 0, "source": "simulated"},
        "docker_gpu_test": {"attempted": has_gpu, "usable": docker_gpu if has_gpu else None,
                            "skipped_reason": "" if has_gpu else "no GPU detected",
                            "detail": "simulated"},
        "cuda_usable_in_docker": bool(docker_gpu),
        "gpu_test_ran": has_gpu,
        "notes": ["SIMULATED MACHINE - this is not real hardware"],
    }

SIMULATIONS = {
    "nvidia-8gb": _simulated(
        "Windows", "AMD64", "Intel Core i7-12700H", 14, 20, 32,
        gpu_vendor="nvidia", gpu_name="NVIDIA GeForce RTX 4060 Laptop GPU",
        vram_gib=8, docker_gpu=True, wsl=True),
    "nvidia-16gb": _simulated(
        "Linux", "x86_64", "AMD Ryzen 7 7800X3D", 8, 16, 32,
        gpu_vendor="nvidia", gpu_name="NVIDIA GeForce RTX 4080",
        vram_gib=16, docker_gpu=True),
    "nvidia-24gb": _simulated(
        "Linux", "x86_64", "AMD Ryzen 9 7950X", 16, 32, 64,
        gpu_vendor="nvidia", gpu_name="NVIDIA GeForce RTX 4090",
        vram_gib=24, docker_gpu=True),
    "macos-arm": _simulated(
        "Darwin", "arm64", "Apple M3 Pro", 11, 11, 18,
        gpu_vendor="apple", gpu_name="Apple M3 Pro (integrated)",
        vram_gib=None, docker_gpu=False, avx2=None),
    "linux-cpu-8gb": _simulated(
        "Linux", "x86_64", "Intel Core i5-8250U", 4, 8, 7.6),
    "laptop-cpu-14gb": _simulated(
        "Linux", "x86_64", "Intel Core i7-1165G7", 4, 8, 13.8,
        gpu_vendor="intel", gpu_name="Intel Iris Xe Graphics"),
    "linux-cpu-16gb": _simulated(
        "Linux", "x86_64", "AMD Ryzen 5 5600G", 6, 12, 15.4),
    "windows-cpu-16gb": _simulated(
        "Windows", "AMD64", "Intel Core i5-1135G7", 4, 8, 15.8,
        gpu_vendor="intel", gpu_name="Intel Iris Xe Graphics", wsl=True),
    "old-cpu-no-avx2": _simulated(
        "Linux", "x86_64", "Intel Core i5-3470", 4, 4, 15.6, avx2=False),
    "amd-gpu": _simulated(
        "Linux", "x86_64", "AMD Ryzen 7 5800X", 8, 16, 32,
        gpu_vendor="amd", gpu_name="AMD Radeon RX 7900 XTX",
        vram_gib=24, docker_gpu=False),
    "nvidia-no-toolkit": _simulated(
        "Windows", "AMD64", "Intel Core i9-13900H", 14, 20, 32,
        gpu_vendor="nvidia", gpu_name="NVIDIA GeForce RTX 4070 Laptop GPU",
        vram_gib=8, docker_gpu=False, wsl=False),
}

def _parse_env(text: str) -> list[tuple[str | None, str]]:
    out: list[tuple[str | None, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append((None, line))
        else:
            out.append((stripped.split("=", 1)[0].strip(), line))
    return out

def _bootstrap_env(log: Log, infra: Path, reset: bool) -> None:
    env_path = infra / ".env"
    if env_path.is_file() and not reset:
        log.info(".env exists; layering profile settings onto it (use --reset-env to recreate)")
        return

    script = infra / "init-env.sh"
    bash = shutil.which("bash")
    if bash and script.is_file():
        args = [bash, str(script), "--quiet"] + (["--force"] if env_path.is_file() else [])
        res = run(args, log, timeout=60, cwd=infra)
        if res.ok and env_path.is_file():
            log.ok("Generated src/infra/.env via init-env.sh")
            return
        log.warn(f"init-env.sh did not complete ({res.first_line() or 'no output'}); "
                 "falling back to the built-in equivalent")

    import secrets

    example = infra / ".env.example"
    if not example.is_file():
        raise InstallError(
            EXIT_ENV_WRITE_FAILED,
            "src/infra/.env.example is missing.",
            f"Looked in {infra}.",
            "Re-extract the ZIP; the source tree is incomplete.",
        )
    if env_path.is_file():
        _backup_env(log, env_path)
    try:
        text = example.read_text(encoding="utf-8")
        secret = secrets.token_hex(32)
        lines = [
            f"JWT_SECRET_KEY={secret}" if ln.startswith("JWT_SECRET_KEY=") else ln
            for ln in text.splitlines()
        ]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _lock_down(env_path)
        log.ok("Generated src/infra/.env (built-in equivalent of init-env.sh)")
    except OSError as exc:
        raise InstallError(
            EXIT_ENV_WRITE_FAILED,
            "Could not write src/infra/.env.",
            str(exc),
            "Check that the folder is writable and not open in another program.",
        ) from exc

def _backup_env(log: Log, env_path: Path) -> Path:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = env_path.with_name(f".env.bak.{stamp}")
    shutil.copy2(env_path, backup)
    _lock_down(backup)
    log.info(f"Backed up existing .env to {backup.name}")
    return backup

def _lock_down(path: Path) -> None:
    if os.name == "posix":
        try:
            path.chmod(0o600)
        except OSError:
            pass

UNSET_MARKER = "#[horus-installer-unset] "

def _reactivate(line: str, wanted: set[str]) -> str:
    if not line.startswith(UNSET_MARKER):
        return line
    body = line[len(UNSET_MARKER):]
    key = body.split("=", 1)[0].strip() if "=" in body else ""
    return body if key in wanted else line

def apply_env(log: Log, infra: Path, updates: dict[str, str], reset: bool) -> Path:
    _bootstrap_env(log, infra, reset)
    env_path = infra / ".env"
    if env_path.is_file() and not reset:
        _backup_env(log, env_path)

    try:
        original = env_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallError(
            EXIT_ENV_WRITE_FAILED, "Could not read src/infra/.env.", str(exc),
            "Check file permissions and try again.",
        ) from exc

    wanted = set(updates)
    stale = set(profiles.MANAGED_KEYS) - wanted

    restored = [_reactivate(ln, wanted) for ln in original.splitlines()]
    pairs = _parse_env("\n".join(restored))

    remaining = dict(updates)
    out: list[str] = []
    seen: set[str] = set()
    deactivated: list[str] = []
    for key, line in pairs:
        if key is not None and key in remaining:
            out.append(f"{key}={remaining[key]}")
            seen.add(key)
        elif key is not None and key in stale:
            out.append(UNSET_MARKER + line.strip())
            deactivated.append(key)
        else:
            out.append(line)
    for key in seen:
        remaining.pop(key, None)

    if remaining:
        out.append("")
        out.append("# " + "=" * 74)
        out.append("# Added by the Horus beta installer "
                   f"({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
        out.append("# Re-running the installer rewrites these in place.")
        out.append("# " + "=" * 74)
        for key, value in remaining.items():
            out.append(f"{key}={value}")

    try:
        env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
        _lock_down(env_path)
    except OSError as exc:
        raise InstallError(
            EXIT_ENV_WRITE_FAILED, "Could not write src/infra/.env.", str(exc),
            "Check that the folder is writable.",
        ) from exc

    log.ok(f"Wrote {len(updates)} setting(s) to src/infra/.env: "
           + ", ".join(sorted(updates)))
    if deactivated:
        log.info("Deactivated settings from a previous profile: "
                 + ", ".join(sorted(set(deactivated))))
    return env_path

def corpus_scan_token(log: Log, infra: Path) -> str:
    import secrets

    env_path = infra / ".env"
    if env_path.is_file():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("CORPUS_SCAN_TOKEN="):
                    existing = line.split("=", 1)[1].strip()
                    if existing:
                        log.info("Reusing the existing CORPUS_SCAN_TOKEN")
                        return existing
        except OSError:
            pass
    log.info("Generated a new CORPUS_SCAN_TOKEN")
    return secrets.token_urlsafe(32)

def _stream(cmd: list[str], log: Log, cwd: Path, label: str,
            heartbeat: int = 30, watch_for: tuple[str, ...] = (),
            found: set[str] | None = None, env: dict[str, str] | None = None) -> int:
    log.debug(f"$ {' '.join(cmd)}   (cwd={cwd})" + (f"   (env {env})" if env else ""))
    start = time.monotonic()
    last_beat = start
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            env={**os.environ, **env} if env else None,
        )
    except OSError as exc:
        log.fail(f"{label}: could not start docker ({exc})")
        return 126

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            print("   " + dim(line[:200]))
            log.debug(f"  {label}: {line}")
            if found is not None:
                for phrase in watch_for:
                    if phrase in line:
                        found.add(phrase)
        now = time.monotonic()
        if now - last_beat >= heartbeat:
            last_beat = now
            msg = f"   ... still working, {elapsed(now - start)} elapsed"
            print(bold(msg))
            log.info(f"{label}: {elapsed(now - start)} elapsed")
    code = proc.wait()
    log.info(f"{label}: exit {code} after {elapsed(time.monotonic() - start)}")
    return code

DEPENDENCY_ABORT = "dependency failed to start"

FIRST_INSTALL_TIME = "1.5 to 2 hours"

PULL_ATTEMPTS = 3
PULL_BACKOFF_SECONDS = 15
ONE_IMAGE_AT_A_TIME = {"COMPOSE_PARALLEL_LIMIT": "1"}
NO_BUILD = "--no-build"

def compose(args: list[str]) -> list[str]:
    return ["docker", "compose"] + args

def compose_config(log: Log, infra: Path) -> tuple[str, dict[str, dict]] | None:
    res = run(compose(["config", "--format", "json"]), log, timeout=90, cwd=infra,
              log_output=False)
    if not res.ok:
        log.debug("  stderr: " + (res.err.splitlines()[0] if res.err else "(empty)"))
        return None
    try:
        config = json.loads(res.out)
    except ValueError:
        return None
    services = config.get("services") if isinstance(config, dict) else None
    if not isinstance(services, dict):
        return None
    project = str(config.get("name") or "")
    return project, {name: spec for name, spec in services.items() if isinstance(spec, dict)}

def ours(spec: dict) -> bool:
    return bool(spec.get("build"))

def images_built_here_before(log: Log, project: str, services: dict[str, dict]) -> list[str]:
    if not project:
        return []
    local = [f"{project}-{name}" for name, spec in services.items() if ours(spec)]
    return [image for image in local if _image_on_this_machine(log, image)]

def _images_in_repository(log: Log, repository: str) -> list[tuple[str, str]]:
    res = run(["docker", "image", "ls", "--format", "{{.ID}} {{.Repository}}:{{.Tag}}",
               repository], log, timeout=60)
    if not res.ok:
        return []
    rows = (line.split() for line in res.out.splitlines())
    return [(row[0], row[1]) for row in rows if len(row) == 2]

def other_releases_left_here(log: Log, services: dict[str, dict]) -> list[str]:
    left: list[str] = []
    for spec in services.values():
        image = str(spec.get("image") or "")
        if not (ours(spec) and image):
            continue
        repository, in_use = images.split_tag(image)
        listed = _images_in_repository(log, repository)
        in_use_ids = {image_id for image_id, name in listed
                      if images.split_tag(name)[1] == in_use}
        left += [name for image_id, name in listed
                 if image_id not in in_use_ids
                 and images.split_tag(name)[1] not in ("", "<none>")]
    return left

def unused_horus_images(log: Log, project: str, services: dict[str, dict]) -> list[str]:
    built_here = images_built_here_before(log, project, services)
    return built_here + other_releases_left_here(log, services)

def point_out_unused_local_images(log: Log, leftovers: list[str]) -> None:
    if not leftovers:
        return
    log.say("")
    log.say("  Earlier installs left these Horus images here. This install does not")
    log.say("  use them, and they take a lot of disk. Free the space with:")
    log.say("    docker image rm " + " ".join(leftovers))

def pullable_images(services: dict[str, dict], from_source: bool) -> dict[str, str]:
    named = {name: str(spec["image"]) for name, spec in services.items() if spec.get("image")}
    first = [name for name in named if ours(services[name]) and not from_source]
    rest = [name for name in named if not ours(services[name])]
    return {name: named[name] for name in [*first, *rest]}

PULLED = "pulled"
REFUSED = "refused"
FAILED = "failed"

def _pull_with_retries(log: Log, infra: Path, label: str, args: list[str],
                       landed=None) -> str:
    cmd = compose(["pull"] + args)
    for attempt in range(1, PULL_ATTEMPTS + 1):
        suffix = "" if attempt == 1 else f" (attempt {attempt} of {PULL_ATTEMPTS})"
        refusals: set[str] = set()
        code = _stream(cmd, log, infra, label + suffix, env=ONE_IMAGE_AT_A_TIME,
                       watch_for=images.REFUSALS, found=refusals)
        if code == 0 and (landed is None or landed()):
            return PULLED
        if refusals:
            log.warn(f"The registry refused `{' '.join(cmd)}` "
                     f"({', '.join(sorted(refusals))}); not trying again")
            return REFUSED
        if code == 0:
            log.warn(f"`{' '.join(cmd)}` exited 0 but the image is not on this machine")
        if attempt < PULL_ATTEMPTS:
            pause = PULL_BACKOFF_SECONDS * attempt
            log.warn(f"`{' '.join(cmd)}` failed (attempt {attempt} of {PULL_ATTEMPTS}); "
                     f"trying again in {pause}s")
            time.sleep(pause)
    return FAILED

def _image_on_this_machine(log: Log, image: str) -> bool:
    return run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
               log, timeout=60).ok

def _unnamed_error(unnamed: list[str], infra: Path) -> InstallError:
    return InstallError(
        EXIT_COMPOSE_PULL_FAILED,
        "Compose gives Horus's own images no name to download.",
        f"{', '.join(unnamed)} would be built here, because {images.REGISTRY_KEY} is not\n"
        f"set in {infra / '.env'}. The installer writes it on every install.",
        "Run START-HERE again so it writes the registry, or build the images\n"
        "on this machine instead (contributors):  --build-from-source",
    )

def _refused_error(service: str, image: str, infra: Path) -> InstallError:
    host = images.registry_host(image)
    return InstallError(
        EXIT_COMPOSE_PULL_FAILED,
        f"{host} refused to send Horus's own images.",
        f"Refused: {service}  ({image})\n"
        "The images are private: the registry needs the access token you were\n"
        "given, or that release was never published there.",
        f"Give the installer the token, as one line  USERNAME:TOKEN :\n"
        f"  - save it as {images.TOKEN_FILE_NAME} next to START-HERE, or\n"
        f"  - set {images.TOKEN_KEY} (and {images.USERNAME_KEY}), or\n"
        "  - pass --registry-token-file PATH\n"
        "then run START-HERE again. Never put the token itself on the command line.\n"
        "Contributors with the source can build the images instead:  --build-from-source\n"
        f"To see Docker's own error:  cd {infra}  then  docker compose pull {service}\n"
        f"Full log: {LOG_PATH}",
    )

def pull_images(log: Log, infra: Path, from_source: bool = False) -> list[str]:
    config = compose_config(log, infra)
    if config is None:
        log.info("`docker compose config` gave no service list; pulling every image "
                 "in one call, still one image at a time")
        args = ["--ignore-buildable"] if from_source else []
        if _pull_with_retries(log, infra, "pull", args) != PULLED:
            log.warn(f"`docker compose pull` still failed after {PULL_ATTEMPTS} tries; "
                     "continuing: the next step surfaces anything genuinely missing")
        return []
    project, services = config

    if not from_source:
        unnamed = [name for name, spec in services.items()
                   if ours(spec) and not spec.get("image")]
        if unnamed:
            raise _unnamed_error(unnamed, infra)

    wanted = pullable_images(services, from_source)
    missing: list[tuple[str, str]] = []
    for index, (service, image) in enumerate(wanted.items(), start=1):
        prebuilt = ours(services[service])
        log.say(f"  [{index}/{len(wanted)}] {service}  " + dim(image)
                + ("  (prebuilt)" if prebuilt else ""))
        landed = (lambda image=image: _image_on_this_machine(log, image)) if prebuilt else None
        outcome = _pull_with_retries(log, infra, f"pull {service}", [service], landed)
        if outcome == PULLED:
            continue
        if _image_on_this_machine(log, image):
            log.warn(f"Could not download {image}; using the copy already on this machine")
            continue
        if outcome == REFUSED and prebuilt:
            raise _refused_error(service, image, infra)
        missing.append((service, image))

    if missing:
        names = " ".join(service for service, _image in missing)
        raise InstallError(
            EXIT_COMPOSE_PULL_FAILED,
            f"{len(missing)} container image(s) could not be downloaded.",
            f"Each was tried {PULL_ATTEMPTS} times, one image at a time:\n  "
            + "\n  ".join(f"{service}  ({image})" for service, image in missing),
            "This is almost always the network or Docker Hub (a timeout or a\n"
            "download limit), not this machine. Everything already downloaded\n"
            "is kept, so trying again only fetches what is missing.\n"
            "  1. Check the internet connection, and the proxy or VPN if you use one.\n"
            "  2. Download what is missing by hand to see Docker's own error:\n"
            f"       cd {infra}\n"
            f"       docker compose pull {names}\n"
            "  3. Run your START-HERE file again. It resumes where it stopped.\n"
            "If Docker says 'toomanyrequests', Docker Hub is limiting this\n"
            "connection: wait a while, or sign in with  docker login  first.\n"
            "If it says 'manifest unknown' for a horus-* image, that release was\n"
            "never published to the registry: check --registry and the version.\n"
            "If it says 'no matching manifest', the prebuilt images are not built\n"
            "for this processor: run START-HERE again with  --build-from-source\n"
            f"Full log: {LOG_PATH}",
        )
    return [] if from_source else unused_horus_images(log, project, services)

def services_still_starting(log: Log, infra: Path) -> list[str]:
    starting: list[str] = []
    for row in _ps(log, infra):
        name = str(row.get("Service") or row.get("Name") or "")
        state, health = _state_of(row)
        if name and state == "running" and health in ("starting", "unhealthy"):
            starting.append(name)
    return starting

def up_waiting_out_a_dependency_abort(log: Log, infra: Path, up: list[str],
                                      timeout: int) -> tuple[list[str], int]:
    seen: set[str] = set()
    code = _stream(compose(up), log, infra, "up",
                   watch_for=(DEPENDENCY_ABORT,), found=seen)
    if code != 0 and DEPENDENCY_ABORT in seen:
        log.say("")
        log.warn("Docker gave up on a service that was still starting.")
        log.say("  On a first install this is almost always a model download:")
        log.say("  the service takes longer than Docker waits, Docker marks it")
        log.say("  unhealthy, and everything depending on it is cancelled. What")
        log.say("  was downloaded is kept. Waiting for that service to finish,")
        log.say("  then starting the rest.")
        log.say("")
        starting = services_still_starting(log, infra)
        if starting:
            wait_for_health(log, infra, starting, timeout=timeout)
        else:
            log.info("no service is still starting; starting the rest straight away")
        up = ["up", "-d"] + [flag for flag in up if flag == NO_BUILD]
        seen.clear()
        code = _stream(compose(up), log, infra, "up (second attempt)",
                       watch_for=(DEPENDENCY_ABORT,), found=seen)
        if code == 0:
            log.ok("Started on the second attempt.")
    return up, code

def build_images(log: Log, infra: Path) -> None:
    log.step("Building the images")
    code = _stream(compose(["build"]), log, infra, "build")
    if code != 0:
        raise InstallError(
            EXIT_COMPOSE_UP_FAILED,
            "The images did not build.",
            f"`docker compose build` exited {code}. The lines above show what "
            "Docker reported; the full output is in the log.",
            "Common causes:\n"
            "  - out of disk space part-way through   ->  docker system df\n"
            "  - a package download that timed out    ->  just run this again,\n"
            "    it reuses every layer that already built\n"
            f"Full log: {LOG_PATH}",
        )

def pull_and_build(log: Log, infra: Path, no_build: bool = False,
                   timeout: int = 1800, before_start=None, from_source: bool = False) -> None:
    log.step("Downloading container images")
    if from_source:
        log.say(f"  This is the long part. A first install takes {FIRST_INSTALL_TIME}:")
        log.say("  the images download one at a time, the containers build, then the")
        log.say("  language model downloads. It is not frozen.")
    else:
        log.say("  This is the long part. Horus's own images come prebuilt and signed,")
        log.say("  so nothing is built here: the images download one at a time, then")
        log.say("  the language model downloads. It is not frozen. A first install that")
        log.say(f"  built the images here took {FIRST_INSTALL_TIME}; downloading them")
        log.say("  instead has not been timed yet.")
    log.say("")

    leftovers = pull_images(log, infra, from_source)
    if from_source and not no_build:
        build_images(log, infra)
    if before_start is not None:
        before_start()

    log.step("Starting the stack")
    first_up = ["up", "-d"] if from_source else ["up", "-d", NO_BUILD]
    up, code = up_waiting_out_a_dependency_abort(log, infra, first_up, timeout)
    if code != 0:
        raise InstallError(
            EXIT_COMPOSE_UP_FAILED,
            "The stack did not start.",
            f"`docker compose {' '.join(up)}` exited {code}. The lines above show what "
            "Docker reported; the full output is in the log.",
            "A container reported UNHEALTHY does not say why - the reason is in\n"
            "that container's own log, and Docker will not show it to you.\n"
            "Read it first:\n"
            f"  cd {infra}\n"
            "  docker compose logs --tail 50 mas\n"
            "replacing mas with whichever container Docker named above.\n"
            "\n"
            "Other common causes:\n"
            "  - out of disk space part-way through   ->  docker system df\n"
            "  - a port became busy after preflight   ->  docker ps\n"
            "  - a transient registry error           ->  just run this again,\n"
            "    it resumes from what was already downloaded\n"
            "\n"
            "This was already retried once, after waiting for the services\n"
            "that were still starting. If Docker named a service that was\n"
            "still downloading a model, the stack is probably fine and only\n"
            "needs starting again:\n"
            "  START-HERE (your platform) --start\n"
            f"Full log: {LOG_PATH}",
        )
    point_out_unused_local_images(log, leftovers)

def _ps(log: Log, infra: Path) -> list[dict]:
    res = run(compose(["ps", "--format", "json", "--all"]), log, timeout=90, cwd=infra)
    if not res.ok or not res.out.strip():
        return []
    rows: list[dict] = []
    text = res.out.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows

def _state_of(row: dict) -> tuple[str, str]:
    return (str(row.get("State", "") or ""), str(row.get("Health", "") or ""))

def wait_for_health(log: Log, infra: Path, expect: list[str],
                    timeout: int = 1800) -> dict:
    log.step("Waiting for services to become healthy")
    log.say(f"  Up to {timeout // 60} minutes. Models download on first start.")
    start = time.monotonic()
    last_report = 0.0
    states: dict[str, tuple[str, str]] = {}

    while time.monotonic() - start < timeout:
        rows = _ps(log, infra)
        states = {}
        for row in rows:
            name = str(row.get("Service") or row.get("Name") or "")
            if name:
                states[name] = _state_of(row)

        pending = []
        for svc in expect:
            state, health = states.get(svc, ("missing", ""))
            if state != "running":
                pending.append(f"{svc}={state or 'missing'}")
            elif health and health not in ("healthy", ""):
                pending.append(f"{svc}={health}")

        log.events.emit(
            "services",
            elapsed_seconds=round(time.monotonic() - start, 1),
            expected=list(expect),
            pending=list(pending),
            services={
                svc: {"state": states.get(svc, ("missing", ""))[0] or "missing",
                      "health": states.get(svc, ("missing", ""))[1]}
                for svc in expect
            },
        )

        if not pending:
            log.ok(f"all {len(expect)} services up after "
                   f"{elapsed(time.monotonic() - start)}")
            return states

        now = time.monotonic()
        if now - last_report >= 20:
            last_report = now
            log.say(f"   {elapsed(now - start)}  waiting on: " + ", ".join(pending[:6]))
        time.sleep(5)

    stuck = []
    for svc in expect:
        state, health = states.get(svc, ("missing", ""))
        if state != "running" or (health and health not in ("healthy", "")):
            stuck.append(f"{svc}: state={state or 'missing'} health={health or 'n/a'}")
    raise InstallError(
        EXIT_HEALTH_TIMEOUT,
        f"{len(stuck)} service(s) never became healthy within {timeout // 60} minutes.",
        "Still not ready:\n  " + "\n  ".join(stuck),
        "Look at what that service is doing:\n"
        f"  cd {infra}\n"
        "  docker compose logs --tail 100 " + (stuck[0].split(":")[0] if stuck else "mas") + "\n"
        "If it is still downloading model weights, re-running this installer is\n"
        "safe and will pick up where it left off.\n"
        f"Full log: {LOG_PATH}",
    )

ARM_MACHINES = frozenset({"arm64", "aarch64"})

def image_source(args, infra: Path) -> str | None:
    if images.build_from_source_requested(args.build_from_source):
        return None
    configured = smoke.read_env(infra / ".env").get(images.REGISTRY_KEY, "")
    return images.registry_to_use(args.registry, os.environ, configured)

def describe_images(registry: str | None, profile_name: str) -> str:
    if registry is None:
        return "built from source on this machine (--build-from-source)"
    names = ",".join(images.image_repository(service).removeprefix("horus-")
                     for service in images.APP_SERVICES)
    flavor = profiles.image_flavor(profile_name)
    return f"{registry}/horus-{{{names}}}:{VERSION}-{flavor}, prebuilt and signed"

def sign_in_to_registry(log: Log, args, registry: str) -> None:
    credentials = images.read_credentials(
        args.registry_token_file, args.registry_user, os.environ,
        BUNDLE_DIR / images.TOKEN_FILE_NAME,
    )
    if credentials is None:
        log.info("no registry token given; pulling with the credentials Docker "
                 "already has, if any")
        return
    images.sign_in(log, registry, credentials)

def warn_if_images_are_emulated(log: Log, probe: dict | None) -> None:
    machine = str(((probe or {}).get("os") or {}).get("machine") or "").lower()
    if machine not in ARM_MACHINES:
        return
    log.warn("This machine has an ARM processor. Horus's prebuilt images are built "
             "for x86-64 (linux/amd64) only, so Docker runs them through emulation: "
             "slower, and not tested yet.")
    log.say("  If the download or the start fails, run START-HERE again with")
    log.say(f"  --build-from-source to build them for this processor ({FIRST_INSTALL_TIME}).")

def warn_cpu_expectations(log: Log, gpu_usable: bool = False) -> None:
    log.say("")
    log.say(yellow("=" * 72))
    if gpu_usable:
        log.say(yellow("  A CPU profile was chosen, so Horus will run on the CPU even though"))
        log.say(yellow("  Docker can use your GPU."))
    else:
        log.say(yellow("  No NVIDIA GPU was usable, so Horus will run on the CPU."))
    log.say(yellow("=" * 72))
    log.say("")
    log.say(f"  Read this before you spend {FIRST_INSTALL_TIME} on the install.")
    log.say("")
    log.say("  Everything except the AI answers works on the CPU: the whole stack")
    log.say("  starts, and sign-in, permissions, users, agents, the knowledge")
    log.say("  store, tasks, conversations and the admin pages all behave")
    log.say("  normally. That is 65 of the 68 acceptance-test scenarios.")
    log.say("")
    log.say(yellow("  What is NOT known yet is how well the model answers."))
    log.say("  The CPU profile now serves one quantized 4B model with llama-server")
    log.say("  instead of two models inside the services. That has not been timed")
    log.say("  on a CPU-only machine. The old setup, measured on a 12-core CPU, took")
    log.say("  14 minutes for one question and came back wrong; a GPU answers in")
    log.say("  about 4 seconds. Test scenarios F41, F42 and F43 need an NVIDIA GPU.")
    log.say("  Nothing else does.")
    log.say("")
    log.say("  The install will still finish and report success. A slow answer is")
    log.say("  expected; please note how long it took in your report.")
    log.say("")


def require_installed(infra: Path, record: Path | None = None) -> None:
    if (infra / ".env").is_file():
        return
    refused = unsupported.from_record(hardware.read_profile_json(record or PROFILE_JSON))
    if refused is not None:
        raise refused
    raise InstallError(
        EXIT_NOT_INSTALLED,
        "Horus has not been installed on this machine yet.",
        f"There is no configuration file at:\n  {infra / '.env'}\n"
        "The source tree is here, but the install never completed.",
        "Run the full installer once first:\n"
        "  Windows  double-click  START-HERE-Windows.bat\n"
        "  macOS    RIGHT-CLICK   START-HERE-macOS.command  and choose Open\n"
        "  Linux    run           ./START-HERE-Linux.sh",
    )

def _require_docker(log: Log) -> None:
    preflight.check_docker(log)
    preflight.check_compose(log)

def _model_token(infra: Path) -> str | None:
    return os.environ.get("HF_TOKEN") or smoke.read_env(infra / ".env").get("HF_TOKEN") or None

def download_model(log: Log, plan: model_manager.ModelPlan, infra: Path,
                   title: str = "Downloading the language model") -> Path:
    entry = plan.entry
    log.step(title)
    log.say(f"  {entry.file}, {human_bytes(entry.size_bytes)}"
            + (f" ({entry.id} {entry.version})" if entry.version else ""))
    log.say(f"  in {plan.models_dir}")
    return plan.ensure(log, token=_model_token(infra))

def stop_llm_before_its_model_changes(log: Log, infra: Path,
                                      plan: model_manager.ModelPlan) -> None:
    if not plan.target.is_file() or model_manager.is_verified(plan.entry, plan.target):
        return
    log.say(f"  {plan.entry.file} was not verified yet, so llm is stopped while it is "
            "checked and maybe replaced")
    if _stream(compose(["stop", profiles.CPU_MODEL_SERVER]), log, infra, "stop llm") != 0:
        log.warn("`docker compose stop llm` failed. If the model file cannot be replaced, "
                 "stop Horus with --stop, then run this again.")

def download_model_for_the_stack(log: Log, plan: model_manager.ModelPlan, infra: Path,
                                 title: str = "Downloading the language model") -> Path:
    stop_llm_before_its_model_changes(log, infra, plan)
    return download_model(log, plan, infra, title)

def ensure_installed_model(log: Log, infra: Path) -> None:
    if not cpu_overlay_active(infra):
        return
    values = smoke.read_env(infra / ".env")
    try:
        manifest = model_manager.load_manifest(model_manager.manifest_path(infra.parent.parent))
    except InstallError as exc:
        log.warn(f"{exc.headline} Using the model named in src/infra/.env.")
        manifest = None
    plan = model_manager.plan_from_env(values, infra, manifest)
    if plan is None:
        log.info("src/infra/.env names no model file; the llm-model service fetches it")
        return
    download_model_for_the_stack(log, plan, infra, "Checking the language model")

def installed_from_registry(infra: Path) -> bool:
    return bool(smoke.read_env(infra / ".env").get(images.REGISTRY_KEY, "").strip())

def start_command(infra: Path, build: bool = False) -> list[str]:
    if build:
        return ["up", "-d", "--build"]
    return ["up", "-d", NO_BUILD] if installed_from_registry(infra) else ["up", "-d"]

def do_start(log: Log, infra: Path, timeout: int, build: bool = False) -> int:
    require_installed(infra)
    _require_docker(log)
    ensure_installed_model(log, infra)

    expect = expected_services(infra)
    log.step("Starting Horus")
    log.say(f"  {len(expect)} services"
            + ("" if profiles.GPU_MODEL_SERVER in expect
               else "  (CPU profile: llama-server runs as llm instead of vllm)"))

    up, code = up_waiting_out_a_dependency_abort(
        log, infra, start_command(infra, build), timeout)
    if code != 0:
        raise InstallError(
            EXIT_COMPOSE_UP_FAILED,
            "The stack did not start.",
            f"`docker compose {' '.join(up)}` exited {code}.",
            "A container reported UNHEALTHY does not say why - the reason is in\n"
            "that container's own log, and Docker will not show it to you.\n"
            "Read it first:\n"
            f"  cd {infra}\n"
            "  docker compose logs --tail 50 mas\n"
            "replacing mas with whichever container Docker named above.\n"
            "\n"
            "If a container is missing or its image was removed, re-run the full\n"
            "installer - it downloads what is missing and keeps your documents.\n"
            f"Full log: {LOG_PATH}",
        )

    wait_for_health(log, infra, expect, timeout=timeout)
    log.say("")
    log.ok(f"Horus is ready at {WEB_URL}")
    log.events.emit("ready", url=WEB_URL, services=expect)
    return EXIT_OK

def do_restart(log: Log, infra: Path, timeout: int) -> int:
    require_installed(infra)
    _require_docker(log)
    ensure_installed_model(log, infra)

    log.step("Restarting Horus")
    code = _stream(compose(["restart"]), log, infra, "restart")
    if code != 0:
        log.warn("`docker compose restart` reported errors; trying `up -d` instead")
        code = _stream(compose(start_command(infra)), log, infra, "up")
        if code != 0:
            raise InstallError(
                EXIT_COMPOSE_UP_FAILED,
                "The stack could not be restarted.",
                f"Both `docker compose restart` and `up -d` failed (exit {code}).",
                "Stop it and start it again:\n"
                f"  cd {infra}\n"
                "  docker compose stop && docker compose up -d\n"
                f"Full log: {LOG_PATH}",
            )

    expect = expected_services(infra)
    wait_for_health(log, infra, expect, timeout=timeout)
    log.say("")
    log.ok(f"Horus is ready at {WEB_URL}")
    log.events.emit("ready", url=WEB_URL, services=expect)
    return EXIT_OK

def do_stop(log: Log, infra: Path) -> int:
    log.step("Stopping Horus")
    code = _stream(compose(["stop"]), log, infra, "stop")
    if code != 0:
        log.warn("`docker compose stop` reported errors; see the log")
        return EXIT_COMPOSE_UP_FAILED
    log.say("")
    log.ok("Stopped. Your data is untouched.")
    log.say("  Start it again with the START-HERE launcher, or:")
    log.say(f"    cd {infra} && docker compose start")
    return EXIT_OK

def do_uninstall(log: Log, infra: Path, assume_yes: bool) -> int:
    log.step("Uninstall Horus")
    log.say("")
    log.say(red("  This removes the containers, the downloaded images, AND the"))
    log.say(red("  named volumes. That includes:"))
    log.say(red("    - every document you uploaded or ingested"))
    log.say(red("    - the vector index built from them"))
    log.say(red("    - all accounts, conversations and task history"))
    log.say(red("    - the model weights the GPU server downloaded (many GB,"))
    log.say(red("      downloaded again next time)"))
    log.say("")
    log.say("  Your own files on disk are NOT touched: the corpus folder was")
    log.say("  mounted read-only and is never written to. The CPU language model")
    log.say("  stays in the models folder; delete that folder to free its space.")
    log.say("")

    if not assume_yes:
        if not sys.stdin or not sys.stdin.isatty():
            log.fail("Refusing to uninstall without confirmation on a "
                     "non-interactive terminal. Pass --yes if you really mean it.")
            return EXIT_UNINSTALL_FAILED
        try:
            answer = input("  Type DELETE to confirm, anything else to cancel: ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "DELETE":
            log.say("")
            log.ok("Cancelled. Nothing was removed.")
            return EXIT_OK

    log.info("uninstall confirmed")
    code = _stream(
        compose(["down", "--volumes", "--rmi", "all", "--remove-orphans"]),
        log, infra, "down",
    )
    if code != 0:
        log.warn("Some resources could not be removed; see the log for detail")
        log.say("  You can finish manually with:")
        log.say(f"    cd {infra} && docker compose down -v --rmi all")
        return EXIT_UNINSTALL_FAILED
    log.say("")
    log.ok("Horus removed.")
    log.say("  The source folder and this installer are still here; delete them")
    log.say("  by hand if you want the disk space back.")
    return EXIT_OK

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="horus-install",
        description="Install and run Horus locally. Everything stays on this machine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
        epilog="Examples:\n"
               "  horus_install.py                       normal install\n"
               "  horus_install.py --dry-run             show what would happen\n"
               "  horus_install.py --dry-run --simulate macos-arm\n"
               "  horus_install.py --profile gpu-16g     override hardware detection\n"
               "  horus_install.py --start               start an installed stack\n"
               "  horus_install.py --restart             restart it in place\n"
               "  horus_install.py --stop                stop the stack, keep data\n"
               "  horus_install.py --download-model      fetch the CPU model only\n"
               "  horus_install.py --build-from-source   build the images here (contributors)\n"
               "  horus_install.py --uninstall           remove everything, DELETES DATA\n",
    )
    p.add_argument("--version", action="version", version=f"Horus beta installer {VERSION}")
    p.add_argument("--repo", metavar="PATH", help="path to the Horus source tree")
    p.add_argument("--profile", metavar="NAME",
                   help="force a tuning profile: " + ", ".join(profiles.PROFILES))
    p.add_argument("--dry-run", action="store_true",
                   help="print the chosen profile and the config it would write, "
                        "then exit without writing any file; Docker is only asked "
                        "how much memory it can use")
    p.add_argument("--simulate", metavar="NAME",
                   help="with --dry-run, pretend to be a different machine: "
                        + ", ".join(SIMULATIONS))
    p.add_argument("--consent", choices=["demo", "folders", "whole-device"],
                   help="preselect the file-access mode. whole-device STILL requires "
                        "the typed confirmation phrase; no flag can skip it.")
    p.add_argument("--skip-disk-check", action="store_true",
                   help="install even if free disk is below the requirement "
                        "(the GPU profile needs about 25 GB less than the CPU one)")
    p.add_argument("--skip-gpu-test", action="store_true",
                   help="skip the `docker run --gpus all` probe (saves a ~250 MB pull; "
                        "host detection alone is then only a hint)")
    p.add_argument("--reset-env", action="store_true",
                   help="regenerate src/infra/.env from the template, rotating the JWT "
                        "secret (signs everyone out). A backup is always kept.")
    p.add_argument("--build-from-source", action="store_true",
                   help="build Horus's own images on this machine instead of downloading "
                        "the prebuilt, signed ones (contributors; same as "
                        f"{images.BUILD_FROM_SOURCE_KEY}=1)")
    p.add_argument("--no-build", action="store_true",
                   help="with --build-from-source, start without rebuilding the images "
                        "(faster re-run)")
    p.add_argument("--registry", metavar="HOST/PATH",
                   help="where the prebuilt images are (default: the registry a previous "
                        f"install used, else {images.DEFAULT_REGISTRY}; or set "
                        f"{images.REGISTRY_KEY})")
    p.add_argument("--registry-user", metavar="NAME",
                   help=f"user name for the image registry (or set {images.USERNAME_KEY})")
    p.add_argument("--registry-token-file", metavar="PATH",
                   help="file holding the registry access token as USERNAME:TOKEN or TOKEN "
                        f"(default: {images.TOKEN_FILE_NAME} next to START-HERE, or set "
                        f"{images.TOKEN_KEY}). The token itself is never a flag.")
    p.add_argument("--models-dir", metavar="PATH",
                   help="where the CPU profiles keep their language model "
                        "(default: the folder a previous install chose, else the "
                        "models folder next to src)")
    p.add_argument("--download-model", action="store_true",
                   help="only download and check the language model of --profile "
                        "(default cpu-standard), then exit; Docker is not needed")
    p.add_argument("--skip-smoke", action="store_true", help="do not run the smoke test")
    p.add_argument("--admin-profile", action="store_true",
                   help="also start pgadmin and redisinsight (Compose profile 'admin')")
    p.add_argument("--timeout", type=int, default=1800, metavar="SECONDS",
                   help="how long to wait for services to become healthy (default 1800)")
    p.add_argument("--non-interactive", action="store_true",
                   help="never prompt; use the safe default for every question")
    p.add_argument("--yes", action="store_true", help="skip the uninstall confirmation")
    p.add_argument("--start", action="store_true",
                   help="start an already-installed stack and wait for it to be "
                        "healthy; no questions, no config changes. Fails with exit "
                        f"{EXIT_NOT_INSTALLED} if the install never completed.")
    p.add_argument("--restart", action="store_true",
                   help="restart the running containers in place, then wait for health")
    p.add_argument("--stop", action="store_true", help="stop the stack and exit")
    p.add_argument("--uninstall", action="store_true",
                   help="remove containers, images and volumes (DELETES INGESTED DOCUMENTS)")
    p.add_argument("--json-events", action="store_true",
                   help="also emit one JSON object per line on STDERR, prefixed "
                        "'@@HORUS ', for a program driving this script. stdout is "
                        "unchanged, so a human transcript reads the same either way.")
    return p

def banner(log: Log) -> None:
    log.say("")
    log.say(bold("  HORUS  " + dim("beta installer " + VERSION)))
    log.say("  " + dim("Everything runs on this machine. Nothing is sent anywhere."))
    log.say("")
    log.say(rule())

def say_detected(log: Log, probe: dict) -> None:
    osi = probe.get("os") or {}
    cpu = probe.get("cpu") or {}
    mem = probe.get("memory") or {}
    gpu = probe.get("gpu") or {}
    docker = probe.get("docker") or {}
    cores = cpu.get("physical_cores")
    ram = mem.get("total_bytes") or 0
    log.say(f"  detected : {osi.get('system') or '?'} {osi.get('machine') or '?'}, "
            f"{cores if cores is not None else '?'} cores, "
            f"{ram / 1024**3:.0f} GB RAM")
    docker_bytes = docker.get("mem_total_bytes")
    log.say("  docker   : " + (f"{docker_bytes / 1024**3:.1f} GiB of memory" if docker_bytes
                              else f"memory not read ({docker.get('detail') or 'unknown'})"))
    vram = gpu.get("vram_bytes")
    log.say(f"  gpu      : {gpu.get('name') or 'none detected'}"
            + (f", {vram / 1024**3:.0f} GB VRAM" if vram else "")
            + ", usable by Docker: "
            + ("yes" if probe.get("cuda_usable_in_docker") else "no"))

def say_refusal(log: Log, probe: dict, reasons: list[str]) -> None:
    refused = unsupported.refusal(probe)
    log.say(f"  profile  : {bold('not supported')}")
    for reason in reasons:
        log.say(f"             - {reason}")
    log.say(f"  stops    : before any download, exit code {refused.code}, with:")
    for line in [refused.headline, "", *refused.detail.splitlines(), "",
                 "What to do:", *refused.fix.splitlines()]:
        log.say(f"             {line}".rstrip())
    log.say("")

def do_dry_run(log: Log, args, repo: Path) -> int:
    log.step("Dry run - nothing will be changed")

    if args.simulate:
        if args.simulate not in SIMULATIONS:
            log.fail(f"Unknown --simulate target {args.simulate!r}")
            log.say("  Available: " + ", ".join(SIMULATIONS))
            return EXIT_PROFILE_UNKNOWN
        probes = [(args.simulate, dict(SIMULATIONS[args.simulate]))]
    else:
        probes = [("this machine", hardware.probe(log, allow_docker_gpu_test=False))]
        if not args.profile:
            probes += [(name, dict(spec)) for name, spec in SIMULATIONS.items()]

    if args.profile and args.profile not in profiles.PROFILES:
        log.fail(f"Unknown profile {args.profile!r}")
        log.say("  Available: " + ", ".join(profiles.PROFILES))
        return EXIT_PROFILE_UNKNOWN

    registry = image_source(args, infra_dir(repo))
    manifest = None
    models_dir = None
    for label, probe in probes:
        if args.profile:
            name, reasons = args.profile, ["forced with --profile"]
        else:
            name, reasons = profiles.select_profile(probe)

        log.say("")
        log.say(rule(label))
        say_detected(log, probe)
        if name == profiles.NOT_SUPPORTED:
            say_refusal(log, probe, reasons)
            continue
        warnings = [profiles.forced_profile_warning(name, probe) if args.profile else None,
                    profiles.avx2_warning(probe) if profiles.is_cpu_profile(name) else None]

        env = profiles.env_for(name, probe)
        plan = None
        if not profiles.get(name).runs_vllm:
            manifest = manifest or model_manager.load_manifest(model_manager.manifest_path(repo))
            models_dir = models_dir or models_dir_to_use(log, repo, args.models_dir)
            plan = model_manager.plan_for_profile(repo, name, models_dir, manifest)
            if plan is not None:
                env.update(plan.env(repo))
        if registry is not None:
            env[images.REGISTRY_KEY] = registry
        osi = probe.get("os") or {}
        log.say(f"  profile  : {bold(name)}")
        for reason in reasons:
            log.say(f"             - {reason}")
        for warning in filter(None, warnings):
            log.say(f"             ! {warning}")
        log.say(f"  images   : {describe_images(registry, name)}")
        if registry is not None and str(osi.get("machine") or "").lower() in ARM_MACHINES:
            log.say("             ! built for x86-64 only: Docker emulates them on this "
                    "processor; --build-from-source builds them for it")
        if plan is not None:
            log.say(f"  model    : {plan.entry.id}, {human_bytes(plan.entry.size_bytes)}, "
                    f"into {plan.models_dir}")
        log.say("")
        log.say("  would write to src/infra/.env:")
        for key in sorted(env):
            log.say(f"      {key}={env[key]}")

    log.say("")
    log.say(rule())
    if args.simulate:
        log.say("  Dry run complete. No files were written and Docker was not contacted.")
    else:
        log.say("  Dry run complete. No files were written; Docker was only asked how much "
                "memory it can use.")
    return EXIT_OK

def models_dir_to_use(log: Log, repo: Path, requested: str | None) -> str | Path | None:
    if requested:
        return requested
    infra = infra_dir(repo)
    configured = smoke.read_env(infra / ".env").get("HORUS_MODELS_DIR", "")
    if not configured:
        return None
    folder = model_manager.models_dir_from_env(configured, infra)
    if folder == model_manager.default_models_dir(repo).resolve():
        return None
    log.say(f"  Keeping the models folder chosen before: {folder}")
    return folder

def plan_model(log: Log, repo: Path, profile: str,
               requested_dir: str | None) -> model_manager.ModelPlan | None:
    if profiles.get(profile).runs_vllm:
        return None
    plan = model_manager.plan_for_profile(repo, profile,
                                          models_dir_to_use(log, repo, requested_dir))
    if plan is None:
        raise InstallError(
            EXIT_MODEL_MANIFEST_INVALID,
            f"models/manifest.json names no language model for the {profile} profile.",
            f"llama-server needs one, and {model_manager.manifest_path(repo)} has no\n"
            f"entry under \"defaults\" for {profile}.",
            "Extract the ZIP again; the manifest ships with Horus.",
        )
    return plan

def do_download_model(log: Log, args, repo: Path) -> int:
    name = args.profile or "cpu-standard"
    plan = plan_model(log, repo, name, args.models_dir)
    if plan is None:
        log.ok(f"The {name} profile has no model file to download: vLLM fetches its own "
               "model when it first starts.")
        return EXIT_OK
    path = download_model(log, plan, infra_dir(repo))
    log.say("")
    log.ok(f"{path} is ready for llama-server")
    return EXIT_OK

def _unknown_profile_error(profile: str) -> InstallError:
    return InstallError(
        EXIT_PROFILE_UNKNOWN,
        f"Unknown profile {profile!r}.",
        "Available: " + ", ".join(profiles.PROFILES),
        "Re-run without --profile to let the installer choose.",
    )

def record_refusal(log: Log, probe: dict, reasons: list[str]) -> unsupported.NotSupported:
    for reason in reasons:
        log.say(f"           {reason}")
    refused = unsupported.refusal(probe)
    hardware.write_profile_json(PROFILE_JSON, probe, profiles.NOT_SUPPORTED, {}, reasons,
                                log=log, refusal=refused.record())
    return refused

def decide_profile(log: Log, args, registry: str | None) -> tuple[dict, str, list[str]]:
    if args.profile and args.profile not in profiles.PROFILES:
        raise _unknown_profile_error(args.profile)
    log.step("Checking your hardware")
    probe = hardware.probe(log, allow_docker_gpu_test=not args.skip_gpu_test,
                           previous=hardware.read_profile_json(PROFILE_JSON))
    if args.profile:
        name, reasons = args.profile, [f"forced with --profile {args.profile}"]
        forced = profiles.forced_profile_warning(name, probe)
        if forced:
            log.warn(forced)
    else:
        name, reasons = profiles.select_profile(probe)
    if name == profiles.NOT_SUPPORTED:
        raise record_refusal(log, probe, reasons)

    log.ok(f"profile: {bold(name)}")
    for reason in reasons:
        log.say(f"           {reason}")
    hardware.write_profile_json(PROFILE_JSON, probe, name, {}, reasons, log=log)
    log.say(f"  images:  {describe_images(registry, name)}")
    if registry is not None:
        warn_if_images_are_emulated(log, probe)

    if profiles.is_cpu_profile(name):
        avx2 = profiles.avx2_warning(probe)
        if avx2:
            log.warn(avx2)
        warn_cpu_expectations(log, gpu_usable=probe.get("cuda_usable_in_docker") is True)
    return probe, name, reasons

def _dispatch(log: Log, args) -> int:
    repo = find_repo(args.repo)
    infra = infra_dir(repo)
    log.info(f"repo: {repo}")
    log.events.emit("located", repo=str(repo), infra=str(infra),
                    bundle=str(BUNDLE_DIR), log=str(LOG_PATH),
                    profile_json=str(PROFILE_JSON), version=VERSION)

    banner(log)

    if args.start:
        return do_start(log, infra, timeout=args.timeout, build=False)
    if args.restart:
        return do_restart(log, infra, timeout=args.timeout)
    if args.stop:
        return do_stop(log, infra)
    if args.uninstall:
        return do_uninstall(log, infra, args.yes)
    if args.dry_run:
        return do_dry_run(log, args, repo)
    if args.download_model:
        return do_download_model(log, args, repo)

    registry = image_source(args, infra)
    preflight.run_engine_checks(log)
    probe, name, reasons = decide_profile(log, args, registry)
    preflight.run_install_checks(log, infra, want_admin_profile=args.admin_profile,
                                 skip_disk_check=args.skip_disk_check,
                                 image_registry=registry,
                                 cpu_profile=profiles.is_cpu_profile(name))
    if registry is not None:
        sign_in_to_registry(log, args, registry)
        if args.no_build:
            log.warn("--no-build only matters with --build-from-source; "
                     "the prebuilt images are never built here")

    choice = consent.choose(
        log, repo,
        non_interactive=args.non_interactive,
        preselect=args.consent,
    )

    env = profiles.env_for(name, probe)
    model_plan = plan_model(log, repo, name, args.models_dir)
    if model_plan is not None:
        env.update(model_plan.env(repo))
    env["HORUS_CORPUS_DIR"] = choice["corpus_dir"]
    env["CORPUS_SCAN_TOKEN"] = corpus_scan_token(log, infra)
    env["HORUS_VERSION"] = VERSION
    if registry is not None:
        env[images.REGISTRY_KEY] = registry

    hardware.write_profile_json(PROFILE_JSON, probe, name, env, reasons)
    log.ok(f"wrote {PROFILE_JSON.name}")

    log.step("Writing configuration")
    apply_env(log, infra, env, reset=args.reset_env)

    pull_and_build(
        log, infra, no_build=args.no_build, timeout=args.timeout,
        before_start=None if model_plan is None
        else lambda: download_model_for_the_stack(log, model_plan, infra),
        from_source=registry is None,
    )

    expect = [*CORE_SERVICES, profiles.model_server(name)]
    wait_for_health(log, infra, expect, timeout=args.timeout)

    if args.skip_smoke:
        log.warn("Smoke test skipped (--skip-smoke). Install is unverified.")
        result = {"passed": True, "steps": [], "answer": None}
    else:
        result = smoke.run(
            log, repo,
            timeout=min(args.timeout, 1200),
            require_answer_quality=not profiles.is_cpu_profile(name),
            model_server=profiles.model_server(name),
        )

    if not result.get("passed"):
        raise InstallError(
            EXIT_SMOKE_FAILED,
            "Horus started, but the smoke test did not pass.",
            "The stack is running; something in the end-to-end path is wrong.\n"
            "Step results are in the log.",
            f"Send us {LOG_PATH.name} and {PROFILE_JSON.name} from:\n  {BUNDLE_DIR}",
        )

    _success(log, infra, name, choice,
             non_interactive=args.non_interactive, built_here=registry is None)
    return EXIT_OK

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = Log(LOG_PATH, events=Events(args.json_events))
    log.info(f"argv: {' '.join(argv if argv is not None else sys.argv[1:])}")

    code = EXIT_OK
    try:
        code = _dispatch(log, args)
    except InstallError as exc:
        exc.report(log)
        code = exc.code
    except KeyboardInterrupt:
        log.say("")
        log.warn("Interrupted. Nothing was left half-installed; re-run when ready.")
        log.say("  If containers were already starting, stop them with:")
        log.say("    START-HERE (your platform) --stop")
        code = EXIT_INTERRUPTED
    finally:
        log.close(code)
    return code

def _success(log: Log, infra: Path, profile_name: str, choice: dict,
             non_interactive: bool = False, built_here: bool = False) -> None:
    creds = _read_admin_credentials(infra)
    log.say("")
    log.say(green("=" * 72))
    log.say(green("  Horus is running."))
    log.say(green("=" * 72))
    log.say("")
    log.say(f"  Open        {bold(WEB_URL)}")
    log.say(f"  Sign in as  {creds[0]} / {creds[1]}")
    log.say("")
    log.say(f"  Profile     {profile_name}")
    log.say(f"  Documents   {consent.describe(choice)}")
    log.say("")
    if profiles.is_cpu_profile(profile_name):
        log.say(yellow("  Running on the CPU: the AI answers come from llama-server"))
        log.say(yellow("  and take minutes, not seconds; this setup has not been"))
        log.say(yellow("  timed yet. Everything else works normally - 65 of the 68"))
        log.say(yellow("  test scenarios. Only F41, F42 and F43 need an NVIDIA GPU."))
        log.say("")
    app_dir = BUNDLE_DIR / "app"
    if app_dir.is_dir():
        log.say(f"  Or open the Horus app in  {app_dir}")
        log.say("  It starts and stops Horus for you, so you do not need this")
        log.say("  window again. Your computer will warn you the first time -")
        log.say("  README-FIRST.txt has the exact clicks.")
    else:
        log.say("  This build has no desktop app in it; use the browser above.")
    log.say("")
    log.say(dim(f"  Log      {LOG_PATH}"))
    log.say(dim(f"  Profile  {PROFILE_JSON}"))
    log.say("")
    log.say("  To stop:       START-HERE (your platform) --stop")
    log.say("  To remove:     START-HERE (your platform) --uninstall")
    log.say("")
    offer_to_reclaim(log, non_interactive=non_interactive, built_here=built_here)
    log.say("")

def reclaimable_build_cache(log: Log) -> int:
    res = run(["docker", "system", "df", "--format", "{{json .}}"], log, timeout=60)
    if not res.ok:
        return 0
    for line in res.out.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("Type") != "Build Cache":
            continue
        match = re.match(r"([\d.]+)\s*([KMGT]?i?B)", str(row.get("Reclaimable") or ""))
        if not match:
            return 0
        scale = {
            "B": 1, "KB": 10**3, "KiB": 1024, "MB": 10**6, "MiB": 1024**2,
            "GB": 10**9, "GiB": 1024**3, "TB": 10**12, "TiB": 1024**4,
        }
        return int(float(match.group(1)) * scale.get(match.group(2), 1))
    return 0

def offer_to_reclaim(log: Log, non_interactive: bool = False, built_here: bool = True) -> None:
    spare = reclaimable_build_cache(log)
    if spare < 1024**3:
        return
    if built_here:
        log.say(f"  The build left {human_bytes(spare)} of Docker build cache behind.")
    else:
        log.say(f"  Docker still holds {human_bytes(spare)} of build cache from images built")
        log.say("  on this machine before. The prebuilt images do not need it.")
    log.say("  It only makes a future rebuild faster. Deleting it does not")
    log.say("  touch Horus, its images or your data.")
    if non_interactive:
        log.say("  Reclaim it with:  docker builder prune -f")
        log.say("")
        return
    try:
        answer = input(f"  Delete it now and get {human_bytes(spare)} back? [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        log.say("")
        return
    if answer.strip().lower() not in ("y", "yes"):
        log.say("  Left alone. You can run  docker builder prune -f  at any time.")
        log.say("")
        return
    res = run(["docker", "builder", "prune", "-f"], log, timeout=900)
    if not res.ok:
        log.warn("`docker builder prune -f` failed; the cache is still there.")
        log.say("")
        return
    freed = max(0, spare - reclaimable_build_cache(log))
    log.ok(f"Reclaimed {human_bytes(freed)} of build cache.")
    log.say("")

def _read_admin_credentials(infra: Path) -> tuple[str, str]:
    user, password = "admin", "admin"
    try:
        for line in (infra / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SUPER_USER_USERNAME="):
                user = line.split("=", 1)[1].strip() or user
            elif line.startswith("SUPER_USER_PASSWORD="):
                password = line.split("=", 1)[1].strip() or password
    except OSError:
        pass
    return user, password

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - last resort; a traceback is better than silence
        import traceback

        traceback.print_exc()
        print()
        print(yellow(f"Unexpected error. Please send us {LOG_PATH}"))
        sys.exit(1)
