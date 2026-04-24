# Data Extraction Tool

`DataExtractorTool` (in `src/services/agent/app/ai_agents/data_extractor_tool.py`)
is a LangChain `BaseTool` that pulls structured information out of raw
document text. It is the tool behind `extract_data(...)` in the ReAct
loop and the core of the "payment analysis" feature.

Extraction runs in two passes: a fast deterministic regex sweep, then an
optional spaCy NER pass to catch entities the regexes miss. When spaCy
is not installed or the environment is `TEST_MODE=true`, the tool falls
back to regex-only so tests stay fast.

---

## 1. Supported extraction types

The tool accepts an `extraction_type` parameter:

| Type | What it extracts | Typical use |
|------|------------------|-------------|
| `payments` | Currency amounts, dates, vendor names, invoice numbers | Invoice and receipt analysis |
| `tables` | Row/column structures from whitespace-aligned or pipe-aligned text | PDF tables, markdown tables |
| `key_values` | `Key: value` and `Key = value` pairs with inferred types | Metadata blocks, config dumps |

Each return value is a dict with `entities: List[dict]` and a summary
`counts` dict, plus a `source_span` pointer for every entity that is
large enough to be worth highlighting.

## 2. Regex rules

The regex pass uses a small, auditable set of patterns:

- **Currency**: `(?P<currency>[€$£¥])\s?(?P<amount>[\d,]+(?:\.\d{1,2})?)` —
  handles `€ 1,234.56`, `$1234.5`, `£100`. Post-processed to normalize
  thousand separators and decimals to a canonical `Decimal`.
- **Dates**: ISO (`2026-04-24`), European (`24/04/2026`), and long-form
  (`24 April 2026`) dates. The parser records the *style* so downstream
  code can disambiguate ambiguous cases (`04/05/2026`).
- **Invoice numbers**: `INV[-\s]?\d{3,}`, `#\d{4,}` — only emitted when
  found near a currency or date token, to cut false positives.
- **Table rows**: lines with ≥2 runs of whitespace separating alphanumeric
  tokens. Headers are inferred from the first row if every cell is a
  word and no cell is numeric.

## 3. spaCy NER pass

When `spacy` is importable and the environment is not `TEST_MODE`, the
tool loads the `en_core_web_sm` model on first use (warm-started with
`spacy.load`) and runs NER on the input text. Entity labels are mapped
to Horus categories:

| spaCy label | Horus category |
|-------------|----------------|
| `ORG` | `vendor` |
| `DATE` | `date` |
| `MONEY` | `payment` |
| `PERSON` | `party` |
| `GPE` | `location` |

Entities produced by both passes are deduplicated by `(text, span)` pair;
when they disagree, the regex pass wins (deterministic results are more
useful than NER guesses for audits).

## 4. Test-mode handling

Loading `en_core_web_sm` adds ~1 s to tool construction. When Horus
runs under pytest or with `TEST_MODE=true`, the tool:

1. Tries to load `en_core_web_sm` but falls back to an empty `spaCy`
   blank model if not installed.
2. Skips the `trf` (transformer) variant even if installed, to keep
   GPU usage out of CI.
3. Caches the model at module scope (`_nlp_model`) so subsequent
   instantiations are free.

## 5. Why this design

- **Regex first** — deterministic, auditable, and fast. For financial
  data, "the same input always produces the same output" matters more
  than catching edge cases.
- **NER as a safety net** — regexes miss vendor names and organization
  mentions; spaCy catches them with reasonable recall.
- **No LLM in the extraction path** — avoids hallucinated amounts on
  invoices. The LLM only sees extracted structured data, never raw OCR.
- **Stop-word aware** — uses spaCy's English stop-word list to filter
  noise tokens before the NER pass, which halves false positives in
  long documents.

## 6. Known limitations

- Tables with merged cells are split on the first row only — multi-row
  headers are not reconstructed.
- Currency detection does not convert between currencies. Downstream
  code must apply exchange rates if needed.
- Dates in mixed styles (`01/02/2026` vs `2026-02-01`) within the same
  document are surfaced separately; the tool does not try to pick one.
- Non-English NER is not supported in the default configuration.
- Very large documents (>200 KB) are chunked before spaCy processing;
  entities spanning chunk boundaries may be missed.

## 7. Related code

- `src/services/agent/app/ai_agents/data_extractor_tool.py` — the tool
- `src/services/agent/app/ai_agents/react_agent.py` — calls it via `extract_data`
- `src/services/agent/app/tests/test_data_extractor_tool.py` — regex and NER tests
