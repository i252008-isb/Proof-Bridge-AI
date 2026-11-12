"""Tests for services.vision_analyzer: honest visual-inspection degradation."""

from io import BytesIO

import pytest
from PIL import Image

from _fakes import FakeVisionProvider
from proofbridge_ai.exceptions import InputValidationError, ProviderError
from proofbridge_ai.schemas import (
    AnalysisSource,
    EvidenceInput,
    ImageQuality,
    VisualIssueType,
    VisionStatus,
)
from proofbridge_ai.services import vision_analyzer
from proofbridge_ai.services.vision_analyzer import (
    _ObservationDraft,
    _VisionInspectionModel,
)


def _png_bytes(size=(400, 300)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _evidence(evidence_id="evt-1", filename="photo.png") -> EvidenceInput:
    return EvidenceInput(evidence_id=evidence_id, filename=filename)


def test_mock_provider_is_clearly_labeled_with_no_observations():
    result = vision_analyzer.analyze_visual_evidence(_png_bytes(), _evidence())
    assert result.status is VisionStatus.MOCK
    assert result.provider_name == "mock"
    assert result.source is AnalysisSource.HEURISTIC
    assert result.visual_observations == []
    assert result.possible_issues == []
    assert any(w.code == "mock_vision_output" for w in result.warnings)
    assert any("no genuine image analysis" in lim for lim in result.limitations)
    assert result.requires_human_review is True


def test_unreadable_image_returns_failed_result_not_exception():
    result = vision_analyzer.analyze_visual_evidence(b"not an image", _evidence())
    assert result.status is VisionStatus.FAILED
    assert result.image_quality is ImageQuality.UNCLEAR
    assert result.visual_observations == []
    assert any(w.code == "image_unreadable" for w in result.warnings)
    assert result.requires_human_review is True


def test_fake_provider_success_preserves_observations_and_adds_limitations():
    model = _VisionInspectionModel(
        visual_observations=[
            _ObservationDraft(
                observation="A visible crack along the left edge",
                confidence=0.9,
                possible_issue=VisualIssueType.CRACK,
            ),
            _ObservationDraft(observation="   "),
        ],
        image_quality=ImageQuality.SUFFICIENT,
        possible_issues=[VisualIssueType.VISIBLE_PHYSICAL_DAMAGE],
        limitations=[],
    )
    fake = FakeVisionProvider(result=model)
    result = vision_analyzer.analyze_visual_evidence(
        _png_bytes(), _evidence(), vision=fake
    )
    assert result.status is VisionStatus.ANALYZED
    assert result.source is AnalysisSource.LLM
    assert result.provider_name == "fake-vision"
    assert [o.observation for o in result.visual_observations] == [
        "A visible crack along the left edge"
    ]
    assert result.visual_observations[0].possible_issue is VisualIssueType.CRACK
    assert VisualIssueType.VISIBLE_PHYSICAL_DAMAGE in result.possible_issues
    assert any("cannot establish when or how" in lim for lim in result.limitations)
    assert any("cannot establish the cause" in lim for lim in result.limitations)
    assert len(fake.calls) == 1


def test_provider_failure_returns_failed_result_not_exception():
    fake = FakeVisionProvider(error=ProviderError("boom", provider="fake-vision"))
    result = vision_analyzer.analyze_visual_evidence(
        _png_bytes(), _evidence(), vision=fake
    )
    assert result.status is VisionStatus.FAILED
    assert result.source is AnalysisSource.HEURISTIC
    assert result.visual_observations == []
    assert any(w.code == "vision_provider_failed" for w in result.warnings)
    assert any("ProviderError" in lim for lim in result.limitations)
    assert result.requires_human_review is True


def test_comparison_path_labels_type_and_reference():
    model = _VisionInspectionModel(
        visual_observations=[
            _ObservationDraft(observation="Different color than the listing")
        ],
    )
    fake = FakeVisionProvider(result=model)
    result = vision_analyzer.analyze_visual_evidence(
        _png_bytes(),
        _evidence("evt-photo"),
        reference_file_bytes=_png_bytes(),
        reference_evidence_input=_evidence("evt-listing", "listing.png"),
        vision=fake,
    )
    assert result.analysis_type == "image_comparison"
    assert result.evidence_id == "evt-photo"
    assert result.reference_evidence_id == "evt-listing"
    assert any("definitive product mismatch" in lim for lim in result.limitations)
    assert any(
        "cannot establish the cause" in lim for lim in result.limitations
    )
    images, system_prompt, _, _ = fake.calls[0]
    assert len(images) == 2
    assert images[0].label == "reference_image"
    assert images[1].label == "customer_photo"
    assert "compare" in system_prompt.lower()


def test_tiny_image_is_flagged_unclear():
    model = _VisionInspectionModel(image_quality=ImageQuality.SUFFICIENT)
    fake = FakeVisionProvider(result=model)
    result = vision_analyzer.analyze_visual_evidence(
        _png_bytes(size=(20, 20)), _evidence(), vision=fake
    )
    assert result.image_quality is ImageQuality.UNCLEAR


def test_tiny_image_mock_path_is_flagged_unclear():
    result = vision_analyzer.analyze_visual_evidence(
        _png_bytes(size=(20, 20)), _evidence()
    )
    assert result.status is VisionStatus.MOCK
    assert result.image_quality is ImageQuality.UNCLEAR


def test_empty_file_bytes_raise():
    with pytest.raises(InputValidationError):
        vision_analyzer.analyze_visual_evidence(b"", _evidence())


def test_non_evidence_input_raises():
    with pytest.raises(InputValidationError):
        vision_analyzer.analyze_visual_evidence(_png_bytes(), "not-evidence")  # type: ignore[arg-type]


def test_reference_bytes_without_reference_input_raises():
    with pytest.raises(InputValidationError):
        vision_analyzer.analyze_visual_evidence(
            _png_bytes(), _evidence(), reference_file_bytes=_png_bytes()
        )
