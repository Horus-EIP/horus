from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
SERVICES = REPO / "src" / "services"
INFRA = REPO / "src" / "infra"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
SCRIPT = REPO / "scripts" / "ci" / "check-cpu-image.py"

sys.path.insert(0, str(REPO / "installer"))
import profiles  # noqa: E402

spec = importlib.util.spec_from_file_location("check_cpu_image", SCRIPT)
check_cpu_image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_cpu_image)

CPU_TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
DEFAULT_INDEX = "https://pypi.org/simple"
CPU_IMAGE_JOB = "cpu-images"

CPU_TORCH_TEST_JOBS = {
    "test-agent": ("src/services/agent/requirements.txt", 90),
    "test-knowledge-store": ("src/services/knowledge-store/requirements.txt", 85),
}

TORCH_SERVICES = {
    "mas": SERVICES / "mas",
    "agent": SERVICES / "agent",
    "knowledge_store": SERVICES / "knowledge-store",
}

REQUIREMENT_FILES = (
    SERVICES / "mas" / "requirements.txt",
    SERVICES / "mas" / "requirements-cpu.txt",
    SERVICES / "agent" / "requirements.txt",
    SERVICES / "knowledge-store" / "requirements.txt",
)

EXACT_PUBLIC_TORCH_PIN = re.compile(r"torch==\d+(?:\.\d+)*")

REINSTALLING_PIP_OPTIONS = {
    "-U", "--upgrade", "--force-reinstall", "-I", "--ignore-installed",
    "-i", "--index-url", "--extra-index-url",
}

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the compose and CI files")


def project_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
    return re.sub(r"[-_.]+", "-", match.group(0)).lower() if match else ""


def torch_requirements(path: Path) -> list[str]:
    found = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].strip()
        if line and not line.startswith(("#", "-")) and project_name(line) == "torch":
            found.append(line.replace(" ", ""))
    return found


def instructions(dockerfile: Path) -> list[tuple[int, str, str]]:
    text = re.sub(r"\\\r?\n", " ", dockerfile.read_text(encoding="utf-8"))
    stage = 0
    found = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keyword, _, rest = line.partition(" ")
        if keyword.upper() == "FROM":
            stage += 1
        found.append((stage, keyword.upper(), rest.strip()))
    return found


def pip_installs(steps: list[tuple[int, str, str]]) -> list[tuple[int, int, str]]:
    return [(index, stage, rest) for index, (stage, keyword, rest) in enumerate(steps)
            if keyword == "RUN" and "pip install" in rest]


def requirements_install(steps) -> tuple[int, int, str]:
    for index, stage, rest in pip_installs(steps):
        if re.search(r"\s-r\s", rest):
            return index, stage, rest
    raise AssertionError("no `pip install -r` step")


def torch_install(steps) -> tuple[int, int, str]:
    for index, stage, rest in pip_installs(steps):
        if "TORCH_INDEX_URL" in rest:
            return index, stage, rest
    raise AssertionError("no `pip install` step reads TORCH_INDEX_URL")


def torch_index_default(steps, stage: int) -> tuple[int, str]:
    for index, (arg_stage, keyword, rest) in enumerate(steps):
        name, _, value = rest.partition("=")
        if keyword == "ARG" and arg_stage == stage and name == "TORCH_INDEX_URL":
            return index, value
    raise AssertionError("no ARG TORCH_INDEX_URL in the stage that installs torch")


def requirements_path(install: str) -> str:
    return re.search(r"\s-r\s+(\S+)", install).group(1)


def build_args(spec: dict) -> dict[str, str]:
    args = (spec.get("build") or {}).get("args") or {}
    if isinstance(args, list):
        return dict(item.split("=", 1) for item in args)
    return {key: str(value) for key, value in args.items()}


def compose_tag(loader, _tag: str, node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)


def load_yaml(path: Path) -> dict:
    loader = type("ComposeLoader", (yaml.SafeLoader,), {})
    loader.add_multi_constructor("!", compose_tag)
    return yaml.load(path.read_text(encoding="utf-8"), Loader=loader)


def check(packages: str, pin: str = "torch==2.14.1\n") -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "packages.txt"
        listing.write_text(packages, encoding="utf-8")
        requirements = Path(tmp) / "requirements.txt"
        requirements.write_text("fastapi\n" + pin, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_cpu_image.main([str(listing), "--requirements", str(requirements)])
    return code, out.getvalue()


class TorchPin(unittest.TestCase):
    def test_every_requirement_file_pins_one_exact_public_torch_version(self):
        for path in REQUIREMENT_FILES:
            with self.subTest(str(path.relative_to(REPO))):
                pins = torch_requirements(path)
                self.assertEqual(len(pins), 1, pins)
                self.assertIsNotNone(EXACT_PUBLIC_TORCH_PIN.fullmatch(pins[0]),
                                     f"{pins[0]} is not torch==X, which both indexes serve")

    def test_all_services_pin_the_same_torch_version(self):
        pins = {str(path.relative_to(REPO)): torch_requirements(path) for path in REQUIREMENT_FILES}
        self.assertEqual(len({tuple(found) for found in pins.values()}), 1, pins)

    def test_the_cpu_requirements_file_reads_torch_from_the_cpu_index(self):
        text = (SERVICES / "mas" / "requirements-cpu.txt").read_text(encoding="utf-8")
        self.assertIn(f"--extra-index-url {CPU_TORCH_INDEX}", text.splitlines())


@needs_yaml
class CiTestJobsInstallCpuTorch(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.jobs = load_yaml(CI_WORKFLOW)["jobs"]

    def runs(self, job: str) -> list[str]:
        return [step.get("run", "") for step in self.jobs[job]["steps"]]

    def step_running(self, job: str, text: str) -> int:
        for index, run in enumerate(self.runs(job)):
            if text in run:
                return index
        raise AssertionError(f"{job} has no step running {text!r}")

    def requirements_install(self, job: str) -> str:
        requirements, _ = CPU_TORCH_TEST_JOBS[job]
        for run in self.runs(job):
            for line in run.splitlines():
                if f"-r {requirements}" in line:
                    return line
        raise AssertionError(f"{job} does not install {requirements}")

    def test_the_requirements_are_installed_with_the_cpu_torch_index_as_an_extra_index(self):
        for job in CPU_TORCH_TEST_JOBS:
            with self.subTest(job):
                install = self.requirements_install(job)
                self.assertIn(f"--extra-index-url {CPU_TORCH_INDEX}", install)
                self.assertIsNone(re.search(r"\s(?:-i|--index-url)[\s=]", install), install)

    def test_the_installed_torch_must_be_the_pinned_cpu_build_before_the_tests_run(self):
        for job, (requirements, _) in CPU_TORCH_TEST_JOBS.items():
            with self.subTest(job):
                check = self.runs(job)[self.step_running(job, "scripts/ci/check-cpu-image.py")]
                self.assertIn("pip list --format=freeze", check)
                self.assertIn(f"--requirements {requirements}", check)
                self.assertLess(self.step_running(job, "scripts/ci/check-cpu-image.py"),
                                self.step_running(job, "pytest -c"))
                self.assertGreater(self.step_running(job, "scripts/ci/check-cpu-image.py"),
                                   self.step_running(job, f"-r {requirements}"))

    def test_the_coverage_gates_are_kept(self):
        for job, (_, gate) in CPU_TORCH_TEST_JOBS.items():
            with self.subTest(job):
                tests = self.runs(job)[self.step_running(job, "pytest -c")]
                self.assertIn(f"--cov-fail-under={gate}", tests)


class DockerfileTorchInstall(unittest.TestCase):
    def test_each_image_declares_a_torch_index_build_arg_defaulting_to_pypi(self):
        for name, context in TORCH_SERVICES.items():
            with self.subTest(name):
                steps = instructions(context / "Dockerfile")
                _, stage, _ = torch_install(steps)
                self.assertEqual(torch_index_default(steps, stage)[1], DEFAULT_INDEX)

    def test_torch_is_installed_from_that_index_before_the_requirements(self):
        for name, context in TORCH_SERVICES.items():
            with self.subTest(name):
                steps = instructions(context / "Dockerfile")
                torch_at, torch_stage, _ = torch_install(steps)
                reqs_at, reqs_stage, _ = requirements_install(steps)
                arg_at, _ = torch_index_default(steps, torch_stage)
                self.assertEqual(torch_stage, reqs_stage)
                self.assertLess(arg_at, torch_at)
                self.assertLess(torch_at, reqs_at)

    def test_the_torch_install_takes_its_version_from_the_service_requirements(self):
        for name, context in TORCH_SERVICES.items():
            with self.subTest(name):
                steps = instructions(context / "Dockerfile")
                torch_run = torch_install(steps)[2]
                path = requirements_path(requirements_install(steps)[2])
                self.assertIn(f"torch_pin=\"$(grep -oE '^torch==[0-9.]+' {path})\"", torch_run)
                self.assertRegex(torch_run, r'--index-url\s+"\$TORCH_INDEX_URL"\s+"\$torch_pin"')

    def test_the_requirements_install_keeps_the_torch_already_installed(self):
        for name, context in TORCH_SERVICES.items():
            with self.subTest(name):
                install = requirements_install(instructions(context / "Dockerfile"))[2]
                options = {token.split("=", 1)[0] for token in install.split()}
                self.assertFalse(options & REINSTALLING_PIP_OPTIONS, install)


class CpuImageCheck(unittest.TestCase):
    def test_a_cpu_only_image_passes(self):
        code, out = check("fastapi==0.128.0\ntorch==2.14.1+cpu\nnumpy==1.26.4\n")
        self.assertEqual(code, 0, out)
        self.assertIn("torch 2.14.1+cpu", out)

    def test_an_nvidia_package_fails_and_is_named(self):
        code, out = check("torch==2.14.1+cpu\nnvidia-cudnn-cu13==9.24.0.43\n")
        self.assertEqual(code, 1)
        self.assertIn("nvidia-cudnn-cu13", out)

    def test_package_names_are_compared_like_pip_compares_them(self):
        code, out = check("torch==2.14.1+cpu\nNVIDIA_cublas.CU12==12.8.4.1\n")
        self.assertEqual(code, 1)
        self.assertIn("NVIDIA_cublas.CU12", out)

    def test_the_cuda_runtime_and_triton_fail(self):
        for package in ("cuda-toolkit==13.0.3", "cuda-bindings==13.0.3", "triton==3.8.0"):
            with self.subTest(package):
                code, out = check(f"torch==2.14.1+cpu\n{package}\n")
                self.assertEqual(code, 1)
                self.assertIn(package.split("==")[0], out)

    def test_a_cuda_build_of_torch_fails(self):
        for torch in ("torch==2.14.1", "torch==2.14.1+cu130"):
            with self.subTest(torch):
                code, out = check(f"{torch}\n")
                self.assertEqual(code, 1)
                self.assertIn("not the CPU build", out)

    def test_a_torch_other_than_the_pinned_one_fails(self):
        code, out = check("torch==2.13.0+cpu\n")
        self.assertEqual(code, 1)
        self.assertIn("pins torch==2.14.1", out)

    def test_direct_url_lines_are_read_by_name(self):
        code, out = check(
            "torch==2.14.1+cpu\n"
            "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/"
            "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl\n"
        )
        self.assertEqual(code, 0, out)

    def test_an_empty_package_list_fails_instead_of_passing_silently(self):
        code, out = check("\n")
        self.assertEqual(code, 1)
        self.assertIn("no packages", out)


@needs_yaml
class ComposeCpuOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = load_yaml(INFRA / profiles.BASE_COMPOSE)["services"]
        cls.overlay = load_yaml(INFRA / profiles.CPU_OVERLAY)["services"]

    def test_the_cpu_overlay_builds_every_torch_service_from_the_cpu_index(self):
        for name in TORCH_SERVICES:
            with self.subTest(name):
                self.assertEqual(build_args(self.overlay[name]).get("TORCH_INDEX_URL"),
                                 CPU_TORCH_INDEX)

    def test_the_overlay_only_adds_build_args_to_the_base_build(self):
        for name in TORCH_SERVICES:
            with self.subTest(name):
                self.assertEqual(set(self.overlay[name]["build"]), {"args"})

    def test_the_base_compose_leaves_torch_on_the_dockerfile_default(self):
        for name in TORCH_SERVICES:
            with self.subTest(name):
                self.assertNotIn("TORCH_INDEX_URL", build_args(self.base[name]))

    def test_each_profile_builds_torch_from_the_index_its_hardware_needs(self):
        layers = {
            profiles.BASE_COMPOSE: self.base,
            profiles.CPU_OVERLAY: self.overlay,
        }
        linux = {"os": {"platform": "linux"}}
        for profile in profiles.PROFILE_ORDER:
            files = profiles.env_for(profile, linux)["COMPOSE_FILE"].split(":")
            expected = CPU_TORCH_INDEX if profiles.is_cpu_profile(profile) else DEFAULT_INDEX
            for name, context in TORCH_SERVICES.items():
                with self.subTest(f"{profile} {name}"):
                    steps = instructions(context / "Dockerfile")
                    index = torch_index_default(steps, torch_install(steps)[1])[1]
                    for file in files:
                        index = build_args(layers[file].get(name) or {}).get(
                            "TORCH_INDEX_URL", index)
                    self.assertEqual(index, expected)


@needs_yaml
class CiCpuImageJob(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.job = load_yaml(CI_WORKFLOW)["jobs"][CPU_IMAGE_JOB]
        cls.matrix = cls.job["strategy"]["matrix"]["include"]
        cls.script = "\n".join(step.get("run", "") for step in cls.job["steps"])

    def test_the_job_builds_every_torch_service(self):
        self.assertEqual({entry["service"] for entry in self.matrix}, set(TORCH_SERVICES))

    def test_each_matrix_entry_names_the_build_context_of_its_service(self):
        for entry in self.matrix:
            with self.subTest(entry["service"]):
                self.assertEqual(SERVICES / entry["context"], TORCH_SERVICES[entry["service"]])

    def test_the_images_are_built_through_the_cpu_overlay(self):
        self.assertRegex(
            self.script,
            rf"-f {re.escape(profiles.BASE_COMPOSE)} -f {re.escape(profiles.CPU_OVERLAY)}"
            r"\s*\\?\s*build \$\{\{ matrix\.service \}\}",
        )

    def test_every_built_image_is_checked_for_cuda_packages(self):
        self.assertIn("pip list --format=freeze", self.script)
        self.assertIn("scripts/ci/check-cpu-image.py", self.script)
        self.assertIn("src/services/${{ matrix.context }}/requirements.txt", self.script)

    def test_the_job_waits_for_the_wiring_checks(self):
        self.assertIn("cpu-build-wiring", self.job.get("needs", []))


if __name__ == "__main__":
    unittest.main()
