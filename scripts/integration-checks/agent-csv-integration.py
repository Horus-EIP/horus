
import json

from ai_agents.data_extractor_tool import DataExtractorTool
from ai_agents.file_parser_tool import FileParserTool


class TestReviewIntegration:
    """
    Integration tests focusing on the combined usage of tools 
    for the semester review demonstration.
    """

    def test_csv_payment_extraction_pipeline(self):
        """
        Verify that we can parse a CSV file containing payment info
        and then extract those payments as structured data.
        """
        # 1. Simulate CSV Content
        # Format: Date, Description, Amount, Currency, Payee
        csv_content = (
            "date,description,amount,currency,payee\n"
            "2023-01-15,Consulting Services,1500.00,USD,Acme Corp\n"
            "2023-02-01,Office Supplies,200.50,EUR,Staples Inc\n"
            "2023-03-10,Software License,99.99,USD,Adobe\n"
        ).encode("utf-8")

        # 2. File Parser Step
        file_parser = FileParserTool()
        parsed_text = file_parser.run({
            "file_content": csv_content,
            "filename": "expenses.csv"
        })

        assert "1500.00" in parsed_text
        assert "Acme Corp" in parsed_text

        # 3. Data Extraction Step
        data_extractor = DataExtractorTool()
        # We assume the extracted text from CSV is fed into the data extractor
        # processing tables or raw text.

        # The parser joins CSV rows with ", " and newlines.
        # "2023-01-15, Consulting Services, 1500.00, USD, Acme Corp"

        extracted_json = data_extractor._run(parsed_text, extraction_type="payments")
        payments = json.loads(extracted_json)

        # 4. Assertions
        assert isinstance(payments, list)
        assert len(payments) >= 3

        # Validate specific entries
        # Note: DataExtractor might normalize or extract slightly differently depending on implementation
        # We look for amounts and currencies primarily

        # Check for 1500.00 USD
        found_acme = False
        for p in payments:
            if p.get("amount") == 1500.0 and p.get("currency") == "USD":
                found_acme = True
                # Bonus if it extracts content/payee if logic permits,
                # but base extraction is often date/amount/currency

        assert found_acme, "Did not find the 1500.00 USD payment from CSV data"

        # Check for 200.50 EUR
        found_staples = False
        for p in payments:
            if p.get("amount") == 200.5 and p.get("currency") == "EUR":
                found_staples = True

        assert found_staples, "Did not find the 200.50 EUR payment from CSV data"
