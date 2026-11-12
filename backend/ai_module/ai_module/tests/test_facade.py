"""Tests for the integration facade surface."""

import asyncio
from datetime import datetime

import pytest

import proofbridge_ai
from proofbridge_ai import (
    ProofBridgeAIFacade,
    analyze_support_case,
    analyze_visual_evidence,
    arun_support_case_analysis,
    compare_support_evidence,
    extract_document,
    extract_document_text,
    extract_evidence,
    extract_evidence_batch,
    extract_refund_policy,
    extract_ticket_claims,
    generate_investigation_report,
    get_facade,
)
from proofbridge_ai.config import Settings
from proofbridge_ai.schemas import (
    EvidenceInput,
    EvidenceUpload,
    EvidenceKind,
    InvestigationReport,
    RefundPolicy,
    SupportCaseAnalysisResult,
    SupportTicket,
    TicketAnalysisResult,
)


def test_module_level_surface_is_complete():
    for name in (
        "extract_document",
        "extract_document_text",
        "extract_ticket_claims",
        "extract_evidence",
        "extract_evidence_batch",
        "analyze_visual_evidence",
        "extract_refund_policy",
        "compare_support_evidence",
        "analyze_support_case",
        "arun_support_case_analysis",
        "generate_investigation_report",
        "ProofBridgeAIFacade",
        "get_facade",
    ):
        assert hasattr(proofbridge_ai, name), name
        assert name in proofbridge_ai.__all__, name


def test_get_facade_returns_cached_instance():
    assert get_facade() is get_facade()
    assert isinstance(get_facade(), ProofBridgeAIFacade)


def test_facade_extract_document_and_text():
    facade = ProofBridgeAIFacade(Settings(demo_mode=True))
    result = facade.extract_document(
        b"Agreement line one.\nLine two.",
        "notes.txt",
    )
    assert result.normalized_text
    assert (
        facade.extract_document_text(b"Just some text.", "notes.txt")
        == "Just some text."
    )


def test_facade_extract_ticket_claims_uses_bound_settings():
    facade = ProofBridgeAIFacade(Settings(demo_mode=True))
    ticket = SupportTicket(
        case_id="case-1",
        complaint="The headphones arrived damaged and I want a refund.",
    )
    result = facade.extract_ticket_claims(ticket)
    assert isinstance(result, TicketAnalysisResult)
    assert result.case_id == "case-1"
    assert result.requires_human_review is True


def test_facade_extract_evidence_and_batch():
    facade = ProofBridgeAIFacade(Settings(demo_mode=True))
    item = facade.extract_evidence(
        b"Receipt\nOrder #ORD-1\nTotal: $49.99",
        EvidenceInput(evidence_id="evt-1", filename="receipt.txt"),
    )
    assert item.evidence_id == "evt-1"
    assert "ORD-1" in item.extracted_text

    batch = facade.extract_evidence_batch(
        [
            EvidenceUpload(
                evidence_input=EvidenceInput(
                    evidence_id="evt-2", filename="chat.txt"
                ),
                file_bytes=b"seller: yes we can help",
            )
        ]
    )
    assert len(batch.items) == 1
    assert batch.items[0].evidence_id == "evt-2"


def test_facade_extract_refund_policy():
    facade = ProofBridgeAIFacade(Settings(demo_mode=True))
    policy = facade.extract_refund_policy(
        policy_text="Items may be returned within 30 days of purchase.",
        policy_id="pol-1",
        policy_name="Store Policy",
    )
    assert isinstance(policy, RefundPolicy)
    assert policy.policy_id == "pol-1"


def test_facade_compare_support_evidence_and_report_roundtrip():
    facade = ProofBridgeAIFacade(Settings(demo_mode=True))
    ticket = SupportTicket(
        case_id="case-2",
        complaint="The left ear cup is cracked.",
    )
    analysis_result = asyncio.run(
        facade.analyze_support_case(
            ticket,
            [
                EvidenceUpload(
                    evidence_input=EvidenceInput(
                        evidence_id="evt-3", filename="receipt.txt"
                    ),
                    file_bytes=(
                        b"Receipt\nOrder #ORD-9\nDate: October 1, 2026\n"
                        b"Total: $49.99\nQuantity: 1"
                    ),
                )
            ],
        )
    )
    assert isinstance(analysis_result, SupportCaseAnalysisResult)

    report = facade.generate_investigation_report(analysis_result, ticket)
    assert isinstance(report, InvestigationReport)
    assert report.case_id == "case-2"
    assert report.human_review_required is True

    alias_result = asyncio.run(
        facade.arun_support_case_analysis(ticket, [])
    )
    assert isinstance(alias_result, SupportCaseAnalysisResult)
    assert alias_result.case_id == "case-2"


def test_module_level_functions_match_services():
    from proofbridge_ai.services import support_case_analyzer as sca
    from proofbridge_ai.services import ticket_analyzer as ta
    from proofbridge_ai.services import vision_analyzer as va
    from proofbridge_ai.services import report_generator as rg

    assert analyze_support_case is sca.analyze_support_case
    assert arun_support_case_analysis is sca.arun_support_case_analysis
    assert extract_ticket_claims is ta.extract_ticket_claims
    assert analyze_visual_evidence is va.analyze_visual_evidence
    assert generate_investigation_report is rg.generate_investigation_report


def test_facade_visual_evidence_mock_is_labeled():
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), color="white").save(buffer, format="PNG")

    facade = ProofBridgeAIFacade(Settings(demo_mode=True))
    result = facade.analyze_visual_evidence(
        buffer.getvalue(),
        EvidenceInput(evidence_id="evt-4", filename="photo.png"),
        content_type="image/png",
    )
    assert result.status.value == "mock"
    assert result.visual_observations == []
    assert any(w.code == "mock_vision_output" for w in result.warnings)


def test_invalid_facade_inputs_raise():
    from proofbridge_ai.exceptions import InputValidationError

    facade = ProofBridgeAIFacade(Settings(demo_mode=True))
    with pytest.raises(InputValidationError):
        facade.extract_evidence(b"", EvidenceInput(evidence_id="e", filename="f.txt"))
    with pytest.raises(InputValidationError):
        facade.extract_document(b"", "empty.txt")


def test_facade_uses_supplied_settings_not_process_default():
    from proofbridge_ai.services.support_case_analyzer import analyze_support_case as svc

    custom = Settings(demo_mode=True)
    facade = ProofBridgeAIFacade(custom)
    assert facade.settings is custom
