"""FastAPI integration example for the ProofBridge AI module.

This file is a working reference for Person 2 (the backend developer). It
shows, end to end, how a FastAPI backend should call the AI module for the
customer-support & refund-investigation workflow:

    from proofbridge_ai.integration.facade import (
        extract_ticket_claims, extract_evidence, extract_evidence_batch,
        analyze_visual_evidence, extract_refund_policy,
        compare_support_evidence, analyze_support_case,
        arun_support_case_analysis, generate_investigation_report,
    )

Division of responsibilities (binding):

    BACKEND (this file)                          AI MODULE
    - owns file storage and the database         - never reads the DB
    - generates and persists all DB IDs          - never creates DB records
    - supplies the ticket, order data and        - never invents timestamps,
      upload timestamps                          order data, or policy text
    - saves every AI result and associates       - returns structured,
      it with the case                           validated Pydantic results
    - returns results to the frontend            - raises ProofBridgeAIError
    - NEVER auto-issues refunds; a human         subclasses on failure
      agent makes the final decision             - human_review_required
                                                 is always True

The repository below is an in-memory stand-in so this example runs as-is;
replace it with the real PostgreSQL repository.

Run it:  uvicorn examples.fastapi_integration:app --reload
Then:    http://127.0.0.1:8000/docs

Offline demo: set PROOFBRIDGE_DEMO_MODE=true to run with clearly labeled
mock providers (no API keys, no network).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from proofbridge_ai import (
    CaseContext,
    CaseEvent,
    EvidenceInput,
    EvidenceUpload,
    EvidenceCategory,
    OrderInformation,
    ProofBridgeAIError,
    RefundPolicy,
    SupportTicket,
)
from proofbridge_ai.integration.facade import (
    analyze_support_case,
    analyze_visual_evidence,
    extract_evidence,
    extract_refund_policy,
    extract_ticket_claims,
    generate_investigation_report,
)


# --------------------------------------------------------------------------
# Backend stand-in repository (replace with the real PostgreSQL repository)
# --------------------------------------------------------------------------


class InMemoryCaseRepository:
    """Stand-in for the backend database. The AI module never touches it."""

    def __init__(self) -> None:
        self._cases: dict[str, dict] = {}
        self._evidence_counters: dict[str, int] = {}

    def create_case(self, ticket: SupportTicket) -> None:
        now = datetime.now(timezone.utc)
        self._cases[ticket.case_id] = {
            "ticket": ticket,
            "case_context": CaseContext(
                case_id=ticket.case_id,
                title=f"Support case {ticket.case_id}",
                description=ticket.complaint,
                created_at=now,
                events=[
                    CaseEvent(
                        event_type="case_created",
                        description=f"Case {ticket.case_id} created",
                        timestamp=now,
                    )
                ],
            ),
            "claims_extraction": None,
            "evidence_items": [],
            "visual_results": [],
            "policy": None,
            "order_information": None,
            "reports": [],
        }

    def get(self, case_id: str) -> dict:
        if case_id not in self._cases:
            raise HTTPException(status_code=404, detail=f"Unknown case {case_id!r}")
        return self._cases[case_id]

    def next_evidence_id(self, case_id: str) -> str:
        self._evidence_counters[case_id] = self._evidence_counters.get(case_id, 0) + 1
        return f"EVD-{self._evidence_counters[case_id]:03d}"


REPOSITORY = InMemoryCaseRepository()


# --------------------------------------------------------------------------
# Error handling: every ProofBridgeAIError maps to an HTTP response
# --------------------------------------------------------------------------


_STATUS_BY_ERROR = {
    "InputValidationError": 400,
    "FileTooLargeError": 413,
    "UnsupportedFileTypeError": 415,
    "DocumentExtractionError": 422,
    "ProviderResponseValidationError": 502,
    "ProviderError": 502,
    "OCRNotAvailableError": 503,
    "ServiceNotImplementedError": 501,
    "ConfigurationError": 500,
    "AnalysisError": 500,
}


def create_app() -> FastAPI:
    app = FastAPI(title="ProofBridge AI — support case investigation example")

    @app.exception_handler(ProofBridgeAIError)
    async def handle_ai_error(request, exc: ProofBridgeAIError):
        status = _STATUS_BY_ERROR.get(type(exc).__name__, 500)
        return JSONResponse(
            status_code=status,
            content={
                "error_code": type(exc).__name__,
                "detail": str(exc),
            },
        )

    _register_routes(app)
    return app


# --------------------------------------------------------------------------
# Request bodies
# --------------------------------------------------------------------------


class TicketBody(BaseModel):
    case_id: str
    complaint: str
    product_name: str | None = None
    order_id: str | None = None
    requested_resolution: str | None = None
    purchase_date: datetime | None = None
    delivery_date: datetime | None = None
    seller_contacted: bool | None = None
    claims: list[dict] = []


class PolicyTextBody(BaseModel):
    policy_text: str
    policy_id: str | None = None
    policy_name: str | None = None


class OrderInformationBody(BaseModel):
    order_id: str
    product_name: str | None = None
    product_model: str | None = None
    seller_name: str | None = None
    purchase_date: datetime | None = None
    delivery_date: datetime | None = None
    price: float | None = None
    currency: str | None = None
    quantity: int | None = None
    status: str | None = None


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def _register_routes(app: FastAPI) -> None:
    @app.post("/cases/{case_id}")
    async def create_case(case_id: str, body: TicketBody):
        """Backend creates the case row (ticket) first; the AI module is
        not involved. Human-corrected ``claims`` supplied by the backend
        are preserved verbatim by the pipeline."""
        if body.case_id != case_id:
            raise HTTPException(status_code=400, detail="case_id mismatch")
        ticket = SupportTicket(
            case_id=body.case_id,
            complaint=body.complaint,
            product_name=body.product_name,
            order_id=body.order_id,
            requested_resolution=body.requested_resolution,
            purchase_date=body.purchase_date,
            delivery_date=body.delivery_date,
            seller_contacted=body.seller_contacted,
            claims=body.claims,
        )
        REPOSITORY.create_case(ticket)
        return {"case_id": case_id, "status": "created"}

    @app.post("/cases/{case_id}/ticket/claims")
    async def extract_case_claims(case_id: str):
        """Extract structured customer claims from the stored ticket.

        Optional: ``analyze_support_case`` runs this stage automatically.
        Exposed separately for frontends that want the claims early.
        """
        case = REPOSITORY.get(case_id)
        result = extract_ticket_claims(case["ticket"])
        # BACKEND: persist the extraction for the frontend.
        case["claims_extraction"] = result
        return result.model_dump(mode="json")

    @app.post("/cases/{case_id}/evidence")
    async def upload_evidence(
        case_id: str,
        upload: UploadFile = File(...),
        uploaded_by: str = Form(...),
        user_description: str = Form(""),
        category: str | None = Form(None),
        uploaded_at: str | None = Form(None),
    ):
        """Backend stores the file, generates the evidence ID, and hands
        the bytes to the AI module. Images additionally run through the
        vision service; a failing vision provider returns a structured
        limitation instead of aborting the upload."""
        case = REPOSITORY.get(case_id)
        file_bytes = await upload.read()
        # BACKEND: persist the raw bytes to your file storage here.
        evidence_input = EvidenceInput(
            evidence_id=REPOSITORY.next_evidence_id(case_id),
            filename=upload.filename or "evidence.bin",
            uploaded_by=uploaded_by,
            uploaded_at=datetime.fromisoformat(uploaded_at) if uploaded_at else None,
            user_description=user_description or None,
            category=EvidenceCategory(category) if category else None,
        )
        item = extract_evidence(file_bytes, evidence_input, upload.content_type)
        # BACKEND: save item (JSON) in the evidence table, associated with
        # the case, and return its ID to the frontend.
        case["evidence_items"].append(item)

        visual_result = None
        if upload.content_type and upload.content_type.startswith("image/"):
            visual_result = analyze_visual_evidence(
                file_bytes, evidence_input, upload.content_type
            )
            case["visual_results"].append(visual_result)

        return {
            "evidence_id": item.evidence_id,
            "kind": item.kind.value,
            "status": item.status.value,
            "summary": item.summary,
            "warnings": [w.code for w in item.extraction_warnings],
            "visual_status": (
                visual_result.status.value if visual_result else None
            ),
        }

    @app.post("/cases/{case_id}/policy")
    async def upload_policy(case_id: str, body: PolicyTextBody):
        """Parse a refund policy from backend-stored text (the backend can
        equally supply the raw policy file bytes to ``extract_refund_policy``
        via ``file_bytes=``)."""
        case = REPOSITORY.get(case_id)
        policy = extract_refund_policy(
            policy_text=body.policy_text,
            policy_id=body.policy_id or f"policy-{case_id}",
            policy_name=body.policy_name or "Refund Policy",
        )
        # BACKEND: persist the structured policy.
        case["policy"] = policy
        return {
            "policy_id": policy.policy_id,
            "rule_count": len(policy.rules),
            "warnings": [w.code for w in policy.policy_extraction_warnings],
        }

    @app.put("/cases/{case_id}/order-information")
    async def supply_order_information(case_id: str, body: OrderInformationBody):
        """Backend supplies authorized order-system data. The pipeline uses
        it verbatim and never overwrites it."""
        case = REPOSITORY.get(case_id)
        case["order_information"] = OrderInformation(**body.model_dump())
        return {"case_id": case_id, "status": "stored"}

    @app.post("/cases/{case_id}/analysis/run")
    async def run_analysis(case_id: str):
        """Run the complete investigation and store the structured report.

        Backend supplies: the ticket, processed evidence items (with their
        DB IDs), the parsed policy (optional), order information (optional),
        and case context. A backend-supplied ``refund_policy`` (parsed
        earlier by a human or by this module) is passed as ``refund_policy=``
        and is never overwritten.
        """
        case = REPOSITORY.get(case_id)
        ticket: SupportTicket = case["ticket"]
        items = case["evidence_items"]
        policy: RefundPolicy | None = case["policy"]
        order_information: OrderInformation | None = case["order_information"]

        # BACKEND: retrieve the stored case context and evidence items
        # (with their DB IDs) before calling the pipeline. The pipeline
        # tolerates partial evidence: one unreadable upload produces a
        # warning, not a lost investigation.
        analysis = await analyze_support_case(
            ticket,
            items,
            refund_policy=policy,
            order_information=order_information,
            case_context=case["case_context"],
        )
        # BACKEND: persist the analysis (claims, contradictions, missing
        # information, policy evaluation, recommendation).
        report = generate_investigation_report(
            analysis, ticket, items, case_context=case["case_context"]
        )
        # BACKEND: save the report JSON in the reports table, associated
        # with the case, then return it to the frontend.
        case["reports"].append(report)
        return report.model_dump(mode="json")

    @app.get("/cases/{case_id}/report")
    async def latest_report(case_id: str):
        """Frontend-facing retrieval of the stored report.

        The frontend must display ``human_review_required`` and
        ``final_decision_notice``: the report is decision support for an
        authorized human support agent, never an automatic refund."""
        case = REPOSITORY.get(case_id)
        if not case["reports"]:
            raise HTTPException(status_code=404, detail="No report generated yet")
        return case["reports"][-1].model_dump(mode="json")


app = create_app()
