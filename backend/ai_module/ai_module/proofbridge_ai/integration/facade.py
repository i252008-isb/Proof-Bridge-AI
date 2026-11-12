"""Stable integration facade for the backend (Person 2).

The module-level functions are thin re-exports of the service functions:
their signatures and docstrings live with the services, so the documented
API surface can never drift from the implementation. Each function accepts
an optional ``settings`` override (tests, alternate configurations).

``ProofBridgeAIFacade`` offers the same operations as methods with the
settings bound once at construction; ``get_facade()`` returns a cached
process-wide instance built from the current configuration.

The AI module stays independent of the backend database: nothing here
creates database records, manages authentication, or moves money.
"""

from __future__ import annotations

from functools import lru_cache

from proofbridge_ai.config import Settings, get_settings
from proofbridge_ai.services.document_extractor import (
    extract_document,
    extract_document_text,
)
from proofbridge_ai.services.evidence_extractor import (
    extract_evidence,
    extract_evidence_batch,
)
from proofbridge_ai.services.policy_extractor import extract_refund_policy
from proofbridge_ai.services.report_generator import (
    generate_investigation_report,
)
from proofbridge_ai.services.similarity_engine import compare_support_evidence
from proofbridge_ai.services.support_case_analyzer import (
    analyze_support_case,
    arun_support_case_analysis,
)
from proofbridge_ai.services.ticket_analyzer import extract_ticket_claims
from proofbridge_ai.services.vision_analyzer import analyze_visual_evidence

__all__ = [
    "ProofBridgeAIFacade",
    "get_facade",
    # module-level integration functions
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


class ProofBridgeAIFacade:
    """Settings-bound facade over the complete AI investigation surface.

    Construct once (optionally with a custom ``Settings``) and call the
    methods; the backend never needs to thread settings through calls.
    Methods mirror the module-level functions minus the ``settings``
    parameter, which is injected from the instance.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def settings(self) -> Settings:
        return self._settings

    def extract_document(self, file_bytes, filename, content_type=None):
        return extract_document(
            file_bytes, filename, content_type, settings=self._settings
        )

    def extract_document_text(self, file_bytes, filename, content_type=None):
        return extract_document_text(
            file_bytes, filename, content_type, settings=self._settings
        )

    def extract_ticket_claims(self, ticket, llm=None):
        return extract_ticket_claims(ticket, settings=self._settings, llm=llm)

    def extract_evidence(self, file_bytes, evidence_input, content_type=None):
        return extract_evidence(
            file_bytes, evidence_input, content_type, settings=self._settings
        )

    def extract_evidence_batch(self, uploads):
        return extract_evidence_batch(uploads, settings=self._settings)

    def analyze_visual_evidence(
        self,
        file_bytes,
        evidence_input,
        content_type=None,
        reference_file_bytes=None,
        reference_evidence_input=None,
        vision=None,
    ):
        return analyze_visual_evidence(
            file_bytes,
            evidence_input,
            content_type=content_type,
            reference_file_bytes=reference_file_bytes,
            reference_evidence_input=reference_evidence_input,
            settings=self._settings,
            vision=vision,
        )

    def extract_refund_policy(
        self,
        policy_text=None,
        file_bytes=None,
        filename=None,
        content_type=None,
        policy_id="policy-1",
        policy_name="Refund Policy",
        llm=None,
    ):
        return extract_refund_policy(
            policy_text=policy_text,
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            policy_id=policy_id,
            policy_name=policy_name,
            settings=self._settings,
            llm=llm,
        )

    def compare_support_evidence(self, claims, evidence_items, embeddings=None):
        return compare_support_evidence(
            claims, evidence_items, settings=self._settings, embeddings=embeddings
        )

    async def analyze_support_case(
        self,
        support_ticket,
        evidence_items,
        refund_policy=None,
        order_information=None,
        case_context=None,
    ):
        return await analyze_support_case(
            support_ticket,
            evidence_items,
            refund_policy=refund_policy,
            order_information=order_information,
            case_context=case_context,
            settings=self._settings,
        )

    async def arun_support_case_analysis(
        self,
        support_ticket,
        evidence_items,
        refund_policy=None,
        order_information=None,
        case_context=None,
    ):
        return await arun_support_case_analysis(
            support_ticket,
            evidence_items,
            refund_policy=refund_policy,
            order_information=order_information,
            case_context=case_context,
            settings=self._settings,
        )

    def generate_investigation_report(
        self,
        analysis,
        support_ticket,
        evidence_items=(),
        order_information=None,
        payment_information=None,
        case_context=None,
    ):
        return generate_investigation_report(
            analysis,
            support_ticket,
            evidence_items=evidence_items,
            order_information=order_information,
            payment_information=payment_information,
            case_context=case_context,
            settings=self._settings,
        )


@lru_cache(maxsize=None)
def get_facade() -> ProofBridgeAIFacade:
    """Return the cached process-wide facade built from current settings.

    Tests that need a custom configuration construct
    ``ProofBridgeAIFacade(settings=...)`` directly.
    """
    return ProofBridgeAIFacade()
