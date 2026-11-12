"""Tests for services.policy_extractor: traceable rule extraction."""

import pytest

from _fakes import FakeLLMProvider
from proofbridge_ai.exceptions import InputValidationError, ProviderError
from proofbridge_ai.schemas import (
    AnalysisSource,
    PolicyRuleCategory,
)
from proofbridge_ai.services import policy_extractor
from proofbridge_ai.services.policy_extractor import _PolicyExtractionModel, _PolicyRuleDraft

POLICY_TEXT = (
    "Customers may return items within 30 days of purchase. "
    "A receipt or invoice is required for all returns. "
    "Damaged on arrival items are eligible for a replacement. "
    "Items must be returned in their original packaging."
)


def test_heuristic_extracts_rules_with_verbatim_quotes():
    policy = policy_extractor.extract_refund_policy(policy_text=POLICY_TEXT)
    categories = {rule.category for rule in policy.rules}
    assert PolicyRuleCategory.RETURN_WINDOW in categories
    assert PolicyRuleCategory.PROOF_REQUIREMENT in categories
    assert PolicyRuleCategory.DAMAGED_ON_ARRIVAL in categories
    assert PolicyRuleCategory.PACKAGING_REQUIREMENT in categories
    for rule in policy.rules:
        assert rule.source_quote is not None
        assert rule.source_quote in POLICY_TEXT
        assert rule.condition == rule.source_quote
    assert policy.source is AnalysisSource.HEURISTIC
    assert any(
        w.code == "llm_unavailable_heuristic_used"
        for w in policy.policy_extraction_warnings
    )


def test_damage_sentence_uses_damage_category_not_replacement():
    policy = policy_extractor.extract_refund_policy(
        policy_text="Damaged on arrival items are eligible for a replacement."
    )
    assert [rule.category for rule in policy.rules] == [
        PolicyRuleCategory.DAMAGED_ON_ARRIVAL
    ]


def test_extracts_from_file_bytes():
    policy = policy_extractor.extract_refund_policy(
        file_bytes=POLICY_TEXT.encode(), filename="policy.txt"
    )
    assert any(rule.category is PolicyRuleCategory.RETURN_WINDOW for rule in policy.rules)


def test_empty_document_yields_no_rules_with_warning(empty_pdf_bytes):
    policy = policy_extractor.extract_refund_policy(
        file_bytes=empty_pdf_bytes, filename="policy.pdf"
    )
    assert policy.rules == []
    assert any(w.code == "policy_text_empty" for w in policy.policy_extraction_warnings)


def test_empty_policy_text_raises():
    with pytest.raises(InputValidationError):
        policy_extractor.extract_refund_policy(policy_text="   ")


def test_missing_source_raises():
    with pytest.raises(InputValidationError):
        policy_extractor.extract_refund_policy()


def test_file_bytes_without_filename_raises():
    with pytest.raises(InputValidationError):
        policy_extractor.extract_refund_policy(file_bytes=b"policy text")


def test_llm_path_keeps_verified_quotes_and_drops_invented():
    fake = FakeLLMProvider(
        result=_PolicyExtractionModel(
            rules=[
                _PolicyRuleDraft(
                    condition="Items can be returned within 30 days.",
                    category=PolicyRuleCategory.RETURN_WINDOW,
                    source_quote="Customers may return items within 30 days of purchase.",
                    requires_evidence=False,
                ),
                _PolicyRuleDraft(
                    condition="A made-up condition.",
                    category=PolicyRuleCategory.PROOF_REQUIREMENT,
                    source_quote="This quote does not appear anywhere.",
                    requires_evidence=True,
                ),
                _PolicyRuleDraft(condition="   "),
            ]
        )
    )
    policy = policy_extractor.extract_refund_policy(
        policy_text=POLICY_TEXT, llm=fake
    )
    assert policy.source is AnalysisSource.LLM
    assert policy.provider_name == "fake-llm"
    assert len(policy.rules) == 2
    assert policy.rules[0].source_quote == "Customers may return items within 30 days of purchase."
    assert policy.rules[1].source_quote is None
    assert policy.rules[1].condition == "A made-up condition."
    assert any(w.code == "llm_quote_dropped" for w in policy.policy_extraction_warnings)


def test_llm_failure_falls_back_heuristically():
    fake = FakeLLMProvider(error=ProviderError("boom", provider="fake"))
    policy = policy_extractor.extract_refund_policy(policy_text=POLICY_TEXT, llm=fake)
    assert policy.source is AnalysisSource.HEURISTIC
    assert any(w.code == "llm_extraction_failed" for w in policy.policy_extraction_warnings)
    assert any(
        rule.category is PolicyRuleCategory.RETURN_WINDOW for rule in policy.rules
    )


def test_rule_ids_are_unique_and_sequential():
    policy = policy_extractor.extract_refund_policy(policy_text=POLICY_TEXT)
    ids = [rule.rule_id for rule in policy.rules]
    assert len(ids) == len(set(ids))
    assert ids == [f"policy-1-rule-{n}" for n in range(1, len(ids) + 1)]


def test_rule_count_capped():
    drafts = [
        _PolicyRuleDraft(
            condition=f"Condition number {n}.",
            source_quote=f"Condition number {n}.",
        )
        for n in range(1, 26)
    ]
    text = " ".join(f"Condition number {n}." for n in range(1, 26))
    fake = FakeLLMProvider(result=_PolicyExtractionModel(rules=drafts))
    policy = policy_extractor.extract_refund_policy(policy_text=text, llm=fake)
    assert len(policy.rules) == policy_extractor.MAX_RULES
