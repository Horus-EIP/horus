from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import hardware  # noqa: E402
import horus_install  # noqa: E402
import profiles  # noqa: E402
import unsupported  # noqa: E402
from common import EVENT_PREFIX, EXIT_HARDWARE_NOT_SUPPORTED, Events, Log, Result  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
GIB = 1024 ** 3
ONE_MINUTE = 60.0


def gib(value: float) -> int:
    return int(value * GIB)


class SlowStepRan(AssertionError):
    pass


def slow(name: str):
    def refuse(*_args, **_kwargs):
        raise SlowStepRan(f"{name} ran before the hardware decision")
    return refuse


def probe_of(system: str = "Linux", ram: float | None = 16, docker: float | None = None,
             vendor: str = "none", gpu: str | None = None, vram: float | None = None,
             usable: bool | None = None, avx2: bool | None = True) -> dict:
    return {
        "os": {"system": system, "machine": "x86_64", "platform": system.lower()},
        "cpu": {"physical_cores": 4, "avx2": avx2},
        "memory": {"total_bytes": None if ram is None else gib(ram)},
        "docker": {"mem_total_bytes": None if docker is None else gib(docker)},
        "gpu": {"vendor": vendor, "name": gpu, "vram_bytes": None if vram is None else gib(vram)},
        "docker_gpu_test": {"usable": usable,
                            "skipped_reason": None if usable is not None else "no GPU"},
        "cuda_usable_in_docker": usable is True,
    }


def events_in(stream: io.StringIO) -> list[dict]:
    return [json.loads(line[len(EVENT_PREFIX):]) for line in stream.getvalue().splitlines()
            if line.startswith(EVENT_PREFIX)]


class FakeMachine:

    def __init__(self, system: str = "Linux", ram: float | None = 7.6,
                 docker: float | None = 7.6, cards: tuple = (), adapters: tuple = (),
                 avx2: bool | None = True):
        self.system = system
        self.ram = ram
        self.docker = docker
        self.cards = [{"name": name, "vram_bytes": gib(vram)} for name, vram in cards]
        self.adapters = list(adapters)
        self.avx2 = avx2

    def gpu(self) -> dict:
        if self.cards:
            largest = max(self.cards, key=lambda card: card["vram_bytes"])
            return {"vendor": "nvidia", "name": largest["name"],
                    "vram_bytes": largest["vram_bytes"], "count": len(self.cards),
                    "gpus": copy.deepcopy(self.cards), "adapters": [], "source": "fake",
                    "detail": "", "driver_version": "fake"}
        vendor = hardware._vendor_of(self.adapters[0]) if self.adapters else "none"
        return {"vendor": vendor, "name": self.adapters[0] if self.adapters else None,
                "vram_bytes": None, "count": len(self.adapters), "gpus": [],
                "adapters": list(self.adapters), "source": "fake", "detail": "",
                "driver_version": None}

    def install(self, stack: contextlib.ExitStack) -> None:
        patch = stack.enter_context
        osinfo = {"platform": self.system.lower(), "system": self.system,
                  "machine": "x86_64", "release": "fake", "is_wsl": False, "is_64bit": True}
        memory = {"total_bytes": None if self.ram is None else gib(self.ram), "source": "fake",
                  "detail": ""}
        docker = {"mem_total_bytes": None if self.docker is None else gib(self.docker),
                  "source": "fake", "detail": "fake docker info"}
        patch(mock.patch.object(hardware, "detect_os", side_effect=lambda log: dict(osinfo)))
        patch(mock.patch.object(hardware, "detect_cpu", side_effect=lambda log: {
            "model": "Fake CPU", "physical_cores": 4, "logical_cores": 8,
            "count_is_logical_fallback": False, "source": "fake"}))
        patch(mock.patch.object(hardware, "detect_avx2", side_effect=lambda log, osi: {
            "avx2": self.avx2, "avx2_source": "fake"}))
        patch(mock.patch.object(hardware, "detect_memory", side_effect=lambda log: dict(memory)))
        patch(mock.patch.object(hardware, "detect_disk", side_effect=lambda log: {
            "path": "fake", "free_bytes": 500 * GIB, "total_bytes": 1000 * GIB, "detail": ""}))
        patch(mock.patch.object(hardware, "detect_gpu_host",
                                side_effect=lambda log, osi: self.gpu()))
        patch(mock.patch.object(hardware, "detect_docker_memory",
                                side_effect=lambda log: dict(docker)))
        patch(mock.patch.object(hardware, "_wsl_status", return_value={
            "present": True, "default_version": 2, "detail": "fake"}))
        patch(mock.patch.object(hardware, "run", side_effect=slow("a command in the probe")))


class TempDir(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        (self.repo / "src" / "infra").mkdir(parents=True)
        self.record = self.tmp / "horus-profile.json"
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(horus_install, "PROFILE_JSON", self.record))
        stack.enter_context(mock.patch.object(horus_install, "LOG_PATH",
                                              self.tmp / "install-log.txt"))

    def log(self, events: io.StringIO | None = None) -> Log:
        log = Log(self.tmp / "test-log.txt", events=Events(events is not None, events))
        self.addCleanup(log.close, 0)
        return log


class EightGigabyteMachineIsToldFirst(TempDir):

    def run_installer(self, machine: FakeMachine, *argv: str,
                      install_checks: Exception | None = None) -> tuple[int, str, list[dict]]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            patch = stack.enter_context
            machine.install(stack)
            patch(mock.patch.object(horus_install, "find_repo", return_value=self.repo))
            preflight = patch(mock.patch.object(horus_install, "preflight"))
            preflight.run_install_checks.side_effect = (
                install_checks or slow("the disk, network and port checks"))
            patch(mock.patch.object(horus_install, "sign_in_to_registry",
                                    side_effect=slow("the registry sign-in")))
            consent = patch(mock.patch.object(horus_install, "consent"))
            consent.choose.side_effect = slow("the file-access questions")
            for name in ("apply_env", "pull_and_build", "download_model", "wait_for_health"):
                patch(mock.patch.object(horus_install, name, side_effect=slow(name)))
            patch(contextlib.redirect_stdout(out))
            patch(contextlib.redirect_stderr(err))
            self.engine = preflight.run_engine_checks
            code = horus_install.main(["--non-interactive", "--json-events", *argv])
        return code, out.getvalue(), events_in(err)

    def test_the_refusal_comes_before_any_slow_step(self):
        started = time.monotonic()
        code, _, events = self.run_installer(FakeMachine(ram=7.6, docker=7.6))
        self.assertLess(time.monotonic() - started, ONE_MINUTE)
        self.assertEqual(code, EXIT_HARDWARE_NOT_SUPPORTED)
        self.engine.assert_called_once()
        kinds = [event["event"] for event in events]
        self.assertIn(unsupported.EVENT, kinds)
        self.assertLess(kinds.index(unsupported.EVENT), kinds.index("exit"))
        self.assertNotIn("download", kinds)
        steps = [event["text"] for event in events if event["event"] == "step"]
        self.assertIn("Checking your hardware", steps)
        self.assertFalse([step for step in steps if "Disk space" in step or "Downloading" in step])

    def test_the_event_says_what_the_machine_has_what_it_needs_and_what_to_do(self):
        _, _, events = self.run_installer(FakeMachine(ram=7.6, docker=7.6))
        refusal = next(event for event in events if event["event"] == unsupported.EVENT)
        self.assertEqual(refusal["headline"], unsupported.HEADLINE)
        self.assertIn("Docker can use 7.6 GiB of memory.", refusal["have"])
        self.assertIn("No NVIDIA GPU.", refusal["have"])
        self.assertTrue(refusal["need"][0].startswith(f"{profiles.cpu_floor_gib():.1f} GiB"))
        self.assertTrue(any("--profile cpu-lean" in item for item in refusal["alternatives"]))
        self.assertEqual(refusal["docker_memory_bytes"], gib(7.6))
        self.assertEqual(refusal["required_bytes"], gib(profiles.cpu_floor_gib()))

    def test_the_screen_shows_the_same_three_parts(self):
        _, out, _ = self.run_installer(FakeMachine(ram=7.6, docker=7.6))
        self.assertIn(f"INSTALL STOPPED: {unsupported.HEADLINE}", out)
        for part in ("This machine:", "Horus needs:", "What to do:", "--profile cpu-lean",
                     profiles.LOW_RAM_ADR, f"Exit code {EXIT_HARDWARE_NOT_SUPPORTED}"):
            with self.subTest(part):
                self.assertIn(part, " ".join(out.split()))

    def test_the_refusal_is_recorded_for_the_next_run_and_for_bug_reports(self):
        self.run_installer(FakeMachine(ram=7.6, docker=7.6))
        document = json.loads(self.record.read_text(encoding="utf-8"))
        self.assertEqual(document["profile"]["name"], profiles.NOT_SUPPORTED)
        self.assertEqual(document["refusal"]["headline"], unsupported.HEADLINE)
        self.assertEqual(document["hardware_fingerprint"]["docker_memory_mib"],
                         gib(7.6) // 1024 ** 2)
        self.assertEqual(document["memory_decision"]["basis"], profiles.DOCKER_BASIS)
        self.assertEqual(document["env_written"], {})
        self.assertNotIn("probe_failed", document["hardware"])
        self.assertFalse(document["hardware"]["docker_gpu_test"]["attempted"])

    def test_a_windows_machine_with_room_is_told_how_to_give_docker_more(self):
        _, out, events = self.run_installer(FakeMachine("Windows", ram=15.8, docker=7.9))
        refusal = next(event for event in events if event["event"] == unsupported.EVENT)
        advice = " ".join(refusal["alternatives"])
        for part in (".wslconfig", "wsl --shutdown", "WSL Settings", "does not change"):
            with self.subTest(part):
                self.assertIn(part, advice)
        self.assertIn("The machine has 15.8 GiB of RAM.", refusal["have"])

    def test_a_forced_profile_goes_on_with_a_warning(self):
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            patch = stack.enter_context
            FakeMachine(ram=7.6, docker=7.6).install(stack)
            patch(mock.patch.object(horus_install, "find_repo", return_value=self.repo))
            patch(mock.patch.object(horus_install, "preflight"))
            patch(mock.patch.object(horus_install, "sign_in_to_registry"))
            consent = patch(mock.patch.object(horus_install, "consent"))
            consent.choose.side_effect = SlowStepRan("reached the questions")
            patch(contextlib.redirect_stdout(out))
            with self.assertRaises(SlowStepRan):
                horus_install._dispatch(self.log(), horus_install.build_parser().parse_args(
                    ["--profile", "cpu-lean", "--non-interactive"]))
        text = " ".join(out.getvalue().split())
        self.assertIn("forces a profile this machine is not supported for", text)
        self.assertNotIn("INSTALL STOPPED", text)

    def test_a_sixteen_gigabyte_linux_machine_goes_on_to_the_install(self):
        with contextlib.ExitStack() as stack:
            patch = stack.enter_context
            FakeMachine(ram=15.4, docker=15.4).install(stack)
            patch(mock.patch.object(horus_install, "find_repo", return_value=self.repo))
            patch(mock.patch.object(horus_install, "preflight"))
            patch(mock.patch.object(horus_install, "sign_in_to_registry"))
            consent = patch(mock.patch.object(horus_install, "consent"))
            consent.choose.side_effect = SlowStepRan("reached the questions")
            patch(contextlib.redirect_stdout(io.StringIO()))
            with self.assertRaises(SlowStepRan):
                horus_install._dispatch(self.log(), horus_install.build_parser().parse_args(
                    ["--non-interactive"]))
        document = hardware.read_profile_json(self.record)
        self.assertEqual(document["profile"]["name"], "cpu-standard")
        self.assertNotIn("refusal", document)
        self.assertEqual(document["env_written"], {})

    def test_a_refusal_is_forgotten_once_the_decision_passes_even_if_a_later_step_fails(self):
        code, _, _ = self.run_installer(FakeMachine("Windows", ram=15.8, docker=7.9))
        self.assertEqual(code, EXIT_HARDWARE_NOT_SUPPORTED)
        disk_full = common.InstallError(common.EXIT_DISK_SPACE, "Not enough free disk space.",
                                        "fake disk check", "Free some space.")
        code, _, events = self.run_installer(FakeMachine("Windows", ram=15.8, docker=15.6),
                                             install_checks=disk_full)
        self.assertEqual(code, common.EXIT_DISK_SPACE)
        self.assertNotIn(unsupported.EVENT, [event["event"] for event in events])
        document = hardware.read_profile_json(self.record)
        self.assertNotIn("refusal", document)
        self.assertEqual(document["profile"]["name"], "cpu-standard")
        with self.assertRaises(common.InstallError) as caught:
            horus_install.require_installed(self.repo / "src" / "infra", self.record)
        self.assertNotIsInstance(caught.exception, unsupported.NotSupported)
        self.assertEqual(caught.exception.code, common.EXIT_NOT_INSTALLED)


class MemoryDecision(unittest.TestCase):

    def chosen(self, **machine) -> str:
        return profiles.select_profile(probe_of(**machine))[0]

    def test_the_adr_006_thresholds_apply_to_the_memory_docker_can_use(self):
        cases = ((16.0, "cpu-standard"), (15.0, "cpu-standard"), (14.99, "cpu-lean"),
                 (13.5, "cpu-lean"), (13.49, profiles.NOT_SUPPORTED),
                 (7.6, profiles.NOT_SUPPORTED))
        for docker, expected in cases:
            with self.subTest(docker=docker):
                self.assertEqual(self.chosen(ram=64, docker=docker), expected)

    def test_docker_memory_wins_over_the_ram_of_the_machine(self):
        self.assertEqual(self.chosen(system="Windows", ram=31.8, docker=15.6), "cpu-standard")
        self.assertEqual(self.chosen(system="Windows", ram=15.8, docker=7.9),
                         profiles.NOT_SUPPORTED)

    def test_without_docker_memory_the_ram_decides_and_says_so(self):
        name, reasons = profiles.select_profile(probe_of(ram=14.0, docker=None))
        self.assertEqual(name, "cpu-lean")
        self.assertIn("Docker did not say how much memory it can use", " ".join(reasons))

    def test_a_machine_whose_memory_cannot_be_read_is_never_refused(self):
        self.assertEqual(self.chosen(ram=None, docker=None), "cpu-lean")

    def test_turning_the_lean_profile_off_refuses_everything_under_cpu_standard(self):
        with mock.patch.object(profiles, "CPU_LEAN_SUPPORTED", False):
            self.assertEqual(self.chosen(ram=64, docker=14.0), profiles.NOT_SUPPORTED)
            self.assertEqual(self.chosen(ram=64, docker=15.2), "cpu-standard")
            self.assertEqual(profiles.cpu_floor_gib(), profiles.CPU_STANDARD_MIN_GIB)

    def test_a_usable_gpu_is_not_held_to_the_cpu_thresholds(self):
        name = self.chosen(ram=7.6, docker=7.6, vendor="nvidia", gpu="RTX 4060", vram=8,
                           usable=True)
        self.assertEqual(name, "gpu-8g")

    def test_a_gpu_too_small_for_the_model_falls_back_to_the_cpu_decision(self):
        name = self.chosen(ram=7.6, docker=7.6, vendor="nvidia", gpu="MX450", vram=2,
                           usable=True)
        self.assertEqual(name, profiles.NOT_SUPPORTED)

    def test_the_simulated_machines_land_where_the_adr_says(self):
        expected = {"linux-cpu-8gb": profiles.NOT_SUPPORTED, "laptop-cpu-14gb": "cpu-lean",
                    "linux-cpu-16gb": "cpu-standard",
                    "windows-cpu-16gb": profiles.NOT_SUPPORTED,
                    "old-cpu-no-avx2": "cpu-standard", "nvidia-8gb": "gpu-8g"}
        for simulation, name in expected.items():
            with self.subTest(simulation):
                probe = dict(horus_install.SIMULATIONS[simulation])
                self.assertEqual(profiles.select_profile(probe)[0], name)

    def test_the_reasons_quote_the_adr_and_say_the_figures_are_still_planning_figures(self):
        _, reasons = profiles.select_profile(probe_of(ram=64, docker=14.0))
        text = " ".join(reasons)
        self.assertIn(profiles.LOW_RAM_ADR, text)
        self.assertIn("planning figures", text)
        self.assertIn("until the run on the 16 GB reference machine", text)
        self.assertNotIn("not measured", text)

    def test_the_cpu_notes_quote_the_first_laptop_run_and_keep_the_thresholds(self):
        notes = " ".join(profiles.get("cpu-lean").notes + profiles.get("cpu-standard").notes)
        self.assertIn("benchmarks/cpu-laptop-2026-10-06.json", notes)
        self.assertIn("8.34 GiB on cpu-standard and 6.21 GiB on cpu-lean", notes)
        self.assertIn("10.5 and 8.5 GiB", notes)
        self.assertIn(f"stay at {profiles.CPU_STANDARD_MIN_GIB:.1f} and "
                      f"{profiles.CPU_LEAN_MIN_GIB:.1f} GiB", notes)
        self.assertNotIn("benchmarked", notes)
        self.assertNotIn("has not been timed", notes)

    def test_the_lean_notes_say_it_failed_the_timing_condition_on_that_run(self):
        lean = profiles.get("cpu-lean")
        notes = " ".join(lean.notes)
        self.assertIn("a median of 33.2 s, 1.87 times cpu-standard", notes)
        self.assertIn("failed the ADR's timing condition", notes)
        self.assertNotIn("Untested", lean.summary)

    def test_the_lean_profile_is_described_by_its_thresholds(self):
        trigger = profiles.get("cpu-lean").trigger
        self.assertIn(f"{profiles.CPU_LEAN_MIN_GIB:.1f}", trigger)
        self.assertIn(f"{profiles.CPU_STANDARD_MIN_GIB:.1f}", trigger)
        self.assertIn("Docker", trigger)

    def test_the_memory_decision_is_recorded_with_its_thresholds(self):
        record = profiles.memory_decision(probe_of(ram=31.8, docker=15.6))
        self.assertEqual(record["basis"], profiles.DOCKER_BASIS)
        self.assertAlmostEqual(record["memory_gib"], 15.6, places=1)
        self.assertEqual(record["cpu_lean_min_gib"], profiles.CPU_LEAN_MIN_GIB)
        self.assertIs(record["cpu_lean_supported"], profiles.CPU_LEAN_SUPPORTED)


class ForcedProfiles(unittest.TestCase):
    def test_a_profile_forced_below_its_floor_is_warned(self):
        warning = profiles.forced_profile_warning("cpu-standard", probe_of(ram=64, docker=14.0))
        self.assertIn("cpu-standard needs 15.0 GiB", warning)
        self.assertIn("Docker can use 14.0 GiB", warning)

    def test_a_profile_forced_on_enough_memory_is_not(self):
        self.assertIsNone(profiles.forced_profile_warning("cpu-lean", probe_of(docker=14.0)))
        self.assertIsNone(profiles.forced_profile_warning("cpu-standard", probe_of(docker=16)))

    def test_cpu_lean_is_held_to_cpu_standard_once_it_is_turned_off(self):
        with mock.patch.object(profiles, "CPU_LEAN_SUPPORTED", False):
            self.assertIsNotNone(profiles.forced_profile_warning("cpu-lean",
                                                                 probe_of(docker=14.0)))

    def test_gpu_profiles_and_unknown_memory_are_not_warned(self):
        self.assertIsNone(profiles.forced_profile_warning("gpu-8g", probe_of(docker=4)))
        self.assertIsNone(profiles.forced_profile_warning("cpu-standard",
                                                          probe_of(ram=None, docker=None)))


class RefusalScreen(TempDir):

    def refusal(self, **machine) -> unsupported.NotSupported:
        return unsupported.refusal(probe_of(**machine))

    def test_windows_with_room_gets_the_wsl_sizes_from_the_adr(self):
        advice = " ".join(self.refusal(system="Windows", ram=31.8, docker=12.0).alternatives)
        self.assertIn("memory=14GB (cpu-lean) or memory=16GB (cpu-standard)", advice)
        self.assertIn(f"{unsupported.WINDOWS_PRACTICAL_RAM_GB} GB of RAM", advice)

    def test_a_windows_machine_without_the_room_is_not_told_to_raise_wsl(self):
        advice = " ".join(self.refusal(system="Windows", ram=7.8, docker=3.9).alternatives)
        self.assertNotIn(".wslconfig", advice)
        self.assertIn("Use a machine with more memory", advice)

    def test_linux_is_told_a_sixteen_gigabyte_machine_is_enough(self):
        advice = " ".join(self.refusal(ram=7.6, docker=7.6).alternatives)
        self.assertIn("16 GB machine is enough", advice)
        self.assertNotIn("wsl", advice.lower())

    def test_macos_is_pointed_at_docker_desktop_resources(self):
        advice = " ".join(self.refusal(system="Darwin", ram=18, docker=9).alternatives)
        self.assertIn("Docker Desktop > Settings > Resources > Memory limit", advice)

    def test_an_nvidia_card_docker_cannot_use_comes_first(self):
        refused = self.refusal(ram=7.6, docker=7.6, vendor="nvidia", gpu="RTX 3050", vram=4,
                               usable=False)
        self.assertIn("RTX 3050, which Docker could not use.", refused.have)
        self.assertTrue(refused.alternatives[0].startswith("Make the NVIDIA GPU usable"))

    def test_every_refusal_offers_to_try_anyway_and_names_its_basis(self):
        refused = self.refusal(ram=7.6, docker=7.6)
        self.assertIn("--profile cpu-lean", refused.alternatives[-1])
        self.assertIn(profiles.THRESHOLDS_BASIS, " ".join(refused.need))
        self.assertEqual(refused.code, EXIT_HARDWARE_NOT_SUPPORTED)

    def test_trying_anyway_calls_the_thresholds_planning_figures(self):
        last = self.refusal(ram=7.6, docker=7.6).alternatives[-1]
        self.assertIn("these thresholds are still planning figures", last)
        self.assertNotIn("not measured", last)

    def test_the_report_emits_the_event_before_the_screen(self):
        stream = io.StringIO()
        log = self.log(stream)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.refusal(ram=7.6, docker=7.6).report(log)
        events = events_in(stream)
        self.assertEqual(events[0]["event"], unsupported.EVENT)
        self.assertEqual(set(unsupported.NUMBER_KEYS) | {"headline", "have", "need",
                                                         "alternatives", "checked_utc"},
                         set(events[0]) - {"event"})
        self.assertIn("This machine:", out.getvalue())

    def test_a_recorded_refusal_reads_back_the_same(self):
        probe = probe_of(system="Windows", ram=15.8, docker=7.9)
        refused = unsupported.refusal(probe)
        hardware.write_profile_json(self.record, probe, profiles.NOT_SUPPORTED, {}, ["r"],
                                    refusal=refused.record())
        again = unsupported.from_record(hardware.read_profile_json(self.record))
        self.assertEqual((again.have, again.need, again.alternatives),
                         (refused.have, refused.need, refused.alternatives))
        self.assertEqual(again.numbers, refused.numbers)
        self.assertTrue(again.checked_utc)
        self.assertIn("Found when START-HERE last ran", again.detail)

    def test_a_record_without_a_refusal_is_not_one(self):
        for document in (None, {}, {"refusal": "no"}, {"profile": {"name": "cpu-lean"}}):
            with self.subTest(document=document):
                self.assertIsNone(unsupported.from_record(document))


class StartAfterARefusal(TempDir):

    def write_refusal(self) -> None:
        probe = probe_of(ram=7.6, docker=7.6)
        hardware.write_profile_json(self.record, probe, profiles.NOT_SUPPORTED, {}, [],
                                    refusal=unsupported.refusal(probe).record())

    def test_a_refused_machine_hears_why_instead_of_not_installed(self):
        self.write_refusal()
        with self.assertRaises(unsupported.NotSupported) as caught:
            horus_install.require_installed(self.repo / "src" / "infra", self.record)
        self.assertEqual(caught.exception.code, EXIT_HARDWARE_NOT_SUPPORTED)

    def test_an_installed_stack_starts_whatever_an_old_record_says(self):
        self.write_refusal()
        (self.repo / "src" / "infra" / ".env").write_text("A=1\n", encoding="utf-8")
        horus_install.require_installed(self.repo / "src" / "infra", self.record)

    def test_the_desktop_start_gets_the_refusal_as_an_event(self):
        self.write_refusal()
        err = io.StringIO()
        with mock.patch.object(horus_install, "find_repo", return_value=self.repo), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = horus_install.main(["--start", "--json-events"])
        self.assertEqual(code, EXIT_HARDWARE_NOT_SUPPORTED)
        refusal = next(event for event in events_in(err) if event["event"] == unsupported.EVENT)
        self.assertTrue(refusal["checked_utc"])
        self.assertIn("Docker can use 7.6 GiB of memory.", refusal["have"])


class Fingerprint(TempDir):

    RTX = (("NVIDIA GeForce RTX 4060 Laptop GPU", 8),)

    def probe(self, machine: FakeMachine, previous: dict | None,
              allow: bool = True) -> tuple[dict, mock.Mock]:
        passed = {"attempted": True, "usable": True, "detail": "NVIDIA-SMI ok",
                  "skipped_reason": None}
        with contextlib.ExitStack() as stack:
            machine.install(stack)
            gpu_test = stack.enter_context(mock.patch.object(
                hardware, "docker_gpu_test", return_value=dict(passed)))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            probe = hardware.probe(self.log(), allow_docker_gpu_test=allow, previous=previous)
        return probe, gpu_test

    def recorded(self, machine: FakeMachine) -> dict:
        probe, _ = self.probe(machine, None)
        name, reasons = profiles.select_profile(probe)
        hardware.write_profile_json(self.record, probe, name, {}, reasons)
        return hardware.read_profile_json(self.record)

    def test_the_fingerprint_is_ram_docker_memory_and_the_gpu_list(self):
        probe, _ = self.probe(FakeMachine(ram=31.8, docker=15.6, cards=self.RTX), None)
        self.assertEqual(probe["hardware_fingerprint"], {
            "ram_mib": gib(31.8) // 1024 ** 2, "docker_memory_mib": gib(15.6) // 1024 ** 2,
            "gpus": ["NVIDIA GeForce RTX 4060 Laptop GPU 8192 MiB"]})

    def test_nothing_changed_so_the_gpu_test_is_not_run_again(self):
        machine = FakeMachine(ram=31.8, docker=15.6, cards=self.RTX)
        previous = self.recorded(machine)
        probe, gpu_test = self.probe(machine, previous)
        gpu_test.assert_not_called()
        self.assertTrue(probe["cuda_usable_in_docker"])
        self.assertFalse(probe["gpu_test_ran"])
        name, reasons = profiles.select_profile(probe)
        self.assertEqual(name, previous["profile"]["name"])
        self.assertIn("was not run again", " ".join(reasons))

    def test_a_change_runs_the_detection_again(self):
        machine = FakeMachine(ram=31.8, docker=15.6, cards=self.RTX)
        previous = self.recorded(machine)
        changed = {
            "ram": FakeMachine(ram=63.8, docker=15.6, cards=self.RTX),
            "docker memory": FakeMachine(ram=31.8, docker=23.6, cards=self.RTX),
            "gpu list": FakeMachine(ram=31.8, docker=15.6,
                                    cards=(("NVIDIA GeForce RTX 4070", 12),)),
        }
        for what, other in changed.items():
            with self.subTest(what):
                _, gpu_test = self.probe(other, previous)
                gpu_test.assert_called_once()

    def test_a_failed_gpu_test_is_run_again_so_a_fixed_driver_is_seen(self):
        machine = FakeMachine(ram=31.8, docker=15.6, cards=self.RTX)
        previous = self.recorded(machine)
        previous["hardware"]["docker_gpu_test"]["usable"] = False
        _, gpu_test = self.probe(machine, previous)
        gpu_test.assert_called_once()

    def test_a_record_from_an_older_installer_has_no_fingerprint_to_trust(self):
        machine = FakeMachine(ram=31.8, docker=15.6, cards=self.RTX)
        previous = self.recorded(machine)
        del previous["hardware_fingerprint"]
        _, gpu_test = self.probe(machine, previous)
        gpu_test.assert_called_once()

    def test_skipping_the_gpu_test_does_not_borrow_an_old_result(self):
        machine = FakeMachine(ram=31.8, docker=15.6, cards=self.RTX)
        previous = self.recorded(machine)
        probe, _ = self.probe(machine, previous, allow=False)
        self.assertFalse(probe["docker_gpu_test"].get("reused_from"))

    def test_the_installer_hands_the_previous_record_to_the_probe(self):
        previous = self.recorded(FakeMachine(ram=31.8, docker=15.6, cards=self.RTX))
        with mock.patch.object(horus_install.hardware, "probe",
                               return_value=probe_of(docker=16)) as probe, \
                contextlib.redirect_stdout(io.StringIO()):
            horus_install.decide_profile(self.log(), horus_install.build_parser().parse_args(
                ["--profile", "gpu-16g"]), None)
        self.assertEqual(probe.call_args.kwargs["previous"]["hardware_fingerprint"],
                         previous["hardware_fingerprint"])

    def test_a_passed_decision_is_recorded_before_the_slow_steps(self):
        machine = FakeMachine(ram=31.8, docker=15.6, cards=self.RTX)
        probe, _ = self.probe(machine, None)
        with mock.patch.object(horus_install.hardware, "probe", return_value=probe), \
                contextlib.redirect_stdout(io.StringIO()):
            horus_install.decide_profile(self.log(), horus_install.build_parser().parse_args(
                []), None)
        _, gpu_test = self.probe(machine, hardware.read_profile_json(self.record))
        gpu_test.assert_not_called()

    def test_profile_still_overrides_a_reused_decision(self):
        machine = FakeMachine(ram=31.8, docker=15.6, cards=self.RTX)
        previous = self.recorded(machine)
        reused, _ = self.probe(machine, previous)
        with mock.patch.object(horus_install.hardware, "probe", return_value=reused), \
                contextlib.redirect_stdout(io.StringIO()):
            _, name, _ = horus_install.decide_profile(
                self.log(), horus_install.build_parser().parse_args(
                    ["--profile", "cpu-standard"]), None)
        self.assertEqual(name, "cpu-standard")

    def test_an_unreadable_record_is_no_record(self):
        self.assertIsNone(hardware.read_profile_json(self.tmp / "missing.json"))
        self.record.write_text("{not json", encoding="utf-8")
        self.assertIsNone(hardware.read_profile_json(self.record))
        self.record.write_text("[1, 2]", encoding="utf-8")
        self.assertIsNone(hardware.read_profile_json(self.record))


class FakeKernel32:
    def __init__(self, answer):
        self.answer = answer
        self.asked: list[int] = []

    def IsProcessorFeaturePresent(self, feature: int):  # noqa: N802
        self.asked.append(feature)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class Avx2(TempDir):

    def cpuinfo(self, flags: str | None) -> Path:
        path = self.tmp / "cpuinfo"
        lines = ["processor\t: 0", "model name\t: Test CPU"]
        if flags is not None:
            lines.append(f"flags\t\t: {flags}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def detect(self, platform: str, machine: str = "x86_64", **kwargs) -> dict:
        with mock.patch.object(hardware.sys, "platform", platform):
            return hardware.detect_avx2(self.log(), {"machine": machine}, **kwargs)

    def test_linux_reads_the_cpuinfo_flags(self):
        self.assertIs(self.detect("linux", cpuinfo=self.cpuinfo("fpu sse4_2 avx avx2 fma"))[
            "avx2"], True)
        self.assertIs(self.detect("linux", cpuinfo=self.cpuinfo("fpu sse4_2 avx"))["avx2"],
                      False)
        self.assertIsNone(self.detect("linux", cpuinfo=self.cpuinfo(None))["avx2"])
        self.assertIsNone(self.detect("linux", cpuinfo=self.tmp / "missing")["avx2"])

    def test_an_arm_processor_needs_no_avx2(self):
        for machine in ("aarch64", "arm64", "ARM64"):
            with self.subTest(machine):
                found = self.detect("linux", machine=machine, cpuinfo=self.cpuinfo("fp asimd"))
                self.assertIsNone(found["avx2"])
                self.assertIn("does not need", found["avx2_source"])

    def test_windows_asks_is_processor_feature_present_40(self):
        for answer, expected in ((1, True), (0, False)):
            with self.subTest(answer=answer):
                kernel32 = FakeKernel32(answer)
                self.assertIs(self.detect("win32", machine="AMD64", kernel32=kernel32)["avx2"],
                              expected)
                self.assertEqual(kernel32.asked, [40])
        broken = self.detect("win32", machine="AMD64", kernel32=FakeKernel32(OSError("no")))
        self.assertIsNone(broken["avx2"])

    def macos(self, answers: dict[str, Result]) -> tuple[dict, list[str]]:
        asked: list[str] = []

        def fake_run(cmd, log, timeout=60, **_kwargs):
            asked.append(cmd[-1])
            return answers.get(cmd[-1], Result(1, "", "unknown oid"))

        with mock.patch.object(hardware, "run", side_effect=fake_run):
            return self.detect("darwin"), asked

    def test_apple_silicon_has_no_avx2_and_is_not_warned(self):
        found, asked = self.macos({"hw.optional.arm64": Result(0, "1", "")})
        self.assertIsNone(found["avx2"])
        self.assertEqual(found["avx2_source"], hardware.APPLE_SILICON)
        self.assertEqual(asked, ["hw.optional.arm64"])
        self.assertIsNone(profiles.avx2_warning({"cpu": found}))

    def test_an_intel_mac_reads_sysctl(self):
        for answer, expected in (("1", True), ("0", False)):
            with self.subTest(answer=answer):
                found, _ = self.macos({"hw.optional.avx2_0": Result(0, answer, "")})
                self.assertIs(found["avx2"], expected)

    def test_only_a_missing_avx2_is_warned(self):
        self.assertIn("no AVX2", profiles.avx2_warning({"cpu": {"avx2": False}}))
        self.assertIn("still runs", profiles.avx2_warning({"cpu": {"avx2": False}}))
        for value in (True, None):
            with self.subTest(value=value):
                self.assertIsNone(profiles.avx2_warning({"cpu": {"avx2": value}}))

    def test_this_machine_answers_without_raising(self):
        found = hardware.detect_avx2(self.log(), hardware.detect_os(self.log()))
        self.assertIn(found["avx2"], (True, False, None))

    def warnings_for(self, simulation: str, *argv: str) -> str:
        out = io.StringIO()
        with mock.patch.object(horus_install.hardware, "probe",
                               return_value=dict(horus_install.SIMULATIONS[simulation])), \
                contextlib.redirect_stdout(out):
            horus_install.decide_profile(self.log(), horus_install.build_parser().parse_args(
                list(argv)), None)
        return " ".join(out.getvalue().split())

    def test_a_cpu_install_without_avx2_is_warned(self):
        self.assertIn("This processor has no AVX2", self.warnings_for("old-cpu-no-avx2"))
        self.assertNotIn("no AVX2", self.warnings_for("linux-cpu-16gb"))

    def test_a_gpu_install_is_not(self):
        probe = dict(horus_install.SIMULATIONS["nvidia-16gb"])
        probe["cpu"] = {**probe["cpu"], "avx2": False}
        out = io.StringIO()
        with mock.patch.object(horus_install.hardware, "probe", return_value=probe), \
                contextlib.redirect_stdout(out):
            horus_install.decide_profile(self.log(), horus_install.build_parser().parse_args(
                []), None)
        self.assertNotIn("no AVX2", out.getvalue())


class DryRun(TempDir):

    def setUp(self) -> None:
        super().setUp()
        (self.repo / "models").mkdir()
        shutil.copy(REPO / "models" / "manifest.json", self.repo / "models" / "manifest.json")

    def dry_run(self, *argv: str) -> str:
        out = io.StringIO()
        with mock.patch.object(horus_install, "find_repo", return_value=self.repo), \
                contextlib.redirect_stdout(out):
            code = horus_install._dispatch(self.log(), horus_install.build_parser().parse_args(
                ["--dry-run", *argv]))
        self.assertEqual(code, common.EXIT_OK)
        return " ".join(out.getvalue().split())

    def test_a_simulated_small_machine_shows_the_screen_it_would_stop_on(self):
        text = self.dry_run("--simulate", "windows-cpu-16gb")
        self.assertIn("profile : not supported", text)
        self.assertIn(f"exit code {EXIT_HARDWARE_NOT_SUPPORTED}", text)
        self.assertIn(".wslconfig", text)
        self.assertNotIn("would write", text)

    def test_the_dry_run_of_this_machine_decides_on_the_memory_docker_can_use(self):
        with contextlib.ExitStack() as stack:
            FakeMachine("Windows", ram=15.8, docker=7.9).install(stack)
            text = self.dry_run()
        first_simulation = f"-- {next(iter(horus_install.SIMULATIONS))} -"
        this_machine = text.split("-- this machine")[1].split(first_simulation)[0]
        self.assertIn("docker : 7.9 GiB of memory", this_machine)
        self.assertIn("profile : not supported", this_machine)
        self.assertIn("Docker was only asked how much memory it can use", text)

    def test_a_simulated_dry_run_does_not_contact_docker(self):
        with mock.patch.object(hardware, "run", side_effect=slow("a Docker command")):
            text = self.dry_run("--simulate", "linux-cpu-16gb")
        self.assertIn("Docker was not contacted", text)


if __name__ == "__main__":
    unittest.main()
