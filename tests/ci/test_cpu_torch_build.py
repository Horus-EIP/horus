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
CPU_REQUIREMENTS = "requirements.txt"
GPU_REQUIREMENTS = "requirements-gpu.txt"
CPU_LOCK = "requirements.lock"
GPU_LOCK = "requirements-gpu.lock"

TORCH_SERVICES = {
    "mas": SERVICES / "mas",
    "agent": SERVICES / "agent",
    "knowledge_store": SERVICES / "knowledge-store",
}

CPU_REQUIREMENT_FILES = (
    *(context / CPU_REQUIREMENTS for context in TORCH_SERVICES.values()),
    SERVICES / "mas" / "requirements-cpu.txt",
)
GPU_REQUIREMENT_FILES = tuple(context / GPU_REQUIREMENTS for context in TORCH_SERVICES.values())
REQUIREMENT_FILES = tuple(sorted(SERVICES.glob("*/requirements*.txt")))
LOCK_ENTRY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:==(\S+)|\s+@\s+(\S+))")
EXACT_PIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?==(\S+)")

NEEDS_TORCH = {
    "torch", "sentence-transformers", "transformers", "accelerate", "bitsandbytes",
    "en-core-web-trf", "spacy-curated-transformers",
}

FASTEMBED_SERVICES = ("mas", "knowledge_store")

TEST_JOBS = {
    "test-mas": ("src/services/mas/requirements.txt", 85, None),
    "test-agent": ("src/services/agent/requirements-gpu.txt", 90, CPU_TORCH_INDEX),
    "test-knowledge-store": ("src/services/knowledge-store/requirements.txt", 85, None),
}

EXACT_PUBLIC_TORCH_PIN = re.compile(r"torch==\d+(?:\.\d+)*")

REINSTALLING_PIP_OPTIONS = {
    "-U", "--upgrade", "--force-reinstall", "-I", "--ignore-installed",
    "-i", "--index-url", "--extra-index-url",
}

REQUIREMENTS_CHOICE = re.compile(
    r'case "\$TORCH_INDEX_URL" in\s+(\S+)\)\s+cp\s+(\S+)\s+(\S+)\s*;;'
    r"\s*\*\)\s+cp\s+(\S+)\s+(\S+)\s*;;\s*esac"
)

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the compose and CI files")


def project_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
    return re.sub(r"[-_.]+", "-", match.group(0)).lower() if match else ""


def requirement_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def projects(path: Path) -> set[str]:
    return {project_name(line) for line in requirement_lines(path) if not line.startswith("-")}


def included(path: Path) -> list[str]:
    return [line.split(None, 1)[1] for line in requirement_lines(path) if line.startswith("-r ")]


def declared(path: Path) -> list[str]:
    lines = []
    for line in requirement_lines(path):
        if line.startswith("-r "):
            lines += declared(path.parent / line.split(None, 1)[1])
        elif not line.startswith("-"):
            lines.append(line)
    return lines


def lock_entries(path: Path) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        if raw[0] not in " \t":
            match = LOCK_ENTRY.match(raw)
            if match is None:
                raise AssertionError(f"{path.name}: cannot read {raw!r}")
            current = project_name(match.group(1))
            entries[current] = {"version": match.group(2) or match.group(3), "hashes": 0}
        elif "--hash=sha256:" in raw:
            entries[current]["hashes"] += 1
    return entries


def torch_requirements(path: Path) -> list[str]:
    return [line.replace(" ", "") for line in requirement_lines(path)
            if not line.startswith("-") and project_name(line) == "torch"]


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


def requirements_choice(steps) -> tuple[int, int, re.Match]:
    for index, (stage, keyword, rest) in enumerate(steps):
        match = REQUIREMENTS_CHOICE.search(rest) if keyword == "RUN" else None
        if match:
            return index, stage, match
    raise AssertionError("no step picks the requirement set from TORCH_INDEX_URL")


def torch_index_default(steps, stage: int) -> tuple[int, str]:
    for index, (arg_stage, keyword, rest) in enumerate(steps):
        name, _, value = rest.partition("=")
        if keyword == "ARG" and arg_stage == stage and name == "TORCH_INDEX_URL":
            return index, value
    raise AssertionError("no ARG TORCH_INDEX_URL in the stage that installs torch")


def requirements_path(install: str) -> str:
    return re.search(r"\s-r\s+(\S+)", install).group(1)


def chosen_requirements(context: Path, index_url: str) -> str:
    match = requirements_choice(instructions(context / "Dockerfile"))[2]
    cpu_index, cpu_source, _, gpu_source, _ = match.groups()
    return Path(cpu_source if index_url == cpu_index else gpu_source).name


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


def run_check(packages: str, requirements: str | None = "fastapi\ntorch==2.14.1\n") -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "packages.txt"
        listing.write_text(packages, encoding="utf-8")
        argv = [str(listing)]
        if requirements is not None:
            path = Path(tmp) / "requirements.txt"
            path.write_text(requirements, encoding="utf-8")
            argv += ["--requirements", str(path)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_cpu_image.main(argv)
    return code, out.getvalue()


def check(packages: str) -> tuple[int, str]:
    return run_check(packages)


def check_cpu_set(packages: str) -> tuple[int, str]:
    return run_check(packages, "fastapi\nfastembed==0.8.1\n")


class RequirementSets(unittest.TestCase):
    def test_the_cpu_requirements_need_no_torch(self):
        for path in CPU_REQUIREMENT_FILES:
            with self.subTest(str(path.relative_to(REPO))):
                self.assertEqual(projects(path) & NEEDS_TORCH, set())

    def test_every_gpu_requirement_file_pins_one_exact_public_torch_version(self):
        for path in GPU_REQUIREMENT_FILES:
            with self.subTest(str(path.relative_to(REPO))):
                pins = torch_requirements(path)
                self.assertEqual(len(pins), 1, pins)
                self.assertIsNotNone(EXACT_PUBLIC_TORCH_PIN.fullmatch(pins[0]),
                                     f"{pins[0]} is not torch==X, which both indexes serve")

    def test_all_services_pin_the_same_torch_version(self):
        pins = {str(path.relative_to(REPO)): torch_requirements(path)
                for path in GPU_REQUIREMENT_FILES}
        self.assertEqual(len({tuple(found) for found in pins.values()}), 1, pins)

    def test_a_gpu_image_installs_everything_a_cpu_image_does(self):
        for path in GPU_REQUIREMENT_FILES:
            with self.subTest(str(path.relative_to(REPO))):
                self.assertEqual(included(path), [CPU_REQUIREMENTS])

    def test_the_mas_cpu_requirements_are_the_cpu_set(self):
        self.assertEqual(included(SERVICES / "mas" / "requirements-cpu.txt"), [CPU_REQUIREMENTS])

    def test_no_image_installs_sentence_transformers(self):
        for path in (*CPU_REQUIREMENT_FILES, *GPU_REQUIREMENT_FILES):
            with self.subTest(str(path.relative_to(REPO))):
                self.assertNotIn("sentence-transformers", projects(path))

    def test_the_embedders_run_on_a_pinned_fastembed(self):
        for name in FASTEMBED_SERVICES:
            with self.subTest(name):
                pins = [line for line in requirement_lines(TORCH_SERVICES[name] / CPU_REQUIREMENTS)
                        if project_name(line) == "fastembed"]
                self.assertEqual(len(pins), 1, pins)
                self.assertRegex(pins[0], r"^fastembed==\d+(?:\.\d+)*$")


class LockFiles(unittest.TestCase):
    def test_every_requirements_file_has_a_lock_next_to_it(self):
        for path in REQUIREMENT_FILES:
            with self.subTest(str(path.relative_to(REPO))):
                self.assertTrue(path.with_suffix(".lock").is_file())

    def test_every_locked_package_is_pinned_and_hashed(self):
        for path in REQUIREMENT_FILES:
            lock = path.with_suffix(".lock")
            for name, entry in lock_entries(lock).items():
                with self.subTest(f"{lock.relative_to(REPO)} {name}"):
                    self.assertTrue(entry["version"])
                    self.assertGreater(entry["hashes"], 0)

    def test_each_lock_holds_what_its_requirements_file_asks_for(self):
        for path in REQUIREMENT_FILES:
            entries = lock_entries(path.with_suffix(".lock"))
            for line in declared(path):
                name = project_name(line)
                with self.subTest(f"{path.relative_to(REPO)} {name}"):
                    self.assertIn(name, entries)
                    pin = EXACT_PIN.fullmatch(line.replace(" ", ""))
                    if pin:
                        self.assertEqual(entries[name]["version"], pin.group(1))

    def test_the_cpu_and_gpu_locks_agree_on_every_shared_package(self):
        for context in TORCH_SERVICES.values():
            gpu = lock_entries(context / GPU_LOCK)
            for lock in sorted(context.glob("requirements*.lock")):
                if lock.name == GPU_LOCK:
                    continue
                for name, entry in lock_entries(lock).items():
                    with self.subTest(f"{lock.relative_to(REPO)} {name}"):
                        self.assertIn(name, gpu)
                        self.assertEqual(entry["version"], gpu[name]["version"])


@needs_yaml
class CiTestJobs(unittest.TestCase):
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
        requirements, _, _ = TEST_JOBS[job]
        for run in self.runs(job):
            for line in run.splitlines():
                if f"-r {requirements}" in line:
                    return line
        raise AssertionError(f"{job} does not install {requirements}")

    def test_only_the_jobs_that_need_torch_read_the_cpu_torch_index(self):
        for job, (_, _, index) in TEST_JOBS.items():
            with self.subTest(job):
                install = self.requirements_install(job)
                self.assertIsNone(re.search(r"\s(?:-i|--index-url)[\s=]", install), install)
                if index is None:
                    self.assertNotIn("--extra-index-url", install)
                else:
                    self.assertIn(f"--extra-index-url {index}", install)

    def test_the_installed_packages_are_checked_before_the_tests_run(self):
        for job, (requirements, _, _) in TEST_JOBS.items():
            with self.subTest(job):
                check = self.runs(job)[self.step_running(job, "scripts/ci/check-cpu-image.py")]
                self.assertIn("pip list --format=freeze", check)
                self.assertIn(f"--requirements {requirements}", check)
                self.assertLess(self.step_running(job, "scripts/ci/check-cpu-image.py"),
                                self.step_running(job, "pytest -c"))
                self.assertGreater(self.step_running(job, "scripts/ci/check-cpu-image.py"),
                                   self.step_running(job, f"-r {requirements}"))

    def test_the_jobs_without_torch_check_against_a_set_that_pins_none(self):
        for job, (requirements, _, index) in TEST_JOBS.items():
            with self.subTest(job):
                pins = torch_requirements(REPO / requirements)
                self.assertEqual(bool(pins), index is not None, pins)

    def test_the_knowledge_store_is_tested_on_the_python_of_its_image(self):
        self.assertEqual(self.jobs["test-knowledge-store"]["env"]["PYTHON_VERSION"], "3.11")
        self.assertIn("FROM python:3.11-slim",
                      (TORCH_SERVICES["knowledge_store"] / "Dockerfile").read_text(encoding="utf-8"))

    def test_the_coverage_gates_are_kept(self):
        for job, (_, gate, _) in TEST_JOBS.items():
            with self.subTest(job):
                tests = self.runs(job)[self.step_running(job, "pytest -c")]
                self.assertIn(f"--cov-fail-under={gate}", tests)


class DockerfileRequirementSets(unittest.TestCase):
    def test_each_image_declares_a_torch_index_build_arg_defaulting_to_pypi(self):
        for name, context in TORCH_SERVICES.items():
            with self.subTest(name):
                steps = instructions(context / "Dockerfile")
                _, stage, _ = torch_install(steps)
                self.assertEqual(torch_index_default(steps, stage)[1], DEFAULT_INDEX)

    def test_both_requirement_sets_are_copied_into_the_build(self):
        for name, context in TORCH_SERVICES.items():
            with self.subTest(name):
                copies = [rest for _, keyword, rest in instructions(context / "Dockerfile")
                          if keyword == "COPY" and GPU_LOCK in rest]
                self.assertEqual(len(copies), 1, copies)
                self.assertIn(CPU_LOCK, copies[0].split())

    def test_the_cpu_torch_index_picks_the_cpu_set_and_any_other_the_gpu_set(self):
        for name, context in TORCH_SERVICES.items():
            with self.subTest(name):
                self.assertEqual(chosen_requirements(context, CPU_TORCH_INDEX), CPU_LOCK)
                self.assertEqual(chosen_requirements(context, DEFAULT_INDEX), GPU_LOCK)
                self.assertEqual(
                    chosen_requirements(context, "https://download.pytorch.org/whl/cu128"),
                    GPU_LOCK,
                )

    def test_the_chosen_set_is_what_torch_and_the_requirements_are_installed_from(self):
        for name, context in TORCH_SERVICES.items():
            with self.subTest(name):
                steps = instructions(context / "Dockerfile")
                choice_at, choice_stage, match = requirements_choice(steps)
                _, _, cpu_target, _, gpu_target = match.groups()
                torch_at, torch_stage, torch_run = torch_install(steps)
                reqs_at, reqs_stage, reqs_run = requirements_install(steps)
                self.assertEqual(cpu_target, gpu_target)
                self.assertEqual(requirements_path(reqs_run), cpu_target)
                self.assertIn(f"grep -oE '^torch==[0-9.]+' {cpu_target}", torch_run)
                self.assertEqual({choice_stage, torch_stage, reqs_stage}, {torch_stage})
                self.assertLess(choice_at, torch_at)
                self.assertLess(torch_at, reqs_at)

    def test_torch_is_installed_from_the_index_only_when_the_set_pins_it(self):
        for name, context in TORCH_SERVICES.items():
            with self.subTest(name):
                torch_run = torch_install(instructions(context / "Dockerfile"))[2]
                self.assertIn('if [ -n "$torch_pin" ]', torch_run)
                self.assertRegex(torch_run, r'--index-url\s+"\$TORCH_INDEX_URL"\s+"\$torch_pin"')

    def test_the_requirements_install_keeps_the_torch_already_installed(self):
        for name, context in TORCH_SERVICES.items():
            with self.subTest(name):
                install = requirements_install(instructions(context / "Dockerfile"))[2]
                options = {token.split("=", 1)[0] for token in install.split()}
                self.assertFalse(options & REINSTALLING_PIP_OPTIONS, install)

    def test_the_requirements_install_checks_every_hash(self):
        for name, context in TORCH_SERVICES.items():
            with self.subTest(name):
                install = requirements_install(instructions(context / "Dockerfile"))[2]
                self.assertIn("--require-hashes", install.split())

    def test_the_embedders_are_baked_in_with_fastembed(self):
        for name in FASTEMBED_SERVICES:
            with self.subTest(name):
                dockerfile = (TORCH_SERVICES[name] / "Dockerfile").read_text(encoding="utf-8")
                self.assertIn("ENV FASTEMBED_CACHE_PATH=", dockerfile)
                self.assertIn("from fastembed import TextEmbedding", dockerfile)
                self.assertNotIn("sentence_transformers", dockerfile)


class CpuImageCheck(unittest.TestCase):
    def test_a_cpu_only_environment_with_its_pinned_torch_passes(self):
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

    def test_a_cpu_image_without_torch_passes(self):
        code, out = check_cpu_set("fastapi==0.128.0\nfastembed==0.8.1\nonnxruntime==1.30.0\n")
        self.assertEqual(code, 0, out)
        self.assertIn("no torch", out)

    def test_any_torch_in_a_cpu_image_fails_even_the_cpu_build(self):
        for torch in ("torch==2.14.1+cpu", "torch==2.14.1"):
            with self.subTest(torch):
                code, out = check_cpu_set(f"fastapi==0.128.0\n{torch}\n")
                self.assertEqual(code, 1)
                self.assertIn("is in a CPU image", out)
                self.assertIn("pins no torch", out)

    def test_sentence_transformers_in_a_cpu_image_fails(self):
        code, out = check_cpu_set("fastapi==0.128.0\nsentence_transformers==3.4.1\n")
        self.assertEqual(code, 1)
        self.assertIn("sentence_transformers==3.4.1 is in a CPU image", out)

    def test_without_a_requirements_file_torch_is_not_allowed(self):
        code, out = run_check("fastapi==0.128.0\ntorch==2.14.1+cpu\n", requirements=None)
        self.assertEqual(code, 1)
        self.assertIn("is in a CPU image", out)


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

    def resolved_index(self, profile: str, name: str, context: Path) -> str:
        layers = {
            profiles.BASE_COMPOSE: self.base,
            profiles.CPU_OVERLAY: self.overlay,
        }
        files = profiles.env_for(profile, {"os": {"platform": "linux"}})["COMPOSE_FILE"].split(":")
        steps = instructions(context / "Dockerfile")
        index = torch_index_default(steps, torch_install(steps)[1])[1]
        for file in files:
            index = build_args(layers[file].get(name) or {}).get("TORCH_INDEX_URL", index)
        return index

    def test_each_profile_builds_torch_from_the_index_its_hardware_needs(self):
        for profile in profiles.PROFILE_ORDER:
            expected = CPU_TORCH_INDEX if profiles.is_cpu_profile(profile) else DEFAULT_INDEX
            for name, context in TORCH_SERVICES.items():
                with self.subTest(f"{profile} {name}"):
                    self.assertEqual(self.resolved_index(profile, name, context), expected)

    def test_cpu_profiles_install_no_torch_and_gpu_profiles_keep_it(self):
        for profile in profiles.PROFILE_ORDER:
            cpu = profiles.is_cpu_profile(profile)
            for name, context in TORCH_SERVICES.items():
                with self.subTest(f"{profile} {name}"):
                    chosen = chosen_requirements(context, self.resolved_index(profile, name, context))
                    self.assertEqual(chosen, CPU_LOCK if cpu else GPU_LOCK)
                    self.assertEqual(bool(torch_requirements(context / chosen)), not cpu)


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

    def test_every_built_image_is_checked_for_cuda_packages_and_torch(self):
        self.assertIn("pip list --format=freeze", self.script)
        self.assertIn("scripts/ci/check-cpu-image.py", self.script)
        self.assertIn(f"src/services/${{{{ matrix.context }}}}/{CPU_REQUIREMENTS}", self.script)

    def test_the_requirements_the_job_checks_against_pin_no_torch(self):
        for entry in self.matrix:
            with self.subTest(entry["service"]):
                self.assertEqual(torch_requirements(SERVICES / entry["context"] / CPU_REQUIREMENTS), [])

    def test_the_job_waits_for_the_wiring_checks(self):
        self.assertIn("cpu-build-wiring", self.job.get("needs", []))


if __name__ == "__main__":
    unittest.main()
