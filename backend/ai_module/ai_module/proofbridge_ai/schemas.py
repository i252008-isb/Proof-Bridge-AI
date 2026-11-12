"""Pydantic models and enums defining the public data contract of ProofBridge AI.

Central principle: customers submit the proof, ProofBridge AI investigates the
proof, human support agents make the final decisions. The data contract enforces
that principle:

- Every customer statement is an allegation until independently supported:
  extracted claims always start with ``VerificationStatus.UNVERIFIED`` and a
  ``source`` label (``customer_ticket``, ``receipt``, ...).
- Every observation is traceable to an evidence item or policy passage
  (``source_quote`` verified verbatim by the extraction services).
- Vision and OCR are separate: OCR extracts readable text, vision interprets
  visual content, and mock vision output is always labeled as mock.
- Every report carries ``human_review_required=True`` and a final-decision
  notice. The system never issues, rejects, or transfers payments.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

CENTRAL_PRINCIPLE = (
    "Customers submit the proof. ProofBridge AI investigates the proof. "
    "Human support agents make the final decisions."
)

FINAL_DECISION_NOTICE = (
    "This is an AI-generated investigation recommendation. "
    "An authorized human support agent must make the final decision."
)

REPORT_TITLE = "ProofBridge AI — Customer Support Case Investigation Report"

REPORT_SCHEMA_VERSION = "2.0"

EXTRACTION_SCHEMA_VERSION = "2.0"


# ------------------------------------------------------------------ enums


class IssueType(str, Enum):
    """Customer complaint categories the ticket analyzer understands."""

    DAMAGED_PRODUCT = "damaged_product"
    DEFECTIVE_PRODUCT = "defective_product"
    WRONG_PRODUCT_RECEIVED = "wrong_product_received"
    MISSING_ITEM = "missing_item"
    PRODUCT_NOT_AS_DESCRIBED = "product_not_as_described"
    MISSING_ACCESSORIES = "missing_accessories"
    INCORRECT_ORDER = "incorrect_order"
    DELIVERY_COMPLAINT = "delivery_complaint"
    LATE_DELIVERY = "late_delivery"
    OTHER = "other"


class VerificationStatus(str, Enum):
    """How a customer claim or cross-source field stands against the evidence.

    ``supported`` means the available evidence independently supports the
    claim; ``unverified`` means no independent evidence addresses it yet;
    ``insufficient_evidence`` means evidence exists but is not enough;
    ``contradicted`` means sources disagree — it never proves dishonesty,
    only an inconsistency that needs human attention.
    """

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EvidenceInventoryStatus(str, Enum):
    """Processing state of one evidence item in the case inventory."""

    COLLECTED = "collected"
    PROCESSING = "processing"
    PROCESSED = "processed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class EvidenceCategory(str, Enum):
    """Customer-support evidence categories (backend labels or inferred)."""

    PURCHASE_RECORD = "purchase_record"
    ORDER_RECORD = "order_record"
    PRODUCT_IMAGE = "product_image"
    PRODUCT_LISTING = "product_listing"
    CONVERSATION = "conversation"
    DELIVERY_RECORD = "delivery_record"
    RETURN_POLICY = "return_policy"
    OTHER = "other"


class RecommendationOutcome(str, Enum):
    """Possible investigation outcomes.

    ``refund_not_supported_by_provided_policy`` is never a definitive
    rejection or a final customer decision — it only means the available
    evidence does not establish eligibility under the supplied policy.
    """

    REFUND_RECOMMENDED = "refund_recommended"
    REQUEST_MORE_INFORMATION = "request_more_information"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    REFUND_NOT_SUPPORTED_BY_PROVIDED_POLICY = "refund_not_supported_by_provided_policy"
    ALTERNATIVE_RESOLUTION_SUGGESTED = "alternative_resolution_suggested"
    INSUFFICIENT_POLICY_INFORMATION = "insufficient_policy_information"


class PolicyEvaluationStatus(str, Enum):
    """Outcome of comparing the case against the supplied refund policy."""

    POLICY_NOT_PROVIDED = "policy_not_provided"
    POLICY_REQUIRES_HUMAN_INTERPRETATION = "policy_requires_human_interpretation"
    EVALUATED = "evaluated"


class PolicyRuleCategory(str, Enum):
    """Kinds of refund-policy conditions the extractor understands."""

    ELIGIBLE_REASON = "eligible_reason"
    RETURN_WINDOW = "return_window"
    DEFECTIVE_PRODUCT = "defective_product"
    DAMAGED_ON_ARRIVAL = "damaged_on_arrival"
    PROOF_REQUIREMENT = "proof_requirement"
    PACKAGING_REQUIREMENT = "packaging_requirement"
    REPLACEMENT_OPTION = "replacement_option"
    REPAIR_OPTION = "repair_option"
    REFUND_EXCEPTION = "refund_exception"
    WARRANTY = "warranty"
    OTHER = "other"


class RuleAssessment(str, Enum):
    """Whether the case satisfies one policy rule."""

    MET = "met"
    PARTIALLY_MET = "partially_met"
    NOT_MET = "not_met"
    NOT_ASSESSABLE = "not_assessable"


class ImageQuality(str, Enum):
    """Usability of an uploaded photograph for visual inspection."""

    SUFFICIENT = "sufficient"
    UNCLEAR = "unclear"
    PRODUCT_NOT_VISIBLE = "product_not_visible"


class VisualIssueType(str, Enum):
    """Visually observable issues vision analysis can report.

    Only observable irregularities — never hidden defects, authenticity, or
    the cause/timing of damage.
    """

    VISIBLE_PHYSICAL_DAMAGE = "visible_physical_damage"
    CRACK = "crack"
    BROKEN_COMPONENT = "broken_component"
    SCRATCH = "scratch"
    MISSING_VISIBLE_PART = "missing_visible_part"
    DEFORMATION = "deformation"
    COLOR_DIFFERENCE = "color_difference"
    APPEARANCE_DIFFERENCE = "appearance_difference"
    OTHER_IRREGULARITY = "other_irregularity"


class VisionStatus(str, Enum):
    """How the visual analysis was produced — honest labeling required."""

    ANALYZED = "analyzed"
    MOCK = "mock"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class ConversationSpeaker(str, Enum):
    CUSTOMER = "customer"
    SELLER = "seller"
    SUPPORT_AGENT = "support_agent"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class EvidenceKind(str, Enum):
    IMAGE = "image"
    PDF = "pdf"
    DOCX = "docx"
    TEXT = "text"
    SOURCE_CODE = "source_code"
    OTHER = "other"


class FileType(str, Enum):
    """File formats the extraction layer understands."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MARKDOWN = "markdown"
    CSV = "csv"
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
    SOURCE_CODE = "source_code"
    OTHER = "other"


class AnalysisSource(str, Enum):
    """Whether a result came from an LLM or a deterministic heuristic."""

    LLM = "llm"
    HEURISTIC = "heuristic"


class SimilarityMethod(str, Enum):
    """How a similarity score was computed.

    ``embeddings`` means real (or mock) embedding vectors were compared.
    ``lexical`` means a lightweight lexical heuristic (token overlap) was
    used and must never be presented as semantic analysis.
    """

    EMBEDDINGS = "embeddings"
    LEXICAL = "lexical"


# ------------------------------------------------------------ shared models


class ExtractionWarning(BaseModel):
    """A non-fatal limitation encountered during extraction, OCR, or vision."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str
    message: str
    page_number: int | None = None


class SourceSummary(BaseModel):
    """Honest labeling of how much of an analysis came from each source."""

    model_config = ConfigDict(extra="forbid")

    llm_count: int = Field(default=0, ge=0)
    heuristic_count: int = Field(default=0, ge=0)


# ------------------------------------------------------------ ticket models


class CustomerClaim(BaseModel):
    """One statement extracted from the customer complaint.

    Claims start ``UNVERIFIED`` with ``source="customer_ticket"``: they are
    allegations until independent evidence supports them. ``source`` is a
    verbatim label of the originating document/party (e.g. ``customer_ticket``,
    ``receipt``, ``seller_conversation``).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    claim: str
    source: str = "customer_ticket"
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class SupportTicket(BaseModel):
    """Backend-supplied customer support ticket.

    All fields except ``case_id`` and ``complaint`` are optional and
    preserved verbatim. ``purchase_date``/``delivery_date`` are backend or
    document values — never invented by the AI module. The backend may
    supply human-corrected ``claims``; when present they are used verbatim
    and are never overwritten.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str
    complaint: str
    product_name: str | None = None
    order_id: str | None = None
    purchase_date: datetime | None = None
    delivery_date: datetime | None = None
    requested_resolution: str = ""
    issue_description: str = ""
    seller_contacted: bool | None = None
    customer_supplied_evidence_ids: list[str] = Field(default_factory=list)
    claims: list[CustomerClaim] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class TicketAnalysisResult(BaseModel):
    """Output of ticket understanding: issue type plus extracted claims.

    ``requires_human_review`` is always True and every extracted claim is
    unverified until evidence comparison.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = EXTRACTION_SCHEMA_VERSION
    case_id: str
    issue_type: IssueType = IssueType.OTHER
    product_name: str | None = None
    customer_claim_summary: str = ""
    requested_resolution: str = ""
    seller_contacted: bool | None = None
    purchase_date_mentioned: datetime | None = None
    delivery_date_mentioned: datetime | None = None
    extracted_claims: list[CustomerClaim] = Field(default_factory=list)
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    requires_human_review: bool = True
    source: AnalysisSource = AnalysisSource.HEURISTIC
    provider_name: str = "none"


# --------------------------------------------------- order / payment models


class OrderInformation(BaseModel):
    """Backend-supplied order details (from the order system, when available).

    Every field is optional: values that the backend does not have stay
    None — nothing is invented. Used verbatim by the pipeline.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    order_id: str
    product_name: str | None = None
    product_model: str | None = None
    seller_name: str | None = None
    purchase_date: datetime | None = None
    delivery_date: datetime | None = None
    price: float | None = None
    currency: str | None = None
    quantity: int | None = Field(default=None, ge=0)
    status: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class PaymentInformation(BaseModel):
    """Payment-provider transaction info (e.g. PayPal) supplied by the backend.

    Used strictly as an additional evidence source for consistency checks.
    The AI module never calls payment APIs and never authorizes, captures,
    or refunds payments.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    transaction_id: str
    order_id: str | None = None
    amount: float | None = None
    currency: str | None = None
    status: str | None = None
    timestamp: datetime | None = None
    merchant: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class PurchaseInformation(BaseModel):
    """Purchase facts extracted from one receipt/invoice/order document.

    Every field is None when the document does not state it — absent
    information is never invented. ``evidence_id`` traces the facts to the
    source document.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str
    seller_name: str | None = None
    product_name: str | None = None
    product_model: str | None = None
    order_number: str | None = None
    purchase_date: datetime | None = None
    price: float | None = None
    currency: str | None = None
    quantity: int | None = Field(default=None, ge=0)
    extraction_warnings: list[ExtractionWarning] = Field(default_factory=list)


# ------------------------------------------------------- conversation models


class ConversationMessage(BaseModel):
    """One message from a chat export.

    ``timestamp`` preserves the original text form (when present) — chat
    exports use many formats and nothing is parsed into an invented
    datetime. ``speaker`` keeps the customer/seller distinction.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    speaker: ConversationSpeaker = ConversationSpeaker.UNKNOWN
    message: str
    timestamp: str | None = None
    source_reference: str | None = None


class ConversationAnalysis(BaseModel):
    """Structured analysis of a seller/customer conversation export.

    Customer statements are never treated as verified facts merely because
    they appear in the chat. ``contradictions`` describe inconsistent
    statements factually — they never accuse anyone of dishonesty.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str
    messages: list[ConversationMessage] = Field(default_factory=list)
    customer_statements: list[str] = Field(default_factory=list)
    seller_statements: list[str] = Field(default_factory=list)
    refund_promises: list[str] = Field(default_factory=list)
    acknowledgements: list[str] = Field(default_factory=list)
    reported_complaint_dates: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    source: AnalysisSource = AnalysisSource.HEURISTIC
    provider_name: str = "none"
    requires_human_review: bool = True


# ------------------------------------------------------------- policy models


class PolicyRule(BaseModel):
    """One refund-policy condition, traceable to the policy text.

    ``source_quote`` must be verbatim text from the supplied policy
    (verified by the extractor, never invented by the LLM).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rule_id: str
    condition: str
    category: PolicyRuleCategory = PolicyRuleCategory.OTHER
    source_quote: str | None = None
    source_reference: str | None = None
    requires_evidence: bool = False


class RefundPolicy(BaseModel):
    """Structured refund/return policy supplied to the system.

    Either extracted from a document by ``extract_refund_policy`` or
    assembled by the backend. Never invented when no policy is supplied.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    policy_id: str
    policy_name: str = "Refund Policy"
    rules: list[PolicyRule] = Field(default_factory=list)
    policy_extraction_warnings: list[ExtractionWarning] = Field(default_factory=list)
    source: AnalysisSource = AnalysisSource.HEURISTIC
    provider_name: str = "none"


class PolicyRuleAssessment(BaseModel):
    """Assessment of one policy rule against the case evidence."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rule_id: str
    condition: str
    category: PolicyRuleCategory = PolicyRuleCategory.OTHER
    assessment: RuleAssessment = RuleAssessment.NOT_ASSESSABLE
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str = ""
    source_quote: str | None = None


class PolicyEvaluationResult(BaseModel):
    """Outcome of evaluating the case against the supplied policy.

    ``status`` distinguishes no-policy, ambiguous-policy, and evaluated
    cases. Explanations trace every conclusion back to policy passages and
    evidence IDs. This is decision support, never a legally binding ruling.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    policy_id: str | None = None
    policy_name: str | None = None
    status: PolicyEvaluationStatus = PolicyEvaluationStatus.POLICY_NOT_PROVIDED
    rule_assessments: list[PolicyRuleAssessment] = Field(default_factory=list)
    unmet_conditions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    explanation: str = ""
    requires_human_review: bool = True


# -------------------------------------------------------------- vision models


class VisualObservation(BaseModel):
    """One visual observation with confidence.

    Confidence is an indicative quality estimate, not a probability of
    defect. Observations are grounded in the image they describe.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    observation: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    possible_issue: VisualIssueType | None = None


class VisualAnalysisResult(BaseModel):
    """Result of vision analysis over one product photograph (or a
    listing-vs-photo comparison when ``reference_evidence_id`` is set).

    ``status`` labels how the result was produced: ``analyzed`` (genuine
    vision model), ``mock`` (offline mock provider — never genuine model
    output), ``failed`` (provider unavailable/failed — no fabricated
    observations). ``limitations`` always notes that a photograph cannot
    establish when or how damage occurred.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str
    reference_evidence_id: str | None = None
    analysis_type: str = "visual_inspection"
    status: VisionStatus = VisionStatus.ANALYZED
    visual_observations: list[VisualObservation] = Field(default_factory=list)
    image_quality: ImageQuality = ImageQuality.SUFFICIENT
    possible_issues: list[VisualIssueType] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    requires_human_review: bool = True
    source: AnalysisSource = AnalysisSource.HEURISTIC
    provider_name: str = "none"


# ----------------------------------------------------------- evidence models


class EvidenceInput(BaseModel):
    """Backend-supplied description of one uploaded evidence item.

    ``evidence_id`` is an externally assigned identifier in whatever format
    the backend uses and is preserved verbatim. ``uploaded_at`` is optional:
    when the backend does not supply it, it stays None — timestamps are
    never invented.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str
    filename: str
    evidence_type: str | None = None
    category: EvidenceCategory | None = None
    source: str | None = None
    uploaded_by: str | None = None
    uploaded_at: datetime | None = None
    user_description: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class EvidenceUpload(BaseModel):
    """One evidence input plus its raw file bytes.

    The backend owns file storage; the AI module only receives the bytes it
    needs to process.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_input: EvidenceInput
    file_bytes: bytes
    content_type: str | None = None


class EvidenceBatchFailure(BaseModel):
    """A single evidence item that could not be processed in a batch."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str
    filename: str
    error_type: str
    message: str


class EvidenceItem(BaseModel):
    """One processed evidence item: provenance, extracted content, summary.

    The externally supplied evidence_id, filename, uploading party, source,
    and upload timestamp (when provided) are preserved verbatim.
    ``extraction_method``/``extraction_warnings`` record how the text was
    produced. ``status`` is the inventory status, kept separate from claim
    verification.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str
    filename: str
    kind: EvidenceKind
    status: EvidenceInventoryStatus = EvidenceInventoryStatus.PROCESSED
    evidence_type: str | None = None
    category: EvidenceCategory | None = None
    source: str | None = None
    uploaded_by: str | None = None
    uploaded_at: datetime | None = None
    user_description: str | None = None
    content_type: str | None = None
    extracted_text: str = ""
    summary: str = ""
    summary_source: AnalysisSource = AnalysisSource.HEURISTIC
    identified_facts: list[str] = Field(default_factory=list)
    related_claim_ids: list[str] = Field(default_factory=list)
    extraction_method: str = ""
    section_reference: str | None = None
    extraction_warnings: list[ExtractionWarning] = Field(default_factory=list)
    ocr_applied: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class EvidenceBatchResult(BaseModel):
    """Result of processing multiple evidence uploads.

    Failures are isolated per item: one broken upload never aborts the batch.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    items: list[EvidenceItem] = Field(default_factory=list)
    failures: list[EvidenceBatchFailure] = Field(default_factory=list)


# --------------------------------------------------------- document models


class ExtractedPage(BaseModel):
    """Text of one document page, with page reference preserved."""

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    text: str = ""
    is_empty: bool = False
    ocr_used: bool = False


class DocumentExtractionResult(BaseModel):
    """Structured result of extracting text from one uploaded document."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    filename: str
    file_type: FileType
    extracted_text: str
    normalized_text: str | None = None
    pages: list[ExtractedPage] = Field(default_factory=list)
    extraction_method: str
    is_ocr_used: bool = False
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    success: bool = True


class OCRResult(BaseModel):
    """Result of running OCR over a single image."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str
    engine: str = "tesseract"
    language: str = "eng"
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    success: bool = True


# ------------------------------------------------- cross-source verification


class ClaimEvidenceMatch(BaseModel):
    """A similarity match between one claim and one evidence item.

    ``score`` is a relevance score only — a high score means the evidence
    appears relevant, never that the claim is true.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    evidence_id: str
    score: float = Field(ge=0.0, le=1.0)
    method: SimilarityMethod


class ClaimSimilarityResult(BaseModel):
    """Relevance scores between customer claims and evidence items."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    matches: list[ClaimEvidenceMatch] = Field(default_factory=list)
    method: SimilarityMethod = SimilarityMethod.LEXICAL
    limitations: list[str] = Field(default_factory=list)


class SimilarityScore(BaseModel):
    """One relevance score attached to a claim finding."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    score: float = Field(ge=0.0, le=1.0)
    method: SimilarityMethod


class CitedPassage(BaseModel):
    """A passage from one evidence item supporting a finding.

    ``text`` must be verbatim text present in the referenced evidence item;
    when no reliable quotation exists, ``text`` stays empty and the
    finding's rationale explains why.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str
    text: str = ""
    page_number: int | None = Field(default=None, ge=1)


class ClaimAssessment(BaseModel):
    """Verification result for one customer claim.

    ``status`` states how the evidence stands relative to the claim.
    Similarity scores record relevance only and never establish truth.
    ``requires_human_review`` is always True.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim_id: str
    claim: str
    source: str = "customer_ticket"
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str = ""
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    cited_passages: list[CitedPassage] = Field(default_factory=list)
    similarity_scores: list[SimilarityScore] = Field(default_factory=list)
    analysis_method: str = "heuristic"
    requires_human_review: bool = True
    source_kind: AnalysisSource = AnalysisSource.HEURISTIC


class FieldValueObservation(BaseModel):
    """One observed value of a comparable field, traced to its source."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    value: str
    source: str
    evidence_id: str | None = None


class CrossSourceFinding(BaseModel):
    """Consistency check of one field across all available sources.

    ``contradicted`` describes an inconsistency factually; it never accuses
    any party of dishonesty or fraud.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    field: str
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    observed_values: list[FieldValueObservation] = Field(default_factory=list)
    rationale: str = ""
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    requires_human_review: bool = True


class Contradiction(BaseModel):
    """One detected inconsistency between sources.

    Factual description only; both sources are referenced and no party is
    accused of dishonesty.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    field: str
    description: str
    evidence_ids: list[str] = Field(default_factory=list)
    observed_values: list[FieldValueObservation] = Field(default_factory=list)


class MissingInformation(BaseModel):
    """One entry under "missing information".

    States what the available evidence does not establish and what could
    clarify it — never a conclusion that a claim is false.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    description: str
    recommended_evidence: list[str] = Field(default_factory=list)


class RefundRecommendation(BaseModel):
    """The recommendation, fully explained and traceable.

    ``outcome`` is always accompanied by reasoning, evidence references,
    relevant policy rules, missing information, and a confidence estimate.
    ``human_review_required`` is always True: the recommendation is never
    a final decision and never an instruction to move money.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    outcome: RecommendationOutcome
    reasoning: str = ""
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    relevant_policy_rule_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    requires_human_review: bool = True


# ------------------------------------------------------- analysis pipeline


class SupportCaseAnalysisResult(BaseModel):
    """Complete structured outcome of ``analyze_support_case``.

    Every sub-list is traceable: claims carry sources, findings carry
    evidence IDs, the recommendation carries its reasoning.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = EXTRACTION_SCHEMA_VERSION
    case_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    issue_type: IssueType = IssueType.OTHER
    requested_resolution: str = ""
    customer_claim_summary: str = ""
    claims: list[ClaimAssessment] = Field(default_factory=list)
    purchase_information: list[PurchaseInformation] = Field(default_factory=list)
    visual_analysis: list[VisualAnalysisResult] = Field(default_factory=list)
    conversation_analysis: list[ConversationAnalysis] = Field(default_factory=list)
    cross_source_findings: list[CrossSourceFinding] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    policy_evaluation: PolicyEvaluationResult | None = None
    recommendation: RefundRecommendation | None = None
    limitations: list[str] = Field(default_factory=list)
    requires_human_review: bool = True
    source_summary: SourceSummary = Field(default_factory=SourceSummary)


# ------------------------------------------------------------ report models


class CaseEvent(BaseModel):
    """One case event supplied by the backend for the report timeline.

    ``timestamp`` is optional: when absent the event is undated. Timestamps
    are never invented.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_type: str
    description: str = ""
    timestamp: datetime | None = None


class CaseContext(BaseModel):
    """Backend-supplied context about the support case."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str
    title: str
    description: str = ""
    created_at: datetime | None = None
    events: list[CaseEvent] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class SupportCaseOverview(BaseModel):
    """Display block: what the support case is about."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str
    issue_type: IssueType = IssueType.OTHER
    product_name: str | None = None
    requested_resolution: str = ""
    complaint_summary: str = ""
    created_at: datetime | None = None


class ReportEvidenceEntry(BaseModel):
    """Display-friendly copy of one evidence item for the inventory."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str
    filename: str
    kind: EvidenceKind
    status: EvidenceInventoryStatus = EvidenceInventoryStatus.PROCESSED
    category: EvidenceCategory | None = None
    evidence_type: str | None = None
    uploaded_by: str | None = None
    uploaded_at: datetime | None = None
    summary: str = ""
    identified_facts: list[str] = Field(default_factory=list)
    extraction_warning_codes: list[str] = Field(default_factory=list)


class OcrFinding(BaseModel):
    """One entry under "OCR findings".

    OCR extracts readable text only — OCR findings never claim that an
    image was visually analyzed.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str
    filename: str
    text_excerpt: str = ""
    warnings: list[str] = Field(default_factory=list)


class PolicySummary(BaseModel):
    """Display-friendly summary of the refund policy used in the case."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    policy_id: str
    policy_name: str = ""
    rule_count: int = Field(default=0, ge=0)
    rule_summaries: list[str] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)


class ReportTimelineEvent(BaseModel):
    """One chronological timeline entry.

    ``timestamp`` is None for undated events: they are listed after dated
    events and excluded from chronological ordering. ``source`` says where
    the event came from — every event is traceable to supplied data.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_type: str
    description: str = ""
    timestamp: datetime | None = None
    source: str


class InvestigationReport(BaseModel):
    """Structured customer-support investigation report.

    The report is decision support: ``human_review_required`` is always
    True and ``final_decision_notice`` restates that an authorized human
    support agent makes the final decision. Claim assessments, visual
    results, and policy assessments are copied verbatim from the analysis
    stage — the report never edits findings.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = REPORT_SCHEMA_VERSION
    case_id: str
    report_title: str = REPORT_TITLE
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    case_overview: SupportCaseOverview
    customer_complaint: str = ""
    product_information: str = ""
    requested_resolution: str = ""
    customer_claims: list[CustomerClaim] = Field(default_factory=list)
    purchase_and_order_information: list[PurchaseInformation] = Field(
        default_factory=list
    )
    order_information: OrderInformation | None = None
    payment_information: PaymentInformation | None = None
    evidence_inventory: list[ReportEvidenceEntry] = Field(default_factory=list)
    ocr_findings: list[OcrFinding] = Field(default_factory=list)
    visual_analysis: list[VisualAnalysisResult] = Field(default_factory=list)
    conversation_analysis: list[ConversationAnalysis] = Field(default_factory=list)
    refund_policy_summary: PolicySummary | None = None
    cross_source_verification: list[CrossSourceFinding] = Field(default_factory=list)
    supporting_findings: list[ClaimAssessment] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    policy_assessment: PolicyEvaluationResult | None = None
    recommended_outcome: RecommendationOutcome = (
        RecommendationOutcome.INSUFFICIENT_POLICY_INFORMATION
    )
    recommendation_reasoning: str = ""
    recommendation: RefundRecommendation | None = None
    evidence_references: list[str] = Field(default_factory=list)
    timeline: list[ReportTimelineEvent] = Field(default_factory=list)
    neutral_summary: str = ""
    limitations: list[str] = Field(default_factory=list)
    human_review_required: bool = True
    final_decision_notice: str = FINAL_DECISION_NOTICE
    status_counts: dict[VerificationStatus, int] = Field(default_factory=dict)
    unresolved_evidence_ids: list[str] = Field(default_factory=list)
    source_summary: SourceSummary = Field(default_factory=SourceSummary)
    generation_method: str = "heuristic"
