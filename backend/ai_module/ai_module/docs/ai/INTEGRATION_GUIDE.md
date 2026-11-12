# Integration Guide — ProofBridge AI (for Person 2)

The AI module is independent of the backend database: it never reads the
database, never creates records, never authenticates users, and never
moves money. The backend owns storage, IDs, timestamps, persistence, and
the final human decision.

## 1. Install

```bash
pip install -e "ai_module[ocr]"     # OCR extra optional (Tesseract)
```

## 2. Configure

Set `PROOFBRIDGE_*` env vars (see [CONFIGURATION.md](CONFIGURATION.md)).
`PROOFBRIDGE_DEMO_MODE=true` runs everything offline with labeled mocks.

## 3. Recommended flow

```python
import asyncio
from proofbridge_ai import (
    EvidenceInput, EvidenceUpload, SupportTicket,
    analyze_support_case, generate_investigation_report,
)

# (1) Backend builds the ticket from its case row.
ticket = SupportTicket(
    case_id=case.case_id,              # your DB ID
    complaint=case.complaint,
    product_name=case.product_name,
    order_id=case.order_id,
    requested_resolution=case.requested_resolution,
    purchase_date=case.purchase_date,  # backend/document values only
    claims=case.human_corrected_claims,  # optional; used verbatim
)

# (2) Backend stores each uploaded file, then hands bytes + metadata to
# the AI module for processing (extract_evidence / extract_evidence_batch).
upload = EvidenceUpload(
    file_bytes=raw_bytes,
    evidence_input=EvidenceInput(
        evidence_id=evidence_row.id,   # your DB ID
        filename=uploaded.filename,
        uploaded_by=case.actor,
        uploaded_at=uploaded.created_at,  # backend timestamp
        category=evidence_row.category,
    ),
    content_type=uploaded.content_type,
)

# (3) Run the complete investigation.
analysis = await analyze_support_case(
    ticket,
    [processed_evidence_items_or_uploads],
    refund_policy=stored_policy,        # optional; used verbatim
    order_information=order_row,        # optional; used verbatim
    case_context=case_context,
)

# (4) Generate the report and store the JSON in the reports table.
report = generate_investigation_report(analysis, ticket, evidence_items,
                                       case_context=case_context)
payload = report.model_dump(mode="json")   # JSON-serializable dict
```

## 4. Contract rules

- **IDs**: the backend generates and persists every DB ID; the AI module
  preserves the supplied `evidence_id` verbatim.
- **Timestamps**: the backend supplies `uploaded_at` and case events; the
  AI module never invents timestamps. Undated events stay undated.
- **Human-corrected data**: `ticket.claims` (and any backend-supplied
  `refund_policy` / `order_information`) are used verbatim and never
  silently overwritten.
- **Partial evidence**: one broken upload yields a warning; the rest of
  the investigation completes.
- **Serialization**: always `model_dump(mode="json")` before storing or
  returning to the frontend.
- **Display**: the frontend must show `human_review_required` and
  `final_decision_notice` from the report. The recommendation is decision
  support for an authorized human support agent — never an automatic
  refund.
- **PayPal**: transaction data may be supplied as `PaymentInformation`
  (informational evidence only). The AI module never calls PayPal APIs
  and never requests payment credentials.

## 5. Async notes

`analyze_support_case` / `arun_support_case_analysis` are coroutines —
await them inside FastAPI endpoints (they are non-blocking only at the
API level; provider HTTP calls are blocking under the hood, so call them
in the endpoint thread or via `run_in_threadpool` if you use sync
providers heavily). The rest of the surface is synchronous.

## 6. Reference implementation

`examples/fastapi_integration.py` is a complete, runnable FastAPI
example: in-memory case repository (replace with PostgreSQL), ticket
creation, claim extraction, evidence upload (with vision for images),
policy upload, order information, full analysis, and report retrieval —
including the error-to-HTTP mapping.
