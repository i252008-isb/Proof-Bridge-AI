"""Tests for services.similarity_engine: relevance-only claim matching."""

import pytest

from proofbridge_ai.exceptions import InputValidationError, ProviderError
from proofbridge_ai.providers.base import BaseEmbeddingsProvider
from proofbridge_ai.schemas import (
    ClaimSimilarityResult,
    CustomerClaim,
    EvidenceItem,
    EvidenceKind,
    SimilarityMethod,
)
from proofbridge_ai.services import similarity_engine


def _claim(claim_id, text):
    return CustomerClaim(id=claim_id, claim=text)


def _evidence(evidence_id, text):
    return EvidenceItem(
        evidence_id=evidence_id,
        filename=f"{evidence_id}.txt",
        kind=EvidenceKind.TEXT,
        extracted_text=text,
    )


class FailingEmbeddingsProvider(BaseEmbeddingsProvider):
    name = "failing"
    is_mock = False

    def embed_texts(self, texts):
        raise ProviderError("embeddings down", provider="failing")

    def embed_query(self, text):
        raise ProviderError("embeddings down", provider="failing")


def test_relevant_evidence_scores_higher_than_unrelated():
    claims = [_claim("claim-1", "The left ear cup of my headphones is cracked")]
    evidence = [
        _evidence("evt-photo", "photo of the damaged left ear cup with a crack"),
        _evidence("evt-receipt", "receipt for a wireless headphones order"),
        _evidence("evt-policy", "return policy: items accepted within 30 days"),
    ]
    result = similarity_engine.compare_support_evidence(claims, evidence)
    assert isinstance(result, ClaimSimilarityResult)
    scores = {match.evidence_id: match.score for match in result.matches}
    assert scores.get("evt-photo", 0.0) > scores.get("evt-policy", 0.0)
    assert result.method is SimilarityMethod.EMBEDDINGS
    assert any("mock" in lim for lim in result.limitations)


def test_empty_inputs_return_empty_matches():
    empty = similarity_engine.compare_support_evidence([], [_evidence("e", "text")])
    assert empty.matches == []
    empty_evidence = similarity_engine.compare_support_evidence([_claim("c", "text")], [])
    assert empty_evidence.matches == []


def test_invalid_inputs_raise():
    with pytest.raises(InputValidationError):
        similarity_engine.compare_support_evidence("not-a-list", [])
    with pytest.raises(InputValidationError):
        similarity_engine.compare_support_evidence([], "not-a-list")


def test_lexical_fallback_on_provider_error():
    claims = [_claim("claim-1", "my headphones arrived with a cracked ear cup")]
    evidence = [
        _evidence("evt-photo", "headphones with a cracked ear cup"),
        _evidence("evt-policy", "return policy"),
    ]
    result = similarity_engine.compare_support_evidence(
        claims, evidence, embeddings=FailingEmbeddingsProvider()
    )
    assert result.method is SimilarityMethod.LEXICAL
    scores = {match.evidence_id: match.score for match in result.matches}
    assert scores.get("evt-photo", 0.0) > scores.get("evt-policy", 0.0)
    assert any("lexical" in lim for lim in result.limitations)


def test_scores_are_bounded_and_positive():
    claims = [_claim("claim-1", "cracked ear cup")]
    evidence = [_evidence("evt-photo", "cracked ear cup")]
    result = similarity_engine.compare_support_evidence(claims, evidence)
    assert result.matches
    for match in result.matches:
        assert 0.0 < match.score <= 1.0


def test_only_top_candidates_kept_per_claim():
    claims = [_claim("claim-1", "damaged product")]
    evidence = [
        _evidence(f"evt-{n}", f"damaged product evidence {n}")
        for n in range(10)
    ]
    result = similarity_engine.compare_support_evidence(claims, evidence)
    per_claim = [m for m in result.matches if m.claim_id == "claim-1"]
    assert len(per_claim) <= 5


def test_evidence_without_text_scores_zero():
    claims = [_claim("claim-1", "cracked ear cup")]
    evidence = [
        _evidence("evt-empty", ""),
        _evidence("evt-photo", "cracked ear cup"),
    ]
    result = similarity_engine.compare_support_evidence(
        claims, evidence, embeddings=FailingEmbeddingsProvider()
    )
    assert all(m.evidence_id != "evt-empty" for m in result.matches)
