from pydantic import BaseModel, Field

from proofbridge_ai.providers.base import VisionImage
from proofbridge_ai.providers.mock_provider import (
    MockEmbeddingsProvider,
    MockLLMProvider,
    MockVisionProvider,
)
from proofbridge_ai.schemas import IssueType, TicketAnalysisResult


class _VisionBoundaryModel(BaseModel):
    """Minimal LLM-boundary model used by the mock vision provider tests."""

    observations: list[str] = Field(default_factory=list)
    image_quality: str = "sufficient"


def test_generate_json_returns_valid_model_instance():
    provider = MockLLMProvider()
    result = provider.generate_json("system", "user", TicketAnalysisResult)
    assert isinstance(result, TicketAnalysisResult)
    assert result.case_id
    assert result.issue_type in IssueType


def test_generate_json_is_deterministic():
    provider = MockLLMProvider()
    first = provider.generate_json("system", "user", TicketAnalysisResult)
    second = provider.generate_json("system", "user", TicketAnalysisResult)
    assert first.model_dump() == second.model_dump()


def test_chat_never_echoes_prompt_content():
    provider = MockLLMProvider()
    secret = "SECRET-DOCUMENT-CONTENT-98765"
    output = provider.chat("system prompt", secret)
    assert output.startswith("MOCK:")
    assert secret not in output


def test_embeddings_deterministic_and_normalized():
    provider = MockEmbeddingsProvider()
    first = provider.embed_texts(["homepage development", "login page"])
    second = provider.embed_texts(["homepage development", "login page"])
    assert first == second
    assert provider.dimensions == 384
    assert all(len(v) == 384 for v in first)
    for vector in first:
        norm = sum(x * x for x in vector)
        assert abs(norm - 1.0) < 1e-9


def test_shared_vocabulary_yields_higher_similarity():
    provider = MockEmbeddingsProvider()
    similar_a = provider.embed_query("login page authentication form")
    similar_b = provider.embed_query("login page user authentication")
    unrelated = provider.embed_query("refund policy payment invoice")
    dot = lambda x, y: sum(a * b for a, b in zip(x, y))
    assert dot(similar_a, similar_b) > dot(similar_a, unrelated)


def test_empty_text_yields_zero_vector():
    provider = MockEmbeddingsProvider()
    vector = provider.embed_query("")
    assert sum(vector) == 0.0


def test_mock_vision_provider_is_labeled_and_schema_valid():
    provider = MockVisionProvider()
    assert provider.is_mock is True
    image = VisionImage(image_bytes=b"\x89PNG-fake-bytes", media_type="image/png")
    result = provider.analyze_image(
        image, "system", "describe the image", _VisionBoundaryModel
    )
    assert isinstance(result, _VisionBoundaryModel)
    assert result.image_quality == "sufficient"
    # The mock provider never fabricates observations: generic fill yields
    # an empty list, and the vision service adds the labeled mock note.
    assert result.observations == []
