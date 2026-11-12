"""Integration layer: the public facade consumed by the backend."""

from proofbridge_ai.integration.facade import (
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

__all__ = [
    "ProofBridgeAIFacade",
    "get_facade",
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
]
