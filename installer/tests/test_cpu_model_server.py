from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parent.parent.parent
INFRA = REPO / "src" / "infra"
OBSERVABILITY = INFRA / "observability"
MANIFEST = REPO / "models" / "manifest.json"
FETCH_SCRIPT = INFRA / "llm" / "fetch-model.sh"
CONVERT_SCRIPT = REPO / "scripts" / "models" / "convert-qwen3-4b-gguf.sh"
MODELS_README = REPO / "scripts" / "models" / "README.md"
sys.path.insert(0, str(REPO / "installer"))
import model_manager  # noqa: E402
import profiles  # noqa: E402
from common import Log  # noqa: E402

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the compose file")
needs_shell = unittest.skipUnless(
    all(shutil.which(tool) for tool in ("sh", "curl", "sha256sum", "stat")),
    "needs sh, curl, sha256sum and stat to run the fetch script",
)

INNERMOST_DEFAULT = re.compile(r"\$\{(\w+):-([^${}]*)\}")

LLAMA_SERVER_TAG = re.compile(r"^ghcr\.io/ggml-org/llama\.cpp:server-b(\d+)$")

def interpolate(value, env: dict[str, str]) -> str:
    value = str(value)
    while True:
        resolved = INNERMOST_DEFAULT.sub(lambda m: env.get(m.group(1)) or m.group(2), value)
        if resolved == value:
            return resolved
        value = resolved

def load_compose(name: str) -> dict:
    loader = type("ComposeOverlayLoader", (yaml.SafeLoader,), {})
    loader.add_constructor("!reset", lambda _loader, _node: None)
    return yaml.load((INFRA / name).read_text(encoding="utf-8"), Loader=loader)

def environment(spec: dict) -> dict[str, str]:
    return dict(entry.split("=", 1) for entry in spec.get("environment", []))

def flag_values(command: list, env: dict[str, str]) -> dict[str, str | None]:
    resolved = [interpolate(item, env) for item in command]
    values: dict[str, str | None] = {}
    for index, item in enumerate(resolved):
        if not item.startswith("--"):
            continue
        following = resolved[index + 1] if index + 1 < len(resolved) else None
        values[item] = None if following is None or following.startswith("--") else following
    return values

def depends(spec: dict) -> dict[str, dict]:
    return spec.get("depends_on") or {}

@needs_yaml
class CpuOverlayRunsLlamaServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = load_compose(profiles.BASE_COMPOSE)
        cls.overlay = load_compose(profiles.CPU_OVERLAY)
        cls.llm = cls.overlay["services"]["llm"]
        cls.fetch = cls.overlay["services"]["llm-model"]
        cls.cpu_env = profiles.env_for("cpu-standard", {"cpu": {"physical_cores": 6}})

    def flags(self, env: dict[str, str] | None = None) -> dict[str, str | None]:
        return flag_values(self.llm["command"], self.cpu_env if env is None else env)

    def test_the_llm_service_exists_only_in_the_cpu_overlay(self):
        self.assertNotIn("llm", self.base["services"])
        self.assertNotIn("llm-model", self.base["services"])
        self.assertIn("vllm", self.base["services"])

    def test_the_image_is_pinned_to_a_llama_cpp_build(self):
        for name in ("llm", "llm-model"):
            with self.subTest(name):
                image = interpolate(self.overlay["services"][name]["image"], {})
                self.assertRegex(image, LLAMA_SERVER_TAG)

    def test_the_port_is_not_published_and_stays_on_horus_net(self):
        self.assertNotIn("ports", self.llm)
        self.assertEqual(self.llm["networks"], ["horus-net"])

    def test_the_server_flags_follow_the_plan(self):
        flags = self.flags()
        self.assertEqual(flags["--model"], "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf")
        self.assertEqual(flags["--host"], "0.0.0.0")
        self.assertEqual(flags["--parallel"], "1")
        self.assertEqual(flags["--load-mode"], "mmap")
        self.assertEqual(flags["--cache-ram"], "1024")
        self.assertEqual(flags["--cache-type-k"], "f16")
        self.assertEqual(flags["--cache-type-v"], "f16")
        self.assertEqual(flags["--flash-attn"], "auto")
        self.assertIn("--metrics", flags)
        self.assertNotIn("--api-key", flags)
        self.assertNotIn("--api-key-file", flags)

    def test_cpu_lean_runs_the_same_model_with_the_adr_006_option_b_flags(self):
        lean = profiles.env_for("cpu-lean", {"cpu": {"physical_cores": 4}})
        flags = self.flags(lean)
        self.assertEqual(flags["--model"], self.flags()["--model"])
        self.assertEqual(flags["--ctx-size"], "4096")
        self.assertEqual(flags["--cache-type-k"], "q8_0")
        self.assertEqual(flags["--cache-type-v"], "q8_0")
        self.assertEqual(flags["--flash-attn"], "on")
        self.assertEqual(flags["--cache-ram"], "256")
        self.assertEqual(interpolate(self.llm["mem_limit"], lean), "5g")

    def test_every_server_setting_a_profile_writes_reaches_the_command(self):
        read = set(re.findall(r"\$\{(\w+)", " ".join(map(str, self.llm["command"]))))
        self.assertLessEqual(set(profiles.SERVER_KEYS), read)
        for name in ("cpu-lean", "cpu-standard"):
            with self.subTest(name):
                self.assertLessEqual(set(profiles.SERVER_KEYS), set(profiles.env_for(name)))

    def test_without_the_installer_the_server_runs_like_cpu_standard(self):
        defaults = self.flags({})
        for key, flag in (("LLM_SERVER_CACHE_TYPE_K", "--cache-type-k"),
                          ("LLM_SERVER_CACHE_TYPE_V", "--cache-type-v"),
                          ("LLM_SERVER_FLASH_ATTN", "--flash-attn"),
                          ("LLM_SERVER_CACHE_RAM_MIB", "--cache-ram"),
                          ("LLM_VLLM_MAX_MODEL_LEN", "--ctx-size")):
            with self.subTest(key):
                self.assertEqual(defaults[flag], self.cpu_env[key])

    def test_the_clients_reach_the_server_at_its_service_name_and_port(self):
        self.assertEqual(self.cpu_env["LLM_VLLM_URL"], f"http://llm:{self.flags()['--port']}/v1")

    def test_the_alias_and_context_are_the_values_the_clients_use(self):
        flags = self.flags()
        self.assertEqual(flags["--alias"], self.cpu_env["LLM_VLLM_MODEL"])
        self.assertEqual(flags["--ctx-size"], self.cpu_env["LLM_VLLM_MAX_MODEL_LEN"])
        self.assertEqual(flags["--ctx-size"], "8192")

    def test_the_server_threads_are_the_physical_cores_the_installer_detected(self):
        self.assertEqual(self.flags()["--threads"], "6")
        self.assertEqual(self.flags({})["--threads"], str(profiles.PHYSICAL_CORES_FALLBACK))

    def test_the_memory_ceiling_defaults_to_six_gib_and_follows_the_env(self):
        limits = (self.llm["mem_limit"], self.llm["memswap_limit"])
        self.assertEqual(tuple(interpolate(v, {}) for v in limits), ("6g", "6g"))
        raised = {"LLM_SERVER_MEM_LIMIT": "8g"}
        self.assertEqual(tuple(interpolate(v, raised) for v in limits), ("8g", "8g"))
        self.assertEqual(interpolate(self.llm["mem_limit"], self.cpu_env), "6g")

    def test_the_healthcheck_probes_health_with_a_long_start_period(self):
        check = self.llm["healthcheck"]
        self.assertEqual(check["test"][:2], ["CMD", "curl"])
        self.assertIn("http://localhost:8080/health", check["test"])
        self.assertGreaterEqual(int(check["start_period"].rstrip("s")), 300)

    def test_mas_and_the_agent_wait_for_a_healthy_llm_on_cpu_only(self):
        for name in ("mas", "agent"):
            with self.subTest(name):
                rule = depends(self.overlay["services"][name]).get("llm")
                self.assertEqual(rule, {"condition": "service_healthy"})
                self.assertNotIn("llm", depends(self.base["services"][name]))

    def test_the_gpu_stack_keeps_the_agent_waiting_for_vllm(self):
        self.assertEqual(depends(self.base["services"]["agent"])["vllm"]["condition"],
                         "service_healthy")

    def models_mount(self, spec: dict, env: dict[str, str]) -> tuple[str, str]:
        mounts = [interpolate(m, env) for m in spec["volumes"] if "/models" in m]
        self.assertEqual(len(mounts), 1, spec["volumes"])
        source, _, rest = mounts[0].rpartition(":/models")
        return source, "/models" + rest

    def test_the_server_reads_the_host_models_folder_read_only(self):
        self.assertEqual(self.models_mount(self.llm, {}), ("../../models", "/models:ro"))
        self.assertEqual((INFRA / "../../models").resolve(), MANIFEST.parent.resolve())
        self.assertNotIn("volumes", self.overlay)

    def test_the_fallback_fetches_into_the_same_folder_before_the_server_starts(self):
        self.assertEqual(depends(self.llm)["llm-model"]["condition"],
                         "service_completed_successfully")
        for env in ({}, {"HORUS_MODELS_DIR": "D:/horus-models"}):
            with self.subTest(env=env):
                source, target = self.models_mount(self.fetch, env)
                self.assertEqual(target, "/models")
                self.assertEqual(source, self.models_mount(self.llm, env)[0])
                self.assertEqual(source, env.get("HORUS_MODELS_DIR", "../../models"))

    def test_the_fetched_file_is_the_one_the_server_loads(self):
        for env in ({}, {"LLM_GGUF_FILE": "own.gguf"}):
            with self.subTest(env=env):
                fetched = interpolate(environment(self.fetch)["LLM_GGUF_FILE"], env)
                self.assertEqual(self.flags({**self.cpu_env, **env})["--model"],
                                 f"/models/{fetched}")

    def test_the_fallback_defaults_are_the_manifest_cpu_model(self):
        manifest = model_manager.load_manifest(MANIFEST)
        entry = manifest.default_for("cpu-standard")
        defaults = {key: interpolate(value, {}) for key, value in environment(self.fetch).items()}
        self.assertEqual(defaults["LLM_GGUF_FILE"], entry.file)
        self.assertEqual(defaults["LLM_GGUF_URL"], manifest.mirrors_for(entry)[0])
        self.assertEqual(defaults["LLM_GGUF_SHA256"], entry.sha256)
        self.assertEqual(int(defaults["LLM_GGUF_SIZE"]), entry.size_bytes)
        self.assertEqual(self.flags({})["--model"], f"/models/{entry.file}")

    def test_the_installer_values_reach_the_fallback_and_the_server(self):
        plan = model_manager.plan_for_profile(REPO, "cpu-standard")
        written = plan.env(REPO)
        fetch_env = {key: interpolate(value, written)
                     for key, value in environment(self.fetch).items()}
        for key in ("LLM_GGUF_FILE", "LLM_GGUF_URL", "LLM_GGUF_SHA256", "LLM_GGUF_SIZE"):
            self.assertEqual(fetch_env[key], written[key])
        self.assertEqual(self.models_mount(self.llm, written)[0], written["HORUS_MODELS_DIR"])

    def test_the_fetch_service_has_no_server_healthcheck(self):
        self.assertIs(self.fetch["healthcheck"].get("disable"), True)
        self.assertNotIn("restart", self.fetch)

    def test_the_fetch_script_is_mounted_from_the_infra_folder(self):
        mounts = [m for m in self.fetch["volumes"] if m.endswith(":ro")]
        source, target = mounts[0].split(":")[:2]
        self.assertEqual((INFRA / source).resolve(), FETCH_SCRIPT.resolve())
        self.assertEqual(self.fetch["entrypoint"], ["/bin/sh", target])

    def test_the_download_is_pinned_by_revision_size_and_hash(self):
        env = {key: interpolate(value, {}) for key, value in environment(self.fetch).items()}
        self.assertRegex(env["LLM_GGUF_URL"], r"/resolve/[0-9a-f]{40}/")
        self.assertRegex(env["LLM_GGUF_SHA256"], r"^[0-9a-f]{64}$")
        self.assertEqual(int(env["LLM_GGUF_SIZE"]), profiles.GGUF_BYTES)

    def test_the_readme_records_the_size_and_hash_the_stack_checks(self):
        env = {key: interpolate(value, {}) for key, value in environment(self.fetch).items()}
        readme = MODELS_README.read_text(encoding="utf-8")
        self.assertIn(env["LLM_GGUF_SHA256"], readme)
        self.assertIn(env["LLM_GGUF_SIZE"], readme)
        self.assertIn(interpolate(self.llm["image"], {}), readme)

    def test_the_conversion_script_uses_the_same_llama_cpp_build(self):
        build = LLAMA_SERVER_TAG.match(interpolate(self.llm["image"], {})).group(1)
        script = CONVERT_SCRIPT.read_text(encoding="utf-8")
        self.assertIn(f"ghcr.io/ggml-org/llama.cpp:full-b{build}", script)
        self.assertIn("--convert", script)
        self.assertIn("Q4_K_M", script)
        self.assertIn("sha256sum", script)

    def test_on_cpu_mas_and_the_agent_default_to_the_profile_ceilings_without_swap(self):
        for name, key in (("mas", "MAS_MEM_LIMIT"), ("agent", "AGENT_MEM_LIMIT")):
            with self.subTest(name):
                spec = self.overlay["services"][name]
                limits = (interpolate(spec["mem_limit"], {}),
                          interpolate(spec["memswap_limit"], {}))
                self.assertEqual(limits, (self.cpu_env[key], self.cpu_env[key]))

    def test_every_ceiling_a_cpu_profile_writes_is_read_by_the_cpu_stack(self):
        read = set()
        for document in (self.base, self.overlay):
            for spec in document["services"].values():
                for field in ("mem_limit", "memswap_limit"):
                    read |= set(re.findall(r"\$\{(\w+)", str(spec.get(field, ""))))
        written = {key for key in self.cpu_env if key.endswith("_MEM_LIMIT")}
        self.assertEqual(len(written), 4)
        self.assertLessEqual(written, read)

def glob_matches(pattern: str, path: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) and "/" not in path[pattern.rfind("/") + 1:]

@needs_yaml
class PrometheusScrapesLlamaServerOnCpuOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = load_compose(profiles.BASE_COMPOSE)
        cls.overlay = load_compose(profiles.CPU_OVERLAY)
        cls.config = yaml.safe_load((OBSERVABILITY / "prometheus.yaml").read_text(encoding="utf-8"))

    def cpu_mount(self) -> tuple[str, str]:
        mounts = self.overlay["services"]["prometheus"]["volumes"]
        self.assertEqual(len(mounts), 1, mounts)
        source, target, mode = mounts[0].split(":")
        self.assertEqual(mode, "ro")
        return source, target

    def test_prometheus_reads_extra_jobs_from_the_folder_the_cpu_overlay_fills(self):
        _, target = self.cpu_mount()
        patterns = self.config["scrape_config_files"]
        self.assertTrue(any(glob_matches(pattern, target) for pattern in patterns), patterns)

    def test_the_mounted_file_scrapes_llama_server_metrics(self):
        source, _ = self.cpu_mount()
        jobs = yaml.safe_load((INFRA / source).read_text(encoding="utf-8"))["scrape_configs"]
        self.assertEqual([job["job_name"] for job in jobs], ["llm"])
        port = flag_values(self.overlay["services"]["llm"]["command"], {})["--port"]
        self.assertEqual(jobs[0]["static_configs"], [{"targets": [f"llm:{port}"]}])
        self.assertEqual(jobs[0].get("metrics_path", "/metrics"), "/metrics")
        self.assertIn("--metrics", self.overlay["services"]["llm"]["command"])

    def test_the_gpu_stack_has_no_llm_target_to_report_down(self):
        base_mounts = self.base["services"]["prometheus"]["volumes"]
        _, target = self.cpu_mount()
        self.assertFalse(any(target in mount for mount in base_mounts), base_mounts)
        targets = [target for job in self.config["scrape_configs"]
                   for config in job.get("static_configs", []) for target in config["targets"]]
        self.assertFalse([t for t in targets if t.startswith(f"{profiles.CPU_MODEL_SERVER}:")])

def run_fetch(models: Path, url: str, sha256: str, size: int,
              attempts: int = 2) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "LLM_MODELS_DIR": models.as_posix(),
        "LLM_GGUF_FILE": "model.gguf",
        "LLM_GGUF_URL": url,
        "LLM_GGUF_SHA256": sha256,
        "LLM_GGUF_SIZE": str(size),
        "LLM_GGUF_ATTEMPTS": str(attempts),
        "LLM_GGUF_RETRY_SECONDS": "0",
        "HF_TOKEN": "",
    }
    return subprocess.run(["sh", str(FETCH_SCRIPT)], env=env, capture_output=True,
                          text=True, timeout=120)

@needs_shell
class FetchScript(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.models = root / "models"
        self.models.mkdir()
        self.payload = os.urandom(300_000)
        self.source = root / "source.gguf"
        self.source.write_bytes(self.payload)
        self.url = self.source.as_uri()
        self.sha = hashlib.sha256(self.payload).hexdigest()
        self.target = self.models / "model.gguf"

    def fetch(self, url: str | None = None, sha: str | None = None,
              attempts: int = 2) -> subprocess.CompletedProcess:
        return run_fetch(self.models, url or self.url, sha or self.sha, len(self.payload),
                         attempts)

    def test_a_fresh_download_is_verified_then_put_in_place(self):
        result = self.fetch()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual((self.models / "model.gguf.sha256").read_text().strip(), self.sha)
        self.assertFalse((self.models / "model.gguf.part").exists())

    def test_a_file_with_the_wrong_hash_is_deleted_and_the_start_fails(self):
        result = self.fetch(sha="0" * 64)
        self.assertEqual(result.returncode, 1)
        self.assertIn("SHA-256", result.stdout)
        self.assertFalse(self.target.exists())
        self.assertFalse((self.models / "model.gguf.part").exists())

    def test_a_verified_file_is_not_downloaded_again(self):
        self.assertEqual(self.fetch().returncode, 0)
        missing = (Path(self._tmp.name) / "gone.gguf").as_uri()
        result = self.fetch(url=missing)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("verified before", result.stdout)

    def test_an_interrupted_download_resumes_from_what_arrived(self):
        (self.models / "model.gguf.part").write_bytes(self.payload[:100_000])
        result = self.fetch()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("100000 already here", result.stdout)
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_a_file_copied_into_the_volume_is_checked_instead_of_downloaded(self):
        self.target.write_bytes(self.payload)
        missing = (Path(self._tmp.name) / "gone.gguf").as_uri()
        result = self.fetch(url=missing)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.models / "model.gguf.sha256").read_text().strip(), self.sha)

    def test_a_different_file_in_the_volume_is_replaced(self):
        self.target.write_bytes(b"x" * len(self.payload))
        result = self.fetch()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_a_file_the_installer_verified_is_used_without_a_download(self):
        entry = model_manager.ModelEntry(
            id="m", version="1", file="model.gguf", size_bytes=len(self.payload),
            sha256=self.sha, min_ram_gb=0, profiles=(), mirrors=())
        self.target.write_bytes(self.payload)
        with tempfile.TemporaryDirectory() as name:
            log = Log(Path(name) / "install-log.txt")
            with contextlib.redirect_stdout(io.StringIO()):
                model_manager.ModelDownload(log, entry, self.models, []).run()
            log.close(0)
        missing = (Path(self._tmp.name) / "gone.gguf").as_uri()
        result = self.fetch(url=missing)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("verified before", result.stdout)

    def test_a_download_that_keeps_failing_stops_after_its_attempts(self):
        missing = (Path(self._tmp.name) / "gone.gguf").as_uri()
        result = self.fetch(url=missing, attempts=2)
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed 2 times", result.stdout)
        self.assertFalse(self.target.exists())

if __name__ == "__main__":
    unittest.main()
