from __future__ import annotations

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
WORKFLOW = REPO / ".github" / "workflows" / "images.yml"
THIS_FILE = Path(__file__).name

sys.path.insert(0, str(REPO / "installer"))
import images  # noqa: E402
import profiles  # noqa: E402

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the compose and CI files")

LINUX = {"os": {"platform": "linux"}}
REGISTRY = "ghcr.io/acme"
RELEASE = "1.2.3"
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
MOCK_OVERLAY = "docker-compose.mock.yml"
MOCK_COMPOSE_FILES = [profiles.BASE_COMPOSE, profiles.CPU_OVERLAY, MOCK_OVERLAY]
TORCH_REQUIREMENTS = {
    "mas": "src/services/mas/requirements.txt",
    "agent": "src/services/agent/requirements.txt",
    "knowledge_store": "src/services/knowledge-store/requirements.txt",
}


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


def resolve(text: str, env: dict[str, str]) -> str:
    out, at = [], 0
    while at < len(text):
        if not text.startswith("${", at):
            out.append(text[at])
            at += 1
            continue
        depth, end = 1, at + 2
        while depth:
            if text.startswith("${", end):
                depth, end = depth + 1, end + 2
                continue
            depth -= text[end] == "}"
            end += 1
        out.append(expand(text[at + 2:end - 1], env))
        at = end
    return "".join(out)


def expand(body: str, env: dict[str, str]) -> str:
    name, operator, rest = re.match(r"(\w+)(:?[-+?])?(.*)", body, re.DOTALL).groups()
    value = env.get(name)
    if operator is None:
        return value or ""
    present = value is not None and (value != "" or not operator.startswith(":"))
    if operator.endswith("-"):
        return value if present else resolve(rest, env)
    if operator.endswith("+"):
        return resolve(rest, env) if present else ""
    if not present:
        raise LookupError(f"{name}: {rest}")
    return value


def compose_files(profile: str) -> list[str]:
    return profiles.env_for(profile, LINUX)["COMPOSE_FILE"].split(":")


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


class ResolveHelper(unittest.TestCase):
    def test_it_follows_the_compose_interpolation_rules_used_here(self):
        env = {"A": "a", "EMPTY": ""}
        self.assertEqual(resolve("${A:-x}/${B:-y}/${EMPTY:-z}", env), "a/y/z")
        self.assertEqual(resolve("${A:+[${A}]}${B:+never}", env), "[a]")
        self.assertEqual(resolve("${B:+${C:?unused}}", env), "")
        with self.assertRaises(LookupError):
            resolve("${A:+${C:?C is required}}", env)


@needs_yaml
class ComposeImageNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.layers = {
            profiles.BASE_COMPOSE: load_yaml(INFRA / profiles.BASE_COMPOSE)["services"],
            profiles.CPU_OVERLAY: load_yaml(INFRA / profiles.CPU_OVERLAY)["services"],
            MOCK_OVERLAY: load_yaml(INFRA / MOCK_OVERLAY)["services"],
        }

    def image(self, service: str, files: list[str], env: dict[str, str]) -> str | None:
        value = None
        for file in files:
            spec = self.layers[file].get(service) or {}
            if "image" in spec:
                value = str(spec["image"])
        return None if value is None else resolve(value, env)

    def test_the_app_services_are_the_four_built_from_source(self):
        built = {name for name, spec in self.layers[profiles.BASE_COMPOSE].items()
                 if "build" in spec}
        self.assertEqual(built, set(images.APP_SERVICES))

    def test_every_profile_names_each_app_image_after_registry_release_and_flavor(self):
        env = {images.REGISTRY_KEY: REGISTRY, "HORUS_VERSION": RELEASE}
        for profile in profiles.PROFILE_ORDER:
            flavor = profiles.image_flavor(profile)
            for service in images.APP_SERVICES:
                with self.subTest(f"{profile} {service}"):
                    self.assertEqual(self.image(service, compose_files(profile), env),
                                     images.image_name(REGISTRY, service, RELEASE, flavor))

    def test_without_a_registry_the_images_keep_their_local_build_names(self):
        env = {"HORUS_VERSION": RELEASE}
        for profile in profiles.PROFILE_ORDER:
            for service in images.APP_SERVICES:
                with self.subTest(f"{profile} {service}"):
                    self.assertEqual(self.image(service, compose_files(profile), env), "")

    def test_a_registry_without_a_release_is_an_error_not_a_broken_tag(self):
        for service in images.APP_SERVICES:
            with self.subTest(service), self.assertRaises(LookupError):
                self.image(service, [profiles.BASE_COMPOSE], {images.REGISTRY_KEY: REGISTRY})

    def test_the_mock_model_server_is_a_cpu_image_named_like_the_others(self):
        env = {images.REGISTRY_KEY: REGISTRY, "HORUS_VERSION": RELEASE}
        self.assertEqual(self.image(images.MOCK_SERVICE, MOCK_COMPOSE_FILES, env),
                         images.image_name(REGISTRY, images.MOCK_SERVICE, RELEASE, images.CPU_FLAVOR))
        self.assertEqual(self.image(images.MOCK_SERVICE, MOCK_COMPOSE_FILES, {"HORUS_VERSION": RELEASE}), "")
        build = self.layers[MOCK_OVERLAY][images.MOCK_SERVICE]["build"]
        self.assertTrue((INFRA / build["context"] / "Dockerfile").is_file())
        self.assertEqual(build["additional_contexts"], {"notices": "../.."})

    def test_every_app_service_can_still_be_built_from_source(self):
        for service in images.APP_SERVICES:
            with self.subTest(service):
                context = self.layers[profiles.BASE_COMPOSE][service]["build"]["context"]
                self.assertTrue((INFRA / context / "Dockerfile").is_file())

    def test_the_env_example_leaves_the_registry_unset(self):
        lines = (INFRA / ".env.example").read_text(encoding="utf-8").splitlines()
        active = [line for line in lines if line.strip().startswith(f"{images.REGISTRY_KEY}=")]
        self.assertEqual(active, [])
        self.assertIn(f"# {images.REGISTRY_KEY}={images.DEFAULT_REGISTRY}", lines)


@needs_yaml
class ReleaseWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = load_yaml(WORKFLOW)
        cls.plan = cls.workflow["jobs"]["plan"]
        cls.job = cls.workflow["jobs"]["image"]
        cls.bundle = cls.workflow["jobs"]["bundle"]
        cls.matrix = cls.job["strategy"]["matrix"]
        cls.steps = cls.job["steps"]

    def step(self, job: dict, text: str) -> tuple[int, dict]:
        for index, step in enumerate(job["steps"]):
            if text in step.get("run", "") or text in step.get("uses", ""):
                return index, step
        raise AssertionError(f"no step runs or uses {text!r}")

    def includes(self, key: str) -> dict[str, dict]:
        return {entry[key]: entry for entry in self.matrix["include"] if key in entry}

    def test_it_runs_on_tags_and_by_hand_never_on_pushes_or_pull_requests(self):
        triggers = workflow_triggers(self.workflow)
        self.assertEqual(set(triggers), {"push", "workflow_dispatch"})
        self.assertEqual(triggers["push"], {"tags": ["v*"]})

    def test_the_matrix_builds_every_app_service_for_both_flavors(self):
        self.assertEqual(set(self.matrix["service"]), {*images.APP_SERVICES, images.MOCK_SERVICE})
        self.assertEqual(self.matrix["flavor"], [images.CPU_FLAVOR, images.GPU_FLAVOR])

    def test_the_mock_model_server_is_built_once_through_the_mock_overlay(self):
        self.assertEqual(self.matrix["exclude"],
                         [{"service": images.MOCK_SERVICE, "flavor": images.GPU_FLAVOR}])
        entry = self.includes("service")[images.MOCK_SERVICE]
        self.assertEqual(entry, {"service": images.MOCK_SERVICE,
                                 "compose_files": ":".join(MOCK_COMPOSE_FILES)})
        flavor_entries = [index for index, item in enumerate(self.matrix["include"]) if "flavor" in item]
        self.assertGreater(self.matrix["include"].index(entry), max(flavor_entries))

    def test_each_flavor_builds_with_the_compose_files_its_profiles_run(self):
        by_flavor = self.includes("flavor")
        for profile in profiles.PROFILE_ORDER:
            with self.subTest(profile):
                entry = by_flavor[profiles.image_flavor(profile)]
                self.assertEqual(entry["compose_files"],
                                 profiles.env_for(profile, LINUX)["COMPOSE_FILE"])

    def test_compose_reads_the_files_the_registry_and_the_release_from_the_job(self):
        env = self.job["env"]
        self.assertEqual(env["COMPOSE_FILE"], "${{ matrix.compose_files }}")
        self.assertEqual(env[images.REGISTRY_KEY], "${{ needs.plan.outputs.registry }}")
        self.assertEqual(env["HORUS_VERSION"], "${{ needs.plan.outputs.version }}")
        self.assertEqual(self.job["needs"], "plan")

    def test_the_image_name_is_read_from_compose_and_checked(self):
        _, step = self.step(self.job, "docker compose config --format json")
        self.assertIn('"$HORUS_REGISTRY"/horus-*":$HORUS_VERSION-$FLAVOR"', step["run"])
        self.assertIn("exit 1", step["run"])

    def test_the_image_is_built_through_compose(self):
        _, step = self.step(self.job, "docker compose --progress plain build")
        self.assertIn('build "$SERVICE"', step["run"])
        self.assertEqual(step["working-directory"], "src/infra")

    def test_cpu_torch_images_are_checked_for_cuda_before_anything_is_pushed(self):
        requirements = {name: entry["requirements"]
                        for name, entry in self.includes("service").items() if "requirements" in entry}
        self.assertEqual(requirements, TORCH_REQUIREMENTS)
        for path in requirements.values():
            self.assertTrue((REPO / path).is_file(), path)
        check_at, check = self.step(self.job, "scripts/ci/check-cpu-image.py")
        self.assertEqual(check["if"], "matrix.flavor == 'cpu' && matrix.requirements")
        login_at, _ = self.step(self.job, "docker/login-action")
        push_at, _ = self.step(self.job, "docker push")
        self.assertLess(check_at, login_at)
        self.assertLess(login_at, push_at)

    def test_copyleft_scan_checks_real_section_7_before_push(self):
        check_at, check = self.step(self.job, "report_image_copyleft.py")
        login_at, _ = self.step(self.job, "docker/login-action")
        push_at, _ = self.step(self.job, "docker push")
        self.assertIn('--service "$SERVICE"', check["run"])
        self.assertIn('--image "$IMAGE"', check["run"])
        self.assertLess(check_at, login_at)
        self.assertLess(login_at, push_at)

        report_at, report = self.step(self.job, "size unpacked")
        self.assertEqual(report["if"], "always()")
        self.assertGreater(report_at, push_at)
        self.assertIn("built in ${BUILD_SECONDS:-?} s", report["run"])

    def test_every_build_gets_a_commit_tag_and_only_a_release_moves_the_version_tag(self):
        _, plan = self.step(self.plan, "GITHUB_OUTPUT")
        self.assertIn('commit_tag=sha-${GITHUB_SHA::12}', plan["run"])
        self.assertIn('^refs/tags/v${version}(-rc[0-9]+|-rc\\.[0-9]+)?$', plan["run"])
        _, push = self.step(self.job, "docker push")
        self.assertIn('docker push "$REPOSITORY:$COMMIT_TAG"', push["run"])
        self.assertIn('RC_TAG="${REF_NAME#v}-${FLAVOR}"', push["run"])
        self.assertIn('docker push "$IMAGE"', push["run"])
        self.assertEqual(push["env"]["COMMIT_TAG"],
                         "${{ needs.plan.outputs.commit_tag }}-${{ matrix.flavor }}")

    def test_bundle_uses_the_same_rc_and_dispatch_image_tags_as_the_image_job(self):
        env = self.bundle["env"]
        self.assertEqual(env["SERVICE"], "${{ matrix.service }}")
        self.assertEqual(env["FLAVOR"], "${{ matrix.flavor }}")
        self.assertEqual(env["COMMIT_TAG"], "${{ needs.plan.outputs.commit_tag }}")
        self.assertEqual(env["REF_NAME"], "${{ github.ref_name }}")
        _, push = self.step(self.job, "docker push")
        _, generate = self.step(self.bundle, "docker pull")
        self.assertIn('RC_TAG="${REF_NAME#v}-${FLAVOR}"', push["run"])
        self.assertIn('RC_TAG="${REF_NAME#v}-${FLAVOR}"', generate["run"])
        self.assertIn('SAFE_SERVICE="${SERVICE//_/-}"', generate["run"])
        self.assertIn('${COMMIT_TAG}-${FLAVOR}', generate["run"])

    def test_a_release_tag_must_name_the_version_file(self):
        _, step = self.step(self.plan, "check-versions.py --tag")
        self.assertEqual(step["if"], "startsWith(github.ref, 'refs/tags/')")

    def test_images_are_signed_keyless_by_digest_after_the_push(self):
        push_at, _ = self.step(self.job, "docker push")
        install_at, _ = self.step(self.job, "sigstore/cosign-installer")
        sign_at, sign = self.step(self.job, "cosign sign")
        self.assertLess(push_at, install_at)
        self.assertLess(install_at, sign_at)
        self.assertEqual(sign["run"].strip(), 'cosign sign --yes "$REPOSITORY@$DIGEST"')
        _, push = self.step(self.job, "imagetools inspect")
        self.assertIn("{{.Manifest.Digest}}", push["run"])
        everything = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("--key", everything)
        self.assertNotIn("COSIGN_PRIVATE_KEY", everything)

    def test_the_cosign_installer_is_pinned_to_a_published_release(self):
        _, step = self.step(self.job, "sigstore/cosign-installer")
        _action, ref = step["uses"].split("@", 1)
        self.assertRegex(ref, r"^(v\d+\.\d+\.\d+|[0-9a-f]{40})$")

    def test_only_the_image_job_may_write_packages_and_request_an_oidc_token(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(self.job["permissions"],
                         {"contents": "read", "packages": "write", "id-token": "write"})
        self.assertNotIn("permissions", self.plan)

    def test_the_signature_is_verified_against_this_workflow_and_commit(self):
        _, step = self.step(self.job, "cosign verify")
        self.assertIn('--certificate-identity "https://github.com/$GITHUB_WORKFLOW_REF"',
                      step["run"])
        self.assertIn('--certificate-oidc-issuer "$OIDC_ISSUER"', step["run"])
        self.assertIn('--certificate-github-workflow-sha "$GITHUB_SHA"', step["run"])
        self.assertEqual(self.workflow["env"]["OIDC_ISSUER"], OIDC_ISSUER)

    def test_the_registry_defaults_to_the_one_the_installer_pulls_from(self):
        _, step = self.step(self.plan, "GITHUB_OUTPUT")
        self.assertIn("import images; print(images.DEFAULT_REGISTRY)", step["run"])
        self.assertEqual(step["env"]["CONFIGURED_REGISTRY"], "${{ vars.HORUS_REGISTRY }}")
        self.assertIn('registry="${registry,,}"', step["run"])

    def test_registry_credentials_come_from_repository_variables_and_secrets(self):
        _, step = self.step(self.job, "docker/login-action")
        self.assertEqual(step["with"], {
            "registry": "${{ needs.plan.outputs.registry_host }}",
            "username": "${{ vars.HORUS_REGISTRY_USERNAME || github.actor }}",
            "password": "${{ secrets.HORUS_REGISTRY_TOKEN || secrets.GITHUB_TOKEN }}",
        })

    def test_the_wiring_and_installer_tests_run_before_any_image_is_built(self):
        _, wiring = self.step(self.plan, THIS_FILE)
        self.assertIn("unittest discover -s tests/ci", wiring["run"])
        _, installer = self.step(self.plan, "installer/tests")
        self.assertIn("unittest discover", installer["run"])

    def test_no_script_interpolates_a_value_an_outsider_controls(self):
        risky = ("github.event", "github.head_ref", "github.ref_name", "github.workflow_ref")
        for job in self.workflow["jobs"].values():
            for step in job["steps"]:
                for expression in re.findall(r"\$\{\{(.*?)\}\}", step.get("run", "")):
                    with self.subTest(expression):
                        self.assertFalse(any(name in expression for name in risky))


if __name__ == "__main__":
    unittest.main()
