"""Claim-to-evidence relevance matching.

Scores express RELEVANCE ONLY: how likely an evidence item is to be
relevant to a customer claim. They never establish that a claim is true,
that evidence is authentic, or that a refund is due. Embedding providers
are used when available (mock embeddings are labeled as such); a
deterministic lexical fallback (token overlap) is used otherwise and is
never presented as semantic analysis.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from proofbridge_ai.config import Settings, get_settings
from proofbridge_ai.exceptions import InputValidationError, ProofBridgeAIError
from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.providers import get_embeddings_provider
from proofbridge_ai.providers.base import BaseEmbeddingsProvider
from proofbridge_ai.schemas import (
    ClaimEvidenceMatch,
    ClaimSimilarityResult,
    CustomerClaim,
    EvidenceItem,
    SimilarityMethod,
)
from proofbridge_ai.services.text_normalizer import truncate_text

logger = get_logger("services.similarity_engine")

_MAX_TEXT_CHARS = 5000
_TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")


def compare_support_evidence(
    claims: Sequence[CustomerClaim],
    evidence_items: Sequence[EvidenceItem],
    settings: Settings | None = None,
    embeddings: BaseEmbeddingsProvider | None = None,
) -> ClaimSimilarityResult:
    """Score every claim against every evidence item for relevance.

    Per claim, only the top ``similarity_max_candidates`` matches with a
    positive score are kept. A high score means "this evidence looks
    relevant to this claim" — never "the claim is true".

    Raises:
        InputValidationError: claims/evidence_items are not sequences.
    """
    if not isinstance(claims, (list, tuple)):
        raise InputValidationError("claims must be a list of CustomerClaim")
    if not isinstance(evidence_items, (list, tuple)):
        raise InputValidationError("evidence_items must be a list of EvidenceItem")
    settings = settings or get_settings()

    if not claims or not evidence_items:
        return ClaimSimilarityResult(matches=[], method=SimilarityMethod.LEXICAL)

    claim_texts = [_claim_text(claim) for claim in claims]
    evidence_texts = [_evidence_text(item) for item in evidence_items]

    limitations: list[str] = []
    method = SimilarityMethod.EMBEDDINGS

    provider = embeddings if embeddings is not None else get_embeddings_provider(settings)
    if provider is not None and provider.is_mock:
        limitations.append(
            "Relevance scores were computed with the mock embeddings "
            "provider: they are deterministic approximations, not genuine "
            "semantic analysis."
        )
    try:
        scores = _embedding_scores(provider, claim_texts, evidence_texts)
    except (ProofBridgeAIError, ValueError) as exc:
        logger.warning(
            "Embeddings unavailable (%s); using lexical fallback",
            type(exc).__name__,
        )
        method = SimilarityMethod.LEXICAL
        scores = _lexical_scores(claim_texts, evidence_texts)
        limitations.append(
            f"Embedding similarity was unavailable ({type(exc).__name__}); "
            "a deterministic lexical fallback (token overlap) was used. "
            "Lexical scores must never be presented as semantic analysis."
        )

    matches: list[ClaimEvidenceMatch] = []
    for claim_index, claim in enumerate(claims):
        ranked = sorted(
            (
                (score, evidence_index)
                for evidence_index, score in enumerate(scores[claim_index])
                if score > 0.0
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        for score, evidence_index in ranked[: settings.similarity_max_candidates]:
            matches.append(
                ClaimEvidenceMatch(
                    claim_id=claim.id,
                    evidence_id=evidence_items[evidence_index].evidence_id,
                    score=round(min(score, 1.0), 4),
                    method=method,
                )
            )
    return ClaimSimilarityResult(matches=matches, method=method, limitations=limitations)


def _embedding_scores(
    provider: BaseEmbeddingsProvider,
    claim_texts: list[str],
    evidence_texts: list[str],
) -> list[list[float]]:
    claim_vectors = provider.embed_texts(claim_texts)
    evidence_vectors = provider.embed_texts(evidence_texts)
    return [
        [_cosine(claim_vector, evidence_vector) for evidence_vector in evidence_vectors]
        for claim_vector in claim_vectors
    ]


def _cosine(a: list[float], b: list[float]) -> float:
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)


def _lexical_scores(
    claim_texts: list[str], evidence_texts: list[str]
) -> list[list[float]]:
    claim_tokens = [_tokens(text) for text in claim_texts]
    evidence_tokens = [_tokens(text) for text in evidence_texts]
    scores: list[list[float]] = []
    for claim in claim_tokens:
        row: list[float] = []
        for evidence in evidence_tokens:
            if not claim or not evidence:
                row.append(0.0)
                continue
            overlap = len(claim & evidence)
            row.append(overlap / math.sqrt(len(claim) * len(evidence)))
        scores.append(row)
    return scores


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(text.lower()))


def _claim_text(claim: CustomerClaim) -> str:
    text, _ = truncate_text(claim.claim.strip(), _MAX_TEXT_CHARS)
    return text


def _evidence_text(item: EvidenceItem) -> str:
    parts = [
        item.user_description or "",
        item.summary or "",
        item.extracted_text or "",
    ]
    text, _ = truncate_text(" ".join(part for part in parts if part).strip(), _MAX_TEXT_CHARS)
    return text
