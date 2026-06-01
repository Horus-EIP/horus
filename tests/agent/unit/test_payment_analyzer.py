import json

import pytest

from ai_agents.payment_analyzer_tool import PaymentAnalyzerTool


class TestPaymentAnalyzerTool:

    @pytest.fixture
    def tool(self):
        return PaymentAnalyzerTool()

    @pytest.fixture
    def sample_data(self):
        return [
            {"amount": 100.0, "currency": "EUR", "payee": "Alice", "context": "Services"},
            {"amount": 200.0, "currency": "EUR", "payee": "Bob", "context": "Goods"},
            {"amount": 50.0, "currency": "USD", "payee": "Alice", "context": "Refund"}
        ]

    @pytest.fixture
    def sample_data_json(self, sample_data):
        return json.dumps(sample_data)

    # --- Total Amount Tests ---

    def test_calculate_total(self, tool, sample_data):
        # 300 EUR, 50 USD
        result = tool._calculate_total(sample_data)
        assert "Total amount EUR: 300.0" in result
        assert "Total amount USD: 50.0" in result

    def test_calculate_total_mixed_types(self, tool):
        # amount as string, int, float
        data = [
            {"amount": "100.5", "currency": "EUR"},
            {"amount": 50, "currency": "EUR"},
            {"amount": 10.0, "currency": "EUR"}
        ]
        result = tool._calculate_total(data)
        # 160.5
        assert "Total amount EUR: 160.5" in result

    def test_calculate_total_invalid_values(self, tool):
        data = [
            {"amount": "invalid", "currency": "EUR"},
            {"amount": 100, "currency": "EUR"}
        ]
        result = tool._calculate_total(data)
        assert "Total amount EUR: 100" in result

    def test_calculate_total_no_currency(self, tool):
        data = [{"amount": 100}]
        # Currency falls back to UNKNOWN or skipped/logged?
        # In current implementation: if currency is empty, it assigns to OTHER or logs?
        # Let's check impl:
        # currency = element.get("currency", "UNKNOWN")
        # if currency == "EUR" ... elif "USD" ... else: try to log but might not add to total message if > 0
        # The logic only adds to message if total_EUR > 0 or total_USD > 0.
        # But wait, looking at my memory of `_calculate_total`:
        # `if not msg_parts: return "No valid EUR or USD amounts..."`
        result = tool._calculate_total(data)
        assert "No valid EUR or USD amounts found to calculate total." in result

    def test_empty_data_total(self, tool):
        result = tool._calculate_total([])
        assert "No data to calculate total" in result

    # --- Average Tests ---

    def test_calculate_average(self, tool, sample_data):
        # Avg EUR: 150, Avg USD: 50
        result = tool._calculate_average(sample_data)
        assert "Average EUR: 150.0" in result
        assert "Average USD: 50.0" in result

    def test_calculate_average_single(self, tool):
        data = [{"amount": 100, "currency": "EUR"}]
        result = tool._calculate_average(data)
        assert "Average EUR: 100.0" in result

    # --- Payee Breakdown Tests ---

    def test_payee_breakdown(self, tool, sample_data):
        result = tool._get_payee_breakdown(sample_data)
        data = json.loads(result)

        # Check Alice (EUR) -> Not present in sample, Alice is EUR and USD separately
        # Alice EUR: 100
        # Alice USD: 50
        # Bob EUR: 200

        assert data.get("Alice (EUR)") == 100.0
        assert data.get("Alice (USD)") == 50.0
        assert data.get("Bob (EUR)") == 200.0

    def test_payee_breakdown_missing_payee(self, tool):
        data = [
            {"amount": 100, "currency": "EUR", "context": "Server Hosting"},
            {"amount": 50, "currency": "EUR"} # No context, no payee
        ]
        result = tool._get_payee_breakdown(data)
        json_res = json.loads(result)

        assert json_res.get("Server Hosting (EUR)") == 100.0
        assert json_res.get("Unknown Payee (EUR)") == 50.0

    def test_payee_breakdown_accumulation(self, tool):
        data = [
            {"amount": 10, "currency": "EUR", "payee": "Alice"},
            {"amount": 20, "currency": "EUR", "payee": "Alice"}
        ]
        result = tool._get_payee_breakdown(data)
        json_res = json.loads(result)
        assert json_res.get("Alice (EUR)") == 30.0

    # --- Forecast Tests ---

    def test_forecast(self, tool, sample_data):
        # Total EUR 300 -> +10% = 330
        # Total USD 50 -> +10% = 55
        result = tool._predict_next_month(sample_data)
        assert "330.0 EUR" in result
        assert "55.0 USD" in result

    def test_forecast_empty(self, tool):
        result = tool._predict_next_month([])
        assert "No data to calculate forecast" in result

    # --- Integration / Runner Tests ---

    def test_run_integration(self, tool, sample_data_json):
        result = tool._run(sample_data_json, "total")
        assert "Total amount EUR: 300.0" in result

    def test_invalid_json_input(self, tool):
        with pytest.raises(ValueError) as excinfo:
            tool._run("invalid json", "total")
        assert "Invalid JSON format" in str(excinfo.value)

    def test_non_list_input(self, tool):
        with pytest.raises(ValueError) as excinfo:
            tool._run("{}", "total")
        assert "Input payment data must be a JSON list" in str(excinfo.value)

    def test_invalid_analysis_type(self, tool, sample_data_json):
        with pytest.raises(ValueError) as excinfo:
            tool._run(sample_data_json, "magic_predict")
        assert "Invalid analysis type" in str(excinfo.value)

    def test_arun_not_implemented(self, tool):
        with pytest.raises(NotImplementedError):
            tool._arun("data", "total")

    def test_calculate_total_other_currency(self, tool):
        """Test that unknown currencies are ignored/logged but don't crash."""
        data = [{"amount": 100, "currency": "GBP"}]
        result = tool._calculate_total(data)
        # Should result in "No valid EUR or USD amounts..." or empty total parts
        assert "No valid EUR or USD amounts found" in result

    def test_calculate_average_malformed_values(self, tool):
        """Test skipping bad values in average calculation."""
        data = [
            {"amount": "not_a_number", "currency": "EUR"},
            {"amount": 100, "currency": "EUR"}
        ]
        result = tool._calculate_average(data)
        assert "Average EUR: 100.0" in result

