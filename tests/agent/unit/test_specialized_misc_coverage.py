"""Coverage-focused unit tests for several small/medium ``agent`` modules.

Targets:
- ``specialized.researcher_agent``
- ``specialized.analyst_agent``
- ``specialized.writer_agent``
- ``agent_server.profiles``
- ``ai_agents.step_emitter``
- ``ai_agents.data_extractor_tool`` (only the branches not already exercised
  by ``test_data_extractor.py`` — no duplication)

Everything that would touch an LLM, retrieval, spaCy NER, or HTTP is mocked.
The conftest already stubs ``langchain``/``transformers``/``torch`` in
``sys.modules`` so importing these modules is hermetic.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_server import profiles as profiles_mod
from agent_server.profiles import (
    AgentProfile,
    get_primary_profile,
    get_profile_by_agent_id,
    unique_agent_types,
    upsert_external_profile,
)
from ai_agents.data_extractor_tool import DataExtractorTool
from ai_agents.step_emitter import emit_step
from specialized.analyst_agent import AnalystAgent
from specialized.researcher_agent import ResearcherAgent
from specialized.writer_agent import WriterAgent

# ---------------------------------------------------------------------------
# ResearcherAgent
# ---------------------------------------------------------------------------


class TestResearcherAgent:
    def _make_agent(self):
        retriever = MagicMock()
        retriever.fetch = AsyncMock(return_value={"docs": ["chunk-a", "chunk-b"]})
        agent = ResearcherAgent(retriever)
        # Replace the real SummarizerTool with a controllable stub.
        agent.summarizer = MagicMock()
        agent.summarizer.run.return_value = "SUMMARY"
        return agent, retriever

    def test_init_sets_type_and_collaborators(self):
        retriever = MagicMock()
        agent = ResearcherAgent(retriever)
        assert agent.type == "researcher"
        assert agent.knowledge_retriever is retriever
        # SummarizerTool is constructed eagerly.
        assert agent.summarizer is not None

    async def test_search_delegates_to_retriever(self):
        agent, retriever = self._make_agent()
        result = await agent.search("what is revenue?")
        assert result == {"docs": ["chunk-a", "chunk-b"]}
        retriever.fetch.assert_awaited_once_with("what is revenue?")

    def test_summarize_wraps_text_in_payload(self):
        agent, _ = self._make_agent()
        out = agent.summarize("a long body of text")
        assert out == "SUMMARY"
        agent.summarizer.run.assert_called_once_with({"text": "a long body of text"})

    async def test_process_request_search(self):
        agent, retriever = self._make_agent()
        res = await agent.process_request("search", "query-x")
        assert res == {"docs": ["chunk-a", "chunk-b"]}
        retriever.fetch.assert_awaited_once_with("query-x")
        agent.summarizer.run.assert_not_called()

    async def test_process_request_summarize(self):
        agent, retriever = self._make_agent()
        res = await agent.process_request("summarize", "raw text")
        assert res == "SUMMARY"
        agent.summarizer.run.assert_called_once_with({"text": "raw text"})
        retriever.fetch.assert_not_awaited()

    async def test_process_request_research_combines_search_and_summary(self):
        agent, retriever = self._make_agent()
        res = await agent.process_request("research", "deep query")
        # research == search then summarize(str(search_result))
        assert res == "SUMMARY"
        retriever.fetch.assert_awaited_once_with("deep query")
        # The summarizer receives the stringified retrieval dict.
        expected_payload = {"text": str({"docs": ["chunk-a", "chunk-b"]})}
        agent.summarizer.run.assert_called_once_with(expected_payload)

    async def test_process_request_unknown_task_type(self):
        agent, retriever = self._make_agent()
        res = await agent.process_request("dance", "data")
        assert res == "Task type not found"
        retriever.fetch.assert_not_awaited()
        agent.summarizer.run.assert_not_called()


# ---------------------------------------------------------------------------
# AnalystAgent
# ---------------------------------------------------------------------------


class TestAnalystAgent:
    def _make_agent(self):
        agent = AnalystAgent()
        agent.data_extractor = MagicMock()
        agent.data_extractor._run.return_value = "EXTRACTED"
        agent.payment_analyzer = MagicMock()
        agent.payment_analyzer._run.return_value = "ANALYZED"
        agent.calculator = MagicMock()
        agent.calculator.run.return_value = "42.0"
        return agent

    def test_init_builds_three_tools(self):
        agent = AnalystAgent()
        assert agent.type == "analyst"
        assert agent.data_extractor is not None
        assert agent.payment_analyzer is not None
        assert agent.calculator is not None

    def test_extract_delegates(self):
        agent = self._make_agent()
        assert agent.extract("some text", "payments") == "EXTRACTED"
        agent.data_extractor._run.assert_called_once_with("some text", "payments")

    def test_analyze_delegates(self):
        agent = self._make_agent()
        assert agent.analyze("[]", "total") == "ANALYZED"
        agent.payment_analyzer._run.assert_called_once_with("[]", "total")

    def test_calculate_wraps_expression(self):
        agent = self._make_agent()
        assert agent.calculate("1 + 1") == "42.0"
        agent.calculator.run.assert_called_once_with({"expression": "1 + 1"})

    async def test_process_request_extract_uses_explicit_type(self):
        agent = self._make_agent()
        res = await agent.process_request(
            "extract", "doc text", {"extraction_type": "tables"}
        )
        assert res == "EXTRACTED"
        agent.data_extractor._run.assert_called_once_with("doc text", "tables")

    async def test_process_request_extract_defaults_to_entities(self):
        agent = self._make_agent()
        # No extra_parameters -> defaults branch (extra_parameters is None).
        res = await agent.process_request("extract", "doc text")
        assert res == "EXTRACTED"
        agent.data_extractor._run.assert_called_once_with("doc text", "entities")

    async def test_process_request_analyze_defaults_to_fraud(self):
        agent = self._make_agent()
        res = await agent.process_request("analyze", "[]")
        assert res == "ANALYZED"
        agent.payment_analyzer._run.assert_called_once_with("[]", "fraud")

    async def test_process_request_analyze_explicit_type(self):
        agent = self._make_agent()
        res = await agent.process_request("analyze", "[]", {"analysis_type": "average"})
        assert res == "ANALYZED"
        agent.payment_analyzer._run.assert_called_once_with("[]", "average")

    async def test_process_request_calculate_uses_expression_param(self):
        agent = self._make_agent()
        res = await agent.process_request("calculate", "ignored", {"expression": "2*3"})
        assert res == "42.0"
        agent.calculator.run.assert_called_once_with({"expression": "2*3"})

    async def test_process_request_calculate_falls_back_to_data(self):
        agent = self._make_agent()
        # No 'expression' key -> str(data) is used.
        res = await agent.process_request("calculate", 7, {})
        assert res == "42.0"
        agent.calculator.run.assert_called_once_with({"expression": "7"})

    async def test_process_request_unknown_task_type(self):
        agent = self._make_agent()
        res = await agent.process_request("teleport", "data")
        assert res == "Task type not found"
        agent.data_extractor._run.assert_not_called()
        agent.payment_analyzer._run.assert_not_called()
        agent.calculator.run.assert_not_called()


# ---------------------------------------------------------------------------
# WriterAgent
# ---------------------------------------------------------------------------


class TestWriterAgent:
    def _make_agent(self):
        decision = MagicMock()
        # WriterAgent calls self.llm.decide(prompt) via asyncio.to_thread.
        decision.decide.return_value = "GENERATED"
        return WriterAgent(decision), decision

    def test_init_sets_type_and_llm(self):
        decision = MagicMock()
        agent = WriterAgent(decision)
        assert agent.type == "writer"
        assert agent.llm is decision

    async def test_generate_report_builds_prompt(self):
        agent, decision = self._make_agent()
        res = await agent.generate_report("Q4 numbers")
        assert res == "GENERATED"
        decision.decide.assert_called_once()
        (prompt,), _ = decision.decide.call_args
        assert "professional report" in prompt
        assert "Q4 numbers" in prompt

    async def test_format_text_builds_prompt(self):
        agent, decision = self._make_agent()
        res = await agent.format_text("hello", "markdown")
        assert res == "GENERATED"
        decision.decide.assert_called_once()
        (prompt,), _ = decision.decide.call_args
        assert "markdown" in prompt
        assert "hello" in prompt

    async def test_process_request_write(self):
        agent, decision = self._make_agent()
        res = await agent.process_request("write", "input data")
        assert res == "GENERATED"
        (prompt,), _ = decision.decide.call_args
        assert "professional report" in prompt

    async def test_process_request_format_reads_format_param(self):
        agent, decision = self._make_agent()
        res = await agent.process_request("format", "body", {"format": "html"})
        assert res == "GENERATED"
        (prompt,), _ = decision.decide.call_args
        assert "html" in prompt

    async def test_process_request_format_missing_param_raises_keyerror(self):
        agent, _ = self._make_agent()
        # The 'format' branch indexes extra_parameters["format"] directly.
        with pytest.raises(KeyError):
            await agent.process_request("format", "body", {})

    async def test_process_request_unknown_task_type(self):
        agent, decision = self._make_agent()
        res = await agent.process_request("sculpt", "data")
        assert res == "Task type not found"
        decision.decide.assert_not_called()


# ---------------------------------------------------------------------------
# agent_server.profiles
# ---------------------------------------------------------------------------


class TestProfilesLoading:
    """Exercise ``_load_profiles`` env precedence.

    We call the private ``_load_profiles`` directly with patched env rather than
    reloading the module — reloading would rebind module-level ContextVars and
    break other already-imported modules (e.g. ``consumers``) that hold
    references to the originals.
    """

    @pytest.fixture
    def load(self, monkeypatch):
        def _call(env: dict):
            for key in (
                "AGENT_PROFILES_JSON",
                "AGENT_NAME",
                "AGENT_TYPE",
                "AGENT_SKILLS",
                "AGENT_DESCRIPTION",
            ):
                monkeypatch.delenv(key, raising=False)
            for key, val in env.items():
                monkeypatch.setenv(key, val)
            return profiles_mod._load_profiles()

        return _call

    def test_defaults_when_no_env(self, load):
        result = load({})
        names = [p.name for p in result]
        assert "General-Assistant" in names
        assert "Finance-Analyst" in names
        assert "Researcher" in names
        # Defaults list is copied, not aliased to the module constant.
        assert result is not profiles_mod.DEFAULT_PROFILES

    def test_profiles_json_override(self, load):
        payload = json.dumps(
            [
                {
                    "name": "Solo",
                    "type": "analyst",
                    "skills": ["x", "y"],
                    "description": "single specialist",
                }
            ]
        )
        result = load({"AGENT_PROFILES_JSON": payload})
        assert len(result) == 1
        prof = result[0]
        assert prof.name == "Solo"
        assert prof.type == "analyst"
        assert prof.skills == ["x", "y"]

    def test_profiles_json_defaults_for_missing_keys(self, load):
        # Only 'name' provided -> type defaults to 'general', skills to [].
        result = load({"AGENT_PROFILES_JSON": json.dumps([{"name": "Bare"}])})
        prof = result[0]
        assert prof.name == "Bare"
        assert prof.type == "general"
        assert prof.skills == []
        assert prof.description == ""

    def test_profiles_json_invalid_falls_back_to_defaults(self, load):
        # Malformed JSON triggers the except branch and logs, then falls back.
        result = load({"AGENT_PROFILES_JSON": "{not valid json"})
        names = [p.name for p in result]
        assert "General-Assistant" in names

    def test_profiles_json_missing_required_key_falls_back(self, load):
        # Valid JSON list but entries lack the required 'name' key -> KeyError
        # inside the comprehension -> except branch -> defaults.
        result = load({"AGENT_PROFILES_JSON": json.dumps([{"type": "analyst"}])})
        names = [p.name for p in result]
        assert "General-Assistant" in names

    def test_single_name_mode_with_explicit_fields(self, load):
        result = load(
            {
                "AGENT_NAME": "Lonely",
                "AGENT_TYPE": "writer",
                "AGENT_SKILLS": "alpha, beta ,, gamma",
                "AGENT_DESCRIPTION": "the only one",
            }
        )
        assert len(result) == 1
        prof = result[0]
        assert prof.name == "Lonely"
        assert prof.type == "writer"
        # Comma-split, trimmed, empties dropped.
        assert prof.skills == ["alpha", "beta", "gamma"]
        assert prof.description == "the only one"

    def test_single_name_mode_defaults(self, load):
        # AGENT_NAME present but type/skills/description absent -> defaults.
        result = load({"AGENT_NAME": "Default-Skills"})
        prof = result[0]
        assert prof.type == "general"
        assert prof.skills == ["knowledge_retrieval", "decision_making", "rag_pipeline"]
        assert prof.description == "Autonomous MAS agent"

    def test_single_name_blank_type_falls_back_to_general(self, load):
        # AGENT_TYPE set to whitespace -> the ``or "general"`` guard applies.
        result = load({"AGENT_NAME": "WS", "AGENT_TYPE": "   "})
        assert result[0].type == "general"


class TestProfilesHelpers:
    """Pure-function helpers operating on a controlled PROFILES list."""

    @pytest.fixture
    def patched_profiles(self, monkeypatch):
        sample = [
            AgentProfile(
                name="A", type="general", skills=["s1"], description="",
                agent_id="id-a", api_key="key-a",
            ),
            AgentProfile(
                name="B", type="analyst", skills=["s2"], description="",
                agent_id="id-b", api_key="key-b",
            ),
            AgentProfile(
                name="C", type="general", skills=["s3"], description="",
                agent_id="id-c", api_key="key-c",
            ),
        ]
        monkeypatch.setattr(profiles_mod, "PROFILES", sample)
        return sample

    def test_unique_agent_types_dedup_preserves_order(self, patched_profiles):
        assert unique_agent_types() == ["general", "analyst"]

    def test_unique_agent_types_skips_empty_type(self, monkeypatch):
        sample = [
            AgentProfile(name="X", type="", skills=[], description=""),
            AgentProfile(name="Y", type="writer", skills=[], description=""),
        ]
        monkeypatch.setattr(profiles_mod, "PROFILES", sample)
        assert unique_agent_types() == ["writer"]

    def test_get_profile_by_agent_id_found(self, patched_profiles):
        prof = get_profile_by_agent_id("id-b")
        assert prof is not None
        assert prof.name == "B"

    def test_get_profile_by_agent_id_none_arg(self, patched_profiles):
        assert get_profile_by_agent_id(None) is None

    def test_get_profile_by_agent_id_empty_string(self, patched_profiles):
        assert get_profile_by_agent_id("") is None

    def test_get_profile_by_agent_id_missing(self, patched_profiles):
        assert get_profile_by_agent_id("nope") is None

    def test_get_primary_profile(self, patched_profiles):
        assert get_primary_profile().name == "A"

    def test_upsert_updates_existing_profile(self, patched_profiles):
        before_len = len(profiles_mod.PROFILES)
        result = upsert_external_profile(
            agent_id="id-b",
            api_key="new-key",
            name="B-renamed",
            agent_type="researcher",
            skills=["new-skill"],
            description="updated",
        )
        assert result.name == "B-renamed"
        assert result.api_key == "new-key"
        assert result.type == "researcher"
        assert result.skills == ["new-skill"]
        assert result.description == "updated"
        # No new profile appended on update.
        assert len(profiles_mod.PROFILES) == before_len

    def test_upsert_existing_keeps_old_values_when_args_blank(self, patched_profiles):
        # Blank/empty args should fall back to the existing values.
        result = upsert_external_profile(
            agent_id="id-a",
            api_key="",
            name="",
            agent_type="",
            skills=[],
            description="",
        )
        assert result.name == "A"
        assert result.api_key == "key-a"
        assert result.type == "general"
        assert result.skills == ["s1"]

    def test_upsert_adds_new_profile(self, patched_profiles):
        before_len = len(profiles_mod.PROFILES)
        result = upsert_external_profile(
            agent_id="id-new",
            api_key="k",
            name="NewOne",
            agent_type="writer",
            skills=["w"],
            description="fresh",
        )
        assert result.name == "NewOne"
        assert result.agent_id == "id-new"
        assert len(profiles_mod.PROFILES) == before_len + 1
        assert profiles_mod.PROFILES[-1] is result

    def test_upsert_new_profile_default_name_and_type(self, patched_profiles):
        # Empty name -> synthesised "AutoAgent-<id[:8]>"; empty type -> general.
        result = upsert_external_profile(
            agent_id="abcdef0123456789",
            api_key="k",
            name="",
            agent_type="",
            skills=[],
            description="",
        )
        assert result.name == "AutoAgent-abcdef01"
        assert result.type == "general"
        assert result.description == "Worker-adopted specialist"


# ---------------------------------------------------------------------------
# ai_agents.step_emitter
# ---------------------------------------------------------------------------


class TestStepEmitter:
    def test_no_emitter_bound_is_noop(self):
        # Default ContextVar value is None -> early return, no error.
        profiles_mod.current_step_emitter.set(None)
        assert emit_step("retrieval.start", "Looking things up") is None

    def test_emitter_receives_event_envelope(self):
        captured = []
        token = profiles_mod.current_step_emitter.set(captured.append)
        try:
            emit_step(
                "reasoning.done",
                "Finished thinking",
                detail="the long form",
                chunks=["c1", "c2"],
            )
        finally:
            profiles_mod.current_step_emitter.reset(token)

        assert len(captured) == 1
        event = captured[0]
        assert event["step_type"] == "reasoning.done"
        assert event["title"] == "Finished thinking"
        assert event["detail"] == "the long form"
        assert event["metadata"] == {"chunks": ["c1", "c2"]}
        assert "timestamp" in event and event["timestamp"]

    def test_event_omits_metadata_when_none_passed(self):
        captured = []
        token = profiles_mod.current_step_emitter.set(captured.append)
        try:
            emit_step("tool.invoke", "Calling tool")
        finally:
            profiles_mod.current_step_emitter.reset(token)
        assert "metadata" not in captured[0]
        assert captured[0]["detail"] == ""

    def test_emitter_exception_is_swallowed(self):
        def boom(_event):
            raise RuntimeError("network down")

        token = profiles_mod.current_step_emitter.set(boom)
        try:
            # Must not propagate — the pipeline should be insulated.
            assert emit_step("error", "kaboom") is None
        finally:
            profiles_mod.current_step_emitter.reset(token)

    def test_import_failure_path_is_noop(self):
        # Force the ``from agent_server.profiles import ...`` to raise so the
        # ``except`` branch sets emitter=None and we early-return (lines 39-40).
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "agent_server.profiles":
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            assert emit_step("retrieval.start", "x") is None


# ---------------------------------------------------------------------------
# ai_agents.data_extractor_tool — ONLY the branches not covered by
# tests/agent/unit/test_data_extractor.py
# ---------------------------------------------------------------------------


class TestDataExtractorUncovered:
    @pytest.fixture
    def tool(self):
        return DataExtractorTool()

    # --- _run routing end-to-end (lines 106-119) ---

    def test_run_routing_payments_end_to_end(self, tool):
        # Real doc (dummy NLP) + real _extract_payments via the router.
        res = tool._run("Paid $250 today.", "payments")
        data = json.loads(res)
        assert any(row["amount"] == 250.0 for row in data)

    def test_run_routing_tables_end_to_end(self, tool):
        res = tool._run("| A | B |\n| 1 | 2 |", "tables")
        data = json.loads(res)
        assert data[0]["header"] == ["A", "B"]

    def test_run_routing_key_values_end_to_end(self, tool):
        res = tool._run("Owner: Alice", "key_values")
        data = json.loads(res)
        assert data["Owner"] == "Alice"

    def test_run_invalid_type_raises(self, tool):
        with pytest.raises(ValueError, match="Unsupported extraction type"):
            tool._run("text", "bogus")

    # --- extract_entities_spacy individual label branches (172-179) ---

    def test_extract_entities_spacy_each_label(self, tool):
        def _ent(label, text):
            e = MagicMock()
            e.label_ = label
            e.text = text
            return e

        doc = MagicMock()
        doc.ents = [
            _ent("PERSON", " Alice "),
            _ent("ORG", "Globex"),
            _ent("MONEY", "$5"),
            _ent("DATE", "2024"),
            _ent("GPE", "Paris"),  # ignored label -> none of the branches fire
        ]
        res = tool.extract_entities_spacy(doc)
        assert res["people"] == ["Alice"]  # stripped + de-duped
        assert res["companies"] == ["Globex"]
        assert res["amounts"] == ["$5"]
        assert res["dates"] == ["2024"]

    # --- CSV heuristic scan (lines 219-278) ---

    def test_csv_scan_extracts_payment_with_date_and_payee(self, tool):
        # Three+ comma-separated fields with a recognised currency token.
        # spaCy is the dummy (no ents) so only the CSV path + regex produce rows.
        text = "2024-01-15, Acme Vendor, 1500.50, USD"
        result = tool._extract_payments(text, tool.nlp(text))
        data = json.loads(result)
        # The CSV row is the first appended entry.
        csv_row = data[0]
        assert csv_row["amount"] == 1500.50
        assert csv_row["currency"] == "USD"
        assert csv_row["estimated_date"] == "2024-01-15"
        # Payee is the last non-numeric, non-date field > 3 chars.
        assert csv_row["payee"] == "Acme Vendor"
        assert csv_row["context"] == text

    def test_csv_scan_no_currency_token_skips_row(self, tool):
        # Three fields but no currency keyword -> CSV branch produces nothing.
        # Also no regex-detectable amount -> overall "No payments found".
        text = "alpha, beta, gamma"
        result = tool._extract_payments(text, tool.nlp(text))
        assert result == "No payments found"

    def test_csv_scan_currency_but_no_numeric_candidate(self, tool):
        # Currency present, >=3 fields, but no parseable number -> candidates
        # empty, so the inner ``if candidates`` block is skipped.
        text = "note, USD, pending"
        result = tool._extract_payments(text, tool.nlp(text))
        assert result == "No payments found"

    def test_csv_scan_picks_candidate_closest_to_currency(self, tool):
        # Two numeric candidates; the one adjacent to the currency wins.
        # parts: ['10', '20', 'USD'] -> currency idx 2; 20 (idx1,dist1) beats
        # 10 (idx0,dist2).
        text = "10, 20, USD"
        result = tool._extract_payments(text, tool.nlp(text))
        data = json.loads(result)
        csv_row = data[0]
        assert csv_row["amount"] == 20.0
        assert csv_row["currency"] == "USD"
        # No date, no payee field qualifies.
        assert csv_row["estimated_date"] is None
        assert csv_row["payee"] is None

    def test_csv_scan_skips_blank_lines(self, tool):
        # Leading blank line exercises the ``if not line: continue`` guard,
        # followed by a valid CSV payment row.
        text = "\n   \nReef Corp, 90, EUR\n"
        result = tool._extract_payments(text, tool.nlp(text))
        data = json.loads(result)
        assert any(row["currency"] == "EUR" and row["amount"] == 90.0 for row in data)

    # --- Amount cleaning edge branches in the regex/amounts loop ---

    def test_comma_thousand_separator_without_decimal(self, tool):
        # "1,000" -> the elif comma branch where it is NOT a 2-digit decimal,
        # so the comma is treated as a thousands separator (line ~320).
        text = "Total of $1,000 paid."
        result = tool._extract_payments(text, tool.nlp(text))
        data = json.loads(result)
        assert any(row["amount"] == 1000.0 for row in data)

    def test_eur_currency_detection_branch(self, tool):
        # "€50" / "EUR" triggers the EUR currency assignment (lines 293-294).
        text = "Invoice for €50 and 75 EUR."
        result = tool._extract_payments(text, tool.nlp(text))
        data = json.loads(result)
        assert any(row["currency"] == "EUR" for row in data)

    def test_proximity_links_close_date_and_payee(self, tool):
        # Amount, date and payee all within the 100/150 windows so the
        # ``if dist <= N`` proximity assignments fire (lines 350-352, 360-362).
        text = "Paid $200 to Bob Smith on 2024-03-03 promptly."
        with patch.object(DataExtractorTool, "extract_entities_regex") as mock_regex:
            with patch.object(DataExtractorTool, "extract_entities_spacy") as mock_spacy:
                mock_regex.return_value = {"amounts": ["$200"], "dates": ["2024-03-03"]}
                mock_spacy.return_value = {
                    "people": ["Bob Smith"],
                    "companies": [],
                    "amounts": [],
                    "dates": [],
                }
                result = tool._extract_payments(text, MagicMock())
        data = json.loads(result)
        row = next(r for r in data if r["amount"] == 200.0)
        assert row["estimated_date"] == "2024-03-03"
        assert row["payee"] == "Bob Smith"

    def test_proximity_equidistant_candidates_take_loopback(self, tool):
        # Two dates and two payees that are EQUIDISTANT from the amount and both
        # inside the window. Whatever order ``set()`` yields, exactly one
        # iteration sets the reference (350->351 / 360->361) and the other finds
        # ``dist < ref`` False (equal, not less) and loops back (350->344,
        # 360->355) — deterministic regardless of set ordering.
        # Layout: place the amount dead-centre with a mirror token on each side.
        # "Aaa $400 Bbb" -> "Aaa" and "Bbb" are equidistant from "$400".
        # "Xx 2020 $400 2021 Yy" -> "2020"/"2021" equidistant from "$400".
        text = "Pay 2020 Aaaa $400 Bbbb 2021 done"
        with patch.object(DataExtractorTool, "extract_entities_regex") as mock_regex:
            with patch.object(DataExtractorTool, "extract_entities_spacy") as mock_spacy:
                mock_regex.return_value = {
                    "amounts": ["$400"],
                    "dates": ["2020", "2021"],
                }
                mock_spacy.return_value = {
                    "people": ["Aaaa", "Bbbb"],
                    "companies": [],
                    "amounts": [],
                    "dates": [],
                }
                result = tool._extract_payments(text, MagicMock())
        row = next(r for r in json.loads(result) if r["amount"] == 400.0)
        # Both candidates are equidistant and in-window, so one of each is chosen
        # (which one is set-order dependent, but it must be a real linked value).
        assert row["estimated_date"] in ("2020", "2021")
        assert row["payee"] in ("Aaaa", "Bbbb")

    def test_amount_that_cannot_parse_is_skipped(self, tool):
        # Drive a value into the amounts loop that survives currency-detection
        # but cleans to a non-float, hitting the ValueError->continue (326-327).
        text = "weird amount"
        with patch.object(DataExtractorTool, "extract_entities_regex") as mock_regex:
            with patch.object(DataExtractorTool, "extract_entities_spacy") as mock_spacy:
                mock_regex.return_value = {"amounts": ["USD"], "dates": []}
                mock_spacy.return_value = {
                    "people": [],
                    "companies": [],
                    "amounts": [],
                    "dates": [],
                }
                # "USD" -> currency USD, cleaned == "" -> float("") raises -> skip.
                result = tool._extract_payments(text, MagicMock())
        assert result == "No payments found"

    def test_date_and_payee_too_far_are_not_linked(self, tool):
        # Amount at start; date/payee far beyond the 100/150 char windows so the
        # proximity ``if dist <= N`` guards stay false (branches 349/350/359/360).
        far = "x" * 300
        text = f"$100 {far} 2024-12-31 Faraway Person"
        with patch.object(DataExtractorTool, "extract_entities_regex") as mock_regex:
            with patch.object(DataExtractorTool, "extract_entities_spacy") as mock_spacy:
                mock_regex.return_value = {"amounts": ["$100"], "dates": ["2024-12-31"]}
                mock_spacy.return_value = {
                    "people": ["Faraway Person"],
                    "companies": [],
                    "amounts": [],
                    "dates": [],
                }
                result = tool._extract_payments(text, MagicMock())
        data = json.loads(result)
        row = next(r for r in data if r["amount"] == 100.0)
        assert row["estimated_date"] is None
        assert row["payee"] is None

    # --- _extract_tables flush branches (lines 455-459, 464->466, 471->474) ---

    def test_table_terminated_by_non_table_pipe_line(self, tool):
        # A pipe line with < 2 cells flushes the accumulated table (455-459).
        text = "\n".join(
            [
                "| A | B |",
                "| 1 | 2 |",
                "| single |",  # only one cell -> not a table row -> flush
                "trailing prose",
            ]
        )
        result = tool._extract_tables(text)
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["header"] == ["A", "B"]
        assert data[0]["content"] == [["1", "2"]]

    def test_table_terminated_by_blank_then_plain_text(self, tool):
        # A table followed by a non-pipe line exercises the block-end flush
        # (464->466), and a trailing table exercises the final flush (471->474).
        text = "\n".join(
            [
                "| H1 | H2 |",
                "| a | b |",
                "plain line ends the table",
                "| K1 | K2 |",
                "| c | d |",
            ]
        )
        result = tool._extract_tables(text)
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["header"] == ["H1", "H2"]
        assert data[1]["header"] == ["K1", "K2"]

    def test_pipe_line_with_only_dividers_flushes_nothing(self, tool):
        # current_table accumulates divider-only rows that parse_table strips to
        # {}, so the flush appends nothing (the ``if table`` guard is False).
        text = "\n".join(["|---|---|", "|___|___|"])
        result = tool._extract_tables(text)
        # parse_table returns {} for all-divider input -> no tables.
        assert result == "No tables found"

    # --- key-values heuristics (key too long / empty value skipped) ---

    def test_key_values_skips_overlong_key(self, tool):
        long_key = "K" * 60  # len >= 50 -> rejected by the heuristic.
        text = f"{long_key}: value\nGood: yes"
        result = tool._extract_key_values(text)
        data = json.loads(result)
        assert long_key not in data
        assert data["Good"] == "yes"

    def test_key_values_none_found_returns_message(self, tool):
        # A colon-less body produces no matches -> the no-pairs return (line 517).
        assert tool._extract_key_values("just words no colon") == (
            "No key-value pairs found"
        )

    def test_key_values_blank_line_continue(self, tool):
        # Embedded blank line exercises the ``if not line: continue`` guard (504).
        text = "A: 1\n\n   \nB: 2"
        data = json.loads(tool._extract_key_values(text))
        assert data == {"A": "1", "B": "2"}

    def test_parse_table_only_dividers_returns_empty(self, tool):
        # All rows reduce to dividers -> parsed_table empty -> {} (line 414-415).
        assert tool.parse_table(["|---|", "|___|"]) == {}

    def test_parse_table_empty_list_returns_empty(self, tool):
        # Empty input -> the ``if not current_table`` guard returns {} (390).
        assert tool.parse_table([]) == {}

    def test_extract_tables_blank_line_inside(self, tool):
        # A blank line between table rows is skipped (445) without ending the
        # accumulated table.
        text = "| H | I |\n   \n| 1 | 2 |"
        data = json.loads(tool._extract_tables(text))
        assert len(data) == 1
        assert data[0]["header"] == ["H", "I"]
        assert data[0]["content"] == [["1", "2"]]

    def test_extract_tables_single_cell_line_with_no_open_table(self, tool):
        # A single-cell pipe line while no table is open: the ``if current_table``
        # guard is False so we just loop back (branch 455->442). No tables found.
        text = "| lonely |\nplain text"
        assert tool._extract_tables(text) == "No tables found"

    def test_extract_tables_divider_only_then_single_cell(self, tool):
        # Accumulate a divider-only row (kept because it has 2+ pipe cells), then
        # a single-cell line forces a flush where parse_table -> {} so nothing is
        # appended (branch 457->459), and current_table resets.
        text = "| --- | --- |\n| x |\nprose"
        assert tool._extract_tables(text) == "No tables found"

    def test_extract_tables_divider_only_then_plain_line(self, tool):
        # Divider-only table rows then a non-pipe line: block-end flush where
        # parse_table returns {} (branch 464->466).
        text = "| --- | --- |\n| ___ | ___ |\nthe end"
        assert tool._extract_tables(text) == "No tables found"

    # --- amount-loop number formatting branches (US vs EU vs comma-decimal) ---

    def test_amount_loop_us_format_comma_and_dot(self, tool):
        # Drive "$1,234.50" through the regex amounts loop (not the CSV path):
        # comma before dot -> US format, strip commas (lines 305-308).
        with patch.object(DataExtractorTool, "extract_entities_regex") as mock_regex:
            with patch.object(DataExtractorTool, "extract_entities_spacy") as mock_spacy:
                mock_regex.return_value = {"amounts": ["$1,234.50"], "dates": []}
                mock_spacy.return_value = {
                    "people": [], "companies": [], "amounts": [], "dates": [],
                }
                data = json.loads(
                    tool._extract_payments("$1,234.50 total", MagicMock())
                )
        assert data[0]["amount"] == 1234.50

    def test_amount_loop_eu_format_dot_and_comma(self, tool):
        # "€1.234,50": dot before comma -> EU format (lines 309-311).
        with patch.object(DataExtractorTool, "extract_entities_regex") as mock_regex:
            with patch.object(DataExtractorTool, "extract_entities_spacy") as mock_spacy:
                mock_regex.return_value = {"amounts": ["€1.234,50"], "dates": []}
                mock_spacy.return_value = {
                    "people": [], "companies": [], "amounts": [], "dates": [],
                }
                data = json.loads(
                    tool._extract_payments("€1.234,50 total", MagicMock())
                )
        assert data[0]["amount"] == 1234.50

    def test_amount_loop_comma_decimal(self, tool):
        # "€10,50": single comma, 2-digit decimal -> comma-as-decimal (line 317).
        with patch.object(DataExtractorTool, "extract_entities_regex") as mock_regex:
            with patch.object(DataExtractorTool, "extract_entities_spacy") as mock_spacy:
                mock_regex.return_value = {"amounts": ["€10,50"], "dates": []}
                mock_spacy.return_value = {
                    "people": [], "companies": [], "amounts": [], "dates": [],
                }
                data = json.loads(tool._extract_payments("€10,50 total", MagicMock()))
        assert data[0]["amount"] == 10.50

    def test_csv_candidate_distance_tie_break(self, tool):
        # Three numeric candidates around the currency; the closest-to-currency
        # one must win, exercising both arcs of the ``if dist < closest`` test
        # (branch 245->243 when a later candidate is NOT closer).
        # parts: ['5','6','USD','7'] -> currency idx 2. 6(idx1,d1) and 7(idx3,d1)
        # tie at distance 1; the first-seen closer one (6) is retained, and 5
        # (idx0,d2) does not displace it.
        text = "5, 6, USD, 7"
        data = json.loads(tool._extract_payments(text, tool.nlp(text)))
        csv_row = data[0]
        assert csv_row["currency"] == "USD"
        assert csv_row["amount"] in (6.0, 7.0)  # a distance-1 candidate, not 5

    # --- CSV scan exception handler (lines 277-278) ---

    def test_csv_scan_handles_splitlines_failure(self, tool):
        # Force text.splitlines() to raise so the outer try/except logs and the
        # scan is skipped; the regex path on a normal str then still runs.
        class WeirdStr(str):
            def splitlines(self, *a, **k):
                raise RuntimeError("boom")

        text = WeirdStr("Paid $300 today.")
        # str.find etc. still work on the subclass for the regex/amount path.
        result = tool._extract_payments(text, tool.nlp("Paid $300 today."))
        data = json.loads(result)
        assert any(row["amount"] == 300.0 for row in data)

    # --- spaCy init: test-mode path where spacy.load('en_core_web_sm')
    #     succeeds (lines 47->54). The other (non-test) fallback chain at
    #     62-86 is unreachable while pytest is imported, so we don't chase it.

    def test_init_test_mode_spacy_load_success(self):
        import ai_agents.data_extractor_tool as det

        original_model = det._nlp_model
        det._nlp_model = None
        sentinel = MagicMock(name="sm-model")
        try:
            # is_test is True (pytest in sys.modules) and _has_spacy is True, so
            # the test-mode branch calls spacy.load("en_core_web_sm"); make it
            # succeed and assign the model (line 54).
            with patch("spacy.load", return_value=sentinel) as mock_load:
                tool = DataExtractorTool()
                assert tool.nlp is sentinel
                mock_load.assert_called_once_with("en_core_web_sm")
        finally:
            det._nlp_model = original_model
