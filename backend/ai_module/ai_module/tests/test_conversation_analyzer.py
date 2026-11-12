"""Tests for conversation (chat export) analysis."""

import pytest

from _fakes import FakeLLMProvider
from proofbridge_ai.exceptions import InputValidationError, ProviderError
from proofbridge_ai.schemas import (
    AnalysisSource,
    ConversationSpeaker,
    EvidenceItem,
    EvidenceKind,
)
from proofbridge_ai.services import conversation_analyzer
from proofbridge_ai.services.conversation_analyzer import _ConversationInsights

CHAT_EXPORT = """\
[2026-11-02 10:12] Customer: My headphones arrived with a cracked left ear cup.
[2026-11-02 10:15] Seller: We are sorry to hear that. We understand your frustration.
[2026-11-02 10:16] Seller: We will issue a full refund once you send photos.
[2026-11-02 10:20] Customer: I reported the issue on November 2, 2026.
[2026-11-03 09:00] Seller: We cannot refund this order because it is outside our policy.
"""


def make_item(text=CHAT_EXPORT, evidence_id="CHAT-1") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        filename="chat-export.txt",
        kind=EvidenceKind.TEXT,
        extracted_text=text,
    )


def test_speakers_attributed_and_timestamps_preserved():
    result = conversation_analyzer.analyze_conversation(make_item())
    assert len(result.messages) == 5
    assert result.messages[0].speaker is ConversationSpeaker.CUSTOMER
    assert result.messages[1].speaker is ConversationSpeaker.SELLER
    assert result.messages[0].timestamp == "2026-11-02 10:12"
    assert result.messages[0].source_reference == "line 1"
    assert any("cracked left ear cup" in s for s in result.customer_statements)
    assert any("full refund" in s for s in result.seller_statements)


def test_promises_acknowledgements_contradictions_heuristic():
    result = conversation_analyzer.analyze_conversation(make_item())
    assert any("full refund" in p for p in result.refund_promises)
    assert any("sorry" in a for a in result.acknowledgements)
    assert any("inconsistent" in c for c in result.contradictions)
    assert any("November 2, 2026" in d for d in result.reported_complaint_dates)
    assert result.source is AnalysisSource.HEURISTIC


def test_customer_statements_are_not_verified_facts():
    result = conversation_analyzer.analyze_conversation(make_item())
    # The analysis preserves statements verbatim but never asserts truth:
    for statement in result.customer_statements:
        assert statement  # recorded
    assert result.requires_human_review is True


def test_unparseable_text_warns():
    result = conversation_analyzer.analyze_conversation(
        make_item(text="This is not a chat format at all.")
    )
    assert result.messages == []
    assert any(w.code == "no_messages_parsed" for w in result.warnings)


def test_llm_insights_used_when_available():
    fake = FakeLLMProvider(
        _ConversationInsights(
            refund_promises=["We will issue a full refund once you send photos."],
            acknowledgements=["We are sorry to hear that."],
            contradictions=["The seller first promised a refund and later refused it."],
        )
    )
    result = conversation_analyzer.analyze_conversation(make_item(), llm=fake)
    assert result.source is AnalysisSource.LLM
    assert result.provider_name == "fake-llm"
    assert "later refused" in result.contradictions[0]


def test_llm_failure_falls_back_to_heuristics():
    fake = FakeLLMProvider(error=ProviderError("boom", provider="fake"))
    result = conversation_analyzer.analyze_conversation(make_item(), llm=fake)
    assert result.source is AnalysisSource.HEURISTIC
    assert any(w.code == "conversation_llm_fallback" for w in result.warnings)
    assert any("full refund" in p for p in result.refund_promises)


def test_invalid_input_raises():
    with pytest.raises(InputValidationError):
        conversation_analyzer.analyze_conversation("not an item")  # type: ignore[arg-type]
