# Handoff Checklist — ProofBridge AI (for Person 2)

## What the AI module now does

ProofBridge AI is now an **AI-powered customer support & refund
investigation system**. The previous freelancer/dispute functionality was
replaced by: ticket claim extraction, evidence processing (receipts,
chats, listings, delivery records), OCR, vision inspection of product
photographs, refund policy extraction and evaluation, cross-source
verification, a recommendation engine, and a structured investigation
report. Generic infrastructure (providers, extraction layer, config,
logging, error hierarchy) was preserved.

## Integration checklist

1. **Install**: `pip install -e "ai_module[ocr]"` (OCR optional).
2. **Configure** `PROOFBRIDGE_*` env vars (`.env.example`).
3. **Import surface**: everything from `proofbridge_ai` —
   `analyze_support_case`, `arun_support_case_analysis`,
   `generate_investigation_report`, `extract_document`,
   `extract_ticket_claims`, `extract_evidence`, `extract_evidence_batch`,
   `analyze_visual_evidence`, `extract_refund_policy`,
   `compare_support_evidence`, plus `ProofBridgeAIFacade`/`get_facade`.
4. **Save uploads in your storage**, then hand bytes + metadata
   (`EvidenceUpload`/`EvidenceInput`) to the AI module. You generate and
   persist every DB ID.
5. **Supply order information** when authorized and available
   (`OrderInformation`) — used verbatim.
6. **Supply the refund policy** (`RefundPolicy`) when available — used
   verbatim; otherwise the pipeline can extract one from a
   `return_policy` evidence upload.
7. **Run** `await analyze_support_case(ticket, evidence, ...)` and
   `generate_investigation_report(...)`; store
   `report.model_dump(mode="json")` in your reports table.
8. **Display** `human_review_required` and `final_decision_notice` to
   the support agent. The AI recommendation is decision support — a
   human makes the final decision. Never auto-refund.
9. **Handle errors** with the mapping in ERROR_HANDLING.md (reference
   handler in `examples/fastapi_integration.py`).
10. **Preserve warnings** (`extraction_warnings` etc.) in storage and
    display — they record mock usage, fallbacks, and dropped
    unverifiable values.

## Message for Person 2

> The AI module is ready for backend integration. It now implements the
> full customer-support investigation workflow. Import everything from
> `proofbridge_ai` (see docs/ai/API_CONTRACT.md for the exact signatures)
> or use the `ProofBridgeAIFacade`. The flow you need:
>
> 1. Build a `SupportTicket` from your case row (case_id, complaint, and
>    any human-corrected claims — those are used verbatim, never
>    overwritten).
> 2. For each uploaded file, persist the raw bytes in your storage, then
>    call `extract_evidence(file_bytes, EvidenceInput(...))` (or the
>    batch variant) and store the returned `EvidenceItem`. For images you
>    can additionally call `analyze_visual_evidence(...)`; the main
>    pipeline also runs vision automatically.
> 3. When you have order-system data, pass it as `OrderInformation`; when
>    you have a policy, pass a `RefundPolicy` (from
>    `extract_refund_policy` or assembled by you).
> 4. Call `await analyze_support_case(ticket, evidence_items,
>    refund_policy=..., order_information=..., case_context=...)`, then
>    `generate_investigation_report(analysis, ticket, evidence_items,
>    case_context=...)`, and store
>    `report.model_dump(mode="json")` in your database.
> 5. Return the report JSON to the frontend and make sure it displays
>    `human_review_required` and `final_decision_notice`: the AI
>    investigates, a human support agent decides.
>
> Guarantees: partial evidence never loses the investigation (failed
> items become warnings); backend-supplied data is never silently
> overwritten; timestamps are never invented; mock/AI-fallback output is
> always labeled; all errors derive from `ProofBridgeAIError` (mapping
> table in docs/ai/ERROR_HANDLING.md; working FastAPI example in
> `examples/fastapi_integration.py`). The module never touches your
> database, never moves money, and never calls PayPal APIs.

## Self-check for Person 2

- [ ] All AI calls go through the documented public functions.
- [ ] Every AI result is persisted and associated with the case.
- [ ] `human_review_required` / `final_decision_notice` reach the UI.
- [ ] No automatic refund path exists in the backend.
- [ ] Uploaded files are validated before storage (size/type).
- [ ] Warnings and limitations are visible to support agents.
