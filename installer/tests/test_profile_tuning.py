from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import hardware  # noqa: E402
import horus_install  # noqa: E402
import profiles  # noqa: E402
from common import Log  # noqa: E402

CPU_PROFILES = [name for name in profiles.PROFILE_ORDER if profiles.is_cpu_profile(name)]
GPU_PROFILES = [name for name in profiles.PROFILE_ORDER if not profiles.is_cpu_profile(name)]
MEMORY_KEYS = ("AGENT_MEM_LIMIT", "KNOWLEDGE_STORE_MEM_LIMIT")
SWAP_KEYS = ("AGENT_MEMSWAP_LIMIT", "KNOWLEDGE_STORE_MEMSWAP_LIMIT")

def cpu_probe(physical: int | None, logical: int | None = None,
              logical_fallback: bool = False) -> dict:
    return {"cpu": {"physical_cores": physical, "logical_cores": logical,
                    "count_is_logical_fallback": logical_fallback}}

def thread_env(physical: int | None, **kwargs) -> tuple[int, int]:
    env = profiles.env_for("cpu-standard", cpu_probe(physical, **kwargs))
    return (int(env["LLM_TORCH_INTRAOP_THREADS"]),
            int(env["AGENT_TORCH_INTRAOP_THREADS"]))

def gib(value: str) -> int:
    assert value.endswith("g"), value
    return int(value[:-1])

class ThreadBudget(unittest.TestCase):
    def test_router_and_worker_threads_add_up_to_the_physical_cores(self):
        for cores in range(2, 33):
            with self.subTest(cores=cores):
                self.assertEqual(sum(thread_env(cores)), cores)

    def test_the_router_gets_fewer_threads_than_the_worker(self):
        for cores in range(3, 33):
            with self.subTest(cores=cores):
                router, worker = thread_env(cores)
                self.assertLess(router, worker)

    def test_a_single_core_still_gives_each_service_one_thread(self):
        self.assertEqual(thread_env(1), (1, 1))

    def test_an_eight_core_machine_gives_the_router_two_threads(self):
        self.assertEqual(thread_env(8), (2, 6))

    def test_a_logical_only_count_is_halved_before_splitting(self):
        self.assertEqual(thread_env(16, logical=16, logical_fallback=True), (2, 6))

    def test_an_unknown_core_count_falls_back_to_four_cores(self):
        for probe in (None, {}, {"cpu": {}}, cpu_probe(None), cpu_probe(0)):
            with self.subTest(probe=probe):
                env = profiles.env_for("cpu-lean", probe)
                self.assertEqual(env["LLM_TORCH_INTRAOP_THREADS"], "1")
                self.assertEqual(env["AGENT_TORCH_INTRAOP_THREADS"], "3")

    def test_every_cpu_profile_writes_both_thread_settings(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name, cpu_probe(6))
                self.assertEqual(env["LLM_TORCH_INTRAOP_THREADS"], "2")
                self.assertEqual(env["AGENT_TORCH_INTRAOP_THREADS"], "4")

    def test_gpu_profiles_leave_the_thread_settings_to_the_code_default(self):
        for name in GPU_PROFILES:
            with self.subTest(name):
                env = profiles.env_for(name, cpu_probe(6))
                for key in profiles.THREAD_KEYS:
                    self.assertNotIn(key, env)

    def test_thread_settings_are_managed_so_a_gpu_reinstall_deactivates_them(self):
        for key in profiles.THREAD_KEYS:
            self.assertIn(key, profiles.MANAGED_KEYS)

    def test_the_provenance_explains_the_split_with_the_detected_cores(self):
        provenance = profiles.provenance_for("cpu-standard", cpu_probe(12))
        router = provenance["LLM_TORCH_INTRAOP_THREADS"]
        worker = provenance["AGENT_TORCH_INTRAOP_THREADS"]
        self.assertEqual((router["value"], worker["value"]), ("4", "8"))
        self.assertEqual(router["provenance"], profiles.DERIVED)
        self.assertIn("12 physical cores detected", router["why"])
        self.assertIn("never oversubscribe", worker["why"])

class MemoryCeilings(unittest.TestCase):
    def test_every_cpu_profile_caps_the_agent_and_the_knowledge_store(self):
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

    def test_the_4b_worker_gets_more_room_than_the_1_5b_worker(self):
        lean = profiles.env_for("cpu-lean")["AGENT_MEM_LIMIT"]
        standard = profiles.env_for("cpu-standard")["AGENT_MEM_LIMIT"]
        self.assertGreaterEqual(gib(standard) - gib(lean), 4)

    def test_the_agent_ceiling_holds_the_worker_weights(self):
        weights_gib = {"cpu-lean": 3.1, "cpu-standard": 8.1}
        for name, weights in weights_gib.items():
            with self.subTest(name):
                ceiling = gib(profiles.env_for(name)["AGENT_MEM_LIMIT"])
                self.assertGreater(ceiling, weights + 2)

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

class ShorterCpuPrompts(unittest.TestCase):
    def test_cpu_profiles_fetch_four_documents(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                self.assertEqual(profiles.env_for(name)["KNOWLEDGE_STORE_N_RESULTS"], "4")

    def test_cpu_profiles_cap_the_retrieved_context_at_six_thousand_characters(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                self.assertEqual(profiles.env_for(name)["AGENT_MAX_CONTEXT_CHARS"], "6000")

    def test_cpu_profiles_stream_the_answer_while_it_is_written(self):
        for name in CPU_PROFILES:
            with self.subTest(name):
                self.assertEqual(profiles.env_for(name)["AGENT_STREAM_TOKENS"], "1")

    def test_gpu_profiles_keep_ten_documents_and_the_code_defaults(self):
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
        self.assertRegex(text, r"LLM_TORCH_INTRAOP_THREADS\s+= 2 ")
        self.assertRegex(text, r"AGENT_TORCH_INTRAOP_THREADS\s+= 6 ")
        self.assertRegex(text, r"AGENT_MEM_LIMIT\s+= 12g ")
        self.assertIn("8 physical cores detected", " ".join(text.split()))

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
            patch(mock.patch.object(horus_install, "banner"))
            patch(mock.patch.object(horus_install, "preflight"))
            consent = patch(mock.patch.object(horus_install, "consent"))
            consent.choose.return_value = {"corpus_dir": "../../demo_assets"}
            probe_machine = patch(mock.patch.object(horus_install.hardware, "probe"))
            probe_machine.return_value = probe
            write_json = patch(mock.patch.object(horus_install.hardware, "write_profile_json"))
            apply_env = patch(mock.patch.object(horus_install, "apply_env"))
            patch(mock.patch.object(horus_install, "pull_and_build"))
            patch(mock.patch.object(horus_install, "wait_for_health"))
            patch(mock.patch.object(horus_install, "_success"))
            patch(contextlib.redirect_stdout(io.StringIO()))
            code = horus_install._dispatch(self.log, args)
        self.assertEqual(code, common.EXIT_OK)
        return apply_env.call_args.args[2], write_json.call_args

    def test_a_cpu_install_writes_threads_from_the_detected_cores(self):
        env, _ = self.install("cpu-lean", "linux-cpu-8gb")
        self.assertEqual(env["LLM_TORCH_INTRAOP_THREADS"], "1")
        self.assertEqual(env["AGENT_TORCH_INTRAOP_THREADS"], "3")

    def test_a_cpu_install_writes_the_memory_ceilings(self):
        env, _ = self.install("cpu-standard", "nvidia-16gb")
        self.assertEqual(env["AGENT_MEM_LIMIT"], "12g")
        self.assertEqual(env["KNOWLEDGE_STORE_MEM_LIMIT"], "6g")
        self.assertEqual(sum(int(env[key]) for key in profiles.THREAD_KEYS), 8)

    def test_the_profile_json_receives_the_probe_the_threads_came_from(self):
        _, written = self.install("cpu-lean", "linux-cpu-8gb")
        probe, name = written.args[1], written.args[2]
        self.assertEqual(name, "cpu-lean")
        provenance = profiles.provenance_for(name, probe)
        self.assertIn("4 physical cores detected",
                      provenance["AGENT_TORCH_INTRAOP_THREADS"]["why"])

class ProfileJsonRecordsTheComputedSettings(unittest.TestCase):
    def test_the_written_provenance_matches_the_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "horus-profile.json"
            probe = cpu_probe(10)
            env = profiles.env_for("cpu-standard", probe)
            hardware.write_profile_json(path, probe, "cpu-standard", env, ["test"])
            document = json.loads(path.read_text(encoding="utf-8"))
        provenance = document["tuning_provenance"]
        self.assertEqual(provenance["LLM_TORCH_INTRAOP_THREADS"]["value"], "3")
        self.assertEqual(provenance["AGENT_TORCH_INTRAOP_THREADS"]["value"], "7")
        self.assertIn("AGENT_TORCH_INTRAOP_THREADS", document["derived_settings"])

if __name__ == "__main__":
    unittest.main()
