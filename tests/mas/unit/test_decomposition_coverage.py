"""Behavioural coverage for ``tasks.decomposition`` and ``tasks.prompts``.

Hermetic: the conftest in ``tests/mas`` already mocks torch/transformers and
forces TEST_MODE + in-memory SQLite, so importing the planner is cheap. Every
external boundary the planner touches — the LLM (``ask_llm``), the agent
registry helpers, the skill-embedding fallback (``rank_skills``), and the
RabbitMQ queue creator — is patched per-test with ``monkeypatch`` so nothing
leaks between tests and no real I/O happens.

The LLM is always stubbed to return a deterministic string so the JSON-parse,
empty-plan, malformed-output, and fallback branches are all reachable on
demand.
"""

from __future__ import annotations

import json
from enum import Enum

import pytest

from tasks import decomposition as D
from tasks import prompts as P


# --------------------------------------------------------------------------- #
# Lightweight fakes — no real ORM, no real DB rows.
# --------------------------------------------------------------------------- #
class _Type(Enum):
    """Stand-in for the real AgentType enum (``.value`` access path)."""

    RESEARCHER = "researcher"
    WRITER = "writer"
    GENERAL = "general"


class _Eq:
    """Captured ``column == value`` predicate, consumed by the fake query."""

    def __init__(self, field, value):
        self.field = field
        self.value = value


class _Ne:
    """Captured ``column != value`` predicate, consumed by the fake query."""

    def __init__(self, field, value):
        self.field = field
        self.value = value


class _FakeColumn:
    """Sentinel for class-level ORM column access (``Agents.id``, ``Agents.name``).

    Production code evaluates filter expressions like ``Agents.id.in_(ids)`` and
    ``Agents.name == 'Manager'`` *before* handing them to ``.filter()``. The fake
    query inspects an ``== `` predicate so ``.first()`` can resolve the right row
    by id (the heuristic fallback looks agents up one id at a time). Other
    predicates are harmless no-ops.
    """

    def __init__(self, field=None):
        self.field = field

    def in_(self, *a, **k):
        return True

    def __eq__(self, other):
        return _Eq(self.field, other)

    def __ne__(self, other):
        return _Ne(self.field, other)

    def desc(self):
        return self

    def __hash__(self):
        return id(self)


class _FakeAgentsModel:
    """Class-only stand-in for ``db.models.Agents`` used as a filter target."""

    id = _FakeColumn("id")
    name = _FakeColumn("name")
    status = _FakeColumn("status")
    type = _FakeColumn("type")
    last_heartbeat = _FakeColumn("last_heartbeat")


class FakeAgent:
    """Minimal duck-typed ``Agents`` row used by the directory queries."""

    def __init__(
        self,
        id="a1",
        name="Researcher",
        type=_Type.RESEARCHER,
        skills=None,
        status="active",
        description="does research",
        last_heartbeat=None,
    ):
        self.id = id
        self.name = name
        self.type = type
        self.skills = skills if skills is not None else ["research"]
        self.status = status
        self.description = description
        self.last_heartbeat = last_heartbeat


class _Query:
    """Chainable query whose terminal calls (.first/.all) read from a list.

    Filtering is intentionally a no-op — tests seed exactly the rows each
    query should observe, which keeps the fake tiny while still exercising the
    production code paths that call ``.filter``/``.order_by``/``.limit``.
    """

    def __init__(self, rows):
        self._rows = list(rows)
        self._eq = []  # list[_Eq]
        self._ne = []  # list[_Ne]

    def filter(self, *a, **k):
        # Honour ``id == value`` and ``name != value`` predicates — the only
        # two filter shapes the module relies on for row selection. Everything
        # else (e.g. status == 'active', which the code re-checks in Python)
        # is a no-op; tests seed exactly the rows each query should observe.
        for pred in a:
            if isinstance(pred, _Eq):
                self._eq.append(pred)
            elif isinstance(pred, _Ne):
                self._ne.append(pred)
        return self

    def order_by(self, *a, **k):
        return self

    def limit(self, n=None, *a, **k):
        if n is not None:
            self._rows = self._rows[:n]
        return self

    def _apply(self):
        rows = self._rows
        for eq in self._eq:
            rows = [r for r in rows if getattr(r, eq.field, None) == eq.value]
        for ne in self._ne:
            rows = [r for r in rows if getattr(r, ne.field, None) != ne.value]
        return rows

    def first(self):
        rows = self._apply()
        return rows[0] if rows else None

    def all(self):
        return self._apply()


class FakeDB:
    """Fake SQLAlchemy session: every ``.query(Model)`` returns seeded rows."""

    def __init__(self, rows=None):
        self._rows = rows if rows is not None else []

    def query(self, *a, **k):
        return _Query(self._rows)


# --------------------------------------------------------------------------- #
# Autouse hygiene: silence pretty_log and neutralise the RabbitMQ queue maker.
# Both are module-level names in tasks.decomposition; monkeypatch reverts them.
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _silence_side_effects(monkeypatch):
    monkeypatch.setattr(D, "pretty_log", lambda *a, **k: None)

    class _RMQ:
        def __init__(self):
            self.created = []

        def create_queue(self, agent_id):
            self.created.append(agent_id)

    monkeypatch.setattr(D, "rabbitmq_instance", _RMQ())


def _patch_llm(monkeypatch, output):
    """Make ``ask_llm`` return *output* (str) or raise (if Exception)."""

    def _fake(prompt, **kwargs):
        if isinstance(output, BaseException):
            raise output
        return output

    monkeypatch.setattr(D, "ask_llm", _fake)


def _capture_llm_prompts(monkeypatch, output):
    prompts = []

    def _fake(prompt, **kwargs):
        prompts.append(prompt)
        return output

    monkeypatch.setattr(D, "ask_llm", _fake)
    return prompts


def _rendered_text(messages):
    return "\n".join(message["content"] for message in messages)


# ============================ clean_json_output ============================ #
class TestCleanJsonOutput:
    def test_plain_object_untouched(self):
        assert P.clean_json_output('{"a": 1}') == '{"a": 1}'

    def test_strips_json_fence(self):
        assert P.clean_json_output('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_strips_bare_fence(self):
        assert P.clean_json_output('```\n{"a": 1}\n```') == '{"a": 1}'

    def test_bare_open_fence_without_close(self):
        # Opening ``` but no trailing fence -> the endswith('```') check is
        # skipped; the object is still extracted by the brace walker.
        assert P.clean_json_output('```\n{"a": 1}') == '{"a": 1}'

    def test_strips_stop_tokens(self):
        out = P.clean_json_output('{"a": 1}<|im_end|>')
        assert out == '{"a": 1}'

    def test_extracts_object_from_preamble_and_trailer(self):
        raw = 'Here is the plan: {"a": 1} Let me know if you need more.'
        assert P.clean_json_output(raw) == '{"a": 1}'

    def test_braces_inside_strings_do_not_confuse_depth(self):
        raw = '{"text": "a { nested } brace"} trailing'
        assert P.clean_json_output(raw) == '{"text": "a { nested } brace"}'

    def test_escaped_quote_inside_string(self):
        raw = '{"text": "she said \\"hi\\""}'
        assert P.clean_json_output(raw) == raw

    def test_no_brace_returns_stripped_input(self):
        assert P.clean_json_output("  no json here  ") == "no json here"

    def test_unbalanced_returns_remainder(self):
        # Opening brace but never closed -> depth never hits 0 -> return as-is.
        raw = '{"a": 1'
        assert P.clean_json_output(raw) == '{"a": 1'


# ============================== prompt builders ============================ #
class TestPromptBuilders:
    AGENTS = [
        ("a1", "Researcher", "finds facts", _Type.RESEARCHER),
        ("a2", "Writer", "writes prose", _Type.WRITER),
    ]

    def test_final_answer_prompt_embeds_history_and_result(self):
        msgs = P.get_prompt_final_answer_generation("orig request", "the result")
        assert msgs[0]["role"] == "system"
        assert "synthesizer" in msgs[0]["content"]
        assert "Address the original user request directly." in msgs[0]["content"]
        assert "the result" in msgs[1]["content"]
        assert msgs[1]["content"].endswith("ORIGINAL USER REQUEST:\norig request")

    def test_router_prompt_lists_agents_and_renders_single_brace_schema(self):
        msgs = P.get_prompt("Q4 revenue?", self.AGENTS)
        system = msgs[0]["content"]
        assert "Researcher: finds facts" in system
        assert '{\n  "classification"' in system
        assert "{{" not in system and "}}" not in system
        assert "COMPLEX_TASK" in system
        assert msgs[1]["content"] == "USER INPUT:\nQ4 revenue?"

    def test_router_prompt_limits_direct_answer_to_greetings_small_talk_and_arithmetic(self):
        system = P.get_prompt("hi", self.AGENTS)[0]["content"]
        assert "trivial questions" not in system
        assert "A factual question is NEVER DIRECT_ANSWER" in system
        assert "capital of Peru" in system

    def test_decomposition_prompt_normalises_dotted_enum_types(self):
        dotted = [("a1", "Researcher", "finds facts", "AgentType.RESEARCHER")]
        msgs = P.get_decomposition_prompt("do a thing", dotted)
        system = msgs[0]["content"]
        assert "Type: researcher" in system
        assert '"sub_tasks": [' in system
        assert "{{" not in system and "}}" not in system
        assert msgs[1]["content"] == "USER INPUT:\ndo a thing"

    def test_decomposition_prompt_lowercases_plain_type(self):
        plain = [("a1", "Writer", "writes", "WRITER")]
        system = P.get_decomposition_prompt("x", plain)[0]["content"]
        assert "Type: writer" in system

    def test_manager_announcement_prompt_enumerates_steps(self):
        steps = [
            {"agent_type": "researcher", "description": "gather data"},
            {"agent_type": "writer", "description": "draft report"},
        ]
        msgs = P.get_manager_announcement_prompt("build a report", steps)
        user = msgs[1]["content"]
        assert "1. researcher: gather data" in user
        assert "2. writer: draft report" in user
        assert user.endswith("USER DEMAND:\nbuild a report")
        assert "Manager" in msgs[0]["content"]
        assert "Plain text, no JSON, no code fences." in msgs[0]["content"]

    def test_manager_review_prompt_with_remaining_steps(self):
        steps = [{"agent_type": "writer", "description": "finish draft"}]
        msgs = P.get_manager_review_prompt(
            user_demand="demand",
            transcript="so far so good",
            remaining_steps=steps,
            available_agent_types=["researcher", "writer"],
        )
        user = msgs[1]["content"]
        assert "writer: finish draft" in user
        assert "researcher, writer" in user
        assert "so far so good" in user
        assert user.endswith("USER DEMAND:\ndemand")
        system = msgs[0]["content"]
        assert '{"decision"' in system
        assert "{{" not in system and "}}" not in system

    def test_manager_review_prompt_empty_remaining_and_types(self):
        msgs = P.get_manager_review_prompt(
            user_demand="d",
            transcript="t",
            remaining_steps=[],
            available_agent_types=[],
        )
        user = msgs[1]["content"]
        assert "none — this was the last planned step" in user
        # default agent type label when none supplied
        assert "general" in user


ROSTER_WITH_IDS = [
    ("agent-id-researcher", "Researcher", "finds facts", _Type.RESEARCHER),
    ("agent-id-writer", "Writer", "writes prose", _Type.WRITER),
    ("agent-id-general", "General", "answers anything", _Type.GENERAL),
]

PROMPT_BUILDERS = {
    "intent": lambda request, agents: P.get_prompt(request, agents),
    "plan": lambda request, agents: P.get_decomposition_prompt(request, agents),
    "aggregate": lambda request, _agents: P.get_prompt_final_answer_generation(
        request, f"Specialist output for: {request}"
    ),
    "announce": lambda request, _agents: P.get_manager_announcement_prompt(
        request, [{"agent_type": "writer", "description": f"Draft: {request}"}]
    ),
    "review": lambda request, _agents: P.get_manager_review_prompt(
        request,
        f"[Step 1] Researcher found facts for {request}",
        [{"agent_type": "writer", "description": f"Draft: {request}"}],
        ["researcher", "writer"],
    ),
}


class TestFixedPromptPrefix:
    @pytest.mark.parametrize("call", sorted(PROMPT_BUILDERS))
    def test_the_system_message_is_byte_identical_across_requests_and_roster_orders(self, call):
        build = PROMPT_BUILDERS[call]

        first = build("What was Q4 2025 revenue?", ROSTER_WITH_IDS)
        second = build("How many vacation days carry over?", list(reversed(ROSTER_WITH_IDS)))

        assert first[0]["role"] == "system"
        assert first[0]["content"].encode("utf-8") == second[0]["content"].encode("utf-8")
        assert "Q4 2025 revenue" not in first[0]["content"]
        assert all(agent_id not in first[0]["content"] for agent_id, *_ in ROSTER_WITH_IDS)

    @pytest.mark.parametrize("call", sorted(PROMPT_BUILDERS))
    def test_the_request_closes_the_user_message(self, call):
        messages = PROMPT_BUILDERS[call]("What was Q4 2025 revenue?", ROSTER_WITH_IDS)

        assert [message["role"] for message in messages] == ["system", "user"]
        assert messages[1]["content"].endswith("What was Q4 2025 revenue?")

    @pytest.mark.parametrize(
        ("run", "expected"),
        [
            (lambda: D.aggregate_results("history", "result"), "aggregate"),
            (lambda: D.decompose_task("Compare revenue and leave", FakeDB()), "plan"),
            (lambda: D.choose_route_with_llm("What was revenue?", FakeDB()), "intent"),
            (lambda: D.manager_review_step("d", "t", [], ["writer"], FakeDB()), "review"),
        ],
        ids=["aggregate", "plan", "intent", "review"],
    )
    def test_each_llm_call_names_its_prompt_for_the_token_metrics(self, monkeypatch, run, expected):
        calls = []

        def _fake(prompt, **kwargs):
            calls.append(kwargs.get("call"))
            return "{}"

        monkeypatch.setattr(D, "ask_llm", _fake)
        monkeypatch.setattr(D, "get_available_agents", lambda db: ROSTER_WITH_IDS)
        monkeypatch.setattr(D, "_heuristic_decompose", lambda user_input, db: (None, []))
        run()

        assert calls == [expected]


# ========================= build_action_list ============================== #
class TestBuildActionList:
    def test_resolves_agents_and_creates_queues(self, monkeypatch):
        monkeypatch.setattr(D, "get_agent_id", lambda name, db: f"id-{name}")
        db = FakeDB()
        # Extra unrecognised key ("extra") exercises the loop's no-match branch.
        actions = [{"agent": "Researcher", "input": "do x", "extra": "ignored"}]
        result = D.build_action_list(actions, [], db)
        assert result == [("id-Researcher", "do x")]
        assert D.rabbitmq_instance.created == ["id-Researcher"]

    def test_empty_agent_name_raises(self, monkeypatch):
        monkeypatch.setattr(D, "get_agent_id", lambda name, db: "x")
        with pytest.raises(ValueError, match="Agent name"):
            D.build_action_list([{"agent": "", "input": "x"}], [], FakeDB())

    def test_unknown_agent_raises(self, monkeypatch):
        monkeypatch.setattr(D, "get_agent_id", lambda name, db: None)
        with pytest.raises(ValueError, match="doesn't exists"):
            D.build_action_list([{"agent": "Ghost", "input": "x"}], [], FakeDB())

    def test_empty_input_raises(self, monkeypatch):
        monkeypatch.setattr(D, "get_agent_id", lambda name, db: "id")
        with pytest.raises(ValueError, match="Input for the agents"):
            D.build_action_list([{"agent": "R", "input": ""}], [], FakeDB())

    def test_db_none_uses_sessionlocal(self, monkeypatch):
        monkeypatch.setattr(D, "get_agent_id", lambda name, db: "id-x")
        monkeypatch.setattr(D, "SessionLocal", lambda: FakeDB())
        result = D.build_action_list([{"agent": "R", "input": "go"}], [])
        assert result == [("id-x", "go")]


# ====================== sort_subtasks_by_dependency ======================= #
class _STask:
    def __init__(self, id, depends_on=None):
        self.id = id
        self.depends_on = depends_on or []


class TestSortSubtasks:
    def test_orders_by_dependency(self):
        # 2 depends on 1, 3 depends on 2 -> order 1,2,3
        tasks = [_STask("3", ["2"]), _STask("1"), _STask("2", ["1"])]
        ordered = [t.id for t in D.sort_subtasks_by_dependency(tasks)]
        assert ordered == ["1", "2", "3"]

    def test_dependency_on_unknown_id_is_dropped_from_output(self):
        # depends_on references a task that isn't in the set; topo sort still
        # yields it but the final filter keeps only known task ids.
        tasks = [_STask("1", ["missing"])]
        ordered = [t.id for t in D.sort_subtasks_by_dependency(tasks)]
        assert ordered == ["1"]


# ========================= build_subtask_list ============================= #
class _Entity:
    def __init__(self, sub_tasks):
        self.sub_tasks = sub_tasks


class _Sub:
    def __init__(self, id, agent_type, description, depends_on=None):
        self.id = id
        self.agent_type = agent_type
        self.description = description
        self.depends_on = depends_on or []


class TestBuildSubtaskList:
    def test_happy_path(self, monkeypatch):
        monkeypatch.setattr(D, "get_agent_by_type", lambda t, db: f"id-{t}")
        ent = _Entity([_Sub("1", "researcher", "find x")])
        result = D.build_subtask_list(ent, [], FakeDB())
        assert [agent for agent, _ in result] == ["id-researcher"]
        assert result[0][1].endswith("=== Your assigned task ===\nfind x")
        assert "id-researcher" in D.rabbitmq_instance.created

    def test_empty_agent_type_raises(self, monkeypatch):
        monkeypatch.setattr(D, "get_agent_by_type", lambda t, db: "id")
        ent = _Entity([_Sub("1", "", "desc")])
        with pytest.raises(ValueError, match="Agent type"):
            D.build_subtask_list(ent, [], FakeDB())

    def test_unresolvable_type_raises(self, monkeypatch):
        monkeypatch.setattr(D, "get_agent_by_type", lambda t, db: None)
        ent = _Entity([_Sub("1", "ghost", "desc")])
        with pytest.raises(ValueError, match="not found or no agents"):
            D.build_subtask_list(ent, [], FakeDB())

    def test_empty_description_raises(self, monkeypatch):
        monkeypatch.setattr(D, "get_agent_by_type", lambda t, db: "id")
        ent = _Entity([_Sub("1", "researcher", "")])
        with pytest.raises(ValueError, match="Input for the agents"):
            D.build_subtask_list(ent, [], FakeDB())

    def test_sort_exception_falls_back_to_unsorted(self, monkeypatch):
        monkeypatch.setattr(D, "get_agent_by_type", lambda t, db: f"id-{t}")
        # Force the topological sorter to blow up so the except branch runs.
        monkeypatch.setattr(
            D,
            "sort_subtasks_by_dependency",
            lambda x: (_ for _ in ()).throw(RuntimeError("cycle")),
        )
        ent = _Entity([_Sub("1", "researcher", "desc")])
        result = D.build_subtask_list(ent, [], FakeDB())
        assert [agent for agent, _ in result] == ["id-researcher"]
        assert result[0][1].endswith("=== Your assigned task ===\ndesc")

    def test_db_none_uses_sessionlocal(self, monkeypatch):
        monkeypatch.setattr(D, "get_agent_by_type", lambda t, db: "id-x")
        monkeypatch.setattr(D, "SessionLocal", lambda: FakeDB())
        ent = _Entity([_Sub("1", "researcher", "desc")])
        result = D.build_subtask_list(ent, [])
        assert [agent for agent, _ in result] == ["id-x"]
        assert result[0][1].endswith("=== Your assigned task ===\ndesc")


# ============================ decompose_task ============================== #
GOOD_PLAN = {
    "sub_tasks": [
        {
            "id": "1",
            "agent_type": "researcher",
            "description": "research it",
            "depends_on": [],
            "status": "pending",
        },
        {
            "id": "2",
            "agent_type": "writer",
            "description": "write it",
            "depends_on": ["1"],
            "status": "pending",
        },
    ]
}


class TestDecomposeTask:
    def test_no_available_agents_returns_empty(self, monkeypatch):
        monkeypatch.setattr(D, "get_available_agents", lambda db: [])
        _patch_llm(monkeypatch, "irrelevant")
        assert D.decompose_task("x", FakeDB()) == (None, [])

    def test_successful_decomposition(self, monkeypatch):
        monkeypatch.setattr(
            D, "get_available_agents", lambda db: [("a1", "R", "d", _Type.RESEARCHER)]
        )
        monkeypatch.setattr(D, "get_agent_by_type", lambda t, db: f"id-{t}")
        _patch_llm(monkeypatch, json.dumps(GOOD_PLAN))
        first, rest = D.decompose_task("complex request", FakeDB())
        # Sorted 1->2; first action popped off, remainder returned.
        assert first[0] == "id-researcher"
        assert first[1].endswith("=== Your assigned task ===\nresearch it")
        assert [agent for agent, _ in rest] == ["id-writer"]
        assert rest[0][1].endswith("=== Your assigned task ===\nwrite it")

    def test_status_and_depends_on_defaulted_when_missing(self, monkeypatch):
        # Planner omits status + depends_on; code should backfill and still
        # build a valid plan rather than discard it.
        plan = {"sub_tasks": [{"id": "1", "agent_type": "researcher", "description": "do it"}]}
        monkeypatch.setattr(
            D, "get_available_agents", lambda db: [("a1", "R", "d", _Type.RESEARCHER)]
        )
        monkeypatch.setattr(D, "get_agent_by_type", lambda t, db: "id-r")
        _patch_llm(monkeypatch, json.dumps(plan))
        first, rest = D.decompose_task("req", FakeDB())
        assert first[0] == "id-r"
        assert first[1].endswith("=== Your assigned task ===\ndo it")
        assert rest == []

    def test_empty_subtasks_triggers_heuristic_fallback(self, monkeypatch):
        monkeypatch.setattr(
            D, "get_available_agents", lambda db: [("a1", "R", "d", _Type.RESEARCHER)]
        )
        _patch_llm(monkeypatch, json.dumps({"sub_tasks": []}))
        sentinel = (("hid", "hdemand"), [("hid2", "x")])
        monkeypatch.setattr(D, "_heuristic_decompose", lambda ui, db: sentinel)
        assert D.decompose_task("req", FakeDB()) == sentinel

    def test_malformed_json_triggers_heuristic_fallback(self, monkeypatch):
        monkeypatch.setattr(
            D, "get_available_agents", lambda db: [("a1", "R", "d", _Type.RESEARCHER)]
        )
        _patch_llm(monkeypatch, "this is not json at all")
        called = {}

        def _fb(ui, db):
            called["hit"] = True
            return (None, [])

        monkeypatch.setattr(D, "_heuristic_decompose", _fb)
        assert D.decompose_task("req", FakeDB()) == (None, [])
        assert called["hit"] is True

    def test_validation_error_triggers_heuristic_fallback(self, monkeypatch):
        # Valid JSON with sub_tasks, but a subtask missing required pydantic
        # field (no 'description') -> CollaborativeTask construction raises ->
        # generic except branch -> heuristic fallback.
        bad = {"sub_tasks": [{"id": "1", "agent_type": "researcher"}]}
        monkeypatch.setattr(
            D, "get_available_agents", lambda db: [("a1", "R", "d", _Type.RESEARCHER)]
        )
        _patch_llm(monkeypatch, json.dumps(bad))
        monkeypatch.setattr(D, "_heuristic_decompose", lambda ui, db: ("fb", []))
        assert D.decompose_task("req", FakeDB()) == ("fb", [])

    def test_plan_maps_to_no_actions_triggers_fallback(self, monkeypatch):
        # build_subtask_list returns [] -> the "PLANNER MAPPED TO NO ACTIONS"
        # branch -> heuristic fallback.
        monkeypatch.setattr(
            D, "get_available_agents", lambda db: [("a1", "R", "d", _Type.RESEARCHER)]
        )
        _patch_llm(monkeypatch, json.dumps(GOOD_PLAN))
        monkeypatch.setattr(D, "build_subtask_list", lambda *a, **k: [])
        monkeypatch.setattr(D, "_heuristic_decompose", lambda ui, db: ("fb", ["r"]))
        assert D.decompose_task("req", FakeDB()) == ("fb", ["r"])

    def test_db_none_uses_sessionlocal(self, monkeypatch):
        monkeypatch.setattr(D, "SessionLocal", lambda: FakeDB())
        monkeypatch.setattr(D, "get_available_agents", lambda db: [])
        _patch_llm(monkeypatch, "x")
        assert D.decompose_task("req") == (None, [])

    def test_planner_prompt_sent_to_model_has_single_braces(self, monkeypatch):
        monkeypatch.setattr(
            D, "get_available_agents", lambda db: [("a1", "R", "d", _Type.RESEARCHER)]
        )
        monkeypatch.setattr(D, "get_agent_by_type", lambda t, db: f"id-{t}")
        prompts = _capture_llm_prompts(monkeypatch, json.dumps(GOOD_PLAN))
        D.decompose_task("complex request", FakeDB())
        rendered = _rendered_text(prompts[0])
        assert '{\n  "sub_tasks": [\n    {\n      "id": "1"' in rendered
        assert "{{" not in rendered and "}}" not in rendered


# ========================= _heuristic_decompose =========================== #
class TestHeuristicDecompose:
    def test_active_specialists_chain(self, monkeypatch):
        import core.skill_cache as sc
        import db.models as m

        ranked = [
            {"agent_id": "a1", "skill": "research", "score": 0.9},
            {"agent_id": "a2", "skill": "writing", "score": 0.8},
        ]
        monkeypatch.setattr(sc, "rank_skills", lambda *a, **k: ranked)
        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        # Both active, non-Manager specialists -> Pass A builds a 2-step chain.
        db = FakeDB(
            [
                FakeAgent(id="a1", name="Researcher", type=_Type.RESEARCHER),
                FakeAgent(id="a2", name="Writer", type=_Type.WRITER),
            ]
        )
        first, rest = D._heuristic_decompose("help me", db)
        assert first[0] == "a1"
        # skill label "research" surfaced in the per-agent sub-demand
        assert "research" in first[1]
        assert "help me" in first[1]
        assert rest and rest[0][0] == "a2"
        assert "writing" in rest[0][1]

    def test_pass_a_inactive_falls_through_to_pass_b(self, monkeypatch):
        # Ranked agents exist but are status!='active' -> Pass A yields 0 ->
        # widen to Pass B (active_only=False) -> 2-step chain built.
        import core.skill_cache as sc
        import db.models as m

        ranked = [
            {"agent_id": "a1", "skill": "research", "score": 0.9},
            {"agent_id": "a2", "skill": "writing", "score": 0.8},
        ]
        monkeypatch.setattr(sc, "rank_skills", lambda *a, **k: ranked)
        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        db = FakeDB(
            [
                FakeAgent(id="a1", name="Researcher", type=_Type.RESEARCHER, status="inactive"),
                FakeAgent(id="a2", name="Writer", type=_Type.WRITER, status="inactive"),
            ]
        )
        first, rest = D._heuristic_decompose("help me", db)
        assert first[0] == "a1"
        assert rest and rest[0][0] == "a2"

    def test_ranked_agent_with_no_type_defaults_general(self, monkeypatch):
        import core.skill_cache as sc
        import db.models as m

        ranked = [
            {"agent_id": "a1", "skill": "research", "score": 0.9},
            {"agent_id": "a2", "skill": "writing", "score": 0.8},
        ]
        monkeypatch.setattr(sc, "rank_skills", lambda *a, **k: ranked)
        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        db = FakeDB(
            [
                FakeAgent(id="a1", name="Researcher", type=None),
                FakeAgent(id="a2", name="Writer", type=_Type.WRITER),
            ]
        )
        first, rest = D._heuristic_decompose("help me", db)
        assert first[0] == "a1"

    def test_rank_skills_exception_then_directory_fallback(self, monkeypatch):
        # rank_skills blows up -> ranked=[] -> active build empty -> widen
        # empty -> last-ditch directory query returns 2 rows -> chain built.
        import core.skill_cache as sc
        import db.models as m

        monkeypatch.setattr(
            sc, "rank_skills", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cold"))
        )
        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        rows = [
            FakeAgent(id="a1", name="Researcher", type=_Type.RESEARCHER, skills=["research"]),
            FakeAgent(id="a2", name="Writer", type=_Type.WRITER, skills=[]),
        ]
        db = FakeDB(rows)
        first, rest = D._heuristic_decompose("demand", db)
        assert first[0] == "a1"
        # a2 had no skills -> default "knowledge_retrieval" label applied.
        assert rest and rest[0][0] == "a2"
        assert "knowledge retrieval" in rest[0][1]

    def test_unresolvable_id_skipped_and_caps_at_four(self, monkeypatch):
        # 'ghost' resolves to no row -> skipped (agent_row is None branch).
        # Five resolvable specialists follow -> chain caps at 4 (break branch).
        import core.skill_cache as sc
        import db.models as m

        ranked = [{"agent_id": "ghost", "skill": "x", "score": 0.99}] + [
            {"agent_id": f"a{i}", "skill": f"s{i}", "score": 0.9} for i in range(1, 6)
        ]
        monkeypatch.setattr(sc, "rank_skills", lambda *a, **k: ranked)
        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        rows = [FakeAgent(id=f"a{i}", name=f"Agent{i}", type=_Type.RESEARCHER) for i in range(1, 6)]
        db = FakeDB(rows)
        first, rest = D._heuristic_decompose("demand", db)
        # ghost dropped; exactly 4 chosen (first + 3 remaining).
        assert first[0] == "a1"
        assert len(rest) == 3
        assert "ghost" not in {first[0], *(a[0] for a in rest)}

    def test_empty_directory_returns_none(self, monkeypatch):
        import core.skill_cache as sc
        import db.models as m

        monkeypatch.setattr(sc, "rank_skills", lambda *a, **k: [])
        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        db = FakeDB([])  # no rows anywhere
        assert D._heuristic_decompose("demand", db) == (None, [])

    def test_ranked_row_missing_or_manager_skipped(self, monkeypatch):
        # Ranked entries: one with no agent_id (skipped), one whose row is the
        # Manager (skipped). With <2 specialists from ranking the code widens
        # then last-ditches to the directory.
        import core.skill_cache as sc
        import db.models as m

        ranked = [
            {"agent_id": None, "skill": "x", "score": 0.5},  # no id -> skipped
            {"agent_id": "mgr", "skill": "y", "score": 0.5},  # Manager -> skipped
        ]
        monkeypatch.setattr(sc, "rank_skills", lambda *a, **k: ranked)
        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        # 'mgr' resolves to the Manager row (skip branch); last-ditch directory
        # query then yields two usable specialists for the chain.
        rows = [
            FakeAgent(id="mgr", name="Manager", type=_Type.GENERAL),
            FakeAgent(id="a1", name="Researcher", type=_Type.RESEARCHER),
            FakeAgent(id="a2", name="Writer", type=_Type.WRITER),
        ]
        db = FakeDB(rows)
        first, rest = D._heuristic_decompose("demand", db)
        # Manager must NOT be in the chain.
        assert first[0] != "mgr"
        assert all(a[0] != "mgr" for a in rest)
        assert len(rest) >= 1


# ===================== get_manager_agent / steps view ===================== #
class TestManagerHelpers:
    def test_get_manager_agent_found(self, monkeypatch):
        import db.models as m

        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        mgr = FakeAgent(id="m1", name="Manager")
        assert D.get_manager_agent(FakeDB([mgr])) is mgr

    def test_get_manager_agent_missing(self, monkeypatch):
        import db.models as m

        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        assert D.get_manager_agent(FakeDB([])) is None

    def test_planned_steps_empty_action_list(self, monkeypatch):
        import db.models as m

        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        assert D._planned_steps_from_actions([], FakeDB()) == []

    def test_planned_steps_resolves_rows(self, monkeypatch):
        import db.models as m

        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        row = FakeAgent(id="a1", name="Researcher", type=_Type.RESEARCHER)
        db = FakeDB([row])
        out = D._planned_steps_from_actions([("a1", "do x")], db)
        assert out == [
            {"agent_type": "researcher", "agent_name": "Researcher", "description": "do x"}
        ]

    def test_planned_steps_unknown_agent_defaults(self, monkeypatch):
        import db.models as m

        monkeypatch.setattr(m, "Agents", _FakeAgentsModel)
        # No rows -> by_id empty -> '?' name and 'general' type.
        out = D._planned_steps_from_actions([("ghost", "demand")], FakeDB([]))
        assert out == [{"agent_type": "general", "agent_name": "?", "description": "demand"}]


# ======================= manager_announce_plan ============================ #
class TestManagerAnnouncePlan:
    def test_no_steps_returns_default(self, monkeypatch):
        monkeypatch.setattr(D, "_planned_steps_from_actions", lambda a, db: [])
        out = D.manager_announce_plan("demand", [], FakeDB())
        assert out == "I'm dispatching this work to a specialist now."

    def test_success_strips_code_fences(self, monkeypatch):
        steps = [{"agent_type": "researcher", "agent_name": "R", "description": "x"}]
        monkeypatch.setattr(D, "_planned_steps_from_actions", lambda a, db: steps)
        _patch_llm(monkeypatch, "```text\nHere is my plan.\n```")
        out = D.manager_announce_plan("demand", [("a1", "x")], FakeDB())
        assert out == "Here is my plan."

    def test_empty_llm_response_uses_fallback(self, monkeypatch):
        steps = [
            {"agent_type": "researcher", "agent_name": "Researcher", "description": "gather data"},
        ]
        monkeypatch.setattr(D, "_planned_steps_from_actions", lambda a, db: steps)
        _patch_llm(monkeypatch, "   ")  # strips to empty -> raises -> fallback
        out = D.manager_announce_plan("demand", [("a1", "x")], FakeDB())
        assert "1 step" in out
        assert "Researcher" in out

    def test_llm_exception_uses_fallback(self, monkeypatch):
        steps = [
            {"agent_type": "writer", "agent_name": "Writer", "description": "draft"},
        ]
        monkeypatch.setattr(D, "_planned_steps_from_actions", lambda a, db: steps)
        _patch_llm(monkeypatch, RuntimeError("LLM down"))
        out = D.manager_announce_plan("demand", [("a1", "x")], FakeDB())
        assert "Dispatching" in out
        assert "Writer" in out


# ======================== manager_review_step ============================= #
class TestManagerReviewStep:
    def _setup(self, monkeypatch):
        monkeypatch.setattr(D, "_planned_steps_from_actions", lambda a, db: [])

    def test_continue_decision(self, monkeypatch):
        self._setup(monkeypatch)
        _patch_llm(monkeypatch, json.dumps({"decision": "CONTINUE"}))
        out = D.manager_review_step("d", "t", [], ["researcher"], FakeDB())
        assert out["decision"] == "CONTINUE"

    def test_insert_decision_populates_next(self, monkeypatch):
        self._setup(monkeypatch)
        _patch_llm(
            monkeypatch,
            json.dumps(
                {
                    "decision": "insert",
                    "next_agent_type": "Researcher",
                    "next_action": "dig deeper",
                    "reasoning": "gap found",
                }
            ),
        )
        out = D.manager_review_step("d", "t", [], ["researcher"], FakeDB())
        assert out["decision"] == "INSERT"
        assert out["next_agent_type"] == "researcher"  # lowercased
        assert out["next_action"] == "dig deeper"
        assert out["reasoning"] == "gap found"

    def test_done_decision(self, monkeypatch):
        self._setup(monkeypatch)
        _patch_llm(monkeypatch, json.dumps({"decision": "DONE"}))
        out = D.manager_review_step("d", "t", [], [], FakeDB())
        assert out["decision"] == "DONE"

    def test_unknown_decision_coerced_to_continue(self, monkeypatch):
        self._setup(monkeypatch)
        _patch_llm(monkeypatch, json.dumps({"decision": "BANANA"}))
        out = D.manager_review_step("d", "t", [], [], FakeDB())
        assert out["decision"] == "CONTINUE"

    def test_missing_decision_key_defaults_continue(self, monkeypatch):
        self._setup(monkeypatch)
        _patch_llm(monkeypatch, json.dumps({"reasoning": "no decision field"}))
        out = D.manager_review_step("d", "t", [], [], FakeDB())
        assert out["decision"] == "CONTINUE"

    def test_parse_error_defaults_continue(self, monkeypatch):
        self._setup(monkeypatch)
        _patch_llm(monkeypatch, "not json")
        out = D.manager_review_step("d", "t", [], [], FakeDB())
        assert out == {"decision": "CONTINUE"}

    def test_llm_exception_defaults_continue(self, monkeypatch):
        self._setup(monkeypatch)
        _patch_llm(monkeypatch, RuntimeError("boom"))
        out = D.manager_review_step("d", "t", [], [], FakeDB())
        assert out == {"decision": "CONTINUE"}

    def test_review_prompt_sent_to_model_has_single_braces(self, monkeypatch):
        self._setup(monkeypatch)
        prompts = _capture_llm_prompts(monkeypatch, json.dumps({"decision": "DONE"}))
        D.manager_review_step("d", "t", [], ["researcher"], FakeDB())
        rendered = _rendered_text(prompts[0])
        assert '{"decision": "CONTINUE" | "INSERT" | "DONE",' in rendered
        assert "{{" not in rendered and "}}" not in rendered


# ======================== select_agent_for_task =========================== #
class TestSelectAgentForTask:
    def _agents(self, monkeypatch):
        monkeypatch.setattr(
            D, "get_available_agents", lambda db: [("a1", "R", "d", _Type.RESEARCHER)]
        )

    def test_no_agents_returns_all_none(self, monkeypatch):
        monkeypatch.setattr(D, "get_available_agents", lambda db: [])
        _patch_llm(monkeypatch, "x")
        assert D.select_agent_for_task("q", FakeDB()) == (None, None, None, [])

    def test_json_parse_failure_returns_all_none(self, monkeypatch):
        self._agents(monkeypatch)
        _patch_llm(monkeypatch, "totally not json")
        assert D.select_agent_for_task("q", FakeDB()) == (None, None, None, [])

    def test_direct_answer(self, monkeypatch):
        self._agents(monkeypatch)
        _patch_llm(
            monkeypatch,
            json.dumps({"classification": "DIRECT_ANSWER", "final_answer": "42"}),
        )
        out = D.select_agent_for_task("what is 6x7?", FakeDB())
        assert out == (None, None, "Response for user : 42", [])

    def test_single_agent_success(self, monkeypatch):
        self._agents(monkeypatch)
        monkeypatch.setattr(D, "get_agent_id", lambda name, db: "id-R")
        _patch_llm(
            monkeypatch,
            json.dumps(
                {
                    "classification": "SINGLE_AGENT",
                    "agent_name": "Researcher",
                    "rewritten_input": "optimized q",
                }
            ),
        )
        assert D.select_agent_for_task("q", FakeDB()) == ("id-R", "optimized q", None, [])

    def test_single_agent_falls_back_to_user_input_when_no_rewrite(self, monkeypatch):
        self._agents(monkeypatch)
        monkeypatch.setattr(D, "get_agent_id", lambda name, db: "id-R")
        _patch_llm(
            monkeypatch,
            json.dumps({"classification": "SINGLE_AGENT", "agent_name": "Researcher"}),
        )
        first, rewritten, direct, rest = D.select_agent_for_task("orig q", FakeDB())
        assert rewritten == "orig q"

    def test_single_agent_missing_name(self, monkeypatch):
        self._agents(monkeypatch)
        _patch_llm(monkeypatch, json.dumps({"classification": "SINGLE_AGENT"}))
        assert D.select_agent_for_task("q", FakeDB()) == (None, None, None, [])

    def test_single_agent_unknown_agent(self, monkeypatch):
        self._agents(monkeypatch)
        monkeypatch.setattr(D, "get_agent_id", lambda name, db: None)
        _patch_llm(
            monkeypatch,
            json.dumps({"classification": "SINGLE_AGENT", "agent_name": "Ghost"}),
        )
        assert D.select_agent_for_task("q", FakeDB()) == (None, None, None, [])

    def test_unknown_classification_returns_all_none(self, monkeypatch):
        self._agents(monkeypatch)
        _patch_llm(monkeypatch, json.dumps({"classification": "WEIRD"}))
        assert D.select_agent_for_task("q", FakeDB()) == (None, None, None, [])

    def test_complex_task_inlines_planner_with_plan(self, monkeypatch):
        self._agents(monkeypatch)
        _patch_llm(monkeypatch, json.dumps({"classification": "COMPLEX_TASK"}))
        monkeypatch.setattr(
            D, "decompose_task", lambda ui, db: (("id-r", "demand"), [("id-w", "x")])
        )
        out = D.select_agent_for_task("complex", FakeDB())
        assert out == ("id-r", "demand", None, [("id-w", "x")])

    def test_complex_task_no_plan_returns_all_none(self, monkeypatch):
        self._agents(monkeypatch)
        _patch_llm(monkeypatch, json.dumps({"classification": "COMPLEX_TASK"}))
        monkeypatch.setattr(D, "decompose_task", lambda ui, db: (None, []))
        assert D.select_agent_for_task("complex", FakeDB()) == (None, None, None, [])

    def test_complex_task_planner_raises_returns_all_none(self, monkeypatch):
        self._agents(monkeypatch)
        _patch_llm(monkeypatch, json.dumps({"classification": "COMPLEX_TASK"}))

        def _boom(ui, db):
            raise RuntimeError("planner exploded")

        monkeypatch.setattr(D, "decompose_task", _boom)
        assert D.select_agent_for_task("complex", FakeDB()) == (None, None, None, [])

    def test_db_none_uses_sessionlocal(self, monkeypatch):
        monkeypatch.setattr(D, "SessionLocal", lambda: FakeDB())
        monkeypatch.setattr(D, "get_available_agents", lambda db: [])
        _patch_llm(monkeypatch, "x")
        assert D.select_agent_for_task("q") == (None, None, None, [])


class TestDirectAnswerPostCheck:
    ROUTER_PLACEHOLDERS = {
        "agent_name": "<agent_name_if_SINGLE_AGENT>",
        "rewritten_input": "<optimized_input_if_SINGLE_AGENT>",
    }

    def _agents(self, monkeypatch, agents=None):
        roster = (
            agents
            if agents is not None
            else [
                ("a1", "Researcher", "finds facts", _Type.RESEARCHER),
                ("g1", "General-Assistant", "general RAG assistant", _Type.GENERAL),
            ]
        )
        monkeypatch.setattr(D, "get_available_agents", lambda db: roster)

    def _router_says_direct_answer(self, monkeypatch, final_answer, **extra):
        reply = {"classification": "DIRECT_ANSWER", "final_answer": final_answer, **extra}
        _patch_llm(monkeypatch, json.dumps(reply))

    def test_f20_capital_of_peru_is_rerouted_to_single_agent(self, monkeypatch):
        self._agents(monkeypatch)
        self._router_says_direct_answer(
            monkeypatch, "The capital of Peru is Lima.", **self.ROUTER_PLACEHOLDERS
        )
        out = D.select_agent_for_task("What is the capital of Peru?", FakeDB())
        assert out == ("g1", "What is the capital of Peru?", None, [])

    def test_hello_stays_direct_answer(self, monkeypatch):
        self._agents(monkeypatch)
        self._router_says_direct_answer(monkeypatch, "Hello! How can I help?")
        out = D.select_agent_for_task("hello", FakeDB())
        assert out == (None, None, "Response for user : Hello! How can I help?", [])

    def test_small_talk_stays_direct_answer(self, monkeypatch):
        self._agents(monkeypatch)
        self._router_says_direct_answer(monkeypatch, "You're welcome!")
        out = D.select_agent_for_task("Thanks a lot!", FakeDB())
        assert out == (None, None, "Response for user : You're welcome!", [])

    def test_arithmetic_stays_direct_answer(self, monkeypatch):
        self._agents(monkeypatch)
        self._router_says_direct_answer(monkeypatch, "4")
        out = D.select_agent_for_task("what's 2+2?", FakeDB())
        assert out == (None, None, "Response for user : 4", [])

    def test_greeting_followed_by_factual_question_is_rerouted(self, monkeypatch):
        self._agents(monkeypatch)
        self._router_says_direct_answer(monkeypatch, "Hi! Lima.")
        demand = "Hi! What is the capital of Peru?"
        assert D.select_agent_for_task(demand, FakeDB()) == ("g1", demand, None, [])

    def test_rerouted_request_uses_router_agent_name_when_it_is_available(self, monkeypatch):
        self._agents(monkeypatch)
        self._router_says_direct_answer(
            monkeypatch, "Lima.", agent_name="Researcher", rewritten_input="capital?"
        )
        out = D.select_agent_for_task("What is the capital of Peru?", FakeDB())
        assert out == ("a1", "What is the capital of Peru?", None, [])

    @pytest.mark.parametrize("router_agent_name", ["Manager", "Offline-Analyst"])
    def test_rerouted_request_ignores_router_agent_name_that_is_not_available(
        self, monkeypatch, router_agent_name
    ):
        self._agents(monkeypatch)
        monkeypatch.setattr(D, "get_agent_id", lambda name, db: "id-without-live-consumer")
        self._router_says_direct_answer(monkeypatch, "Lima.", agent_name=router_agent_name)
        out = D.select_agent_for_task("What is the capital of Peru?", FakeDB())
        assert out == ("g1", "What is the capital of Peru?", None, [])

    def test_rerouted_request_without_general_agent_uses_first_available(self, monkeypatch):
        self._agents(
            monkeypatch,
            [
                ("w1", "Writer", "writes prose", _Type.WRITER),
                ("a1", "Researcher", "finds facts", _Type.RESEARCHER),
            ],
        )
        self._router_says_direct_answer(monkeypatch, "Lima.")
        out = D.select_agent_for_task("What is the capital of Peru?", FakeDB())
        assert out == ("w1", "What is the capital of Peru?", None, [])

    def test_rerouted_request_matches_plain_string_general_type(self, monkeypatch):
        self._agents(
            monkeypatch,
            [
                ("a1", "Researcher", "finds facts", "researcher"),
                ("g1", "General-Assistant", "general RAG assistant", "general"),
            ],
        )
        self._router_says_direct_answer(monkeypatch, "Lima.")
        out = D.select_agent_for_task("What is the capital of Peru?", FakeDB())
        assert out == ("g1", "What is the capital of Peru?", None, [])

    def test_router_prompt_sent_to_model_has_single_braces(self, monkeypatch):
        self._agents(monkeypatch)
        prompts = _capture_llm_prompts(
            monkeypatch, json.dumps({"classification": "DIRECT_ANSWER", "final_answer": "Hi!"})
        )
        D.select_agent_for_task("hello", FakeDB())
        rendered = _rendered_text(prompts[0])
        assert '{\n  "classification": "DIRECT_ANSWER" | "SINGLE_AGENT"' in rendered
        assert '"final_answer": "<answer_if_DIRECT_ANSWER>"\n}' in rendered
        assert "{{" not in rendered and "}}" not in rendered


# ========================= select_agent_by_mode =========================== #
class TestSelectAgentByMode:
    def test_specific_agent_missing_id_falls_back(self):
        out = D.select_agent_by_mode("d", [], "specific_agent", None, FakeDB())
        assert out == (None, None, None, [])

    def test_specific_agent_not_found_falls_back(self):
        out = D.select_agent_by_mode("d", [], "specific_agent", "x", FakeDB([]))
        assert out == (None, None, None, [])

    def test_specific_agent_found(self):
        agent = FakeAgent(id="x", name="R")
        out = D.select_agent_by_mode("demand", [], "specific_agent", "x", FakeDB([agent]))
        assert out == ("x", "demand", None, [])

    def test_any_with_skill_empty_skills_falls_back(self):
        out = D.select_agent_by_mode("d", [], "any_with_skill", None, FakeDB())
        assert out == (None, None, None, [])

    def test_any_with_skill_no_match_falls_back(self, monkeypatch):
        a = FakeAgent(id="a1", skills=["cooking"])
        out = D.select_agent_by_mode("d", ["research"], "any_with_skill", None, FakeDB([a]))
        assert out == (None, None, None, [])

    def test_any_with_skill_live_match_preferred(self, monkeypatch):
        monkeypatch.setattr(D, "_is_agent_recently_alive", lambda a: True)
        a = FakeAgent(id="live", skills=["research"])
        out = D.select_agent_by_mode("demand", ["research"], "any_with_skill", None, FakeDB([a]))
        assert out == ("live", "demand", None, [])

    def test_any_with_skill_seeded_fallback(self, monkeypatch):
        # Not recently alive -> recorded as seeded_match, returned when no live.
        monkeypatch.setattr(D, "_is_agent_recently_alive", lambda a: False)
        a = FakeAgent(id="seeded", skills=["research"])
        out = D.select_agent_by_mode("demand", ["research"], "any_with_skill", None, FakeDB([a]))
        assert out == ("seeded", "demand", None, [])

    def test_any_with_skill_first_seeded_match_kept(self, monkeypatch):
        # Two matching, neither alive: the first becomes seeded_match and the
        # second must NOT overwrite it (the `seeded_match is None` False path).
        monkeypatch.setattr(D, "_is_agent_recently_alive", lambda a: False)
        a1 = FakeAgent(id="seed1", skills=["research"])
        a2 = FakeAgent(id="seed2", skills=["research"])
        out = D.select_agent_by_mode(
            "demand", ["research"], "any_with_skill", None, FakeDB([a1, a2])
        )
        assert out == ("seed1", "demand", None, [])

    def test_auto_mode_falls_back(self):
        assert D.select_agent_by_mode("d", [], "auto", None, FakeDB()) == (None, None, None, [])

    def test_none_mode_falls_back(self):
        assert D.select_agent_by_mode("d", [], None, None, FakeDB()) == (None, None, None, [])


# ============================ aggregate_results =========================== #
class TestAggregateResults:
    def test_returns_llm_output(self, monkeypatch):
        captured = {}

        def _fake(prompt, **kwargs):
            captured["prompt"] = prompt
            captured["max"] = kwargs.get("max_new_tokens")
            return "final synthesized answer"

        monkeypatch.setattr(D, "ask_llm", _fake)
        out = D.aggregate_results("history text", "result text")
        assert out == "final synthesized answer"
        # Confirm it routed through the synthesis prompt builder.
        assert captured["max"] == 3072
        assert any("history text" in m["content"] for m in captured["prompt"])
