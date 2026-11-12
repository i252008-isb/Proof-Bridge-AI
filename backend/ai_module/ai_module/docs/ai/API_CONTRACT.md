# API Contract — ProofBridge AI

The stable integration surface for the backend. These signatures are
documented and consistent; the module-level functions are thin re-exports
of the service functions, so the contract can never drift from the
implementation. All functions accept an optional `settings=None` override;
omit it to use the process configuration (`PROOFBRIDGE_*` env vars).

Everything imported from `proofbridge_ai` (package root) or from
`proofbridge_ai.integration.facade`. All errors derive from
`ProofBridgeAIError`. All results are Pydantic models; serialize them with
`result.model_dump(mode="json")`.

## Public functions

### extract_document

```python
def extract_document(
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
    settings: Settings | None = None,
) -> DocumentExtractionResult
```

Extracts text from PDF, DOCX, TXT/markdown, or an image (OCR). Returns
`DocumentExtractionResult` with `extracted_text`, `normalized_text`,
per-page detail (PDF), `extraction_method`, `is_ocr_used`, and
`warnings`. Raises `InputValidationError`, `FileTooLargeError`,
`UnsupportedFileTypeError`, `DocumentExtractionError`,
`OCRNotAvailableError` (image input without Tesseract).

Convenience: `extract_document_text(...) -> str` returns only the text.

### extract_ticket_claims

```python
def extract_ticket_claims(
    ticket: SupportTicket,
    settings: Settings | None = None,
    llm: BaseLLMProvider | None = None,
) -> TicketAnalysisResult
```

Analyzes the complaint and extracts structured customer claims. Claims
extracted from the complaint are always
`verification_status="unverified"` with `source="customer_ticket"` — the
ticket is an allegation, never a verified fact. Backend-supplied
human-corrected claims (`ticket.claims`) are used **verbatim** and never
overwritten.

### extract_evidence

```python
def extract_evidence(
    file_bytes: bytes,
    evidence_input: EvidenceInput,
    content_type: str | None = None,
    settings: Settings | None = None,
) -> EvidenceItem
```

Processes one uploaded evidence file into an `EvidenceItem`: text
extraction (OCR for images), normalization, summary, deterministic facts.
`evidence_id`, filename, `uploaded_by`, `source`, and `uploaded_at` are
preserved exactly as supplied. Raises the same errors as
`extract_document` plus `ConfigurationError`.

### extract_evidence_batch

```python
def extract_evidence_batch(
    uploads: list[EvidenceUpload],
    settings: Settings | None = None,
) -> EvidenceBatchResult
```

Batch processing with per-item error isolation: one broken upload never
aborts the batch. Successes land in `.items`, failures in `.failures`
(`evidence_id`, `filename`, `error_type`, `message`).

### analyze_visual_evidence

```python
def analyze_visual_evidence(
    file_bytes: bytes,
    evidence_input: EvidenceInput,
    content_type: str | None = None,
    reference_file_bytes: bytes | None = None,
    reference_evidence_input: EvidenceInput | None = None,
    settings: Settings | None = None,
    vision: BaseVisionProvider | None = None,
) -> VisualAnalysisResult
```

Visual inspection of one product photograph, optionally against a
reference image (product listing) — then `analysis_type` is
`"image_comparison"`. Honest degradation: unreadable image or provider
failure returns `status="failed"` with a structured limitation (never an
exception); the mock provider returns `status="mock"` with no fabricated
observations. Vision and OCR are strictly separate services.

### extract_refund_policy

```python
def extract_refund_policy(
    policy_text: str | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    policy_id: str = "policy-1",
    policy_name: str = "Refund Policy",
    settings: Settings | None = None,
    llm: BaseLLMProvider | None = None,
) -> RefundPolicy
```

Extracts structured policy rules. Exactly one source: raw `policy_text`
or document `file_bytes` (PDF/DOCX/TXT; screenshots via OCR). Every rule
carries a verbatim `source_quote`; quotes that cannot be verified against
the source text are dropped with a warning — nothing is invented. Empty
or unreadable policies yield a policy with zero rules plus a warning.

### compare_support_evidence

```python
def compare_support_evidence(
    claims: Sequence[CustomerClaim],
    evidence_items: Sequence[EvidenceItem],
    settings: Settings | None = None,
    embeddings: BaseEmbeddingsProvider | None = None,
) -> ClaimSimilarityResult
```

Scores every claim against every evidence item for **relevance only**.
A high score means the evidence appears relevant — never that the claim
is true. With a real embeddings provider the method is `"embeddings"`;
otherwise a deterministic lexical approximation is used and labeled
(`limitations`). Zero scores are filtered; per claim the top
`similarity_max_candidates` are kept.

### analyze_support_case

```python
async def analyze_support_case(
    support_ticket: SupportTicket,
    evidence_items: Sequence[EvidenceItem | EvidenceUpload],
    refund_policy: RefundPolicy | None = None,
    order_information: OrderInformation | None = None,
    case_context: CaseContext | None = None,
    settings: Settings | None = None,
) -> SupportCaseAnalysisResult
```

The complete investigation (15 pipeline steps: validate ticket, extract
claims, process evidence, OCR, vision, purchase details, conversations,
policy, cross-source comparison, contradictions, missing information,
policy evaluation, recommendation, validated result). `evidence_items`
accepts processed `EvidenceItem`s and/or raw `EvidenceUpload`s mixed.
Backend-supplied data (corrected claims, order information, supplied
policy) is used verbatim and never silently overwritten. Partial evidence
tolerance: one unreadable upload produces a warning, never a lost
investigation. Returns `SupportCaseAnalysisResult` with
`requires_human_review=True`.

`async def arun_support_case_analysis(...)` is an alias with the same
signature (kept for compatibility with the documented name).

### generate_investigation_report

```python
def generate_investigation_report(
    analysis: SupportCaseAnalysisResult,
    support_ticket: SupportTicket,
    evidence_items: Sequence[EvidenceItem] = (),
    order_information: OrderInformation | None = None,
    payment_information: PaymentInformation | None = None,
    case_context: CaseContext | None = None,
    settings: Settings | None = None,
) -> InvestigationReport
```

Builds the structured `InvestigationReport` from the analysis result.
Findings are copied verbatim — the report never edits them. The timeline
uses only supplied timestamps (ticket dates, evidence `uploaded_at`,
backend case events); undated events are listed after dated ones.
`human_review_required` is always True and `final_decision_notice` is
always set. If generation fails on unexpected data, a deterministic
fallback report is returned that preserves the underlying findings
(flagged in `limitations`).

## Facade class

```python
from proofbridge_ai import ProofBridgeAIFacade, get_facade

facade = get_facade()                    # cached, current settings
facade = ProofBridgeAIFacade(settings)   # or with custom settings
await facade.analyze_support_case(ticket, evidence)
facade.generate_investigation_report(analysis, ticket, evidence)
```

Same operations as the module-level functions with the settings bound at
construction (no `settings` parameter on methods).

## Error mapping (for FastAPI)

| Exception | HTTP |
| --- | --- |
| `InputValidationError` | 400 |
| `FileTooLargeError` | 413 |
| `UnsupportedFileTypeError` | 415 |
| `DocumentExtractionError` | 422 |
| `ServiceNotImplementedError` | 501 |
| `ProviderError`, `ProviderResponseValidationError` | 502 |
| `OCRNotAvailableError` | 503 |
| `ConfigurationError`, `AnalysisError` | 500 |

Reference implementation: `examples/fastapi_integration.py`.

## JSON example (minimal round trip)

```python
import asyncio
from proofbridge_ai import (
    EvidenceInput, EvidenceUpload, SupportTicket,
    analyze_support_case, generate_investigation_report,
)

ticket = SupportTicket(
    case_id="C-1",
    complaint="My order ORD-1 arrived damaged: cracked left ear cup.",
    order_id="ORD-1",
    requested_resolution="refund",
)
upload = EvidenceUpload(
    file_bytes=b"Receipt\nOrder #ORD-1\nDate: October 1, 2026\nTotal: $49.99",
    evidence_input=EvidenceInput(evidence_id="EVD-1", filename="receipt.txt"),
)

analysis = asyncio.run(analyze_support_case(ticket, [upload]))
report = generate_investigation_report(analysis, ticket, [])
payload = report.model_dump(mode="json")   # JSON-serializable dict for the DB/frontend
```

The returned dict contains `human_review_required: true` and
`final_decision_notice` — display both to the support agent.
