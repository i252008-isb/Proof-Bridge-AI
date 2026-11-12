"""Deterministic evaluation of the case against the supplied refund policy.

The evaluator never decides a refund — it assesses which policy conditions
are met, partially met, not met, or not deterministically assessable, and
always requires human review. Status values:

- ``policy_not_provided``: no policy was supplied at all.
- ``policy_requires_human_interpretation``: a policy exists but no rule
  could be deterministically assessed (unreadable policy text or missing
  case information).
- ``evaluated``: at least one rule was deterministically assessed.

Missing information is collected and surfaced, never papered over.
"""

from __future__ import annotations

import re
from datetime import datetime

from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.schemas import (
    ExtractionWarning,
    PolicyEvaluationResult,
    PolicyEvaluationStatus,
    PolicyRule,
    PolicyRuleAssessment,
    PolicyRuleCategory,
    PurchaseInformation,
    RefundPolicy,
    RuleAssessment,
    TicketAnalysisResult,
    VisionStatus,
    VisualAnalysisResult,
)

logger = get_logger("services.policy_evaluator")

_WINDOW_PATTERN = re.compile(
    r"\b(\d+)\s+(?:calendar\s+|business\s+)?days?\b", re.IGNORECASE
)
_PROOF_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("receipt/invoice", re.compile(r"\breceipt|invoice|proof of purchase\b", re.IGNORECASE)),
    ("photograph/video", re.compile(r"\bphoto|photograph|picture|image|video\b", re.IGNORECASE)),
]
_DAMAGE_ISSUE_TYPES = {"damaged_product", "defective_product"}


def evaluate_refund_policy(
    policy: RefundPolicy | None,
    ticket_analysis: TicketAnalysisResult | None = None,
    purchase_information: PurchaseInformation | None = None,
    visual_analysis: VisualAnalysisResult | None = None,
    now: datetime | None = None,
) -> PolicyEvaluationResult:
    """Assess every policy rule against the available case information.

    Args:
        policy: Extracted (or backend-assembled) refund policy; None means
            no policy was supplied.
        ticket_analysis: Ticket analysis result (issue type, mentioned
            dates, requested resolution).
        purchase_information: Receipt/order facts extracted from evidence.
        visual_analysis: Vision result for the customer photograph(s).
        now: Reference date for window checks (defaults to today; tests
            inject a fixed date).

    Returns:
        PolicyEvaluationResult — always ``requires_human_review=True``.
    """
    if policy is None or not policy.rules:
        return _not_provided(policy)

    ticket_analysis = (
        ticket_analysis
        if isinstance(ticket_analysis, TicketAnalysisResult)
        else None
    )
    has_receipt = purchase_information is not None and bool(
        purchase_information.evidence_id
    )
    photo_supplied = (
        visual_analysis is not None
        and visual_analysis.status is not VisionStatus.FAILED
    )
    photo_observations = bool(
        visual_analysis and visual_analysis.visual_observations
    )

    issue_type = ticket_analysis.issue_type if ticket_analysis else None
    purchase_date = (
        ticket_analysis.purchase_date_mentioned
        if ticket_analysis and ticket_analysis.purchase_date_mentioned
        else purchase_information.purchase_date
        if purchase_information
        else None
    )
    delivery_date = (
        ticket_analysis.delivery_date_mentioned if ticket_analysis else None
    )
    reference = now or datetime.now()

    assessments: list[PolicyRuleAssessment] = []
    missing_information: list[str] = []
    for rule in policy.rules:
        assessment, missing = _assess_rule(
            rule,
            issue_type=issue_type,
            purchase_date=purchase_date,
            delivery_date=delivery_date,
            has_receipt=has_receipt,
            photo_supplied=photo_supplied,
            photo_observations=photo_observations,
            receipt_evidence_id=(
                purchase_information.evidence_id if purchase_information else None
            ),
            photo_evidence_id=(
                visual_analysis.evidence_id if visual_analysis else None
            ),
            reference=reference,
        )
        assessments.append(assessment)
        missing_information.extend(missing)

    warnings = list(policy.policy_extraction_warnings)
    met = sum(1 for a in assessments if a.assessment is RuleAssessment.MET)
    partial = sum(1 for a in assessments if a.assessment is RuleAssessment.PARTIALLY_MET)
    unmet = sum(1 for a in assessments if a.assessment is RuleAssessment.NOT_MET)
    not_assessable = sum(
        1 for a in assessments if a.assessment is RuleAssessment.NOT_ASSESSABLE
    )

    if not any(
        a.assessment is not RuleAssessment.NOT_ASSESSABLE for a in assessments
    ):
        warnings.append(
            ExtractionWarning(
                code="policy_requires_human_interpretation",
                message=(
                    "No policy rule could be deterministically assessed from "
                    "the available case information; a human support agent "
                    "must interpret the policy."
                ),
            )
        )
        return PolicyEvaluationResult(
            policy_id=policy.policy_id,
            policy_name=policy.policy_name,
            status=PolicyEvaluationStatus.POLICY_REQUIRES_HUMAN_INTERPRETATION,
            rule_assessments=assessments,
            unmet_conditions=[],
            missing_information=list(dict.fromkeys(missing_information)),
            warnings=warnings,
            explanation=(
                "The supplied policy could not be deterministically "
                "evaluated: none of its rules could be assessed from the "
                "available case information. A human support agent must "
                "interpret the policy for this case."
            ),
            requires_human_review=True,
        )

    unmet_conditions = [
        rule.condition
        for rule, assessment in zip(policy.rules, assessments)
        if assessment.assessment
        in (RuleAssessment.NOT_MET, RuleAssessment.PARTIALLY_MET)
    ]
    explanation = (
        f"Evaluated {len(assessments)} policy rule(s) against the available "
        f"case information: {met} met, {partial} partially met, {unmet} not "
        f"met, {not_assessable} not deterministically assessable. "
        + (
            f"Missing information: {'; '.join(dict.fromkeys(missing_information))}."
            if missing_information
            else "No missing information was identified."
        )
    )
    return PolicyEvaluationResult(
        policy_id=policy.policy_id,
        policy_name=policy.policy_name,
        status=PolicyEvaluationStatus.EVALUATED,
        rule_assessments=assessments,
        unmet_conditions=unmet_conditions,
        missing_information=list(dict.fromkeys(missing_information)),
        warnings=warnings,
        explanation=explanation,
        requires_human_review=True,
    )


def _not_provided(policy: RefundPolicy | None) -> PolicyEvaluationResult:
    warnings: list[ExtractionWarning] = []
    if policy is not None:
        warnings = list(policy.policy_extraction_warnings)
        warnings.append(
            ExtractionWarning(
                code="policy_rules_missing",
                message=(
                    "The supplied policy contains no extractable rules; a "
                    "human support agent must interpret the policy."
                ),
            )
        )
        return PolicyEvaluationResult(
            policy_id=policy.policy_id,
            policy_name=policy.policy_name,
            status=PolicyEvaluationStatus.POLICY_REQUIRES_HUMAN_INTERPRETATION,
            rule_assessments=[],
            unmet_conditions=[],
            missing_information=[
                "The supplied refund policy could not be parsed into rules; "
                "the policy text may be unreadable or contain no evaluable "
                "conditions."
            ],
            warnings=warnings,
            explanation=(
                "A refund policy was supplied but no rules could be "
                "extracted from it. A human support agent must interpret "
                "the policy for this case."
            ),
            requires_human_review=True,
        )
    warnings.append(
        ExtractionWarning(
            code="policy_not_provided",
            message=(
                "No refund policy was supplied for this case; no policy "
                "conditions could be evaluated."
            ),
        )
    )
    return PolicyEvaluationResult(
        policy_id=None,
        policy_name=None,
        status=PolicyEvaluationStatus.POLICY_NOT_PROVIDED,
        rule_assessments=[],
        unmet_conditions=[],
        missing_information=["The seller's refund/return policy was not supplied."],
        warnings=warnings,
        explanation=(
            "No seller refund policy was supplied, so no policy conditions "
            "could be evaluated. A human support agent must decide how to "
            "handle this case."
        ),
        requires_human_review=True,
    )


def _assess_rule(
    rule: PolicyRule,
    *,
    issue_type: str | None,
    purchase_date: datetime | None,
    delivery_date: datetime | None,
    has_receipt: bool,
    photo_supplied: bool,
    photo_observations: bool,
    receipt_evidence_id: str | None,
    photo_evidence_id: str | None,
    reference: datetime,
) -> tuple[PolicyRuleAssessment, list[str]]:
    base = dict(
        rule_id=rule.rule_id,
        condition=rule.condition,
        category=rule.category,
        source_quote=rule.source_quote,
    )
    if rule.category is PolicyRuleCategory.RETURN_WINDOW:
        return _assess_return_window(
            rule,
            purchase_date=purchase_date,
            delivery_date=delivery_date,
            receipt_evidence_id=receipt_evidence_id,
            reference=reference,
            **base,
        )
    if rule.category is PolicyRuleCategory.PROOF_REQUIREMENT:
        return _assess_proof_requirement(
            rule,
            has_receipt=has_receipt,
            photo_supplied=photo_supplied,
            receipt_evidence_id=receipt_evidence_id,
            photo_evidence_id=photo_evidence_id,
            **base,
        )
    if rule.category in (
        PolicyRuleCategory.DAMAGED_ON_ARRIVAL,
        PolicyRuleCategory.DEFECTIVE_PRODUCT,
    ):
        return _assess_damage_rule(
            rule,
            issue_type=issue_type,
            photo_supplied=photo_supplied,
            photo_observations=photo_observations,
            photo_evidence_id=photo_evidence_id,
            **base,
        )
    if rule.category is PolicyRuleCategory.PACKAGING_REQUIREMENT:
        return (
            PolicyRuleAssessment(
                **base,
                assessment=RuleAssessment.NOT_ASSESSABLE,
                explanation=(
                    "Whether the item is still in its original packaging "
                    "is unknown and cannot be checked deterministically."
                ),
            ),
            ["Whether the item is still in its original packaging."],
        )
    return (
        PolicyRuleAssessment(
            **base,
            assessment=RuleAssessment.NOT_ASSESSABLE,
            explanation=(
                "This is an informational policy statement; it does not "
                "impose a deterministically evaluable condition on this case."
            ),
        ),
        [],
    )


def _assess_return_window(
    rule: PolicyRule,
    *,
    purchase_date: datetime | None,
    delivery_date: datetime | None,
    receipt_evidence_id: str | None,
    reference: datetime,
    **base,
) -> tuple[PolicyRuleAssessment, list[str]]:
    match = _WINDOW_PATTERN.search(rule.condition)
    if not match:
        return (
            PolicyRuleAssessment(
                **base,
                assessment=RuleAssessment.NOT_ASSESSABLE,
                explanation=(
                    "The rule does not state a numeric return window, so it "
                    "cannot be checked deterministically."
                ),
            ),
            [],
        )
    window_days = int(match.group(1))
    anchor = purchase_date
    anchor_label = "purchase date"
    if re.search(r"\bdeliver", rule.condition, re.IGNORECASE) and delivery_date:
        anchor = delivery_date
        anchor_label = "delivery date"
    if anchor is None:
        return (
            PolicyRuleAssessment(
                **base,
                assessment=RuleAssessment.NOT_ASSESSABLE,
                explanation=(
                    f"The {anchor_label} is unknown, so the stated "
                    f"{window_days}-day window cannot be checked."
                ),
            ),
            [f"The {anchor_label}, needed to check the return window."],
        )
    days_elapsed = max(0, (reference.date() - anchor.date()).days)
    evidence_ids = [receipt_evidence_id] if receipt_evidence_id else []
    if days_elapsed <= window_days:
        return (
            PolicyRuleAssessment(
                **base,
                assessment=RuleAssessment.MET,
                evidence_ids=evidence_ids,
                explanation=(
                    f"The {anchor_label} ({anchor.date().isoformat()}) is "
                    f"{days_elapsed} day(s) before the reference date, within "
                    f"the stated {window_days}-day window."
                ),
            ),
            [],
        )
    return (
        PolicyRuleAssessment(
            **base,
            assessment=RuleAssessment.NOT_MET,
            evidence_ids=evidence_ids,
            explanation=(
                f"The {anchor_label} ({anchor.date().isoformat()}) is "
                f"{days_elapsed} day(s) before the reference date, outside "
                f"the stated {window_days}-day window."
            ),
        ),
        [],
    )


def _assess_proof_requirement(
    rule: PolicyRule,
    *,
    has_receipt: bool,
    photo_supplied: bool,
    receipt_evidence_id: str | None,
    photo_evidence_id: str | None,
    **base,
) -> tuple[PolicyRuleAssessment, list[str]]:
    required: list[str] = [
        label
        for label, pattern in _PROOF_PATTERNS
        if pattern.search(rule.condition)
    ]
    if not required:
        return (
            PolicyRuleAssessment(
                **base,
                assessment=RuleAssessment.NOT_ASSESSABLE,
                explanation=(
                    "The rule mentions no recognizable proof type, so it "
                    "cannot be checked deterministically."
                ),
            ),
            [],
        )
    satisfied: list[str] = []
    missing: list[str] = []
    for label in required:
        present = has_receipt if label == "receipt/invoice" else photo_supplied
        (satisfied if present else missing).append(label)
    evidence_ids = [
        evidence_id
        for evidence_id in (receipt_evidence_id, photo_evidence_id)
        if evidence_id
    ]
    explanation = (
        f"Proof types required by the rule: {', '.join(required)}. "
        f"Supplied: {', '.join(satisfied) if satisfied else 'none'}."
    )
    if not missing:
        return (
            PolicyRuleAssessment(
                **base,
                assessment=RuleAssessment.MET,
                evidence_ids=evidence_ids,
                explanation=explanation,
            ),
            [],
        )
    if satisfied:
        return (
            PolicyRuleAssessment(
                **base,
                assessment=RuleAssessment.PARTIALLY_MET,
                evidence_ids=evidence_ids,
                explanation=explanation,
            ),
            [f"Missing proof type(s): {', '.join(missing)}."],
        )
    return (
        PolicyRuleAssessment(
            **base,
            assessment=RuleAssessment.NOT_MET,
            evidence_ids=evidence_ids,
            explanation=explanation,
        ),
        [f"Missing proof type(s): {', '.join(missing)}."],
    )


def _assess_damage_rule(
    rule: PolicyRule,
    *,
    issue_type: str | None,
    photo_supplied: bool,
    photo_observations: bool,
    photo_evidence_id: str | None,
    **base,
) -> tuple[PolicyRuleAssessment, list[str]]:
    relevant = issue_type in _DAMAGE_ISSUE_TYPES if issue_type else None
    if relevant is False:
        return (
            PolicyRuleAssessment(
                **base,
                assessment=RuleAssessment.NOT_MET,
                explanation=(
                    f"The customer reported issue type {issue_type!r}, which "
                    "does not match this rule's condition."
                ),
            ),
            [],
        )
    if not photo_supplied:
        return (
            PolicyRuleAssessment(
                **base,
                assessment=RuleAssessment.NOT_ASSESSABLE,
                explanation=(
                    "No readable customer photograph was supplied, so "
                    "visible damage cannot be assessed."
                ),
            ),
            ["A readable customer photograph of the product."],
        )
    evidence_ids = [photo_evidence_id] if photo_evidence_id else []
    if photo_observations:
        return (
            PolicyRuleAssessment(
                **base,
                assessment=RuleAssessment.MET,
                evidence_ids=evidence_ids,
                explanation=(
                    "The customer photograph shows visually observable "
                    "irregularities consistent with this rule's condition."
                ),
            ),
            [],
        )
    if issue_type in _DAMAGE_ISSUE_TYPES:
        return (
            PolicyRuleAssessment(
                **base,
                assessment=RuleAssessment.PARTIALLY_MET,
                evidence_ids=evidence_ids,
                explanation=(
                    "The customer reported damage, and a photograph was "
                    "supplied, but the visual analysis reported no clearly "
                    "observable irregularities."
                ),
            ),
            [],
        )
    return (
        PolicyRuleAssessment(
            **base,
            assessment=RuleAssessment.NOT_ASSESSABLE,
            explanation=(
                "A photograph was supplied but neither the ticket nor the "
                "visual analysis establishes this rule's condition."
            ),
        ),
        [],
    )
