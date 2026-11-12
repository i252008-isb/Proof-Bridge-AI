"""Main pipeline: coordinate ticket, evidence, vision, policy, and verdict.

The orchestrator never decides anything itself: it extracts, compares, and
evaluates, then produces a recommendation that always requires human
review. Partial evidence tolerance: one unreadable or unsupported item is
reported as a limitation and never aborts the investigation.

Evidence inputs may be a mix of:

- ``EvidenceItem`` (already processed by the backend, used verbatim), and
- ``EvidenceUpload`` (raw bytes + metadata; processed here — OCR and, for
  images, visual analysis run on the bytes).

Backend-supplied corrected ticket claims and order information are used
verbatim and never silently overwritten.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

from proofbridge_ai.config import Settings, get_settings
from proofbridge_ai.exceptions import InputValidationError, ProofBridgeAIError
from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.providers import get_llm_provider
from proofbridge_ai.schemas import (
    AnalysisSource,
    CaseContext,
    ClaimAssessment,
    ClaimEvidenceMatch,
    Contradiction,
    ConversationAnalysis,
    CustomerClaim,
    EvidenceCategory,
    EvidenceInput,
    EvidenceItem,
    EvidenceKind,
    EvidenceUpload,
    MissingInformation,
    OrderInformation,
    PolicyEvaluationResult,
    PolicyEvaluationStatus,
    PurchaseInformation,
    RecommendationOutcome,
    RefundPolicy,
    RefundRecommendation,
    RuleAssessment,
    SimilarityScore,
    SourceSummary,
    SupportCaseAnalysisResult,
    SupportTicket,
    TicketAnalysisResult,
    VerificationStatus,
    VisionStatus,
    VisualAnalysisResult,
)
from proofbridge_ai.services.conversation_analyzer import analyze_conversation
from proofbridge_ai.services.cross_source_verifier import verify_cross_source
from proofbridge_ai.services.evidence_extractor import extract_evidence
from proofbridge_ai.services.policy_evaluator import evaluate_refund_policy
from proofbridge_ai.services.policy_extractor import extract_refund_policy
from proofbridge_ai.services.product_analyzer import extract_purchase_information
from proofbridge_ai.services.similarity_engine import compare_support_evidence
from proofbridge_ai.services.ticket_analyzer import extract_ticket_claims
from proofbridge_ai.services.vision_analyzer import analyze_visual_evidence

logger = get_logger("services.support_case_analyzer")

_DAMAGE_PATTERN = re.compile(
    r"\b(?:damag\w*|crack\w*|broken|broke|scratch\w*|dent\w*|defect\w*|"
    r"malfunction\w*|not working|does not work|faulty)\b",
    re.IGNORECASE,
)
_ORDER_NUMBER_PATTERN = re.compile(
    r"(?i)\b(?:order|invoice|receipt|tracking|ref(?:erence)?|payment)\b"
    r"\s*#?\s*((?-i:[A-Z0-9][A-Z0-9-]{2,}))"
)
_DATE_PATTERN = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}\b"
    r"|\b(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4}\b",
    re.IGNORECASE,
)

_RECEIPT_CATEGORIES = {
    EvidenceCategory.PURCHASE_RECORD,
    EvidenceCategory.ORDER_RECORD,
}

_CONFIDENCE = {
    "escalate": 0.6,
    "insufficient_policy": 0.5,
    "request_more": 0.6,
    "refund_recommended": 0.7,
    "not_supported": 0.7,
    "alternative": 0.6,
}


async def analyze_support_case(
    support_ticket: SupportTicket,
    evidence_items: Sequence[EvidenceItem | EvidenceUpload],
    refund_policy: RefundPolicy | None = None,
    order_information: OrderInformation | None = None,
    case_context: CaseContext | None = None,
    settings: Settings | None = None,
) -> SupportCaseAnalysisResult:
    """Run the complete investigation for one customer support case.

    Args:
        support_ticket: Backend-supplied ticket (customer allegations).
        evidence_items: Processed evidence items and/or raw uploads.
        refund_policy: Optional backend-supplied or extracted policy.
        order_information: Backend order-system data, used verbatim.
        case_context: Backend case context (informational).
        settings: Optional Settings override (tests).

    Returns:
        SupportCaseAnalysisResult with claims, findings, contradictions,
        missing information, policy evaluation, and a recommendation.
        ``requires_human_review`` is always True.
    """
    return _analyze_support_case(
        support_ticket,
        evidence_items,
        refund_policy,
        order_information,
        case_context,
        settings,
    )


async def arun_support_case_analysis(
    support_ticket: SupportTicket,
    evidence_items: Sequence[EvidenceItem | EvidenceUpload],
    refund_policy: RefundPolicy | None = None,
    order_information: OrderInformation | None = None,
    case_context: CaseContext | None = None,
    settings: Settings | None = None,
) -> SupportCaseAnalysisResult:
    """Async alias of :func:`analyze_support_case` (same behavior)."""
    return _analyze_support_case(
        support_ticket,
        evidence_items,
        refund_policy,
        order_information,
        case_context,
        settings,
    )


def _analyze_support_case(
    support_ticket: SupportTicket,
    evidence_items: Sequence[EvidenceItem | EvidenceUpload],
    refund_policy: RefundPolicy | None,
    order_information: OrderInformation | None,
    case_context: CaseContext | None,
    settings: Settings | None,
) -> SupportCaseAnalysisResult:
    settings = settings or get_settings()
    if not isinstance(support_ticket, SupportTicket):
        raise InputValidationError("support_ticket must be a SupportTicket")
    if not isinstance(evidence_items, (list, tuple)):
        raise InputValidationError("evidence_items must be a list")
    if refund_policy is not None and not isinstance(refund_policy, RefundPolicy):
        raise InputValidationError("refund_policy must be a RefundPolicy or None")
    if order_information is not None and not isinstance(
        order_information, OrderInformation
    ):
        raise InputValidationError("order_information must be an OrderInformation or None")
    if case_context is not None and not isinstance(case_context, CaseContext):
        raise InputValidationError("case_context must be a CaseContext or None")

    limitations: list[str] = []
    if get_llm_provider(settings).is_mock:
        limitations.append(
            "The configured LLM provider is a mock: LLM-based extractions "
            "and summaries are deterministic heuristics, not model output."
        )

    ticket_analysis = extract_ticket_claims(support_ticket, settings)

    processed_items, visuals, conversations, purchases, extracted_policy = (
        _process_evidence(
            evidence_items,
            refund_policy,
            settings,
            limitations,
        )
    )
    policy = refund_policy or extracted_policy

    similarity = compare_support_evidence(
        ticket_analysis.extracted_claims, processed_items, settings
    )
    limitations.extend(similarity.limitations)

    primary_purchase = _primary_purchase(purchases)
    primary_conversation = conversations[0] if conversations else None
    findings, contradictions, verifier_missing = verify_cross_source(
        support_ticket,
        ticket_analysis=ticket_analysis,
        purchase_information=primary_purchase,
        order_information=order_information,
        conversation_analysis=primary_conversation,
    )

    claim_assessments, claim_missing = _assess_claims(
        ticket_analysis.extracted_claims,
        similarity.matches,
        purchases,
        visuals,
        order_information,
        settings,
    )

    policy_evaluation = evaluate_refund_policy(
        policy,
        ticket_analysis=ticket_analysis,
        purchase_information=primary_purchase,
        visual_analysis=_primary_visual(visuals),
    )
    recommendation = _recommend(
        ticket_analysis,
        policy_evaluation,
        contradictions,
        conversations,
    )

    missing_information = _dedupe_missing(
        list(verifier_missing) + claim_missing + _policy_missing(policy_evaluation)
    )

    limitations.extend(
        _visual_limitations(visuals, processed_items)
    )

    return SupportCaseAnalysisResult(
        case_id=support_ticket.case_id,
        issue_type=ticket_analysis.issue_type,
        requested_resolution=ticket_analysis.requested_resolution,
        customer_claim_summary=ticket_analysis.customer_claim_summary,
        claims=claim_assessments,
        purchase_information=purchases,
        visual_analysis=visuals,
        conversation_analysis=conversations,
        cross_source_findings=findings,
        contradictions=contradictions,
        missing_information=missing_information,
        policy_evaluation=policy_evaluation,
        recommendation=recommendation,
        limitations=list(dict.fromkeys(limitations)),
        requires_human_review=True,
        source_summary=_source_summary(
            ticket_analysis, processed_items, conversations, policy
        ),
    )


# ------------------------------------------------------------ evidence


def _process_evidence(
    evidence_items: Sequence[EvidenceItem | EvidenceUpload],
    supplied_policy: RefundPolicy | None,
    settings: Settings,
    limitations: list[str],
) -> tuple[
    list[EvidenceItem],
    list[VisualAnalysisResult],
    list[ConversationAnalysis],
    list[PurchaseInformation],
    RefundPolicy | None,
]:
    processed_items: list[EvidenceItem] = []
    visuals: list[VisualAnalysisResult] = []
    conversations: list[ConversationAnalysis] = []
    purchases: list[PurchaseInformation] = []
    extracted_policy: RefundPolicy | None = None

    for entry in evidence_items:
        if isinstance(entry, EvidenceUpload):
            item: EvidenceItem | None = None
            try:
                item = extract_evidence(
                    entry.file_bytes, entry.evidence_input, entry.content_type, settings
                )
                processed_items.append(item)
            except ProofBridgeAIError as exc:
                _note_failure(limitations, entry.evidence_input, exc)
            if _upload_is_image(entry):
                try:
                    visuals.append(
                        analyze_visual_evidence(
                            entry.file_bytes,
                            entry.evidence_input,
                            entry.content_type,
                            settings=settings,
                        )
                    )
                except ProofBridgeAIError as exc:
                    limitations.append(
                        f"Visual analysis for evidence "
                        f"{entry.evidence_input.evidence_id!r} failed and was "
                        f"skipped: {type(exc).__name__}."
                    )
            if item is not None:
                extracted_policy = _specialize(
                    item, conversations, purchases, extracted_policy, settings, limitations
                ) or extracted_policy
        elif isinstance(entry, EvidenceItem):
            processed_items.append(entry)
            if _is_image(entry):
                limitations.append(
                    f"Visual analysis for image {entry.evidence_id!r} was not "
                    "performed because raw image bytes were not supplied to "
                    "the pipeline; analyze_visual_evidence can be run on the "
                    "bytes separately."
                )
            extracted_policy = _specialize(
                entry, conversations, purchases, extracted_policy, settings, limitations
            ) or extracted_policy
        else:
            limitations.append(
                f"Skipped one evidence entry of unexpected type "
                f"{type(entry).__name__}; expected EvidenceItem or EvidenceUpload."
            )
    return processed_items, visuals, conversations, purchases, extracted_policy


def _specialize(
    item: EvidenceItem,
    conversations: list[ConversationAnalysis],
    purchases: list[PurchaseInformation],
    extracted_policy: RefundPolicy | None,
    settings: Settings,
    limitations: list[str],
) -> RefundPolicy | None:
    if item.category in _RECEIPT_CATEGORIES:
        try:
            purchases.append(extract_purchase_information(item, settings))
        except ProofBridgeAIError as exc:
            limitations.append(
                f"Purchase information for evidence {item.evidence_id!r} "
                f"could not be extracted ({type(exc).__name__}); the item "
                "was kept in the inventory."
            )
    elif item.category is EvidenceCategory.CONVERSATION:
        try:
            conversations.append(analyze_conversation(item, settings))
        except ProofBridgeAIError as exc:
            limitations.append(
                f"Conversation analysis for evidence {item.evidence_id!r} "
                f"failed ({type(exc).__name__}); the item was kept in the "
                "inventory."
            )
    elif item.category is EvidenceCategory.RETURN_POLICY and extracted_policy is None:
        try:
            return extract_refund_policy(
                policy_text=item.extracted_text,
                policy_id=f"policy-{item.evidence_id}",
                policy_name=item.filename or "Refund Policy",
                settings=settings,
            )
        except ProofBridgeAIError as exc:
            limitations.append(
                f"Refund policy extraction from evidence "
                f"{item.evidence_id!r} failed ({type(exc).__name__})."
            )
    return None


def _is_image(item: EvidenceItem) -> bool:
    return (
        item.category is EvidenceCategory.PRODUCT_IMAGE
        or item.kind is EvidenceKind.IMAGE
    )


_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff")


def _upload_is_image(upload: EvidenceUpload) -> bool:
    evidence_input = upload.evidence_input
    if evidence_input.category is EvidenceCategory.PRODUCT_IMAGE:
        return True
    if upload.content_type and upload.content_type.startswith("image/"):
        return True
    return evidence_input.filename.lower().endswith(_IMAGE_EXTENSIONS)


def _note_failure(
    limitations: list[str], evidence_input: EvidenceInput, exc: ProofBridgeAIError
) -> None:
    limitations.append(
        f"Evidence item {evidence_input.evidence_id!r} "
        f"({evidence_input.filename!r}) could not be processed "
        f"({type(exc).__name__}); the investigation continued with the "
        "remaining evidence."
    )


# ---------------------------------------------------------------- claims


def _assess_claims(
    claims: list[CustomerClaim],
    matches: list[ClaimEvidenceMatch],
    purchases: list[PurchaseInformation],
    visuals: list[VisualAnalysisResult],
    order_information: OrderInformation | None,
    settings: Settings,
) -> tuple[list[ClaimAssessment], list[MissingInformation]]:
    by_claim: dict[str, list[ClaimEvidenceMatch]] = {}
    for match in matches:
        by_claim.setdefault(match.claim_id, []).append(match)
    assessments: list[ClaimAssessment] = []
    missing: list[MissingInformation] = []
    for index, claim in enumerate(claims, start=1):
        claim_matches = sorted(
            by_claim.get(claim.id, []), key=lambda m: m.score, reverse=True
        )
        assessment, is_missing = _assess_claim(
            claim,
            claim_matches,
            purchases,
            visuals,
            order_information,
            settings,
        )
        assessments.append(assessment)
        if is_missing:
            missing.append(
                MissingInformation(
                    id=f"missing-claim-{index}",
                    description=(
                        f"No evidence relevant to the claim "
                        f"{claim.claim!r} was found."
                    ),
                    recommended_evidence=[
                        "Receipt or order confirmation",
                        "Product photographs",
                        "Seller conversation export",
                    ],
                )
            )
    return assessments, missing


def _assess_claim(
    claim: CustomerClaim,
    matches: list[ClaimEvidenceMatch],
    purchases: list[PurchaseInformation],
    visuals: list[VisualAnalysisResult],
    order_information: OrderInformation | None,
    settings: Settings,
) -> tuple[ClaimAssessment, bool]:
    partial_threshold = settings.similarity_partial_threshold
    supported_threshold = settings.similarity_supported_threshold
    relevant_ids = [
        match.evidence_id for match in matches if match.score >= partial_threshold
    ]
    supporting_ids = [
        match.evidence_id for match in matches if match.score >= supported_threshold
    ]
    scores = [
        SimilarityScore(
            evidence_id=match.evidence_id, score=match.score, method=match.method
        )
        for match in matches
    ]
    base = dict(
        claim_id=claim.id,
        claim=claim.claim,
        source=claim.source,
        similarity_scores=scores,
        requires_human_review=True,
    )

    order_number = _first_order_number(claim.claim)
    if order_number is not None:
        known = _known_order_numbers(purchases, order_information)
        if known:
            if order_number in known:
                return (
                    ClaimAssessment(
                        **base,
                        status=VerificationStatus.SUPPORTED,
                        supporting_evidence_ids=supporting_ids,
                        rationale=(
                            f"The order number stated in this claim "
                            f"({order_number}) matches the order number "
                            "found in the supplied documents."
                        ),
                    ),
                    False,
                )
            return (
                ClaimAssessment(
                    **base,
                    status=VerificationStatus.CONTRADICTED,
                    contradicting_evidence_ids=supporting_ids,
                    rationale=(
                        f"The order number stated in this claim "
                        f"({order_number}) does not match the order "
                        f"number(s) found in the supplied documents "
                        f"({', '.join(sorted(known))}). This inconsistency "
                        "is reported factually."
                    ),
                ),
                False,
            )

    claim_dates = _parse_dates(claim.claim)
    if claim_dates:
        known_dates = _known_purchase_dates(purchases, order_information)
        if known_dates:
            if any(date in known_dates for date in claim_dates):
                return (
                    ClaimAssessment(
                        **base,
                        status=VerificationStatus.SUPPORTED,
                        supporting_evidence_ids=supporting_ids,
                        rationale=(
                            "A date stated in this claim matches the "
                            "purchase date found in the supplied documents."
                        ),
                    ),
                    False,
                )
            return (
                ClaimAssessment(
                    **base,
                    status=VerificationStatus.CONTRADICTED,
                    contradicting_evidence_ids=supporting_ids,
                    rationale=(
                        "A date stated in this claim does not match the "
                        "purchase date(s) found in the supplied documents. "
                        "This inconsistency is reported factually."
                    ),
                ),
                False,
            )

    if _DAMAGE_PATTERN.search(claim.claim):
        photo_ids = [
            visual.evidence_id
            for visual in visuals
            if visual.evidence_id in relevant_ids
        ]
        observed_ids = [
            visual.evidence_id
            for visual in visuals
            if visual.evidence_id in relevant_ids
            and visual.visual_observations
            and visual.status is VisionStatus.ANALYZED
        ]
        if observed_ids:
            return (
                ClaimAssessment(
                    **base,
                    status=VerificationStatus.SUPPORTED,
                    supporting_evidence_ids=observed_ids,
                    rationale=(
                        "The customer photograph shows visually observable "
                        "irregularities consistent with this claim."
                    ),
                ),
                False,
            )
        if photo_ids:
            return (
                ClaimAssessment(
                    **base,
                    status=VerificationStatus.PARTIALLY_SUPPORTED,
                    supporting_evidence_ids=photo_ids,
                    rationale=(
                        "A relevant customer photograph was supplied, but "
                        "automated visual analysis could not confirm the "
                        "described damage (vision unavailable, failed, or "
                        "no clear irregularities observed)."
                    ),
                ),
                False,
            )

    if relevant_ids:
        return (
            ClaimAssessment(
                **base,
                status=VerificationStatus.UNVERIFIED,
                supporting_evidence_ids=supporting_ids,
                rationale=(
                    "Relevant evidence exists, but it does not "
                    "independently confirm this claim."
                ),
            ),
            False,
        )
    return (
        ClaimAssessment(
            **base,
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            rationale=(
                "No evidence relevant to this claim was found among the "
                "supplied evidence items."
            ),
        ),
        True,
    )


def _first_order_number(text: str) -> str | None:
    match = _ORDER_NUMBER_PATTERN.search(text)
    return match.group(1).upper() if match else None


def _known_order_numbers(
    purchases: list[PurchaseInformation],
    order_information: OrderInformation | None,
) -> set[str]:
    """Independent confirmation sources only — never the ticket itself,
    which is the allegation under investigation."""
    known = {
        purchase.order_number.upper()
        for purchase in purchases
        if purchase.order_number
    }
    if order_information and order_information.order_id:
        known.add(order_information.order_id.upper())
    return known


def _parse_dates(text: str) -> list:
    dates = []
    for match in _DATE_PATTERN.finditer(text):
        token = match.group(0)
        for fmt in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y"):
            try:
                dates.append(datetime.strptime(token, fmt).date())
                break
            except ValueError:
                continue
    return dates


def _known_purchase_dates(
    purchases: list[PurchaseInformation],
    order_information: OrderInformation | None,
) -> set:
    """Independent confirmation sources only — never the ticket itself."""
    known = {
        purchase.purchase_date.date()
        for purchase in purchases
        if purchase.purchase_date
    }
    if order_information and order_information.purchase_date:
        known.add(order_information.purchase_date.date())
    return known


def _primary_purchase(
    purchases: list[PurchaseInformation],
) -> PurchaseInformation | None:
    if not purchases:
        return None
    for purchase in purchases:
        if purchase.order_number:
            return purchase
    return purchases[0]


def _primary_visual(
    visuals: list[VisualAnalysisResult],
) -> VisualAnalysisResult | None:
    if not visuals:
        return None
    for visual in visuals:
        if visual.visual_observations:
            return visual
    return visuals[0]


# --------------------------------------------------------- recommendation


def _recommend(
    ticket_analysis: TicketAnalysisResult,
    policy_evaluation: PolicyEvaluationResult,
    contradictions: list[Contradiction],
    conversations: list[ConversationAnalysis],
) -> RefundRecommendation:
    seller_promised = any(
        conversation.refund_promises for conversation in conversations
    )
    if contradictions:
        fields = ", ".join(
            sorted({contradiction.field for contradiction in contradictions})
        )
        return RefundRecommendation(
            outcome=RecommendationOutcome.ESCALATE_TO_HUMAN,
            reasoning=(
                f"Inconsistencies were found across sources "
                f"({fields}). The AI cannot determine which source is "
                "correct, so a human support agent must investigate and "
                "decide."
            ),
            contradicting_evidence_ids=list(
                dict.fromkeys(
                    evidence_id
                    for contradiction in contradictions
                    for evidence_id in contradiction.evidence_ids
                )
            ),
            missing_information=list(policy_evaluation.missing_information),
            confidence=_CONFIDENCE["escalate"],
        )

    if policy_evaluation.status is PolicyEvaluationStatus.POLICY_NOT_PROVIDED:
        reasoning = (
            "No refund policy was supplied, so the AI cannot evaluate "
            "whether the case meets any refund conditions."
        )
        if seller_promised:
            reasoning += (
                " The conversation analysis recorded statements suggesting "
                "the seller promised a refund; a human agent must confirm "
                "them before any decision."
            )
        return RefundRecommendation(
            outcome=RecommendationOutcome.INSUFFICIENT_POLICY_INFORMATION,
            reasoning=reasoning,
            missing_information=list(policy_evaluation.missing_information),
            confidence=_CONFIDENCE["insufficient_policy"],
        )

    if (
        policy_evaluation.status
        is PolicyEvaluationStatus.POLICY_REQUIRES_HUMAN_INTERPRETATION
    ):
        return RefundRecommendation(
            outcome=RecommendationOutcome.INSUFFICIENT_POLICY_INFORMATION,
            reasoning=(
                "A refund policy was supplied but none of its rules could "
                "be deterministically evaluated from the available case "
                "information. A human support agent must interpret the "
                "policy for this case."
            ),
            missing_information=list(policy_evaluation.missing_information),
            relevant_policy_rule_ids=[
                assessment.rule_id
                for assessment in policy_evaluation.rule_assessments
            ],
            confidence=_CONFIDENCE["insufficient_policy"],
        )

    not_met = [
        assessment
        for assessment in policy_evaluation.rule_assessments
        if assessment.assessment is RuleAssessment.NOT_MET
    ]
    partially_met = [
        assessment
        for assessment in policy_evaluation.rule_assessments
        if assessment.assessment is RuleAssessment.PARTIALLY_MET
    ]
    met = [
        assessment
        for assessment in policy_evaluation.rule_assessments
        if assessment.assessment is RuleAssessment.MET
    ]
    relevant_rule_ids = [
        assessment.rule_id for assessment in policy_evaluation.rule_assessments
    ]
    supporting_evidence_ids = list(
        dict.fromkeys(
            evidence_id
            for assessment in met
            for evidence_id in assessment.evidence_ids
        )
    )

    if not_met:
        conditions = "; ".join(assessment.condition for assessment in not_met)
        if policy_evaluation.missing_information:
            return RefundRecommendation(
                outcome=RecommendationOutcome.REQUEST_MORE_INFORMATION,
                reasoning=(
                    f"Policy conditions were not met: {conditions}. "
                    "However, the following information is missing and "
                    "could change the assessment: "
                    f"{'; '.join(policy_evaluation.missing_information)}. "
                    "Requesting this information from the customer or "
                    "seller is recommended before a final decision."
                ),
                missing_information=list(policy_evaluation.missing_information),
                relevant_policy_rule_ids=relevant_rule_ids,
                confidence=_CONFIDENCE["request_more"],
            )
        return RefundRecommendation(
            outcome=RecommendationOutcome.REFUND_NOT_SUPPORTED_BY_PROVIDED_POLICY,
            reasoning=(
                f"Policy conditions were not met: {conditions}. This is "
                "not a definitive rejection: the AI reports that the "
                "available evidence does not establish refund eligibility "
                "under the supplied policy. A human support agent makes "
                "the final decision."
            ),
            relevant_policy_rule_ids=relevant_rule_ids,
            confidence=_CONFIDENCE["not_supported"],
        )

    if partially_met:
        conditions = "; ".join(assessment.condition for assessment in partially_met)
        return RefundRecommendation(
            outcome=RecommendationOutcome.REQUEST_MORE_INFORMATION,
            reasoning=(
                f"Some policy conditions were only partially met: "
                f"{conditions}. Additional information is needed to "
                "complete the assessment."
            ),
            missing_information=list(policy_evaluation.missing_information),
            relevant_policy_rule_ids=relevant_rule_ids,
            confidence=_CONFIDENCE["request_more"],
        )

    not_assessable = [
        assessment
        for assessment in policy_evaluation.rule_assessments
        if assessment.assessment is RuleAssessment.NOT_ASSESSABLE
    ]
    if not_assessable and policy_evaluation.missing_information:
        conditions = "; ".join(
            assessment.condition for assessment in not_assessable
        )
        return RefundRecommendation(
            outcome=RecommendationOutcome.REQUEST_MORE_INFORMATION,
            reasoning=(
                f"Some policy conditions could not be evaluated: "
                f"{conditions}. The following information is missing and "
                "could change the assessment: "
                f"{'; '.join(policy_evaluation.missing_information)}. "
                "Requesting this information before a final decision is "
                "recommended."
            ),
            missing_information=list(policy_evaluation.missing_information),
            relevant_policy_rule_ids=relevant_rule_ids,
            confidence=_CONFIDENCE["request_more"],
        )

    requested = ticket_analysis.requested_resolution.lower()
    if "refund" in requested:
        reasoning = (
            "All evaluable policy conditions were met, and the customer "
            "requested a refund. The AI recommends a refund as the "
            "supported outcome; an authorized human agent must make the "
            "final decision."
        )
        if seller_promised:
            reasoning += (
                " The conversation analysis also recorded statements "
                "suggesting the seller promised a refund."
            )
        return RefundRecommendation(
            outcome=RecommendationOutcome.REFUND_RECOMMENDED,
            reasoning=reasoning,
            supporting_evidence_ids=supporting_evidence_ids,
            relevant_policy_rule_ids=relevant_rule_ids,
            confidence=_CONFIDENCE["refund_recommended"],
        )
    if "replac" in requested or "repair" in requested:
        return RefundRecommendation(
            outcome=RecommendationOutcome.ALTERNATIVE_RESOLUTION_SUGGESTED,
            reasoning=(
                f"All evaluable policy conditions were met. The customer "
                f"requested: {ticket_analysis.requested_resolution}. An "
                "alternative resolution matching that request should be "
                "considered; a human support agent makes the final "
                "decision."
            ),
            supporting_evidence_ids=supporting_evidence_ids,
            relevant_policy_rule_ids=relevant_rule_ids,
            confidence=_CONFIDENCE["alternative"],
        )
    return RefundRecommendation(
        outcome=RecommendationOutcome.ESCALATE_TO_HUMAN,
        reasoning=(
            "All evaluable policy conditions were met, but the customer's "
            "requested resolution is unclear. A human support agent "
            "should decide how to resolve the case."
        ),
        supporting_evidence_ids=supporting_evidence_ids,
        relevant_policy_rule_ids=relevant_rule_ids,
        confidence=_CONFIDENCE["escalate"],
    )


# ------------------------------------------------------------- assembly


def _dedupe_missing(items: list[MissingInformation]) -> list[MissingInformation]:
    deduped: dict[str, MissingInformation] = {}
    for item in items:
        if item.description not in deduped:
            deduped[item.description] = item
    return list(deduped.values())


def _policy_missing(
    policy_evaluation: PolicyEvaluationResult,
) -> list[MissingInformation]:
    return [
        MissingInformation(
            id=f"missing-policy-{index}",
            description=description,
            recommended_evidence=["Additional policy documentation"],
        )
        for index, description in enumerate(
            policy_evaluation.missing_information, start=1
        )
    ]


def _visual_limitations(
    visuals: list[VisualAnalysisResult],
    processed_items: list[EvidenceItem],
) -> list[str]:
    limitations: list[str] = []
    image_ids = {
        item.evidence_id for item in processed_items if _is_image(item)
    }
    for visual in visuals:
        if visual.status is VisionStatus.MOCK:
            limitations.append(
                f"Visual analysis for image {visual.evidence_id!r} used "
                "the mock vision provider: no genuine image analysis was "
                "performed."
            )
        elif visual.status is VisionStatus.FAILED:
            limitations.append(
                f"Visual analysis for image {visual.evidence_id!r} failed; "
                "manual visual inspection is required."
            )
        image_ids.discard(visual.evidence_id)
    for evidence_id in sorted(image_ids):
        limitations.append(
            f"Image {evidence_id!r} was not visually analyzed (no raw "
            "bytes supplied to the pipeline)."
        )
    return limitations


def _source_summary(
    ticket_analysis: TicketAnalysisResult,
    processed_items: list[EvidenceItem],
    conversations: list[ConversationAnalysis],
    policy: RefundPolicy | None,
) -> SourceSummary:
    llm_count = 0
    heuristic_count = 0
    sources: list[AnalysisSource | None] = [ticket_analysis.source]
    sources.extend(item.summary_source for item in processed_items)
    sources.extend(conversation.source for conversation in conversations)
    if policy is not None:
        sources.append(policy.source)
    for source in sources:
        if source is AnalysisSource.LLM:
            llm_count += 1
        elif source is AnalysisSource.HEURISTIC:
            heuristic_count += 1
    return SourceSummary(llm_count=llm_count, heuristic_count=heuristic_count)
