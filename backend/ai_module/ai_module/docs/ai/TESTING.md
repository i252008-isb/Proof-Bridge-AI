# Testing — ProofBridge AI

## Running the tests

```bash
cd ai_module
python -m pytest tests/ -q
```

No paid APIs, no internet, no API keys required: the suite uses the
deterministic mock providers and scripted fakes (`tests/_fakes.py`).
Each test runs in an isolated environment (conftest scrubs
`PROOFBRIDGE_*` variables and clears provider caches).

**Current results: `238 passed, 3 skipped`** (skips: OCR tests requiring
Tesseract, which is not installed in this environment — install it per
OCR_SETUP.md to run them).

## Suite layout

| File | Coverage |
| --- | --- |
| `test_ticket_analyzer.py` | Claim extraction: unverified labeling, backend claims verbatim, LLM date verification, heuristic fallback |
| `test_evidence_extractor.py` | Evidence processing: summaries, facts, warnings, category inference |
| `test_document_extractor.py` | PDF/DOCX/TXT extraction, normalization, limits |
| `test_ocr_service.py` | OCR availability + extraction (skipped without Tesseract) |
| `test_vision_analyzer.py` | Mock labeling, unreadable images, provider failure, comparison mode, tiny images |
| `test_product_analyzer.py` | Receipt fact extraction (only values present in the document) |
| `test_conversation_analyzer.py` | Chat parsing, speakers, refund promises |
| `test_policy_extractor.py` | Rule extraction, verbatim quote verification, heuristic fallback |
| `test_policy_evaluator.py` | Return window, damage rules, proof requirements, statuses, missing information |
| `test_similarity_engine.py` | Embedding + lexical relevance, zero-score filtering |
| `test_cross_source_verifier.py` | Field consistency, factual contradictions, receipt confirmation gaps |
| `test_support_case_analyzer.py` | Full pipeline: recommendations, partial evidence, backend data verbatim, mock vision implication |
| `test_report_generator.py` | Report invariants, verbatim findings, timeline ordering, fallback report |
| `test_scenarios.py` | Scenario tests A–J (below) |
| `test_facade.py` | Facade surface: all public functions, settings binding, error isolation |

## Scenario tests A–J

| Scenario | Assertions |
| --- | --- |
| A. Damaged product + receipt + photo | Matching receipt + scripted vision observations → `refund_recommended`; report carries the recommendation |
| B. Missing receipt | `request_more_information`; missing information listed — the pipeline never guesses |
| C. Inconsistent order details | Ticket order vs receipt order → factual contradiction → `escalate_to_human`; claim `contradicted` |
| D. Policy not supplied | `insufficient_policy_information`; evaluation status `policy_not_provided` |
| E. Customer/seller conversation | Conversation analyzed with both speakers; report copies it verbatim |
| F. Late complaint vs policy window | Purchase 300+ days old → `refund_not_supported_by_provided_policy`; reasoning explicitly says "not a definitive rejection" |
| G. Vision unavailable | Provider failure → limitation; the investigation continues and the report is still produced |
| H. Unreadable image | Broken upload isolated (`evt-broken` limitation); the receipt still processes |
| I. Conflicting dates | Ticket vs receipt purchase date → `purchase_date` contradiction, factually worded |
| J. Unrelated evidence | No claim supported; claims stay `unverified`/`insufficient_evidence` |

## Offline demo check

```bash
PROOFBRIDGE_DEMO_MODE=true python examples/run_demo.py
```

Runs all nine stages visibly (fixtures, OCR, ticket, evidence, vision,
policy, similarity, pipeline, report) plus a clearly labeled DEMO
SIMULATION of the genuine-vision happy path. See DEMO_GUIDE.md.
