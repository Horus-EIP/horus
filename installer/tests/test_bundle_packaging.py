from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parent.parent.parent
BUNDLER = REPO / "packaging" / "build_bundle.py"
INFRA = REPO / "src" / "infra"
sys.path.insert(0, str(REPO / "packaging"))
sys.path.insert(0, str(REPO / "installer"))
import build_bundle  # noqa: E402
import horus_install  # noqa: E402
import profiles  # noqa: E402

posix_only = unittest.skipUnless(
    os.name == "posix", "needs a POSIX kernel for modes and symlinks"
)
needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the compose file")

SOURCE_BUILT_SERVICES = {"mas", "agent", "knowledge_store", "web-client"}

MEMORY_REFERENCE = re.compile(r"^\$\{(\w+):-(\d+g)\}$")

SWAP_REFERENCE = re.compile(r"^\$\{(\w+):-")

INNERMOST_DEFAULT = re.compile(r"\$\{(\w+):-([^${}]*)\}")

def interpolate(value: str, env: dict[str, str]) -> str:
    while True:
        resolved = INNERMOST_DEFAULT.sub(lambda m: env.get(m.group(1)) or m.group(2), value)
        if resolved == value:
            return resolved
        value = resolved

def referenced_keys(value: str) -> set[str]:
    return set(re.findall(r"\$\{(\w+)", value))

def compose_services() -> dict:
    text = (INFRA / "docker-compose.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text)["services"]

def duration_seconds(value) -> int:
    match = re.fullmatch(r"(\d+)([smh])", str(value).strip())
    if match is None:
        raise ValueError(f"not a plain duration: {value!r}")
    return int(match.group(1)) * {"s": 1, "m": 60, "h": 3600}[match.group(2)]

def dependency_conditions(spec: dict) -> dict[str, str]:
    depends = spec.get("depends_on") or {}
    if isinstance(depends, list):
        return dict.fromkeys(depends, "service_started")
    return {name: (rule or {}).get("condition", "service_started")
            for name, rule in depends.items()}

def probe_command(healthcheck: dict) -> list[str]:
    test = healthcheck["test"]
    if isinstance(test, str):
        return test.split()
    if test[0] == "CMD-SHELL":
        return test[1].split()
    return list(test[1:])

def final_stage(dockerfile: Path) -> tuple[str, str]:
    text = dockerfile.read_text(encoding="utf-8").replace("\\\n", " ")
    starts = list(re.finditer(r"^FROM\s+(\S+)", text, re.MULTILINE))
    last = starts[-1]
    return last.group(1), text[last.end():]

def image_ships(tool: str, base: str, stage: str) -> bool:
    if tool in ("python", "python3") and base.startswith("python:"):
        return True
    if tool == "wget" and "alpine" in base:
        return True
    installs = [line for line in stage.splitlines()
                if line.lstrip().startswith("RUN") and "install" in line]
    return any(re.search(rf"\b{re.escape(tool)}\b", line) for line in installs)

def container_ports(spec: dict) -> set[str]:
    return {str(mapping).rsplit(":", 1)[-1] for mapping in spec.get("ports", [])}

def make_app(root: Path) -> Path:
    app = root / "Horus.app"
    macos = app / "Contents" / "MacOS"
    versions = app / "Contents" / "Frameworks" / "A" / "Versions" / "1"
    macos.mkdir(parents=True)
    versions.mkdir(parents=True)

    (macos / "Horus").write_text("macho", encoding="utf-8")
    os.chmod(macos / "Horus", 0o755)
    (app / "Contents" / "Info.plist").write_text("<plist/>", encoding="utf-8")
    (versions / "A").write_text("FRAMEWORK", encoding="utf-8")
    os.symlink("1", versions.parent / "Current")
    os.symlink("Versions/Current/A", versions.parent.parent / "A")
    return app

def build(app_dir: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BUNDLER), "--out", str(out), "--app-dir", str(app_dir)],
        capture_output=True, text=True, cwd=str(REPO), timeout=300,
    )

def entries(zip_path: Path) -> dict:
    out = {}
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if not info.filename.startswith("app/"):
                continue
            mode = info.external_attr >> 16
            payload = zf.read(info.filename)
            out[info.filename] = (mode & 0o777, stat.S_ISLNK(mode), payload)
    return out

@posix_only
class AppBundleIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.app_dir = tmp / "app"
        cls.app_dir.mkdir()
        make_app(cls.app_dir)
        os.symlink("/etc/passwd", cls.app_dir / "Horus.app" / "Contents" / "escape.txt")

        cls.result = build(cls.app_dir, tmp / "dist")
        cls.zip_path = next((tmp / "dist").glob("*.zip"), None)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        if self.zip_path is None:
            self.fail(f"no archive was produced:\n{self.result.stdout}\n{self.result.stderr}")
        self.entries = entries(self.zip_path)

    def test_the_build_succeeded(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout)

    def test_the_macos_binary_keeps_its_executable_bit(self):
        mode, is_link, _ = self.entries["app/Horus.app/Contents/MacOS/Horus"]
        self.assertFalse(is_link)
        self.assertTrue(mode & 0o111, f"shipped {oct(mode)}; macOS will not open it")

    def test_ordinary_files_are_not_made_executable(self):
        mode, _, _ = self.entries["app/Horus.app/Contents/Info.plist"]
        self.assertFalse(mode & 0o111)

    def test_framework_symlinks_are_stored_as_symlinks(self):
        for name, target in (
            ("app/Horus.app/Contents/Frameworks/A/Versions/Current", "1"),
            ("app/Horus.app/Contents/Frameworks/A/A", "Versions/Current/A"),
        ):
            with self.subTest(name):
                _, is_link, payload = self.entries[name]
                self.assertTrue(is_link, f"{name} was flattened into a file")
                self.assertEqual(payload.decode(), target)

    def test_the_link_target_is_stored_once_not_twice(self):
        copies = [n for n, (_, is_link, payload) in self.entries.items()
                  if not is_link and payload == b"FRAMEWORK"]
        self.assertEqual(len(copies), 1, f"duplicated as {copies}")

    def test_a_symlink_out_of_the_tree_is_refused(self):
        self.assertNotIn("app/Horus.app/Contents/escape.txt", self.entries)
        for name, (_, _, payload) in self.entries.items():
            self.assertNotIn(b"root:", payload, f"{name} absorbed /etc/passwd")

    def test_the_refusal_is_reported_not_silent(self):
        self.assertIn("escape.txt", self.result.stdout)

    def test_the_bundle_still_resolves_after_extraction(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with zipfile.ZipFile(self.zip_path) as zf:
                for info in zf.infolist():
                    if not info.filename.startswith("app/"):
                        continue
                    dest = root / info.filename
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        os.symlink(zf.read(info.filename).decode(), dest)
                    else:
                        dest.write_bytes(zf.read(info.filename))
                        os.chmod(dest, mode & 0o777)

            through_links = root / "app/Horus.app/Contents/Frameworks/A/A"
            self.assertEqual(through_links.read_text(encoding="utf-8"), "FRAMEWORK")
            binary = root / "app/Horus.app/Contents/MacOS/Horus"
            self.assertTrue(os.access(binary, os.X_OK))

class LineEndingGuard(unittest.TestCase):

    def setUp(self):
        build_bundle.NORMALISED.clear()

    def roundtrip(self, name: str, payload: bytes) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / name
            src.write_bytes(payload)
            zip_path = Path(tmp) / "t.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                build_bundle.add(zf, src, "horus/" + name)
            with zipfile.ZipFile(zip_path) as zf:
                return zf.read("horus/" + name)

    def test_a_crlf_shell_script_is_stored_as_lf(self):
        out = self.roundtrip("stack-up.sh", b"#!/bin/sh\r\necho hi\r\n")
        self.assertEqual(out, b"#!/bin/sh\necho hi\n")
        self.assertEqual(build_bundle.NORMALISED, ["horus/stack-up.sh  (CRLF -> LF)"])

    def test_command_files_and_dockerfiles_are_stored_as_lf(self):
        self.assertEqual(self.roundtrip("START-HERE-macOS.command", b"a\r\nb\r\n"), b"a\nb\n")
        self.assertEqual(self.roundtrip("Dockerfile", b"FROM x\r\nRUN y \\\r\n  z\r\n"),
                         b"FROM x\nRUN y \\\n  z\n")
        self.assertEqual(len(build_bundle.NORMALISED), 2)

    def test_an_lf_batch_file_is_stored_as_crlf(self):
        out = self.roundtrip("START-HERE-Windows.bat", b"@echo off\ngoto :x\n:x\n")
        self.assertEqual(out, b"@echo off\r\ngoto :x\r\n:x\r\n")
        self.assertEqual(build_bundle.NORMALISED, ["horus/START-HERE-Windows.bat  (LF -> CRLF)"])

    def test_already_correct_files_are_not_reported(self):
        self.roundtrip("ok.sh", b"#!/bin/sh\n")
        self.roundtrip("ok.bat", b"@echo off\r\n")
        self.assertEqual(build_bundle.NORMALISED, [])

    def test_other_files_are_left_byte_for_byte(self):
        self.assertEqual(self.roundtrip("notes.py", b"a\r\nb\n"), b"a\r\nb\n")
        self.assertEqual(self.roundtrip("README.md", b"a\r\n"), b"a\r\n")
        self.assertEqual(build_bundle.NORMALISED, [])

@posix_only
class ExecutableBitGuard(unittest.TestCase):

    def test_a_non_executable_app_binary_fails_the_build(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            app_dir = tmp / "app"
            app_dir.mkdir()
            app = make_app(app_dir)
            os.chmod(app / "Contents" / "MacOS" / "Horus", 0o644)

            result = build(app_dir, tmp / "dist")
            self.assertEqual(result.returncode, 1)
            self.assertIn("not executable", result.stdout)
            self.assertFalse(list((tmp / "dist").glob("*.zip")),
                             "a broken archive was written anyway")

class BundleShipsTheVersion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.result = subprocess.run(
            [sys.executable, str(BUNDLER), "--out", str(cls.tmp / "dist")],
            capture_output=True, text=True, cwd=str(REPO), timeout=300,
        )
        cls.zip_path = next((cls.tmp / "dist").glob("*.zip"), None)
        cls.version = (REPO / "VERSION").read_text(encoding="utf-8").strip()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        if self.zip_path is None:
            self.fail(f"no archive was produced:\n{self.result.stdout}\n{self.result.stderr}")

    def test_the_archive_is_named_after_the_version_file(self):
        self.assertEqual(self.zip_path.name, f"Horus-Beta-{self.version}.zip")

    def test_the_version_file_ships_next_to_the_installer(self):
        with zipfile.ZipFile(self.zip_path) as zf:
            names = set(zf.namelist())
            self.assertIn("VERSION", names)
            self.assertIn("installer/common.py", names)
            self.assertEqual(zf.read("VERSION").decode("utf-8").strip(), self.version)

    def test_the_model_manifest_ships_where_the_installer_reads_it(self):
        with zipfile.ZipFile(self.zip_path) as zf:
            names = set(zf.namelist())
        self.assertIn("horus/models/manifest.json", names)
        self.assertIn("installer/model_manager.py", names)

    def test_the_third_party_notices_ship_next_to_the_licence(self):
        with zipfile.ZipFile(self.zip_path) as zf:
            names = set(zf.namelist())
            shipped = zf.read("horus/THIRD_PARTY_NOTICES").decode("utf-8")
        self.assertIn("horus/LICENSE", names)
        committed = (REPO / "THIRD_PARTY_NOTICES").read_text(encoding="utf-8")
        self.assertEqual(shipped.replace("\r\n", "\n"), committed)

    def test_the_licence_ships_as_committed(self):
        with zipfile.ZipFile(self.zip_path) as zf:
            shipped = zf.read("horus/LICENSE").decode("utf-8")
        committed = (REPO / "LICENSE").read_text(encoding="utf-8")
        self.assertEqual(shipped.replace("\r\n", "\n"), committed)

    def test_every_licence_text_and_notice_ships_with_them(self):
        with zipfile.ZipFile(self.zip_path) as zf:
            names = set(zf.namelist())
        for folder in ("LICENSES", "NOTICES"):
            for path in sorted((REPO / folder).rglob("*")):
                if path.is_file():
                    with self.subTest(path.relative_to(REPO).as_posix()):
                        self.assertIn("horus/" + path.relative_to(REPO).as_posix(), names)

    def test_no_downloaded_model_file_ships(self):
        with zipfile.ZipFile(self.zip_path) as zf:
            names = zf.namelist()
        for suffix in (".gguf", ".part", ".gguf.sha256"):
            self.assertEqual([n for n in names if n.endswith(suffix)], [], suffix)

    def test_the_unpacked_installer_reports_the_shipped_version(self):
        dest = self.tmp / "unpacked"
        with zipfile.ZipFile(self.zip_path) as zf:
            for name in ("VERSION", "installer/common.py"):
                target = dest / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(name))
        proc = subprocess.run(
            [sys.executable, "-c", "import common; print(common.VERSION)"],
            capture_output=True, text=True, cwd=str(dest / "installer"), timeout=60,
        )
        self.assertEqual(proc.stdout.strip(), self.version, proc.stderr)

class ModelFilesStayOutOfTheBundle(unittest.TestCase):
    def test_downloaded_and_partial_models_are_pruned(self):
        for name in ("models/qwen3.gguf", "models/qwen3.gguf.part",
                     "models/qwen3.gguf.sha256"):
            with self.subTest(name):
                self.assertTrue(build_bundle.pruned(Path(name)))
        self.assertFalse(build_bundle.pruned(Path("models/manifest.json")))

@needs_yaml
class ComposeReleaseVersion(unittest.TestCase):
    def test_every_python_service_receives_the_release_version(self):
        services = compose_services()
        for name in ("mas", "agent", "knowledge_store"):
            with self.subTest(name):
                self.assertIn("HORUS_VERSION=${HORUS_VERSION:-}",
                              services[name].get("environment", []))

@needs_yaml
class ComposeMemoryCeilings(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.services = compose_services()

    def limits(self, name: str, env: dict[str, str]) -> tuple[str, str]:
        spec = self.services[name]
        return (interpolate(str(spec["mem_limit"]), env),
                interpolate(str(spec["memswap_limit"]), env))

    def test_each_python_service_takes_its_memory_ceilings_from_the_env(self):
        for name in ("mas", "agent", "knowledge_store"):
            with self.subTest(name):
                spec = self.services[name]
                self.assertRegex(str(spec.get("mem_limit", "")), MEMORY_REFERENCE)
                self.assertRegex(str(spec.get("memswap_limit", "")), SWAP_REFERENCE)
                for limit in self.limits(name, {}):
                    self.assertRegex(limit, r"^\d+g$")

    def test_each_python_service_defaults_to_no_swap(self):
        for name in ("mas", "agent", "knowledge_store"):
            with self.subTest(name):
                limit, swap = self.limits(name, {})
                self.assertEqual(limit, swap)

    def test_raising_only_the_memory_limit_raises_the_swap_limit_with_it(self):
        for name in ("mas", "agent", "knowledge_store"):
            with self.subTest(name):
                key = MEMORY_REFERENCE.match(self.services[name]["mem_limit"]).group(1)
                self.assertEqual(self.limits(name, {key: "20g"}), ("20g", "20g"))

    def test_no_memory_limit_alone_leaves_the_swap_limit_below_it(self):
        for name in ("mas", "agent", "knowledge_store"):
            key = MEMORY_REFERENCE.match(self.services[name]["mem_limit"]).group(1)
            for gigabytes in (4, 8, 16, 17, 24, 32, 64):
                with self.subTest(f"{name} {key}={gigabytes}g"):
                    limit, swap = self.limits(name, {key: f"{gigabytes}g"})
                    self.assertGreaterEqual(int(swap.rstrip("g")), int(limit.rstrip("g")))

    def test_a_swap_limit_set_in_the_env_still_wins(self):
        for name in ("mas", "agent", "knowledge_store"):
            with self.subTest(name):
                spec = self.services[name]
                key = MEMORY_REFERENCE.match(spec["mem_limit"]).group(1)
                swap_key = SWAP_REFERENCE.match(spec["memswap_limit"]).group(1)
                self.assertNotEqual(swap_key, key)
                self.assertEqual(self.limits(name, {key: "16g", swap_key: "20g"}),
                                 ("16g", "20g"))

    def test_every_memory_ceiling_a_profile_writes_is_read_by_compose(self):
        read = {
            key
            for services in (self.services, cpu_overlay_services())
            for spec in services.values()
            for field in ("mem_limit", "memswap_limit") if field in spec
            for key in referenced_keys(str(spec[field]))
        }
        written = {key for key in profiles.MANAGED_KEYS
                   if key.endswith(("_MEM_LIMIT", "_MEMSWAP_LIMIT"))}
        self.assertTrue(written)
        self.assertLessEqual(written, read)

@needs_yaml
class ComposeHealthchecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.services = compose_services()
        cls.built = {name: spec for name, spec in cls.services.items() if "build" in spec}

    def test_the_app_services_are_the_ones_built_from_source(self):
        self.assertEqual(set(self.built), SOURCE_BUILT_SERVICES)

    def test_every_app_service_declares_a_healthcheck(self):
        for name, spec in self.built.items():
            with self.subTest(name):
                self.assertIn("healthcheck", spec, f"{name} declares no healthcheck")
                self.assertTrue(probe_command(spec["healthcheck"]))

    def test_every_service_the_installer_waits_for_declares_a_healthcheck(self):
        for name in [*horus_install.CORE_SERVICES, "vllm"]:
            with self.subTest(name):
                self.assertIn("healthcheck", self.services[name],
                              f"the installer waits on {name}, which never reports health")

    def test_app_healthchecks_allow_a_slow_first_start(self):
        for name, spec in self.built.items():
            with self.subTest(name):
                period = duration_seconds(spec["healthcheck"].get("start_period", "0s"))
                self.assertGreaterEqual(period, 120)

    def test_each_probe_uses_a_tool_its_image_ships(self):
        for name, spec in self.built.items():
            with self.subTest(name):
                build = spec["build"]
                dockerfile = INFRA / build["context"] / build.get("dockerfile", "Dockerfile")
                base, stage = final_stage(dockerfile)
                tool = probe_command(spec["healthcheck"])[0]
                self.assertTrue(image_ships(tool, base, stage),
                                f"{name} probes with {tool}, which its {base} image lacks")

    def test_each_probe_targets_the_port_its_service_listens_on(self):
        for name, spec in self.built.items():
            with self.subTest(name):
                probe = " ".join(probe_command(spec["healthcheck"]))
                ports = set(re.findall(r"//(?:localhost|127\.0\.0\.1):(\d+)/", probe))
                self.assertTrue(ports, f"{name} probe has no local URL: {probe}")
                self.assertLessEqual(ports, container_ports(spec))

    def test_app_services_wait_for_dependencies_to_be_healthy(self):
        for name, spec in self.built.items():
            for dependency, condition in dependency_conditions(spec).items():
                if "healthcheck" not in self.services[dependency]:
                    continue
                with self.subTest(f"{name} -> {dependency}"):
                    self.assertEqual(condition, "service_healthy")

KNOWLEDGE_STORE_APP = REPO / "src" / "services" / "knowledge-store" / "app"

def knowledge_store_settings() -> set[str]:
    names: set[str] = set()
    for source in KNOWLEDGE_STORE_APP.rglob("*.py"):
        names.update(re.findall(r"\"(KNOWLEDGE_STORE_[A-Z_]+)\"", source.read_text(encoding="utf-8")))
    return names

@needs_yaml
class ComposeKnowledgeStoreSettings(unittest.TestCase):
    def test_every_setting_the_knowledge_store_reads_reaches_its_container(self):
        spec = compose_services()["knowledge_store"]
        self.assertNotIn("env_file", spec)
        passed = {entry.split("=", 1)[0] for entry in spec["environment"]}
        settings = knowledge_store_settings()
        self.assertTrue(settings)
        self.assertEqual(settings - passed, set())

def cpu_overlay_services() -> dict:
    loader = type("ComposeOverlayLoader", (yaml.SafeLoader,), {})
    loader.add_constructor("!reset", lambda _loader, _node: None)
    text = (INFRA / "docker-compose.cpu.yml").read_text(encoding="utf-8")
    return yaml.load(text, Loader=loader)["services"]

@needs_yaml
class ComposeAgentWaitsForVllm(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vllm_rule = (compose_services()["agent"].get("depends_on") or {}).get("vllm")

    def test_on_gpu_the_agent_starts_once_vllm_is_healthy(self):
        self.assertIsNotNone(self.vllm_rule, "the agent does not wait for vllm")
        self.assertEqual(self.vllm_rule.get("condition"), "service_healthy")

    def test_the_dependency_is_optional_so_the_cpu_overlay_still_starts(self):
        self.assertIsNotNone(self.vllm_rule, "the agent does not wait for vllm")
        self.assertIs(self.vllm_rule.get("required"), False)

    def test_the_cpu_overlay_keeps_vllm_out_of_the_stack(self):
        vllm = cpu_overlay_services()["vllm"]
        self.assertEqual(vllm.get("profiles"), ["gpu"])
        self.assertEqual(vllm["deploy"]["replicas"], 0)

if __name__ == "__main__":
    unittest.main()
