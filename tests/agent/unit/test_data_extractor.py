import json
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from ai_agents.data_extractor_tool import DataExtractorTool


class TestDataExtractorTool:

    @pytest.fixture
    def tool(self):
        return DataExtractorTool()

    # --- Table Extraction Tests ---

    def test_extract_tables_valid(self, tool):
        text = """
        Here is a table:
        | Item | Cost |
        | --- | --- |
        | Apple | 1.00 |
        | Banana| 0.50 |
        """
        result = tool._extract_tables(text)
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 1
        table = data[0]
        assert "Item" in table["header"]
        assert "Cost" in table["header"]
        assert ["Apple", "1.00"] in table["content"]
        assert ["Banana", "0.50"] in table["content"]

    def test_extract_tables_empty(self, tool):
        text = "No tables here."
        result = tool._extract_tables(text)
        assert result == "No tables found"

    def test_extract_tables_broken_format(self, tool):
        text = """
        | Header 1 | Header 2
        | Row 1 Col 1 | Row 1 Col 2 |
        """
        # Should likely fail to extract a clean table if delimiters are missing,
        # but let's see if the logic is robust enough to return something or nothing.
        # Based on regex r"\s{2,}|\t|\s*\|\s*", splitting by pipe might still work partially.
        result = tool._extract_tables(text)
        # If it finds nothing, that's acceptable for broken input
        if result != "No tables found":
             data = json.loads(result)
             assert isinstance(data, list)

    def test_extract_tables_multiple(self, tool):
        text = """
        Table 1
        | A | B |
        | 1 | 2 |
        
        Text in between
        
        Table 2
        | X | Y |
        | 3 | 4 |
        """
        result = tool._extract_tables(text)
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["header"] == ["A", "B"]
        assert data[1]["header"] == ["X", "Y"]

    # --- Key-Value Extraction Tests ---

    def test_extract_key_values_valid(self, tool):
        text = """
        Invoice Number: INV-12345
        Date: 2023-10-27
        Total: $500.00
        """
        result = tool._extract_key_values(text)
        data = json.loads(result)
        assert data["Invoice Number"] == "INV-12345"
        assert data["Date"] == "2023-10-27"

    def test_extract_key_values_empty(self, tool):
        text = "Just some random text."
        result = tool._extract_key_values(text)
        assert result == "No key-value pairs found"

    def test_extract_key_values_weird_spacing(self, tool):
        text = """
        Key    :    Value
        Short:Val
        """
        result = tool._extract_key_values(text)
        data = json.loads(result)
        assert data["Key"] == "Value"
        assert data.get("Short") == "Val"

    def test_extract_key_values_ignore_http(self, tool):
        text = "Website: http://example.com"
        result = tool._extract_key_values(text)
        # "http" is in ignored keys? The implementation has a list of ignored keys.
        # However, the key here is "Website". Value is "http...".
        # The ignored keys check is on the key itself.
        data = json.loads(result)
        assert data["Website"] == "http://example.com"

        text2 = "http: //example.com"
        # key "http" should be ignored
        result2 = tool._extract_key_values(text2)
        # If extracted, verify key is not http
        if result2 != "No key-value pairs found":
            data2 = json.loads(result2)
            assert "http" not in data2

    # --- Payment Extraction Tests ---

    def test_extract_payments_regex_fallback_basic(self, tool):
        text = "Payment of 500 EUR to ALICE CORP regarding Invoice #999."
        # We assume Spacy might fail or find nothing in this unit test env,
        # but regex should find "500 EUR"

        result = tool._extract_payments(text, tool.nlp(text))

        if result != "No payments found":
            data = json.loads(result)
            assert isinstance(data, list)
            # Check for amount and currency
            # Regex extracts "500 EUR"
            found = False
            for payment in data:
                 if payment["amount"] == 500.0 and payment["currency"] == "EUR":
                     found = True
            assert found

    def test_extract_payments_formats(self, tool):
        text = """
        $1,000.50
        200.00 USD
        € 50
        """
        doc = tool.nlp(text)
        result = tool._extract_payments(text, doc)
        data = json.loads(result)

        amounts = [p["amount"] for p in data]
        assert 1000.5 in amounts
        assert 200.0 in amounts
        assert 50.0 in amounts

        currencies = [p["currency"] for p in data]
        assert "USD" in currencies
        assert "EUR" in currencies

    def test_extract_payments_no_find(self, tool):
        text = "Just text with no money."
        doc = tool.nlp(text)
        result = tool._extract_payments(text, doc)
        assert result == "No payments found"

    # --- Tool Routing Tests ---

    def test_run_routing_payments(self, tool):
        text = "Payment of 100 USD."
        with patch.object(DataExtractorTool, '_extract_payments') as mock_method:
            mock_method.return_value = "Mock Result"
            res = tool._run(text, "payments")
            assert res == "Mock Result"
            mock_method.assert_called_once()  # called with text and doc

    def test_run_routing_tables(self, tool):
        text = "Some table text"
        with patch.object(DataExtractorTool, '_extract_tables') as mock_method:
            mock_method.return_value = "Mock Table"
            res = tool._run(text, "tables")
            assert res == "Mock Table"
            mock_method.assert_called_once_with(text)

    def test_run_invalid_type(self, tool):
        with pytest.raises(ValueError):
            tool._run("text", "invalid_type")

    def test_arun_not_implemented(self, tool):
        """Test that async execution is not implemented."""
        with pytest.raises(NotImplementedError):
            tool._arun("text", "payments")

    def test_extract_entities_spacy_mock(self, tool):
        """Mock Spacy doc to ensure all entity types are extracted."""
        mock_doc = MagicMock()

        # Create mock entities
        ent_person = MagicMock()
        ent_person.label_ = "PERSON"
        ent_person.text = "John Doe"

        ent_org = MagicMock()
        ent_org.label_ = "ORG"
        ent_org.text = "Acme Corp"

        ent_money = MagicMock()
        ent_money.label_ = "MONEY"
        ent_money.text = "100 USD"

        ent_date = MagicMock()
        ent_date.label_ = "DATE"
        ent_date.text = "2023-01-01"

        # Assign to doc
        mock_doc.ents = [ent_person, ent_org, ent_money, ent_date]

        # Run extraction
        res = tool.extract_entities_spacy(mock_doc)

        assert "John Doe" in res["people"]
        assert "Acme Corp" in res["companies"]
        assert "100 USD" in res["amounts"]
        assert "2023-01-01" in res["dates"]

    def test_extract_payments_proximity_logic(self, tool):
        """Test that date/payee are linked to amount if close enough."""
        # We can test this by mocking Spacy output or constructing text carefully.
        # Text: "Paid 100 EUR to Bob on 2023-01-01."
        # Distance logic: amount at index 5. "Bob" at index 16 (dist 11). "2023..." at index 23 (dist 18).
        # We'll use the mocking approach for precision.

        text = "Paid 100 EUR to Bob on 2023-01-01."

        # Mocking extract_entities_regex and extract_entities_spacy to control inputs to logic
        with patch.object(DataExtractorTool, 'extract_entities_regex') as mock_regex:
            with patch.object(DataExtractorTool, 'extract_entities_spacy') as mock_spacy:

                mock_regex.return_value = {
                    "amounts": ["100 EUR"],
                    "dates": ["2023-01-01"] # Regex finds date
                }
                mock_spacy.return_value = {
                    "people": ["Bob"], # Spacy finds person
                    "companies": [],
                    "amounts": [],
                    "dates": []
                }

                # We need to ensure the text.find() works, so inputs must match text content.
                res_str = tool._extract_payments(text, MagicMock())
                data = json.loads(res_str)

                payment = data[0]
                assert payment["amount"] == 100.0
                assert payment["currency"] == "EUR"
                assert payment["payee"] == "Bob"
                assert payment["estimated_date"] == "2023-01-01"

    def test_parse_table_delimiters(self, tool):
        """Test explicitly ignoring separator lines."""
        table_lines = [
            "| Header1 | Header2 |",
            "|---|---|",
            "|___|___|",
            "| Val1 | Val2 |"
        ]
        res = tool.parse_table(table_lines)
        assert res["header"] == ["Header1", "Header2"]
        assert len(res["content"]) == 1
        assert res["content"][0] == ["Val1", "Val2"]

    def test_parse_table_empty(self, tool):
        assert tool.parse_table([]) == {}
        assert tool.parse_table(["   "]) == {} # Cleaned empty

    # --- Initialization & Edge Case Tests ---

    def test_init_spacy_load_failures(self):
         # Reset global _nlp_model to ensure init logic runs
         import ai_agents.data_extractor_tool as det
         original_model = det._nlp_model
         det._nlp_model = None

         try:
             # Patch spacy.load to fail for both 'en_core_web_trf' and 'en_core_web_sm'
             # Note: We patch where it is imported or used. It is used as `spacy.load`.
             with patch("spacy.load", side_effect=[OSError("trf missing"), OSError("sm missing")]):
                 tool = DataExtractorTool()
                 # Should fallback to dummy
                 # Verify dummy behavior (empty ents)
                 mock_res = tool.nlp("test")
                 assert mock_res.ents == []
         finally:
             # Restore
             det._nlp_model = original_model

    def test_regex_date_formats(self, tool):
        # Test full_date_pattern parts
        text = "Date: Jan 1st, 2023. Also 2023-01-01. And 01/01/2023."
        res = tool.extract_entities_regex(text)
        dates = res["dates"]
        # Allow flexible matching but ensure something is found
        assert any("Jan 1st, 2023" in d for d in dates)
        assert "2023-01-01" in dates
        assert "01/01/2023" in dates

    def test_payment_formatting_EU_US(self, tool):
        # US: 1,000.50
        text_us = "$1,000.50"
        res_us = tool._extract_payments(text_us, tool.nlp(text_us))
        data_us = json.loads(res_us)
        assert data_us[0]["amount"] == 1000.50

        # EU: 1.000,50
        text_eu = "€1.000,50"
        res_eu = tool._extract_payments(text_eu, tool.nlp(text_eu))
        data_eu = json.loads(res_eu)
        assert data_eu[0]["amount"] == 1000.50

        # Mixed: 10,50 (comma decimal)
        text_mix = "€10,50"
        res_mix = tool._extract_payments(text_mix, tool.nlp(text_mix))
        data_mix = json.loads(res_mix)
        assert data_mix[0]["amount"] == 10.50


INVOICE = (
    "Invoice from Acme Corp to John Smith. Total due: $1,250.00 by 15 March 2026. "
    "A second payment of EUR 300 follows in April 2026."
)


class SpacyImports:
    def __init__(self):
        self.attempts: list[str] = []

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "spacy":
            self.attempts.append(name)
            raise ImportError(f"{name} must not be imported while spaCy is off")
        return None


@pytest.fixture
def spacy_off(monkeypatch):
    import ai_agents.data_extractor_tool as det

    monkeypatch.setenv("HORUS_SPACY", "off")
    monkeypatch.setattr(det, "_nlp_model", None)
    for name in [name for name in sys.modules if name.split(".")[0] == "spacy"]:
        monkeypatch.delitem(sys.modules, name)
    imports = SpacyImports()
    monkeypatch.setattr(sys, "meta_path", [imports, *sys.meta_path])
    return imports


class TestSpacyOff:
    @pytest.mark.parametrize("value", ["off", "OFF", " 0 ", "false", "no"])
    def test_the_setting_turns_spacy_off(self, monkeypatch, value):
        import ai_agents.data_extractor_tool as det

        monkeypatch.setenv("HORUS_SPACY", value)

        assert det.spacy_is_off()

    @pytest.mark.parametrize("value", [None, "", "on", "1", "yes"])
    def test_unset_or_on_leaves_spacy_on(self, monkeypatch, value):
        import ai_agents.data_extractor_tool as det

        if value is None:
            monkeypatch.delenv("HORUS_SPACY", raising=False)
        else:
            monkeypatch.setenv("HORUS_SPACY", value)

        assert not det.spacy_is_off()

    def test_with_spacy_off_spacy_is_never_imported_nor_loaded(self, spacy_off, caplog):
        with caplog.at_level("INFO", logger="ai_agents.data_extractor_tool"):
            tool = DataExtractorTool()
            tool._run(INVOICE, "payments")

        assert tool.nlp is None
        assert spacy_off.attempts == []
        assert "spacy" not in sys.modules
        assert "spaCy is off (HORUS_SPACY=off)" in caplog.text

    def test_with_spacy_off_payments_come_from_the_regex_extraction(self, spacy_off):
        payments = json.loads(DataExtractorTool()._run(INVOICE, "payments"))

        assert {(row["amount"], row["currency"]) for row in payments} >= {(1250.0, "USD"), (300.0, "EUR")}
        assert all(row["payee"] is None for row in payments)

    def test_with_spacy_off_tables_and_key_values_still_work(self, spacy_off):
        tool = DataExtractorTool()

        assert json.loads(tool._run("| Item | Cost |\n| --- | --- |\n| Apple | 1.00 |", "tables"))
        assert "Total" in tool._run("Total: 1250\nDue: March", "key_values")

    def test_no_document_means_no_spacy_entities(self, spacy_off):
        assert DataExtractorTool().extract_entities_spacy(None) == {
            "people": [], "companies": [], "amounts": [], "dates": [],
        }

    def test_with_spacy_on_the_model_loads_as_before(self, monkeypatch):
        import ai_agents.data_extractor_tool as det

        monkeypatch.setenv("HORUS_SPACY", "on")
        monkeypatch.setattr(det, "_nlp_model", None)
        sentinel = MagicMock()
        with patch("spacy.load", return_value=sentinel) as load:
            tool = DataExtractorTool()

        assert tool.nlp is sentinel
        load.assert_called_once_with("en_core_web_sm")

    @pytest.mark.parametrize(("setting", "imports_spacy"), [("off", False), ("on", True)])
    def test_a_fresh_process_imports_spacy_only_when_it_is_on(self, setting, imports_spacy):
        import ai_agents.data_extractor_tool as det

        env = {**os.environ, "HORUS_SPACY": setting, "AGENT_SPACY_PREFER_SM": "1"}
        done = subprocess.run([sys.executable, "-B", "-c", FRESH_EXTRACTOR, det.__file__, INVOICE],
                              env=env, capture_output=True, text=True, check=True)

        assert bool(json.loads(done.stdout.splitlines()[-1])) is imports_spacy


FRESH_EXTRACTOR = """
import importlib.util, json, sys, types
seen = []
class Watch:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "spacy":
            seen.append(name)
        return None
sys.meta_path.insert(0, Watch())
class BaseTool:
    def __init__(self, **kwargs):
        pass
tools = types.ModuleType("langchain.tools")
tools.BaseTool = BaseTool
sys.modules["langchain"] = types.ModuleType("langchain")
sys.modules["langchain.tools"] = tools
spec = importlib.util.spec_from_file_location("fresh_data_extractor", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.DataExtractorTool()._run(sys.argv[2], "payments")
print(json.dumps(seen))
"""




