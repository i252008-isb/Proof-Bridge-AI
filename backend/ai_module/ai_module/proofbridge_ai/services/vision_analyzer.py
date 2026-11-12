"""Visual inspection of product photographs via the vision provider.

Vision and OCR are strictly separate: OCR extracts readable text (see
document_extractor/ocr_service), this module interprets visual content.
Honest degradation rules:

- Mock vision provider -> clearly labeled ``status="mock"`` result, no
  fabricated observations.
- Vision provider unavailable or failing -> ``status="failed"`` with a
  structured limitation; the pipeline continues with other evidence.
- Visual observations never establish when or how damage occurred, product
  authenticity, or a definitive product mismatch.
"""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from proofbridge_ai.config import Settings, get_settings
from proofbridge_ai.exceptions import (
    ConfigurationError,
    InputValidationError,
    ProviderError,
    ProviderResponseValidationError,
)
from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.providers import get_vision_provider
from proofbridge_ai.providers.base import BaseVisionProvider, VisionImage
from proofbridge_ai.schemas import (
    AnalysisSource,
    EvidenceInput,
    ExtractionWarning,
    ImageQuality,
    VisualAnalysisResult,
    VisualIssueType,
    VisualObservation,
    VisionStatus,
)

logger = get_logger("services.vision_analyzer")

_INSPECTION_SYSTEM_PROMPT = (
    "You are the vision analysis engine of ProofBridge AI, an AI-powered "
    "customer support and refund investigation system. You describe what is "
    "VISIBLY observable in product photographs. Rules: report only visible "
    "irregularities (cracks, broken components, scratches, missing visible "
    "parts, deformation). Never infer hidden defects, authenticity, "
    "counterfeits, when or how damage occurred, or who caused it. A "
    "photograph cannot establish the cause or timing of damage — say so in "
    "limitations. If the image is unclear or the product is not visible, "
    "set image_quality accordingly and do not invent observations."
)

_COMPARISON_SYSTEM_PROMPT = (
    "You are the vision analysis engine of ProofBridge AI. You compare two "
    "product images: a reference image (e.g. the original product listing) "
    "and a customer photograph. Report observable visual differences "
    "(color differences, different visible components, missing visible "
    "accessories, different appearance, visible damage). Visual differences "
    "are observations only — never conclude a definitive product mismatch, "
    "authenticity, or fraud. Never infer when or how any difference arose."
)

_ALWAYS_LIMITATIONS = [
    "A photograph cannot establish when or how any observed damage occurred.",
    "A photograph alone cannot establish the cause of any observed damage.",
]

_COMPARISON_LIMITATION = (
    "Visual differences are observations only; image comparison alone "
    "cannot establish a definitive product mismatch."
)


class _ObservationDraft(BaseModel):
    """LLM-boundary model for one visual observation."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    observation: str = Field(default="", max_length=300)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    possible_issue: VisualIssueType | None = None


class _VisionInspectionModel(BaseModel):
    """LLM-boundary model for vision inspection output."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    visual_observations: list[_ObservationDraft] = Field(default_factory=list)
    image_quality: ImageQuality = ImageQuality.SUFFICIENT
    possible_issues: list[VisualIssueType] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def analyze_visual_evidence(
    file_bytes: bytes,
    evidence_input: EvidenceInput,
    content_type: str | None = None,
    reference_file_bytes: bytes | None = None,
    reference_evidence_input: EvidenceInput | None = None,
    settings: Settings | None = None,
    vision: BaseVisionProvider | None = None,
) -> VisualAnalysisResult:
    """Analyze one product photograph (optionally against a reference image).

    Returns a structured VisualAnalysisResult. Unreadable images, missing
    vision credentials, and provider failures produce a clearly limited
    result (``status="failed"``) instead of an exception, so evidence
    processing can continue. Mock providers produce ``status="mock"`` with
    no fabricated observations.

    Args:
        file_bytes: The customer photograph bytes.
        evidence_input: Backend-supplied EvidenceInput (id preserved verbatim).
        content_type: Optional MIME type hint.
        reference_file_bytes: Optional reference image (e.g. product listing).
        reference_evidence_input: Backend EvidenceInput for the reference.
        settings: Optional Settings override (tests).
        vision: Optional vision provider injection (tests).

    Returns:
        VisualAnalysisResult (``analysis_type="visual_inspection"`` or
        ``"image_comparison"`` when a reference image is supplied).
    """
    if not isinstance(file_bytes, bytes) or not file_bytes:
        raise InputValidationError("file_bytes must be a non-empty bytes object")
    if not isinstance(evidence_input, EvidenceInput):
        raise InputValidationError("evidence_input must be an EvidenceInput")
    settings = settings or get_settings()

    comparison = reference_file_bytes is not None
    if comparison and (
        not isinstance(reference_file_bytes, bytes) or not reference_file_bytes
    ):
        raise InputValidationError("reference_file_bytes must be non-empty bytes")
    if comparison and not isinstance(reference_evidence_input, EvidenceInput):
        raise InputValidationError(
            "reference_evidence_input must be an EvidenceInput when a "
            "reference image is supplied"
        )

    opened, width, height = _inspect_image(file_bytes)
    if not opened:
        logger.info("vision: image could not be opened id=%s", evidence_input.evidence_id)
        return VisualAnalysisResult(
            evidence_id=evidence_input.evidence_id,
            reference_evidence_id=(
                reference_evidence_input.evidence_id if reference_evidence_input else None
            ),
            analysis_type="image_comparison" if comparison else "visual_inspection",
            status=VisionStatus.FAILED,
            image_quality=ImageQuality.UNCLEAR,
            limitations=[
                "The image file could not be opened or decoded; no visual "
                "analysis was performed. Manual visual inspection is required."
            ],
            warnings=[
                ExtractionWarning(
                    code="image_unreadable",
                    message="The uploaded image could not be opened or decoded.",
                )
            ],
            requires_human_review=True,
            source=AnalysisSource.HEURISTIC,
            provider_name="none",
        )

    media_type = _media_type(content_type, file_bytes)

    provider = vision if vision is not None else get_vision_provider(settings)
    if provider.is_mock:
        return _mock_result(evidence_input, reference_evidence_input, comparison, width, height)

    try:
        if comparison:
            model = provider.analyze_images(
                [
                    VisionImage(
                        image_bytes=reference_file_bytes,
                        media_type=_media_type(None, reference_file_bytes),
                        label="reference_image",
                    ),
                    VisionImage(
                        image_bytes=file_bytes,
                        media_type=media_type,
                        label="customer_photo",
                    ),
                ],
                _COMPARISON_SYSTEM_PROMPT,
                _comparison_user_prompt(),
                _VisionInspectionModel,
            )
        else:
            model = provider.analyze_image(
                VisionImage(image_bytes=file_bytes, media_type=media_type, label="customer_photo"),
                _INSPECTION_SYSTEM_PROMPT,
                _inspection_user_prompt(),
                _VisionInspectionModel,
            )
    except (ProviderError, ProviderResponseValidationError, ConfigurationError) as exc:
        logger.warning(
            "vision analysis failed id=%s error=%s",
            evidence_input.evidence_id,
            type(exc).__name__,
        )
        return VisualAnalysisResult(
            evidence_id=evidence_input.evidence_id,
            reference_evidence_id=(
                reference_evidence_input.evidence_id if reference_evidence_input else None
            ),
            analysis_type="image_comparison" if comparison else "visual_inspection",
            status=VisionStatus.FAILED,
            image_quality=ImageQuality.SUFFICIENT if opened else ImageQuality.UNCLEAR,
            limitations=[
                "The vision provider is unavailable or failed "
                f"({type(exc).__name__}); no visual observations were produced. "
                "Manual visual inspection is required."
            ],
            warnings=[
                ExtractionWarning(
                    code="vision_provider_failed",
                    message=f"Vision provider failed: {type(exc).__name__}.",
                )
            ],
            requires_human_review=True,
            source=AnalysisSource.HEURISTIC,
            provider_name=provider.name,
        )

    observations = [
        VisualObservation(
            observation=draft.observation.strip(),
            confidence=draft.confidence,
            possible_issue=draft.possible_issue,
        )
        for draft in model.visual_observations
        if draft.observation.strip()
    ]
    limitations = list(model.limitations)
    if not observations and model.visual_observations:
        limitations.append(
            "Some vision model observations were empty and were dropped."
        )
    if not any(
        "cause" in limitation.lower() for limitation in limitations
    ):
        limitations.extend(_ALWAYS_LIMITATIONS)
    if comparison:
        limitations.append(_COMPARISON_LIMITATION)

    quality = model.image_quality
    if width < 50 or height < 50:
        quality = ImageQuality.UNCLEAR

    return VisualAnalysisResult(
        evidence_id=evidence_input.evidence_id,
        reference_evidence_id=(
            reference_evidence_input.evidence_id if reference_evidence_input else None
        ),
        analysis_type="image_comparison" if comparison else "visual_inspection",
        status=VisionStatus.ANALYZED,
        visual_observations=observations,
        image_quality=quality,
        possible_issues=list(model.possible_issues),
        limitations=list(dict.fromkeys(limitations)),
        requires_human_review=True,
        source=AnalysisSource.LLM,
        provider_name=provider.name,
    )


def _mock_result(
    evidence_input: EvidenceInput,
    reference_evidence_input: EvidenceInput | None,
    comparison: bool,
    width: int,
    height: int,
) -> VisualAnalysisResult:
    quality = ImageQuality.SUFFICIENT
    if width < 50 or height < 50:
        quality = ImageQuality.UNCLEAR
    return VisualAnalysisResult(
        evidence_id=evidence_input.evidence_id,
        reference_evidence_id=(
            reference_evidence_input.evidence_id if reference_evidence_input else None
        ),
        analysis_type="image_comparison" if comparison else "visual_inspection",
        status=VisionStatus.MOCK,
        visual_observations=[],
        image_quality=quality,
        possible_issues=[],
        limitations=[
            "Mock vision provider output: no genuine image analysis was "
            "performed (offline demo). Manual visual inspection is required."
        ],
        warnings=[
            ExtractionWarning(
                code="mock_vision_output",
                message=(
                    "The configured vision provider is a mock; results are "
                    "placeholder data, never genuine model output."
                ),
            )
        ],
        requires_human_review=True,
        source=AnalysisSource.HEURISTIC,
        provider_name="mock",
    )


def _inspect_image(file_bytes: bytes) -> tuple[bool, int, int]:
    try:
        with Image.open(io.BytesIO(file_bytes)) as image:
            image.load()
            return True, image.width, image.height
    except (UnidentifiedImageError, OSError, ValueError):
        return False, 0, 0


def _media_type(content_type: str | None, file_bytes: bytes) -> str:
    if content_type and content_type.startswith("image/"):
        return content_type.split(";")[0].strip()
    try:
        with Image.open(io.BytesIO(file_bytes)) as image:
            fmt = (image.format or "jpeg").lower()
        if fmt == "png":
            return "image/png"
        if fmt == "webp":
            return "image/webp"
        return "image/jpeg"
    except (UnidentifiedImageError, OSError, ValueError):
        return "image/jpeg"


def _inspection_user_prompt() -> str:
    return (
        "Analyze the customer photograph of the product. Describe only "
        "visibly observable irregularities and assess whether the image is "
        "clear enough and the product is visible."
    )


def _comparison_user_prompt() -> str:
    return (
        "Compare the reference image with the customer photograph. Describe "
        "only observable visual differences."
    )
