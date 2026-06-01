"""LangChain tool that extracts structured data (payments, tables, key-value
pairs) from unstructured document text using regex and spaCy NER.

See ``docs/architecture.md`` for entity types and rules.
"""

import json
import logging
import re
from typing import Any

from langchain.tools import BaseTool

try:
    import spacy
    from spacy.lang.en.stop_words import STOP_WORDS
    _has_spacy = True
except ImportError:
    spacy = None
    STOP_WORDS = set()
    _has_spacy = False

_nlp_model = None

logger = logging.getLogger(__name__)

class DataExtractorTool(BaseTool):
    """Extract payments, dates, tables, and key-value pairs from raw text."""

    name: str = "document_data_extractor"
    description: str = (
        "Use this tool to extract structured data from document text. "
        "Supported extraction_types: 'payments', 'tables', 'key_values'."
    )

    nlp: Any = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        global _nlp_model

        # Check if we are in a testing environment
        import os
        import sys
        is_test = "pytest" in sys.modules or "unittest" in sys.modules or os.environ.get("TEST_MODE") == "true"

        if is_test:
             # Use a mock/dummy or explicitly 'sm' during tests to avoid heavy load
             logger.info("Test environment detected. Skipping 'trf' model load.")
             try:
                if _has_spacy and spacy:
                    _nlp_model = spacy.load("en_core_web_sm")
                else:
                    raise ImportError("Spacy missing")
             except (OSError, ImportError, AttributeError):
                from unittest.mock import MagicMock
                mock = MagicMock()
                mock.ents = []
                _nlp_model = lambda text: mock

        if _nlp_model is None:
            try:
                if not _has_spacy or not spacy:
                    raise ImportError("Spacy missing")
                prefer_sm = os.getenv("AGENT_SPACY_PREFER_SM", "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                )
                if prefer_sm:
                    logger.info("AGENT_SPACY_PREFER_SM: loading en_core_web_sm (lighter).")
                    _nlp_model = spacy.load("en_core_web_sm")
                else:
                    logger.info("Loading spacy model en_core_web_trf...")
                    _nlp_model = spacy.load("en_core_web_trf")
                    logger.info("Spacy model loaded successfully")
            except (OSError, ImportError):
                logger.warning("Spacy 'en_core_web_trf' not found. Trying 'en_core_web_sm'.")
                try:
                    _nlp_model = spacy.load("en_core_web_sm")
                except (OSError, ImportError):
                     logger.warning("No Spacy model found. Using dummy.")
                     from unittest.mock import MagicMock
                     mock = MagicMock()
                     mock.ents = []
                     _nlp_model = lambda text: mock

        self.nlp = _nlp_model


    def _run(self, text: str, extraction_type: str) -> str:
        """
        Main execution method for the tool. Routes to specific extraction logic.

        Args:
            text (str): The raw text content of the document.
            extraction_type (str): The type of extraction to perform. 
                                   Options: 'payments', 'tables', 'key_values'.

        Returns:
            str: JSON string containing the extracted data, or an error/status message.
        """
        logger.info(f"DataExtractorTool running with extraction_type='{extraction_type}'")

        # Determine if Spacy doc is needed
        doc = self.nlp(text)

        if extraction_type == "payments":
            res = self._extract_payments(text, doc)
            return res
        elif extraction_type == "tables":
            res = self._extract_tables(text)
            return res
        elif extraction_type == "key_values":
            res = self._extract_key_values(text)
            return res
        else:
            logger.warning(f"Unsupported extraction type: {extraction_type}")
            raise ValueError(f"Unsupported extraction type: {extraction_type}")

    def _arun(self, text: str, extraction_type: str) -> str:
        """Async execution is not supported."""
        raise NotImplementedError("Async extraction not implemented.")

    def extract_entities_regex(self, text: str) -> dict[str, list[str]]:
        """
        Extract entities like amounts and dates using regular expressions.

        Args:
            text (str): The text to search.

        Returns:
            Dict[str, List[str]]: Found 'amounts' and 'dates'.
        """
        regex_amounts = r"(?:\$|€|USD|EUR)\s?\d+(?:[.,]\d+)*|\d+(?:[.,]\d+)*\s?(?:\$|€|USD|EUR)"
        matches_amounts = re.findall(regex_amounts, text)

        # Comprehensive date patterns
        months = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December"
        patt_num = r"\b\d{4}[-/.]\d{2}[-/.]\d{2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b"
        patt_text = rf"\b(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{months})[,\s]+\d{{4}}|(?:{months})\s+\d{{1,2}}(?:st|nd|rd|th)?[,\s]+\d{{4}})\b"
        patt_month_year = rf"\b(?:{months})[,\s]+\d{{4}}\b"
        patt_no_year = rf"\b(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{months})|(?:{months})\s+\d{{1,2}}(?:st|nd|rd|th)?)\b"
        patt_year = r"\b(?:19|20)\d{2}\b"
        full_date_pattern = f"{patt_num}|{patt_text}|{patt_month_year}|{patt_no_year}|{patt_year}"

        matches_dates = re.findall(full_date_pattern, text, re.IGNORECASE)
        matches_dates = [d.strip() for d in matches_dates if d.strip()]

        logger.debug(f"Regex extracted {len(matches_amounts)} amounts and {len(matches_dates)} dates.")
        return {
            "amounts": matches_amounts,
            "dates": matches_dates,
        }

    def extract_entities_spacy(self, doc) -> dict[str, list[str]]:
        """
        Extract named entities using Spacy NER.

        Args:
            doc (spacy.tokens.Doc): The processed document.

        Returns:
            Dict[str, List[str]]: Found 'people', 'companies', 'amounts', 'dates'.
        """
        money = []
        dates = []
        people = []
        companies = []

        for ent in doc.ents:
            if ent.label_ == "PERSON":
                people.append(ent.text.strip())
            if ent.label_ == "ORG":
                companies.append(ent.text.strip())
            if ent.label_ == "MONEY":
                money.append(ent.text.strip())
            if ent.label_ == "DATE":
                dates.append(ent.text.strip())

        logger.debug(f"Spacy extraction summary: Money={len(money)}, Dates={len(dates)}, People={len(people)}, Org={len(companies)}")

        people = list(set(people))
        companies = list(set(companies))
        money = list(set(money))
        dates = list(set(dates))

        return {
            "people": people,
            "companies": companies,
            "amounts": money,
            "dates": dates,
        }

    def _extract_payments(self, text: str, doc) -> str:
        """
        Extracts payment information including amounts, currencies, estimated dates, and payees.
        Combines Regex and Spacy results.

        Args:
            text (str): Raw text.
            doc: Spacy doc object.

        Returns:
            str: JSON list of payment objects.
        """
        logger.info("Extracting payments...")

        payment_data = []

        # --- CSV Heuristic Scan ---
        try:
            lines = text.splitlines()
            for line in lines:
                line = line.strip()
                if not line: continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    currencies = ["USD", "EUR", "GBP", "CHF", "AUD", "CAD"]
                    found_currency = None
                    currency_idx = -1
                    for idx, part in enumerate(parts):
                        if part.upper() in currencies:
                            found_currency = part.upper()
                            currency_idx = idx
                            break

                    if found_currency:
                        candidates = []
                        for idx, part in enumerate(parts):
                            if idx == currency_idx: continue
                            clean = part.replace(" ", "")
                            try:
                                val = float(clean)
                                candidates.append((val, idx))
                            except ValueError:
                                pass

                        if candidates:
                            # Pick candidate closest to currency
                            best_candidate = candidates[0][0]
                            closest_dist = 999
                            for val, idx in candidates:
                                dist = abs(idx - currency_idx)
                                if dist < closest_dist:
                                    closest_dist = dist
                                    best_candidate = val

                            # Heuristics for Date and Payee
                            date_pattern = r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}"
                            possible_dates = []
                            possible_payees = []
                            for idx, part in enumerate(parts):
                                if idx == currency_idx: continue
                                try:
                                    if float(part.replace(" ", "")) == best_candidate: continue
                                except Exception: pass

                                if re.search(date_pattern, part):
                                    possible_dates.append(part)
                                    continue

                                if len(part) > 3 and not re.match(r"^\d+$", part):
                                    possible_payees.append(part)

                            est_date = possible_dates[0] if possible_dates else None
                            est_payee = possible_payees[-1] if possible_payees else None

                            payment_data.append({
                                "raw_value": str(best_candidate),
                                "amount": best_candidate,
                                "currency": found_currency,
                                "payee": est_payee,
                                "context": line,
                                "estimated_date": est_date
                            })
        except Exception as e:
            logger.warning(f"CSV scan failed: {e}")

        regex_entities = self.extract_entities_regex(text)
        spacy_entities = self.extract_entities_spacy(doc)

        all_dates = list(set(regex_entities.get("dates", []) + spacy_entities.get("dates", [])))
        all_amounts = list(set(regex_entities.get("amounts", []) + spacy_entities.get("amounts", [])))
        all_payees = list(set(spacy_entities.get("people", []) + spacy_entities.get("companies", [])))


        # payment_data initialized above

        for amount in all_amounts:
            # 1. Determine Currency
            currency = "Unknown"
            if "EUR" in amount or "€" in amount:
                currency = "EUR"
            if "$" in amount or "USD" in amount:
                currency = "USD"

            # 2. Clean amount to float
            cleaned = amount.replace("€", "")
            cleaned = cleaned.replace("$", "")
            cleaned = cleaned.replace("EUR", "")
            cleaned = cleaned.replace("USD", "")

            # Normalize European number format (1.000,00 -> 1000.00) if likely
            if "," in cleaned and "." in cleaned:
                if cleaned.find(",") < cleaned.find("."):
                    # US/UK format: 1,000.50 -> 1000.50
                    cleaned = cleaned.replace(",", "")
                else:
                     # EU format: 1.000,50 -> 1000.50
                     cleaned = cleaned.replace(".", "").replace(",", ".")
            elif "," in cleaned:
                 # Assume comma is decimal if no dots found? Or thousand separator?
                 # Heuristic: if comma is near end (2 chars), it is likely decimal
                 if len(cleaned) - cleaned.rfind(",") == 3:
                     # 10,50 -> 10.50
                     cleaned = cleaned.replace(",", ".")
                 else:
                     # 1,000 -> 1000
                     cleaned = cleaned.replace(",", "")

            cleaned_number = "".join(c for c in cleaned if c.isdigit() or c == '.')

            try:
                price = float(cleaned_number)
            except ValueError:
                continue

            # 3. Find Context
            position = text.find(amount)
            start_index = max(0, position - 50)
            end_index = min(len(text), position + 20)

            context = text[start_index:end_index]
            context = context.replace("\n", "").strip()

            # 4. Proximity Search for Date and Payee
            estimated_date = None
            estimated_person = None
            distance_date_ref = -1
            distance_person_ref = -1

            # Find closest date
            for date in all_dates:
                # Limit search scope for date (heuristic optimization could go here)
                date_pos = text.find(date)
                dist = abs(position - date_pos)

                if dist <= 100:
                    if distance_date_ref == -1 or dist < distance_date_ref:
                        estimated_date = date
                        distance_date_ref = dist

            # Find closest payee
            for person in all_payees:
                payee_pos = text.find(person)
                dist = abs(position - payee_pos)

                if dist <= 150:
                    if distance_person_ref == -1 or dist < distance_person_ref:
                        estimated_person = person
                        distance_person_ref = dist

            res = {
                "raw_value": amount,
                "amount": price,
                "currency": currency,
                "payee": estimated_person,
                "context": context,
                "estimated_date": estimated_date
            }
            payment_data.append(res)

        if payment_data:
            return json.dumps(payment_data, indent=2)
        else:
            return "No payments found"

    def parse_table(self, current_table: list[str]) -> dict:
        """
        Parses a list of text lines into a structured table (header + rows).

        Args:
            current_table (List[str]): List of strings representing lines of a potential table.

        Returns:
            Dict: {'header': List[str], 'content': List[List[str]]} or empty dict.
        """
        if not current_table:
            return {}

        parsed_table = []
        for line in current_table:
            # Simple split by pipe
            cells = line.split("|")

            # Clean cells
            clean_cells = []
            for cell in cells:
                cell = cell.strip()
                # Remove cells that are just delimiters like '---' or '___' or empty strings
                if not cell:
                    continue
                # Skip divider lines entirely if the whole cell is dashes
                if all(c in "-_" for c in cell):
                     continue

                clean_cells.append(cell)

            # Only add if we found valid data content
            if clean_cells:
                parsed_table.append(clean_cells)

        if not parsed_table:
            return {}

        # First line is header, rest is content
        return {
            "header": parsed_table[0],
            "content": parsed_table[1:]
        }

    def _extract_tables(self, text: str) -> str:
        """
        Extracts tables from text based on pipe delimiters.
        Optimized to avoid regex performance issues.

        Args:
            text (str): Raw text.

        Returns:
            str: JSON list of found tables.
        """
        logger.info("Extracting tables...")
        lines  = text.splitlines()
        tables = []
        current_table = []

        # Simple pipe detection instead of complex regex
        # table_pattern = re.compile(r"\s{2,}|\t|\s*\|\s*") # Cause of ReDoS

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Heuristic: Table rows usually have pipes
            if "|" in stripped:
                # Basic split by pipe
                clean_line = [c.strip() for c in stripped.split("|") if c.strip()]
                if len(clean_line) >= 2:
                    current_table.append(line)
                else:
                     # Not a valid table row
                     if current_table:
                        table = self.parse_table(current_table)
                        if table:
                            tables.append(table)
                        current_table = []
            else:
                # End of a table block
                if current_table:
                    table = self.parse_table(current_table)
                    if table:
                        tables.append(table)
                    current_table = []

        # Flush last block if exists
        if current_table:
            table = self.parse_table(current_table)
            if table:
                tables.append(table)

        if not tables:
            return "No tables found"

        return json.dumps(tables, indent=2)

    def _extract_key_values(self, text: str) -> str:
        """
        Extracts Key-Value pairs using simple regex line matching.
        Simplified to avoid catastrophic backtracking in complex lookaheads.

        Args:
            text (str): Raw text.

        Returns:
            str: JSON list of pairs found.
        """
        logger.info("Extracting key-value pairs...")
        lines  = text.splitlines()
        key_data = {}

        # Simpler pattern: Capture Key (at start or distinct) : Value (rest of line)
        # ^\s* -> Start of line with optional space
        # ([a-zA-Z0-9\-_ ]+) -> Key group
        # :\s* -> Colon separator
        # (.+) -> Value group (rest of line)
        pattern = r"^\s*([a-zA-Z0-9\-_ ]+):\s*(.+)$"

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Simple match per line first
            match = re.match(pattern, line)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()

                # Heuristics
                if len(key) < 50 and value and not key.lower().startswith("http"):
                    key_data[key] = value

        if not key_data:
            return "No key-value pairs found"

        return json.dumps(key_data, indent=2)
