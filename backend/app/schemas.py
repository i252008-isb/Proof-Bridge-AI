from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator
)

from proofbridge_ai.schemas import InvestigationReport, SupportCaseAnalysisResult


# ==================================================
# 1. USER REGISTRATION SCHEMA
# ==================================================

class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: Literal["freelancer", "client"]

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()

        if len(normalized) < 2:
            raise ValueError("Name must be at least 2 characters.")

        return normalized

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password cannot exceed 72 UTF-8 bytes.")

        if not value.strip():
            raise ValueError("Password cannot be only whitespace.")

        return value


# ==================================================
# 2. USER RESPONSE SCHEMA
# ==================================================

class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==================================================
# 3. USER LOGIN SCHEMA
# ==================================================

class UserLogin(BaseModel):
    email: EmailStr
    password: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


# ==================================================
# 4. JWT TOKEN RESPONSE SCHEMA
# ==================================================

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


def validate_amount_str(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = str(value).strip()
    if not trimmed:
        return None
    try:
        d = Decimal(trimmed)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Amount must be a valid positive number.")
    if d <= 0:
        raise ValueError("Amount must be positive.")
    parts = trimmed.split(".")
    if len(parts) == 2 and len(parts[1]) > 2:
        raise ValueError("Amount can have at most 2 decimal places.")
    return f"{d:.2f}"


def validate_currency_str(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = str(value).strip().upper()
    if len(trimmed) != 3 or not trimmed.isalpha():
        raise ValueError("Currency must be a 3-letter code.")
    return trimmed


# ==================================================
# 5. PROJECT CREATION SCHEMA
# ==================================================

class ProjectCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    freelancer_id: int = Field(gt=0)
    amount: str | None = None
    currency: str | None = "USD"

    model_config = ConfigDict(extra="forbid")

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()

        if len(normalized) < 3:
            raise ValueError("Title must be at least 3 characters.")

        return normalized

    @field_validator("amount")
    @classmethod
    def check_amount(cls, value: str | None) -> str | None:
        return validate_amount_str(value)

    @field_validator("currency")
    @classmethod
    def check_currency(cls, value: str | None) -> str:
        return validate_currency_str(value) or "USD"


# ==================================================
# 6. PROJECT UPDATE SCHEMA
# ==================================================

class ProjectUpdate(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=3,
        max_length=255
    )
    description: str | None = Field(default=None, max_length=5000)
    amount: str | None = None
    currency: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()

        if len(normalized) < 3:
            raise ValueError("Title must be at least 3 characters.")

        return normalized

    @field_validator("amount")
    @classmethod
    def check_amount(cls, value: str | None) -> str | None:
        return validate_amount_str(value)

    @field_validator("currency")
    @classmethod
    def check_currency(cls, value: str | None) -> str | None:
        return validate_currency_str(value)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")

        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("Title cannot be null.")

        return self


# ==================================================
# 7. PROJECT RESPONSE SCHEMA
# ==================================================

class ProjectResponse(BaseModel):
    id: int
    title: str
    description: str | None
    status: str
    freelancer_id: int
    client_id: int
    agreement_name: str | None
    amount: str | None = None
    currency: str = "USD"
    paypal_order_id: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==================================================
# 8. PROJECT STATUS SCHEMAS
# ==================================================

class ProjectStatusUpdate(BaseModel):
    status: Literal[
        "created",
        "in_progress",
        "under_review",
        "completed",
        "cancelled"
    ]
    note: str | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra="forbid")


class ProjectStatusEntry(BaseModel):
    status: str
    note: str | None
    changed_by: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectStatusResponse(BaseModel):
    project_id: int
    status: str
    history: list[ProjectStatusEntry]


# ==================================================
# 9. REQUIREMENT SCHEMAS
# ==================================================

class RequirementCreate(BaseModel):
    text: str = Field(
        min_length=10,
        max_length=2000,
        description=(
            "Specific, testable requirement suitable for "
            "comparison against delivered evidence."
        )
    )
    category: str | None = Field(default=None, max_length=100)
    source_quote: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()

        if len(normalized) < 10:
            raise ValueError("Requirement text must be at least 10 characters.")

        return normalized

    @field_validator("category", "source_quote")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return value.strip() or None


class RequirementUpdate(BaseModel):
    text: str | None = Field(
        default=None,
        min_length=10,
        max_length=2000
    )
    category: str | None = Field(default=None, max_length=100)
    source_quote: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()

        if len(normalized) < 10:
            raise ValueError("Requirement text must be at least 10 characters.")

        return normalized

    @field_validator("category", "source_quote")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return value.strip() or None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")

        if "text" in self.model_fields_set and self.text is None:
            raise ValueError("Requirement text cannot be null.")

        return self


class RequirementResponse(BaseModel):
    id: int
    project_id: int
    text: str
    category: str | None
    source_quote: str | None

    model_config = ConfigDict(from_attributes=True)


# ==================================================
# 10. AGREEMENT SCHEMAS
# ==================================================

class AgreementResponse(BaseModel):
    project_id: int
    agreement_name: str
    mime_type: str
    size_bytes: int
    replaced_existing: bool


# ==================================================
# 11. EVIDENCE SCHEMAS
# ==================================================

class EvidenceResponse(BaseModel):
    id: int
    project_id: int
    uploaded_by: int
    filename: str
    mime_type: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==================================================
# 12. AI ANALYSIS SCHEMAS
# ==================================================

class AnalysisInputSummary(BaseModel):
    requirement_ids: list[int] = Field(default_factory=list)
    evidence_ids: list[int] = Field(default_factory=list)
    skipped_evidence_ids: list[int] = Field(default_factory=list)
    evidence_files_processed: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="forbid")


class RequirementFinding(BaseModel):
    """One project requirement compared against the uploaded evidence.

    The values mirror Person 3's ``ClaimAssessment`` for the requirement;
    they are not recalculated or inferred by the backend.
    """

    requirement_id: int
    requirement_text: str
    status: Literal[
        "supported",
        "partially_supported",
        "contradicted",
        "unverified",
        "insufficient_evidence",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    supporting_evidence_ids: list[int] = Field(default_factory=list)
    contradicting_evidence_ids: list[int] = Field(default_factory=list)
    cited_evidence_ids: list[int] = Field(default_factory=list)
    analysis_method: str
    source_kind: str
    requires_human_review: bool

    model_config = ConfigDict(extra="forbid")


class RequirementComparisonSummary(BaseModel):
    """Deterministic grouping of the AI's actual requirement findings."""

    verified_requirement_ids: list[int] = Field(default_factory=list)
    supported_requirement_ids: list[int] = Field(default_factory=list)
    partially_supported_requirement_ids: list[int] = Field(
        default_factory=list
    )
    unverified_requirement_ids: list[int] = Field(default_factory=list)
    insufficient_evidence_requirement_ids: list[int] = Field(
        default_factory=list
    )
    contradicted_requirement_ids: list[int] = Field(default_factory=list)
    missing_evidence_requirement_ids: list[int] = Field(
        default_factory=list
    )
    uncertain_requirement_ids: list[int] = Field(default_factory=list)
    human_attention_requirement_ids: list[int] = Field(
        default_factory=list
    )
    evidence_needing_attention_ids: list[int] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ProjectAnalysisContent(BaseModel):
    """Validated envelope stored in ``Report.content``.

    The nested ``analysis`` and ``report`` objects are Person 3's own
    Pydantic models, so a stored report can never contain values that the
    AI module's schema would reject.
    """

    kind: Literal["project_ai_analysis"] = "project_ai_analysis"
    schema_version: str = "1.1"
    status: Literal["completed", "completed_with_warnings"] = "completed"
    project_id: int
    case_id: str
    generated_at: datetime
    ai_package_version: str
    human_review_required: bool
    final_decision_notice: str
    provider_modes: dict[str, str]
    external_processing: bool
    input_fingerprint: str = ""
    input_summary: AnalysisInputSummary
    integration_warnings: list[str] = Field(default_factory=list)
    requirement_findings: list[RequirementFinding] = Field(
        default_factory=list
    )
    comparison: RequirementComparisonSummary = Field(
        default_factory=RequirementComparisonSummary
    )
    analysis_result_ids: list[int] = Field(default_factory=list)
    analysis: SupportCaseAnalysisResult
    report: InvestigationReport

    model_config = ConfigDict(extra="forbid")


class ProjectAnalysisResponse(ProjectAnalysisContent):
    report_id: int
    created_at: datetime


class AnalysisHistoryItem(BaseModel):
    """Compact history entry; full output is available per report ID."""

    report_id: int
    project_id: int
    case_id: str
    status: Literal["completed", "completed_with_warnings"] = "completed"
    generated_at: datetime
    created_at: datetime
    ai_package_version: str
    human_review_required: bool
    input_fingerprint: str = ""
    requirement_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    analysis_result_count: int = Field(default=0, ge=0)
    supported_requirement_count: int = Field(default=0, ge=0)
    human_attention_requirement_count: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="forbid")


class AnalysisHistoryResponse(BaseModel):
    items: list[AnalysisHistoryItem] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


# ==================================================
# 13. PROJECT REPORT SCHEMAS
# ==================================================

REPORT_ADVISORY_NOTICE = (
    "AI observations in this report are advisory only. A human reviewer "
    "makes the final case decision. ProofBridge does not hold, move, "
    "release, or refund money and does not control PayPal funds."
)

MONEY_CONTROL_NOTICE = (
    "PayPal is an external payment provider. ProofBridge only retrieves "
    "and stores transaction information that PayPal returns. Stored "
    "transaction data does not mean ProofBridge holds, controls, or can "
    "move those funds."
)


class ReportProjectInfo(BaseModel):
    project_id: int
    title: str
    description: str | None
    status: str
    client_id: int
    freelancer_id: int
    created_at: datetime

    model_config = ConfigDict(extra="forbid")


class ReportEvidenceReference(BaseModel):
    evidence_id: int
    filename: str
    kind: str
    status: str
    summary: str = ""
    needs_attention: bool = False
    extraction_warning_codes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ReportObservedValue(BaseModel):
    value: str
    source: str
    evidence_id: int | None = None

    model_config = ConfigDict(extra="forbid")


class ReportInconsistency(BaseModel):
    id: str
    field: str
    description: str
    evidence_ids: list[int] = Field(default_factory=list)
    observed_values: list[ReportObservedValue] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ReportMissingInformation(BaseModel):
    id: str
    description: str
    recommended_evidence: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ReportRequirementFinding(BaseModel):
    requirement_id: int
    requirement_text: str
    status: Literal[
        "supported",
        "partially_supported",
        "contradicted",
        "unverified",
        "insufficient_evidence",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    supporting_evidence_ids: list[int] = Field(default_factory=list)
    contradicting_evidence_ids: list[int] = Field(default_factory=list)
    cited_evidence_ids: list[int] = Field(default_factory=list)
    missing_evidence: bool
    uncertain: bool
    requires_human_review: bool
    human_review_reason: str | None = None

    model_config = ConfigDict(extra="forbid")


class ReportHumanReviewRecommendation(BaseModel):
    requirement_id: int
    status: str
    reason: str

    model_config = ConfigDict(extra="forbid")


class ProjectReportContent(BaseModel):
    """Stored investigation report derived from one persisted AI snapshot.

    Human review decisions and notes live only in the reviewer-only review
    endpoints; this report contains AI findings and review recommendations
    only.
    """

    kind: Literal["project_investigation_report"] = (
        "project_investigation_report"
    )
    schema_version: str = "1.0"
    status: Literal["completed", "completed_with_warnings"]
    project: ReportProjectInfo
    analysis_report_id: int
    analysis_generated_at: datetime
    ai_package_version: str
    generated_at: datetime
    human_review_required: bool
    final_decision_notice: str
    advisory_notice: str = REPORT_ADVISORY_NOTICE
    requirement_findings: list[ReportRequirementFinding] = Field(
        default_factory=list
    )
    evidence_inventory: list[ReportEvidenceReference] = Field(
        default_factory=list
    )
    missing_information: list[ReportMissingInformation] = Field(
        default_factory=list
    )
    inconsistencies: list[ReportInconsistency] = Field(
        default_factory=list
    )
    uncertain_requirement_ids: list[int] = Field(default_factory=list)
    contradicted_requirement_ids: list[int] = Field(default_factory=list)
    missing_evidence_requirement_ids: list[int] = Field(
        default_factory=list
    )
    human_review_recommendations: list[
        ReportHumanReviewRecommendation
    ] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ProjectReportResponse(ProjectReportContent):
    report_id: int
    created_at: datetime


class ProjectReportSummary(BaseModel):
    report_id: int
    project_id: int
    status: Literal["completed", "completed_with_warnings"]
    generated_at: datetime
    created_at: datetime
    analysis_report_id: int
    ai_package_version: str
    requirement_count: int = Field(default=0, ge=0)
    missing_evidence_count: int = Field(default=0, ge=0)
    contradiction_count: int = Field(default=0, ge=0)
    human_attention_count: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="forbid")


class ProjectReportListResponse(BaseModel):
    items: list[ProjectReportSummary] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


# ==================================================
# 14. HUMAN REVIEW SCHEMAS
# ==================================================

HumanReviewDecision = Literal[
    "verified",
    "partially_verified",
    "rejected",
    "needs_more_evidence",
]


class HumanReviewCreate(BaseModel):
    decision: HumanReviewDecision
    notes: str = Field(min_length=10, max_length=5000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str) -> str:
        normalized = value.strip()

        if len(normalized) < 10:
            raise ValueError("Review notes must be at least 10 characters.")

        return normalized


class HumanReviewResponse(BaseModel):
    id: int
    project_id: int
    reviewer_id: int
    decision: str
    notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HumanReviewSubmissionResponse(BaseModel):
    review: HumanReviewResponse
    project_status: str

    model_config = ConfigDict(extra="forbid")


class HumanReviewHistoryResponse(BaseModel):
    project_id: int
    items: list[HumanReviewResponse] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="forbid")


class PendingReviewItem(BaseModel):
    project_id: int
    title: str
    status: str
    latest_analysis_report_id: int
    analysis_generated_at: datetime
    requirement_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    human_attention_requirement_count: int = Field(default=0, ge=0)
    project_created_at: datetime

    model_config = ConfigDict(extra="forbid")


class PendingReviewListResponse(BaseModel):
    items: list[PendingReviewItem] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="forbid")


class ReviewContextResponse(BaseModel):
    project: ProjectResponse
    latest_analysis: ProjectAnalysisResponse
    evidence: list[EvidenceResponse] = Field(default_factory=list)
    status_history: list[ProjectStatusEntry] = Field(default_factory=list)
    reviews: list[HumanReviewResponse] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


# ==================================================
# 15. CASE HISTORY SCHEMAS
# ==================================================

class CaseTimelineEvent(BaseModel):
    event_type: Literal["status", "analysis", "report", "human_review"]
    occurred_at: datetime
    actor_id: int | None = None
    summary: str
    status: str | None = None
    reference_id: int | None = None

    model_config = ConfigDict(extra="forbid")


class CaseHistoryResponse(BaseModel):
    project_id: int
    current_status: str
    events: list[CaseTimelineEvent] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


# ==================================================
# 16. PAYPAL SCHEMAS
# ==================================================

class PayPalSyncRequest(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=255)

    model_config = ConfigDict(extra="forbid")

    @field_validator("transaction_id")
    @classmethod
    def normalize_transaction_id(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("transaction_id must not be empty.")

        return normalized


class PayPalOrderSyncRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=255)

    model_config = ConfigDict(extra="forbid")

    @field_validator("order_id")
    @classmethod
    def normalize_order_id(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("order_id must not be empty.")

        return normalized


class PayPalTransactionResponse(BaseModel):
    id: int
    project_id: int
    paypal_transaction_id: str
    amount: float
    currency: str
    status: str
    raw_data: dict | None
    created_at: datetime
    information_type: Literal["capture", "order"] | None = None
    intent: str | None = None
    payment_state: str | None = None
    authorization_id: str | None = None
    authorization_status: str | None = None
    capture_id: str | None = None
    case_reference: str | None = None
    provider: Literal["paypal"] = "paypal"
    money_control_notice: str = MONEY_CONTROL_NOTICE

    model_config = ConfigDict(from_attributes=True)


class PayPalSyncResponse(BaseModel):
    transaction: PayPalTransactionResponse
    created: bool

    model_config = ConfigDict(extra="forbid")


class PayPalStatusResponse(BaseModel):
    configured: bool
    environment: Literal["sandbox", "live"]
    lookup_mode: Literal["read_only_transaction_information"] = (
        "read_only_transaction_information"
    )
    money_control_notice: str = MONEY_CONTROL_NOTICE

    model_config = ConfigDict(extra="forbid")


# ==================================================
# 17. HEALTH SCHEMAS
# ==================================================

class HealthResponse(BaseModel):
    status: str
    app: str
    version: str


class DatabaseHealth(BaseModel):
    status: str
    database: str
    latency_ms: float
    missing_tables: list[str] = Field(default_factory=list)


# ==================================================
# 18. GENERIC MESSAGE SCHEMA
# ==================================================

class MessageResponse(BaseModel):
    message: str


# ==================================================
# 19. PAYMENT SCHEMAS
# ==================================================

class PaymentCreateResponse(BaseModel):
    order_id: str
    approval_link: str | None = None
    payment_state: str

    model_config = ConfigDict(extra="forbid")


class PaymentCaptureRequest(BaseModel):
    token: str | None = None

    model_config = ConfigDict(extra="forbid")


class PaymentCaptureResponse(BaseModel):
    order_id: str
    capture_id: str | None = None
    status: str
    payment_state: str
    amount: str | None = None
    currency: str = "USD"

    model_config = ConfigDict(extra="forbid")


class PaymentDetailResponse(BaseModel):
    payment_state: str
    amount: str | None = None
    currency: str = "USD"
    order_id: str | None = None
    capture_id: str | None = None

    model_config = ConfigDict(extra="forbid")
