"""Tests for services.policy_evaluator: honest, traceable rule assessment."""

from datetime import datetime

from proofbridge_ai.schemas import (
    IssueType,
    PolicyEvaluationStatus,
    PolicyRule,
    PolicyRuleCategory,
    PurchaseInformation,
    RefundPolicy,
    RuleAssessment,
    TicketAnalysisResult,
    VisionStatus,
    VisualAnalysisResult,
)
from proofbridge_ai.services import policy_evaluator
from proofbridge_ai.services.policy_evaluator import evaluate_refund_policy

NOW = datetime(2026, 11, 10, 12, 0, 0)


def _rule(
    rule_id="p-rule-1",
    condition="Items can be returned within 30 days of purchase.",
    category=PolicyRuleCategory.RETURN_WINDOW,
) -> PolicyRule:
    return PolicyRule(rule_id=rule_id, condition=condition, category=category)


def _policy(*rules: PolicyRule) -> RefundPolicy:
    return RefundPolicy(policy_id="pol-1", policy_name="Store Policy", rules=list(rules))


def _ticket(issue_type=IssueType.DAMAGED_PRODUCT, purchase=None, delivery=None):
    return TicketAnalysisResult(
        case_id="C-1",
        issue_type=issue_type,
        purchase_date_mentioned=purchase,
        delivery_date_mentioned=delivery,
    )


def _purchase(evidence_id="evt-receipt", purchase_date=None) -> PurchaseInformation:
    return PurchaseInformation(evidence_id=evidence_id, purchase_date=purchase_date)


def _visual(evidence_id="evt-photo", observations=("A visible crack",)) -> VisualAnalysisResult:
    return VisualAnalysisResult(
        evidence_id=evidence_id,
        status=VisionStatus.ANALYZED,
        visual_observations=[
            {"observation": text, "confidence": 0.8} for text in observations
        ],
    )


def test_no_policy_returns_policy_not_provided():
    result = evaluate_refund_policy(None, ticket_analysis=_ticket())
    assert result.status is PolicyEvaluationStatus.POLICY_NOT_PROVIDED
    assert any(w.code == "policy_not_provided" for w in result.warnings)
    assert result.missing_information
    assert result.requires_human_review is True


def test_policy_without_rules_requires_human_interpretation():
    result = evaluate_refund_policy(_policy(), ticket_analysis=_ticket())
    assert result.status is PolicyEvaluationStatus.POLICY_REQUIRES_HUMAN_INTERPRETATION
    assert any(w.code == "policy_rules_missing" for w in result.warnings)


def test_window_met_when_complaint_within_days():
    result = evaluate_refund_policy(
        _policy(_rule()),
        ticket_analysis=_ticket(purchase=datetime(2026, 10, 31)),
        now=NOW,
    )
    assert result.status is PolicyEvaluationStatus.EVALUATED
    assert result.rule_assessments[0].assessment is RuleAssessment.MET
    assert result.unmet_conditions == []


def test_window_not_met_for_late_complaint():
    result = evaluate_refund_policy(
        _policy(_rule()),
        ticket_analysis=_ticket(purchase=datetime(2026, 9, 1)),
        now=NOW,
    )
    assert result.status is PolicyEvaluationStatus.EVALUATED
    assert result.rule_assessments[0].assessment is RuleAssessment.NOT_MET
    assert result.unmet_conditions == [result.rule_assessments[0].condition]


def test_window_uses_delivery_date_when_rule_mentions_delivery():
    rule = _rule(condition="Returns accepted within 14 days of delivery.")
    result = evaluate_refund_policy(
        _policy(rule),
        ticket_analysis=_ticket(
            purchase=datetime(2026, 9, 1), delivery=datetime(2026, 11, 5)
        ),
        now=NOW,
    )
    assert result.rule_assessments[0].assessment is RuleAssessment.MET


def test_window_not_assessable_without_date():
    result = evaluate_refund_policy(
        _policy(_rule()), ticket_analysis=_ticket(purchase=None), now=NOW
    )
    assert result.status is PolicyEvaluationStatus.POLICY_REQUIRES_HUMAN_INTERPRETATION
    assert result.rule_assessments[0].assessment is RuleAssessment.NOT_ASSESSABLE
    assert any("purchase date" in item for item in result.missing_information)


def test_proof_requirement_met_with_receipt_and_photo():
    rule = _rule(
        rule_id="p-rule-2",
        condition="Customers must provide a receipt and a photograph.",
        category=PolicyRuleCategory.PROOF_REQUIREMENT,
    )
    result = evaluate_refund_policy(
        _policy(rule),
        ticket_analysis=_ticket(),
        purchase_information=_purchase(),
        visual_analysis=_visual(),
        now=NOW,
    )
    assessment = result.rule_assessments[0]
    assert assessment.assessment is RuleAssessment.MET
    assert set(assessment.evidence_ids) == {"evt-receipt", "evt-photo"}


def test_proof_requirement_partially_met_with_receipt_only():
    rule = _rule(
        rule_id="p-rule-2",
        condition="Customers must provide a receipt and a photograph.",
        category=PolicyRuleCategory.PROOF_REQUIREMENT,
    )
    result = evaluate_refund_policy(
        _policy(rule), ticket_analysis=_ticket(), purchase_information=_purchase()
    )
    assessment = result.rule_assessments[0]
    assert assessment.assessment is RuleAssessment.PARTIALLY_MET
    assert any("photograph" in item for item in result.missing_information)


def test_proof_requirement_not_met_without_any_proof():
    rule = _rule(
        rule_id="p-rule-2",
        condition="Customers must provide a receipt and a photograph.",
        category=PolicyRuleCategory.PROOF_REQUIREMENT,
    )
    result = evaluate_refund_policy(_policy(rule), ticket_analysis=_ticket())
    assert result.rule_assessments[0].assessment is RuleAssessment.NOT_MET


def test_damage_rule_met_with_photo_observations():
    rule = _rule(
        rule_id="p-rule-3",
        condition="Damaged on arrival items qualify for a refund.",
        category=PolicyRuleCategory.DAMAGED_ON_ARRIVAL,
    )
    result = evaluate_refund_policy(
        _policy(rule), ticket_analysis=_ticket(), visual_analysis=_visual()
    )
    assert result.rule_assessments[0].assessment is RuleAssessment.MET


def test_damage_rule_not_met_for_unrelated_issue():
    rule = _rule(
        rule_id="p-rule-3",
        condition="Damaged on arrival items qualify for a refund.",
        category=PolicyRuleCategory.DAMAGED_ON_ARRIVAL,
    )
    result = evaluate_refund_policy(
        _policy(rule), ticket_analysis=_ticket(issue_type=IssueType.LATE_DELIVERY)
    )
    assert result.rule_assessments[0].assessment is RuleAssessment.NOT_MET


def test_informational_rule_only_requires_human_interpretation():
    rule = _rule(
        rule_id="p-rule-4",
        condition="Damaged items may be replaced free of charge.",
        category=PolicyRuleCategory.REPLACEMENT_OPTION,
    )
    result = evaluate_refund_policy(_policy(rule), ticket_analysis=_ticket())
    assert result.status is PolicyEvaluationStatus.POLICY_REQUIRES_HUMAN_INTERPRETATION
    assert result.rule_assessments[0].assessment is RuleAssessment.NOT_ASSESSABLE
