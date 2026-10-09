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
SERVICES = REPO / "src" / "services"
MOCK_SERVER = SERVICES / "llm-mock"
CLIENTS = ("mas", "agent")
EMBEDDERS = {"mas": "MAS_EMBED", "knowledge_store": "KNOWLEDGE_STORE_EMBED"}
EMBEDDINGS_CLIENTS = (
    SERVICES / "mas" / "core" / "embeddings_client.py",
    SERVICES / "knowledge-store" / "app" / "chroma_db" / "embeddings_client.py",
)
AI_MODE_SERVICES = ("mas", "agent", "knowledge_store")
TURNED_OFF = ("llm", "llm-model", "vllm")

sys.path.insert(0, str(REPO / "installer"))
sys.path.insert(0, str(MOCK_SERVER))
import profiles  # noqa: E402
import smoke  # noqa: E402

from llm_mock import settings as mock_settings  # noqa: E402
from llm_mock.server import PURPOSE_HEADER  # noqa: E402

needs_yaml = unittest.skipUnless(yaml is not None, "needs PyYAML to read the compose files")


def compose_tag(loader, _tag: str, node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


def services(name: str) -> dict:
    loader = type("ComposeLoader", (yaml.SafeLoader,), {})
    loader.add_multi_constructor("!", compose_tag)
    return yaml.load((INFRA / name).read_text(encoding="utf-8"), Loader=loader)["services"]


def environment(spec: dict) -> dict[str, str]:
    return dict(item.split("=", 1) for item in spec.get("environment", []))


def default_of(value: str) -> str:
    return re.fullmatch(r"\$\{\w+:-([^}]*)\}", value).group(1)


@needs_yaml
class MockOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = services(profiles.BASE_COMPOSE)
        cls.cpu = services(profiles.CPU_OVERLAY)
        cls.mock = services(profiles.MOCK_OVERLAY)

    def test_the_overlay_turns_the_real_model_servers_off(self):
        for name in TURNED_OFF:
            with self.subTest(name):
                spec = self.mock[name]
                self.assertEqual(spec["deploy"], {"replicas": 0})
                self.assertTrue(spec["profiles"])
                self.assertNotIn("dev-tools", spec["profiles"])

    def test_mas_and_the_agent_call_llm_mock_under_its_own_model_name(self):
        for name in CLIENTS:
            with self.subTest(name):
                env = environment(self.mock[name])
                self.assertEqual(env["LLM_BACKEND"], "vllm")
                self.assertEqual(env["LLM_VLLM_URL"],
                                 f"http://{profiles.MOCK_MODEL_SERVER}:{mock_settings.DEFAULT_PORT}/v1")
                self.assertEqual(env["LLM_VLLM_MODEL"], profiles.MOCK_MODEL_NAME)

    def test_the_answer_cache_can_never_mix_mock_and_model_answers(self):
        local_names = {profiles.env_for(name)["LLM_VLLM_MODEL"] for name in profiles.PROFILE_ORDER}
        self.assertNotIn(profiles.MOCK_MODEL_NAME, local_names)
        self.assertEqual(environment(self.mock[profiles.MOCK_MODEL_SERVER])["LLM_VLLM_MODEL"],
                         profiles.MOCK_MODEL_NAME)

    def test_mas_and_the_agent_wait_for_llm_mock_and_no_longer_for_llm(self):
        for name in CLIENTS:
            with self.subTest(name):
                needs = self.mock[name]["depends_on"]
                self.assertEqual(needs["llm"], {"condition": "service_healthy", "required": False})
                self.assertEqual(needs[profiles.MOCK_MODEL_SERVER], {"condition": "service_healthy"})
                self.assertEqual(self.cpu[name]["depends_on"]["llm"], {"condition": "service_healthy"})

    def test_mas_and_the_knowledge_store_embed_with_llm_mock(self):
        for name, prefix in EMBEDDERS.items():
            with self.subTest(name):
                env = environment(self.mock[name])
                self.assertEqual(env[f"{prefix}_URL"],
                                 f"http://{profiles.MOCK_MODEL_SERVER}:{mock_settings.DEFAULT_PORT}/v1")
                self.assertEqual(env[f"{prefix}_MODEL"], profiles.MOCK_MODEL_NAME)

    def test_the_overlay_sets_the_names_the_services_read(self):
        readers = {
            "mas": SERVICES / "mas" / "core" / "embedding_setup.py",
            "knowledge_store": SERVICES / "knowledge-store" / "app" / "chroma_db" / "setup.py",
        }
        for name, prefix in EMBEDDERS.items():
            source = readers[name].read_text(encoding="utf-8")
            for key in (f"{prefix}_URL", f"{prefix}_MODEL"):
                with self.subTest(key):
                    self.assertIn(f'"{key}"', source)

    def test_the_knowledge_store_waits_for_llm_mock_before_it_embeds(self):
        self.assertEqual(self.mock["knowledge_store"]["depends_on"],
                         {profiles.MOCK_MODEL_SERVER: {"condition": "service_healthy"}})

    def test_a_local_install_leaves_the_embeddings_urls_unset(self):
        env = environment(self.base["knowledge_store"])
        self.assertEqual(default_of(env["KNOWLEDGE_STORE_EMBED_URL"]), "")
        self.assertEqual(default_of(env["KNOWLEDGE_STORE_EMBED_MODEL"]), "")
        for spec in (self.base["mas"], self.cpu["mas"], self.cpu["knowledge_store"]):
            self.assertNotIn("MAS_EMBED_URL", environment(spec))
        self.assertNotIn("KNOWLEDGE_STORE_EMBED_URL", environment(self.cpu["knowledge_store"]))
        self.assertFalse({"MAS_EMBED_URL", "KNOWLEDGE_STORE_EMBED_URL"}
                         & smoke.read_env(INFRA / ".env.example").keys())

    def test_every_service_learns_the_mode_from_the_files_not_from_env(self):
        for name in AI_MODE_SERVICES:
            with self.subTest(name):
                self.assertEqual(environment(self.base[name])["HORUS_AI_MODE"], "local")
                self.assertEqual(environment(self.mock[name])["HORUS_AI_MODE"], "mock")

    def test_llm_mock_is_healthy_only_when_it_answers_on_its_port(self):
        check = " ".join(self.mock[profiles.MOCK_MODEL_SERVER]["healthcheck"]["test"])
        self.assertIn(f"http://localhost:{mock_settings.DEFAULT_PORT}/health", check)

    def test_the_overlay_defaults_are_the_server_defaults(self):
        env = environment(self.mock[profiles.MOCK_MODEL_SERVER])
        self.assertEqual(int(default_of(env["HORUS_MOCK_LATENCY_MS"])), mock_settings.DEFAULT_LATENCY_MS)
        self.assertEqual(default_of(env["HORUS_MOCK_SCENARIO"]), mock_settings.DEFAULT_SCENARIO)
        self.assertEqual(float(default_of(env["HORUS_MOCK_MIN_SCORE"])), mock_settings.DEFAULT_MIN_SCORE)

    def test_the_server_reads_the_header_the_clients_send(self):
        mas = (REPO / "src" / "services" / "mas" / "core" / "llm_setup.py").read_text(encoding="utf-8")
        agent = (REPO / "src" / "services" / "agent" / "app" / "ai_agents"
                 / "decision_making_agent.py").read_text(encoding="utf-8")
        for text in (mas, agent):
            self.assertIn(f'PURPOSE_HEADER = "{PURPOSE_HEADER}"', text)


class EmbeddingsClients(unittest.TestCase):
    def test_mas_and_the_knowledge_store_carry_the_same_generic_client(self):
        mas, knowledge_store = (path.read_text(encoding="utf-8") for path in EMBEDDINGS_CLIENTS)
        self.assertEqual(mas, knowledge_store)
        self.assertNotIn("mock", mas.lower())


class EnvTemplate(unittest.TestCase):
    def test_the_template_documents_the_mode_and_every_mock_setting(self):
        text = (INFRA / ".env.example").read_text(encoding="utf-8")
        self.assertEqual(smoke.read_env(INFRA / ".env.example")["HORUS_AI_MODE"], "local")
        self.assertIn(f"# HORUS_MOCK_LATENCY_MS={mock_settings.DEFAULT_LATENCY_MS}", text)
        self.assertIn(f"# HORUS_MOCK_SCENARIO={mock_settings.DEFAULT_SCENARIO}", text)
        self.assertIn(f"# HORUS_MOCK_MIN_SCORE={mock_settings.DEFAULT_MIN_SCORE}", text)
        for scenario in mock_settings.SCENARIOS:
            with self.subTest(scenario):
                self.assertIn(scenario, text)


if __name__ == "__main__":
    unittest.main()
