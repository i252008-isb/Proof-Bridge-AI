# Vision Setup — ProofBridge AI

The vision service inspects product photographs: visible cracks, broken
components, scratches, missing visible parts, deformation — and compares
customer photos against a reference (e.g. product listing) image. Vision
and OCR are strictly separate: OCR extracts readable text, vision
interprets visual content.

## Configuration

```bash
PROOFBRIDGE_VISION_PROVIDER=openai        # or "mock" for offline demo
PROOFBRIDGE_VISION_API_KEY=sk-...         # required for openai
PROOFBRIDGE_VISION_BASE_URL=https://api.openai.com/v1
PROOFBRIDGE_VISION_MODEL=gpt-4o-mini      # any multimodal model
```

The provider factory (`get_vision_provider`) resolves:
- `demo_mode=true` or `vision_provider="mock"` → deterministic mock,
  `status="mock"`, zero observations, clearly labeled;
- `vision_provider="openai"` with a key → real multimodal provider;
- `vision_provider="openai"` without a key → `ConfigurationError`, which
  `analyze_visual_evidence` converts into a structured
  `status="failed"` result with a limitation (the pipeline continues).

## What the service guarantees

- **Never** concludes when or how damage occurred, product authenticity,
  counterfeiting, or a definitive product mismatch from a photograph.
  These limitations are attached to every analyzed result.
- Unreadable images → `status="failed"`, `image_quality="unclear"`,
  warning `image_unreadable`, no observations invented.
- Tiny images (< 50 px in either dimension) → `image_quality="unclear"`.
- Comparison results carry the additional limitation that visual
  differences alone cannot establish a product mismatch.
- Every analyzed result has `requires_human_review=True`.

## Using the service

```python
from proofbridge_ai import analyze_visual_evidence, EvidenceInput

result = analyze_visual_evidence(
    photo_bytes,
    EvidenceInput(evidence_id="EVD-5", filename="photo.jpg"),
    content_type="image/jpeg",
    reference_file_bytes=listing_bytes,          # optional comparison
    reference_evidence_input=EvidenceInput(
        evidence_id="EVD-2", filename="listing.jpg"
    ),
)
print(result.status.value)      # "analyzed" | "mock" | "failed"
print(result.visual_observations)
```

The main pipeline (`analyze_support_case`) runs vision automatically for
image evidence — even when OCR extraction of the same image fails, vision
still runs (independent capabilities).

## Mock behavior (offline demo)

With the mock provider the service performs **no** image analysis. It
returns `status="mock"` with empty observations, a `mock_vision_output`
warning, and the limitation that manual visual inspection is required.
Mock results are never presented as genuine model output.
