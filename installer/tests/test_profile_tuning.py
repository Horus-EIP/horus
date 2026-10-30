from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
REPO = Path(__file__).resolve().parents[2]

import common  # noqa: E402
import hardware  # noqa: E402
import horus_install  # noqa: E402
import model_manager  # noqa: E402
import profiles  # noqa: E402
from common import Log  # noqa: E402

CPU_PROFILES = [name for name in profiles.PROFILE_ORDER if profiles.is_cpu_profile(name)]
GPU_PROFILES = [name for name in profiles.PROFILE_ORDER if not profiles.is_cpu_profile(name)]
MEMORY_KEYS = ("MAS_MEM_LIMIT", "AGENT_MEM_LIMIT", "KNOWLEDGE_STORE_MEM_LIMIT",
               "LLM_SERVER_MEM_LIMIT")
SWAP_KEYS = ("MAS_MEMSWAP_LIMIT", "AGENT_MEMSWAP_LIMIT", "KNOWLEDGE_STORE_MEMSWAP_LIMIT",
             "LLM_SERVER_MEMSWAP_LIMIT")
IN_PROCESS_MODEL_KEYS = ("LLM_MODEL_ID", "MODEL_NAME")
GIB = 1024 ** 3
KV_BYTES = {"f16": 2.0, "q8_0": 34 / 32}

def cpu_probe(physical: int | None, logical: int | None = None,
              logical_fallback: bool = False) -> dict:
    return {"cpu": {"physical_cores": physical, "logical_cores": logical,
                    "count_is_logical_fallback": logical_fallback}}

def thread_env(physical: int | None, **kwargs) -> tuple[int, int, int]:
    env = profiles.env_for("cpu-standard", cpu_probe(physical, **kwargs))
    return (int(env["LLM_SERVER_THREADS"]),
            int(env["LLM_TORCH_INTRAOP_THREADS"]),
            int(env["AGENT_TORCH_INTRAOP_THREADS"]))

def gib(value: str) -> int:
    assert value.endswith("g"), value
    return int(value[:-1])

class ThreadBudget(unittest.TestCase):
    def test_llama_server_gets_every_physical_core(self):
        for cores in range(1, 33):
            with self.subTest(cores=cores):
                self.assertEqual(thread_env(cores)[0], cores)

    def test_mas_and_the_agent_keep_one_torch_thread_each(self):
        for cores in range(1, 33):
            with self.subTest(cores=cores):
                self.assertEqual(thread_env(cores)[1:], (1, 1))

    def test_an_eight_core_machine_gives_llama_server_eight_threads(self):
        self.assertEqual(thread_env(8), (8, 1, 1))

    def test_a_logical_only_count_is_halved_before_it_reaches_llama_server(self):
        self.assertEqual(thread_env(16, logical=16, logical_fallback=True), (8, 1, 1))

    def test_an_unknown_core_count_falls_back_to_four_cores(self):
        for probe in (None, {}, {"cpu": {}}, cpu_probe(None), cpu_probe(0)):
            with self.subTest(probe=probe):
                env = profiles.env_for("cpu-lean", probe)
                self.assertEqual(env["LLM_SERVER_THREADS"], "4")
                self.assertEqual(env["LLM_TORCH_INTRAOP_THREADS"], "1")
                self.assertEqual(env["AGENT_TORCH_INTRAOP_THREADS"], "1")

    def test_every_cpu_profile_writes_all_three_thread_settings(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name, cpu_probe(6))
                self.assertEqual(
                    [env[key] for key in profiles.THREAD_KEYS], ["6", "1", "1"])

    def test_gpu_profiles_leave_the_thread_settings_to_the_code_default(self):
        for name in GPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name, cpu_probe(6))
                for key in profiles.THREAD_KEYS:
                    self.assertNotIn(key, env)

    def test_thread_settings_are_managed_so_a_gpu_reinstall_deactivates_them(self):
        for key in profiles.THREAD_KEYS:
            self.assertIn(key, profiles.MANAGED_KEYS)

    def test_the_provenance_explains_the_threads_with_the_detected_cores(self):
        provenance = profiles.provenance_for("cpu-standard", cpu_probe(12))
        server = provenance["LLM_SERVER_THREADS"]
        self.assertEqual(server["value"], "12")
        self.assertEqual(server["provenance"], profiles.DERIVED)
        self.assertIn("12 physical cores detected", server["why"])
        for key in ("LLM_TORCH_INTRAOP_THREADS", "AGENT_TORCH_INTRAOP_THREADS"):
            with self.subTest(key):
                self.assertIn("llama-server", provenance[key]["why"])

KNOWLEDGE_STORE = REPO / "src" / "services" / "knowledge-store"
MAS_EMBEDDER = REPO / "src" / "services" / "mas" / "core" / "embedding_setup.py"
CUDA_ONNXRUNTIME = "onnxruntime-gpu"

def requirement_projects(path: Path) -> set[str]:
    projects = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
        if match and not line.startswith("-"):
            projects.add(re.sub(r"[-_.]+", "-", match.group(0)).lower())
    return projects

def knowledge_store_images_can_embed_on_cuda() -> bool:
    return any(CUDA_ONNXRUNTIME in requirement_projects(path)
               for path in KNOWLEDGE_STORE.glob("requirements*.txt"))

class Embedders(unittest.TestCase):
    def test_no_profile_asks_for_a_cuda_embedder_the_knowledge_store_image_cannot_run(self):
        can_embed_on_cuda = knowledge_store_images_can_embed_on_cuda()
        for name in profiles.PROFILE_ORDER:
            with self.subTest(name):
                device = profiles.env_for(name).get("KNOWLEDGE_STORE_EMBED_DEVICE", "auto")
                self.assertFalse(device.startswith("cuda") and not can_embed_on_cuda)

    def test_the_8_gb_card_keeps_the_embedder_off_the_shared_card(self):
        self.assertEqual(profiles.env_for("gpu-8g")["KNOWLEDGE_STORE_EMBED_DEVICE"], "cpu")
        self.assertEqual(profiles.get("gpu-8g").confidence, profiles.MEASURED)

    def test_no_gpu_profile_says_the_embedder_is_on_the_card(self):
        for name in GPU_PROFILES:
            with self.subTest(name):
                self.assertNotIn("embedder back on the card", profiles.get(name).summary)

    def test_the_mas_thread_setting_is_explained_as_the_onnx_embedder_budget(self):
        source = MAS_EMBEDDER.read_text(encoding="utf-8")
        self.assertLess(source.index('"MAS_EMBED_THREADS"'),
                        source.index('"LLM_TORCH_INTRAOP_THREADS"'))
        for name in CPU_PROFILES:
            why = profiles.provenance_for(name)["LLM_TORCH_INTRAOP_THREADS"]["why"]
            with self.subTest(name):
                self.assertIn("MAS_EMBED_THREADS", why)
                self.assertIn("ONNX Runtime", why)
                self.assertNotIn("Its torch", why)

    def test_no_cpu_reason_puts_torch_in_mas_or_the_agent(self):
        for name in CPU_PROFILES:
            provenance = profiles.provenance_for(name)
            for key in ("MAS_MEM_LIMIT", "AGENT_MEM_LIMIT", "AGENT_TORCH_INTRAOP_THREADS"):
                with self.subTest(f"{name} {key}"):
                    self.assertIn("no torch", provenance[key]["why"])

class CpuModelServer(unittest.TestCase):
    def test_cpu_profiles_point_both_clients_at_llama_server(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name)
                self.assertEqual(env["LLM_BACKEND"], "vllm")
                self.assertEqual(env["LLM_VLLM_URL"], "http://llm:8080/v1")
                self.assertEqual(env["LLM_VLLM_MODEL"], "qwen3-4b")
                self.assertEqual(env["LLM_VLLM_TIMEOUT"], "900")

    def test_cpu_standard_keeps_the_8k_context_and_cpu_lean_halves_it(self):
        self.assertEqual(profiles.env_for("cpu-standard")["LLM_VLLM_MAX_MODEL_LEN"], "8192")
        self.assertEqual(profiles.env_for("cpu-lean")["LLM_VLLM_MAX_MODEL_LEN"], "4096")

    def test_cpu_profiles_configure_no_local_model(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name, cpu_probe(8))
                for key in IN_PROCESS_MODEL_KEYS:
                    self.assertNotIn(key, env)
                self.assertNotIn("transformers", env.values())
                self.assertEqual(profiles.model_server(name), "llm")

    def test_a_cpu_reinstall_deactivates_the_in_process_model_ids(self):
        for key in IN_PROCESS_MODEL_KEYS:
            self.assertIn(key, profiles.MANAGED_KEYS)

    def test_gpu_profiles_keep_vllm_and_its_timeout(self):
        for name in GPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name)
                self.assertEqual(env["LLM_VLLM_URL"], "http://vllm:8000/v1")
                self.assertNotIn("LLM_VLLM_TIMEOUT", env)
                self.assertNotIn("LLM_SERVER_THREADS", env)
                self.assertEqual(profiles.model_server(name), "vllm")

    def test_the_cpu_client_settings_are_derived_until_a_cpu_run(self):
        for name in CPU_PROFILES:
            provenance = profiles.provenance_for(name)
            for key in ("LLM_BACKEND", "LLM_VLLM_URL", "LLM_VLLM_MODEL",
                        "LLM_VLLM_MAX_MODEL_LEN", "LLM_VLLM_TIMEOUT"):
                with self.subTest(f"{name} {key}"):
                    self.assertEqual(provenance[key]["provenance"], profiles.DERIVED)

    def test_the_model_server_follows_the_compose_files(self):
        self.assertEqual(profiles.model_server_for_compose_file(
            f"{profiles.BASE_COMPOSE}:{profiles.CPU_OVERLAY}"), "llm")
        self.assertEqual(profiles.model_server_for_compose_file(
            f"{profiles.BASE_COMPOSE};{profiles.CPU_OVERLAY}"), "llm")
        self.assertEqual(profiles.model_server_for_compose_file(profiles.BASE_COMPOSE), "vllm")
        self.assertEqual(profiles.model_server_for_compose_file(""), "vllm")

class MemoryCeilings(unittest.TestCase):
    def test_every_cpu_profile_caps_each_python_service_and_the_model_server(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name)
                for key in MEMORY_KEYS:
                    self.assertRegex(env[key], r"^\d+g$")

    def test_profiles_leave_the_swap_ceiling_to_follow_the_memory_ceiling(self):
        for name in profiles.PROFILE_ORDER:
            with self.subTest(name):
                env = profiles.env_for(name)
                for key in SWAP_KEYS:
                    self.assertNotIn(key, env)

    def test_the_memory_reason_says_the_swap_ceiling_follows_it(self):
        for name in CPU_PROFILES:
            provenance = profiles.provenance_for(name)
            for key, swap_key in zip(MEMORY_KEYS, SWAP_KEYS, strict=True):
                with self.subTest(f"{name} {key}"):
                    self.assertIn(swap_key, provenance[key]["why"])
                    self.assertIn("never swaps", provenance[key]["why"])

    def test_a_hand_set_swap_ceiling_survives_a_reinstall(self):
        for key in SWAP_KEYS:
            self.assertNotIn(key, profiles.MANAGED_KEYS)

    def test_mas_and_the_agent_get_less_room_now_that_they_hold_no_model(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name)
                self.assertLess(gib(env["MAS_MEM_LIMIT"]), 14)
                self.assertLess(gib(env["AGENT_MEM_LIMIT"]), 6)

    def test_the_model_server_ceiling_holds_weights_kv_cache_and_prompt_cache(self):
        weights = profiles.GGUF_BYTES / GIB
        for name in CPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name)
                context = int(env["LLM_VLLM_MAX_MODEL_LEN"])
                kv_cache = sum(36 * 8 * 128 * KV_BYTES[env[key]] * context / GIB
                               for key in ("LLM_SERVER_CACHE_TYPE_K", "LLM_SERVER_CACHE_TYPE_V"))
                prompt_cache = int(env["LLM_SERVER_CACHE_RAM_MIB"]) / 1024
                ceiling = gib(env["LLM_SERVER_MEM_LIMIT"])
                self.assertGreater(ceiling, weights + kv_cache + prompt_cache + 0.5)

    def test_the_lean_model_server_needs_less_than_the_standard_one(self):
        lean, standard = profiles.env_for("cpu-lean"), profiles.env_for("cpu-standard")
        self.assertLess(gib(lean["LLM_SERVER_MEM_LIMIT"]), gib(standard["LLM_SERVER_MEM_LIMIT"]))
        self.assertLess(int(lean["LLM_SERVER_CACHE_RAM_MIB"]),
                        int(standard["LLM_SERVER_CACHE_RAM_MIB"]))

    def test_memory_ceilings_are_derived_and_explained(self):
        for name in CPU_PROFILES:
            provenance = profiles.provenance_for(name)
            for key in MEMORY_KEYS:
                with self.subTest(f"{name} {key}"):
                    self.assertEqual(provenance[key]["provenance"], profiles.DERIVED)
                    self.assertTrue(provenance[key]["why"])

    def test_gpu_profiles_keep_the_measured_configuration(self):
        for name in GPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name)
                for key in MEMORY_KEYS:
                    self.assertNotIn(key, env)
        self.assertEqual(profiles.get("gpu-8g").confidence, profiles.MEASURED)

    def test_memory_ceilings_are_managed_so_a_gpu_reinstall_deactivates_them(self):
        for key in MEMORY_KEYS:
            self.assertIn(key, profiles.MANAGED_KEYS)

PASSAGE_PROMPT_CHARS = 1060
AGENT_DEFAULT_CONTEXT_CHARS = 12000

class ShorterCpuPrompts(unittest.TestCase):
    def test_cpu_profiles_fetch_five_passages(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                self.assertEqual(profiles.env_for(name)["KNOWLEDGE_STORE_N_RESULTS"], "5")

    def test_every_profile_fits_its_passages_whole_under_the_context_cap(self):
        for name in profiles.PROFILE_ORDER:
            with self.subTest(name):
                env = profiles.env_for(name)
                cap = int(env.get("AGENT_MAX_CONTEXT_CHARS", AGENT_DEFAULT_CONTEXT_CHARS))
                passages = int(env["KNOWLEDGE_STORE_N_RESULTS"])
                self.assertLessEqual(passages * PASSAGE_PROMPT_CHARS, cap)

    def test_cpu_profiles_fetch_as_many_passages_as_their_cap_holds(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name)
                passages = int(env["KNOWLEDGE_STORE_N_RESULTS"])
                self.assertGreater(
                    (passages + 1) * PASSAGE_PROMPT_CHARS, int(env["AGENT_MAX_CONTEXT_CHARS"])
                )

    def test_cpu_profiles_cap_the_retrieved_context_at_six_thousand_characters(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                self.assertEqual(profiles.env_for(name)["AGENT_MAX_CONTEXT_CHARS"], "6000")

    def test_cpu_profiles_stream_the_answer_while_it_is_written(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                self.assertEqual(profiles.env_for(name)["AGENT_STREAM_TOKENS"], "1")

    def test_gpu_profiles_keep_ten_passages_and_the_code_defaults(self):
        for name in GPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name)
                self.assertEqual(env["KNOWLEDGE_STORE_N_RESULTS"], "10")
                self.assertNotIn("AGENT_MAX_CONTEXT_CHARS", env)
                self.assertNotIn("AGENT_STREAM_TOKENS", env)

    def test_the_shorter_prompt_settings_are_derived_until_the_test_set_runs(self):
        for name in CPU_PROFILES:
            provenance = profiles.provenance_for(name)
            for key in ("KNOWLEDGE_STORE_N_RESULTS", "AGENT_MAX_CONTEXT_CHARS",
                        "AGENT_STREAM_TOKENS"):
                with self.subTest(f"{name} {key}"):
                    self.assertEqual(provenance[key]["provenance"], profiles.DERIVED)

    def test_a_gpu_reinstall_deactivates_the_cpu_prompt_settings(self):
        for key in ("AGENT_MAX_CONTEXT_CHARS", "AGENT_STREAM_TOKENS"):
            self.assertIn(key, profiles.MANAGED_KEYS)

class DescribeShowsTheComputedSettings(unittest.TestCase):
    def test_describe_lists_thread_and_memory_settings_with_their_reasons(self):
        text = profiles.describe("cpu-standard", cpu_probe(8))
        self.assertRegex(text, r"LLM_SERVER_THREADS\s+= 8 ")
        self.assertRegex(text, r"LLM_TORCH_INTRAOP_THREADS\s+= 1 ")
        self.assertRegex(text, r"AGENT_TORCH_INTRAOP_THREADS\s+= 1 ")
        self.assertRegex(text, r"AGENT_MEM_LIMIT\s+= 4g ")
        self.assertRegex(text, r"LLM_SERVER_MEM_LIMIT\s+= 6g ")
        self.assertIn("8 physical cores detected", " ".join(text.split()))

    def test_describe_names_the_model_server_of_each_profile(self):
        self.assertIn("Model server:   llm (llama-server on the CPU)",
                      profiles.describe("cpu-standard"))
        self.assertIn("Model server:   vllm (GPU inference)", profiles.describe("gpu-8g"))

    def test_describe_all_still_renders_every_profile(self):
        text = profiles.describe_all()
        for name in profiles.PROFILE_ORDER:
            self.assertIn(f"Profile: {name}", text)

class LinuxPhysicalCores(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.log = Log(self.tmp / "install-log.txt")
        self.addCleanup(self.log.close, 0)

    def write_cpuinfo(self, blocks: list[dict[str, str]]) -> Path:
        path = self.tmp / "cpuinfo"
        text = "\n\n".join(
            "\n".join(f"{key}\t: {value}" for key, value in block.items())
            for block in blocks
        )
        path.write_text(text + "\n", encoding="utf-8")
        return path

    def write_sysfs(self, siblings: list[str]) -> Path:
        root = self.tmp / "cpu"
        for index, value in enumerate(siblings):
            topology = root / f"cpu{index}" / "topology"
            topology.mkdir(parents=True)
            (topology / "thread_siblings_list").write_text(value + "\n", encoding="utf-8")
        (root / "cpufreq").mkdir(parents=True)
        return root

    def test_hyperthreads_count_once_per_physical_core(self):
        blocks = [
            {"processor": str(n), "model name": "Test CPU",
             "physical id": "0", "core id": str(n % 4)}
            for n in range(8)
        ]
        cpuinfo = self.write_cpuinfo(blocks)
        model, count, _ = hardware._cpu_linux(self.log, cpuinfo, self.tmp / "none")
        self.assertEqual((model, count), ("Test CPU", 4))

    def test_two_sockets_count_their_cores_separately(self):
        blocks = [
            {"processor": str(n), "physical id": str(n // 4), "core id": str(n % 4)}
            for n in range(8)
        ]
        cpuinfo = self.write_cpuinfo(blocks)
        _, count, _ = hardware._cpu_linux(self.log, cpuinfo, self.tmp / "none")
        self.assertEqual(count, 8)

    def test_without_topology_in_cpuinfo_sysfs_siblings_are_counted(self):
        cpuinfo = self.write_cpuinfo([{"processor": str(n), "BogoMIPS": "50.00"}
                                      for n in range(8)])
        sysfs = self.write_sysfs(["0,4", "1,5", "2,6", "3,7", "0,4", "1,5", "2,6", "3,7"])
        _, count, source = hardware._cpu_linux(self.log, cpuinfo, sysfs)
        self.assertEqual(count, 4)
        self.assertIn("thread siblings", source)

    def test_an_unreadable_cpuinfo_still_reads_sysfs(self):
        sysfs = self.write_sysfs(["0", "1", "2", "3", "4", "5"])
        _, count, _ = hardware._cpu_linux(self.log, self.tmp / "missing", sysfs)
        self.assertEqual(count, 6)

    def test_with_neither_source_the_count_is_unknown(self):
        cpuinfo = self.write_cpuinfo([{"processor": "0"}])
        _, count, _ = hardware._cpu_linux(self.log, cpuinfo, self.tmp / "none")
        self.assertIsNone(count)

    def test_detect_cpu_falls_back_to_the_logical_count_and_says_so(self):
        with mock.patch.object(hardware.sys, "platform", "linux"), \
                mock.patch.object(hardware, "_cpu_linux", return_value=(None, None, "x")), \
                mock.patch.object(hardware.os, "cpu_count", return_value=12):
            info = hardware.detect_cpu(self.log)
        self.assertEqual(info["physical_cores"], 12)
        self.assertTrue(info["count_is_logical_fallback"])
        self.assertEqual(profiles.physical_cores({"cpu": info})[0], 6)

class InstallWritesTheTuning(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        (self.repo / "src" / "infra").mkdir(parents=True)
        (self.repo / "models").mkdir()
        shutil.copy(REPO / "models" / "manifest.json", self.repo / "models" / "manifest.json")
        self.log = Log(self.repo / "install-log.txt")
        self.addCleanup(self.log.close, 0)

    def install(self, profile: str, simulation: str) -> tuple[dict[str, str], dict]:
        args = horus_install.build_parser().parse_args(
            ["--profile", profile, "--non-interactive", "--skip-smoke"]
        )
        probe = dict(horus_install.SIMULATIONS[simulation])
        with contextlib.ExitStack() as stack:
            patch = stack.enter_context
            patch(mock.patch.object(horus_install, "find_repo", return_value=self.repo))
            patch(mock.patch.object(horus_install, "PROFILE_JSON",
                                    self.repo / "horus-profile.json"))
            patch(mock.patch.object(horus_install, "banner"))
            patch(mock.patch.object(horus_install, "existing_volumes", return_value=[]))
            self.preflight = patch(mock.patch.object(horus_install, "preflight"))
            consent = patch(mock.patch.object(horus_install, "consent"))
            consent.choose.return_value = {"corpus_dir": "../../demo_assets"}
            probe_machine = patch(mock.patch.object(horus_install.hardware, "probe"))
            probe_machine.return_value = probe
            write_json = patch(mock.patch.object(horus_install.hardware, "write_profile_json"))
            apply_env = patch(mock.patch.object(horus_install, "apply_env"))
            self.pull_and_build = patch(mock.patch.object(horus_install, "pull_and_build"))
            self.download_model = patch(mock.patch.object(horus_install, "download_model"))
            self.wait_for_health = patch(mock.patch.object(horus_install, "wait_for_health"))
            patch(mock.patch.object(horus_install, "_success"))
            patch(contextlib.redirect_stdout(io.StringIO()))
            code = horus_install._dispatch(self.log, args)
        self.assertEqual(code, common.EXIT_OK)
        return apply_env.call_args.args[2], write_json.call_args

    def test_a_cpu_install_writes_threads_from_the_detected_cores(self):
        env, _ = self.install("cpu-lean", "linux-cpu-8gb")
        self.assertEqual(env["LLM_SERVER_THREADS"], "4")
        self.assertEqual(env["LLM_TORCH_INTRAOP_THREADS"], "1")
        self.assertEqual(env["AGENT_TORCH_INTRAOP_THREADS"], "1")

    def test_only_a_cpu_install_checks_the_registry_of_the_llama_server_image(self):
        for profile, simulation, cpu_profile in (("cpu-standard", "nvidia-16gb", True),
                                                 ("gpu-8g", "nvidia-8gb", False)):
            with self.subTest(profile):
                self.install(profile, simulation)
                checks = self.preflight.run_install_checks.call_args
                self.assertIs(checks.kwargs["cpu_profile"], cpu_profile)

    def test_a_cpu_install_writes_the_memory_ceilings(self):
        env, _ = self.install("cpu-standard", "nvidia-16gb")
        self.assertEqual(env["MAS_MEM_LIMIT"], "3g")
        self.assertEqual(env["AGENT_MEM_LIMIT"], "4g")
        self.assertEqual(env["KNOWLEDGE_STORE_MEM_LIMIT"], "6g")
        self.assertEqual(env["LLM_SERVER_MEM_LIMIT"], "6g")
        self.assertEqual(env["LLM_SERVER_THREADS"], "8")

    def test_a_cpu_install_waits_for_llama_server_instead_of_vllm(self):
        self.install("cpu-standard", "nvidia-16gb")
        expect = self.wait_for_health.call_args.args[2]
        self.assertIn("llm", expect)
        self.assertNotIn("vllm", expect)

    def test_a_gpu_install_still_waits_for_vllm(self):
        self.install("gpu-8g", "nvidia-8gb")
        expect = self.wait_for_health.call_args.args[2]
        self.assertIn("vllm", expect)
        self.assertNotIn("llm", expect)

    def test_a_cpu_install_downloads_its_model_just_before_the_first_start(self):
        env, _ = self.install("cpu-standard", "nvidia-16gb")
        self.assertEqual(env["HORUS_MODELS_DIR"], "../../models")
        self.assertEqual(env["LLM_GGUF_FILE"], "qwen3-4b-instruct-2507-Q4_K_M.gguf")
        self.assertEqual(env["LLM_GGUF_SIZE"], str(profiles.GGUF_BYTES))
        before_start = self.pull_and_build.call_args.kwargs["before_start"]
        self.download_model.assert_not_called()
        with mock.patch.object(horus_install, "download_model") as download_model:
            before_start()
        plan = download_model.call_args.args[1]
        self.assertEqual(plan.entry.id, "qwen3-4b-q4km")
        self.assertEqual(plan.models_dir, self.repo / "models")

    def test_a_gpu_install_has_no_model_file_to_download(self):
        env, _ = self.install("gpu-8g", "nvidia-8gb")
        self.assertFalse(set(model_manager.MODEL_ENV_KEYS) & set(env))
        self.assertIsNone(self.pull_and_build.call_args.kwargs["before_start"])

    def test_a_small_machine_forced_onto_a_cpu_profile_is_warned_in_the_log(self):
        self.install("cpu-lean", "linux-cpu-8gb")
        self.log.close(0)
        text = (self.repo / "install-log.txt").read_text(encoding="utf-8")
        self.assertIn("forces a profile this machine is not supported for", text)
        self.assertIn("13.5 GiB", text)

    def test_the_profile_json_records_the_model_file_it_installs(self):
        _, written = self.install("cpu-standard", "nvidia-16gb")
        expected = model_manager.load_manifest(REPO / "models" / "manifest.json")
        self.assertEqual(written.args[3]["LLM_GGUF_SHA256"],
                         expected.default_for("cpu-standard").sha256)

    def test_the_profile_json_receives_the_probe_the_threads_came_from(self):
        _, written = self.install("cpu-lean", "linux-cpu-8gb")
        probe, name = written.args[1], written.args[2]
        self.assertEqual(name, "cpu-lean")
        provenance = profiles.provenance_for(name, probe)
        self.assertIn("4 physical cores detected",
                      provenance["LLM_SERVER_THREADS"]["why"])

class ProfileJsonRecordsTheComputedSettings(unittest.TestCase):
    def test_the_written_provenance_matches_the_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "horus-profile.json"
            probe = cpu_probe(10)
            env = profiles.env_for("cpu-standard", probe)
            hardware.write_profile_json(path, probe, "cpu-standard", env, ["test"])
            document = json.loads(path.read_text(encoding="utf-8"))
        provenance = document["tuning_provenance"]
        self.assertEqual(provenance["LLM_SERVER_THREADS"]["value"], "10")
        self.assertEqual(provenance["LLM_TORCH_INTRAOP_THREADS"]["value"], "1")
        self.assertEqual(provenance["AGENT_TORCH_INTRAOP_THREADS"]["value"], "1")
        self.assertIn("LLM_SERVER_THREADS", document["derived_settings"])
        self.assertEqual(document["profile"]["model_server"], "llm")

if __name__ == "__main__":
    unittest.main()
