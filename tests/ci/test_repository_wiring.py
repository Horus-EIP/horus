from __future__ import annotations

import configparser
import fnmatch
import re
import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parents[2]
INFRA = REPO / "src" / "infra"
SERVICES = REPO / "src" / "services"
WORKFLOWS = REPO / ".github" / "workflows"
DOCS = REPO / "docs"
COMPOSE_FILES = (INFRA / "docker-compose.yml", INFRA / "docker-compose.cpu.yml")
EVAL_TESTS = REPO / "tests" / "eval"
RESEARCH_NOTE = "tech-watch/IGPU_NPU_RESEARCH.md"

sys.path.insert(0, str(REPO / "installer"))
sys.path.insert(0, str(REPO / "scripts" / "licences"))
import images  # noqa: E402
import third_party_notices  # noqa: E402

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the CI files")

LIBRARY_SWITCHES = {"SENTENCE_TRANSFORMERS_": "sentence-transformers"}
DEV_TOOLS = ("pgadmin", "redisinsight")
EXACT_TAG = r"\d+\.\d+\.\d+|^\d+\.\d+$|-b\d+$"
IMAGE_SERVICES = ("mas", "agent", "knowledge-store", "web-client")
NOTICE_PATHS = ("THIRD_PARTY_NOTICES", "LICENSES", "NOTICES")


def project_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
    return re.sub(r"[-_.]+", "-", match.group(0)).lower() if match else ""


def installed_projects() -> set[str]:
    found = set()
    for path in SERVICES.glob("*/requirements*.txt"):
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split(" #", 1)[0].strip()
            if line and not line.startswith(("#", "-")):
                found.add(project_name(line))
    return found


def compose_variables() -> set[str]:
    names = set()
    for path in COMPOSE_FILES:
        names.update(re.findall(r"^\s*-\s*([A-Z][A-Z0-9_]*)=", path.read_text(encoding="utf-8"),
                                re.MULTILINE))
    return names


def load_workflow(name: str) -> dict:
    document = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    if True in document and "on" not in document:
        document["on"] = document.pop(True)
    return document


def step_running(job: dict, text: str) -> dict:
    for step in job["steps"]:
        if text in step.get("run", ""):
            return step
    raise AssertionError(f"no step runs {text!r}")


def requirement_pins_torch(path: Path) -> bool:
    return any(project_name(line.strip()) == "torch"
               for line in path.read_text(encoding="utf-8").splitlines()
               if not line.strip().startswith(("#", "-")))


def ignore_patterns() -> list[str]:
    patterns = []
    for raw in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith(("#", "!")):
            patterns.append(line.lstrip("/").removeprefix("**/"))
    return patterns


def eval_script_folders() -> list[str]:
    parser = configparser.ConfigParser()
    parser.read(EVAL_TESTS / "pytest.ini", encoding="utf-8")
    folders = []
    for entry in parser["pytest"]["pythonpath"].split():
        folder = (EVAL_TESTS / entry).resolve()
        folders.append(folder.relative_to(REPO).as_posix())
    return folders


class ComposeEnvironment(unittest.TestCase):
    def test_no_service_sets_a_switch_for_a_library_no_image_installs(self):
        installed = installed_projects()
        for variable in sorted(compose_variables()):
            for prefix, project in LIBRARY_SWITCHES.items():
                if variable.startswith(prefix):
                    with self.subTest(variable):
                        self.assertTrue(project in installed,
                                        f"{variable} configures {project}, which no image installs")


@needs_yaml
class ReleaseWorkflow(unittest.TestCase):
    def test_the_cpu_image_check_is_named_like_the_ci_one(self):
        release = load_workflow("images.yml")["jobs"]["image"]
        ci = load_workflow("ci.yml")["jobs"]["cpu-images"]
        check = "scripts/ci/check-cpu-image.py"
        self.assertEqual(step_running(release, check)["name"], step_running(ci, check)["name"])

    def test_the_cpu_image_check_name_matches_requirements_without_torch(self):
        release = load_workflow("images.yml")["jobs"]["image"]
        requirements = [entry["requirements"] for entry in release["strategy"]["matrix"]["include"]
                        if "requirements" in entry]
        self.assertTrue(requirements)
        name = step_running(release, "scripts/ci/check-cpu-image.py")["name"]
        for path in requirements:
            with self.subTest(path):
                self.assertFalse(requirement_pins_torch(REPO / path))
                self.assertNotIn("pinned", name)
                self.assertIn("any torch", name)


@needs_yaml
class EvalWorkflowTriggers(unittest.TestCase):
    def test_every_script_folder_the_eval_tests_import_triggers_the_workflow(self):
        triggers = load_workflow("eval-testset.yml")["on"]
        folders = eval_script_folders()
        self.assertIn("scripts/benchmarks", folders)
        for event in ("push", "pull_request"):
            for folder in folders:
                with self.subTest(event=event, folder=folder):
                    self.assertIn(f"{folder}/**", triggers[event]["paths"])


def compose_service(name: str) -> str:
    lines = (INFRA / "docker-compose.yml").read_text(encoding="utf-8").splitlines()
    start = lines.index(f"  {name}:")
    block = []
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith("   "):
            break
        block.append(line)
    return "\n".join(block)


def installer_sources() -> list[Path]:
    return [
        *sorted((REPO / "installer").glob("*.py")),
        *sorted((REPO / "desktop" / "src-tauri" / "src").glob("*.rs")),
        *sorted(path for path in (REPO / "packaging").iterdir() if path.is_file()),
        REPO / "stack-up.sh",
    ]


class DevTools(unittest.TestCase):
    def test_pgadmin_and_redisinsight_start_only_with_the_dev_tools_profile(self):
        for name in DEV_TOOLS:
            with self.subTest(name):
                self.assertRegex(compose_service(name), r'(?m)^    profiles: \["dev-tools"\]$')

    def test_the_installer_never_turns_the_profile_on(self):
        for path in installer_sources():
            text = path.read_text(encoding="utf-8", errors="ignore")
            with self.subTest(path.relative_to(REPO).as_posix()):
                self.assertNotIn("dev-tools", text)
                self.assertNotIn("COMPOSE_PROFILES", text)

    def test_the_env_file_the_installer_copies_sets_no_profile(self):
        text = (INFRA / ".env.example").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?m)^\s*COMPOSE_PROFILES\s*=")


def final_stage(dockerfile: Path) -> list[str]:
    lines = [line.strip() for line in dockerfile.read_text(encoding="utf-8").splitlines()]
    starts = [index for index, line in enumerate(lines) if line.upper().startswith("FROM ")]
    return lines[starts[-1]:]


class LicenceFilesInImages(unittest.TestCase):
    def test_every_image_copies_the_notices_in_its_final_stage(self):
        for service in IMAGE_SERVICES:
            stage = final_stage(SERVICES / service / "Dockerfile")
            for name in NOTICE_PATHS:
                with self.subTest(f"{service} {name}"):
                    self.assertIn(f"COPY --from=notices {name} /usr/share/doc/horus/{name}", stage)

    def test_every_image_build_gets_the_repository_root_as_the_notices_context(self):
        text = (INFRA / "docker-compose.yml").read_text(encoding="utf-8")
        for service in IMAGE_SERVICES:
            with self.subTest(service):
                self.assertRegex(text, rf"context: \.\./services/{re.escape(service)}\n"
                                       r"\s+dockerfile: Dockerfile\n"
                                       r"\s+additional_contexts:\n\s+notices: \.\./\.\.\n")

    def test_the_notices_exist_at_the_repository_root(self):
        self.assertTrue((REPO / "THIRD_PARTY_NOTICES").is_file())
        self.assertTrue((REPO / "LICENSES").is_dir())
        self.assertTrue((REPO / "NOTICES").is_dir())


class LogShipping(unittest.TestCase):
    config = (INFRA / "observability" / "config.alloy").read_text(encoding="utf-8")

    def test_alloy_ships_the_logs_and_promtail_is_gone(self):
        self.assertRegex(compose_service("alloy"), r"(?m)^    image: grafana/alloy:v\d+\.\d+\.\d+$")
        self.assertFalse((INFRA / "observability" / "promtail.yaml").exists())
        for path in COMPOSE_FILES:
            with self.subTest(path.name):
                self.assertNotIn("promtail", path.read_text(encoding="utf-8").lower())

    def test_alloy_mounts_its_config_and_the_docker_socket_read_only(self):
        block = compose_service("alloy")
        self.assertIn("- ./observability/config.alloy:/etc/alloy/config.alloy:ro", block)
        self.assertIn("- /var/run/docker.sock:/var/run/docker.sock:ro", block)

    def test_loki_gets_the_labels_the_admin_logs_page_queries(self):
        route = (SERVICES / "web-client" / "app" / "api" / "logs" / "route.ts").read_text(encoding="utf-8")
        used = set(re.findall(r"label/(\w+)/values|\{(\w+)=|stream\?\.(\w+)", route))
        labels = {name for match in used for name in match if name}
        self.assertEqual(labels, {"compose_service", "container"})
        for label in labels:
            with self.subTest(label):
                self.assertRegex(self.config, rf'target_label\s*=\s*"{label}"')

    def test_containers_without_a_compose_service_are_never_read(self):
        self.assertRegex(self.config, r"targets\s*=\s*discovery\.relabel\.compose\.output")
        self.assertRegex(self.config, r'com_docker_compose_service"\]\s*regex\s*=\s*""\s*action\s*=\s*"drop"')
        self.assertNotIn("relabel_rules", self.config)


class ImageTags(unittest.TestCase):
    def test_every_image_names_an_exact_version(self):
        images = third_party_notices.used_images()
        self.assertTrue(images)
        for image, where in sorted(images.items()):
            tag = third_party_notices.tag_of(image)
            with self.subTest(f"{image} in {', '.join(sorted(where))}"):
                self.assertNotEqual(tag, "latest")
                self.assertRegex(tag, EXACT_TAG)


class GitIgnore(unittest.TestCase):
    def test_the_registry_token_file_is_never_committed(self):
        name = images.TOKEN_FILE_NAME
        self.assertTrue(any(fnmatch.fnmatch(name, pattern) for pattern in ignore_patterns()))


class DocsNav(unittest.TestCase):
    def setUp(self) -> None:
        self.nav = (DOCS / "mkdocs.yml").read_text(encoding="utf-8")

    def listed(self, page: str) -> bool:
        return re.search(rf":\s*{re.escape(page)}\s*$", self.nav, re.MULTILINE) is not None

    def test_every_adr_is_in_the_nav(self):
        for adr in sorted((DOCS / "adr").glob("ADR-*.md")):
            with self.subTest(adr.name):
                self.assertTrue(self.listed(f"adr/{adr.name}"))

    def test_the_integrated_gpu_and_npu_note_is_in_the_nav(self):
        self.assertTrue((DOCS / RESEARCH_NOTE).is_file())
        self.assertTrue(self.listed(RESEARCH_NOTE))


if __name__ == "__main__":
    unittest.main()
