# Configuration — ProofBridge AI

All configuration comes from environment variables prefixed with
`PROOFBRIDGE_` (pydantic-settings). No hardcoded keys, no config files
required. Copy `.env.example` to `.env` in the project root for local
development. Never commit real API keys.

## Providers

| Variable | Default | Meaning |
| --- | --- | --- |
| `PROOFBRIDGE_DEMO_MODE` | `false` | `true` forces all providers to the offline mocks (labeled output) |
| `PROOFBRIDGE_LLM_PROVIDER` | `mock` | `"mock"` or `"openai"` (any OpenAI-compatible API) |
| `PROOFBRIDGE_LLM_API_KEY` | — | API key (SecretStr; never logged) |
| `PROOFBRIDGE_LLM_BASE_URL` | `https://api.openai.com/v1` | Base URL of the compatible API |
| `PROOFBRIDGE_LLM_MODEL` | `gpt-4o-mini` | Model name |
| `PROOFBRIDGE_LLM_TEMPERATURE` | `0.0` | Sampling temperature |
| `PROOFBRIDGE_EMBEDDINGS_PROVIDER` | `mock` | `"mock"` or `"openai"` |
| `PROOFBRIDGE_EMBEDDINGS_API_KEY` | — | API key |
| `PROOFBRIDGE_EMBEDDINGS_BASE_URL` | `https://api.openai.com/v1` | Base URL |
| `PROOFBRIDGE_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `PROOFBRIDGE_VISION_PROVIDER` | `mock` | `"mock"` or `"openai"` (multimodal) |
| `PROOFBRIDGE_VISION_API_KEY` | — | API key |
| `PROOFBRIDGE_VISION_BASE_URL` | `https://api.openai.com/v1` | Base URL |
| `PROOFBRIDGE_VISION_MODEL` | `gpt-4o-mini` | Multimodal model |

With the `mock` provider (or demo mode) every AI stage runs offline and
deterministically, and results are explicitly labeled mock/heuristic.
With a real provider selected but no API key configured, services raise
`ConfigurationError` (except vision, which returns a structured
`status="failed"` result with a limitation).

## Reliability

| Variable | Default | Meaning |
| --- | --- | --- |
| `PROOFBRIDGE_MAX_RETRIES` | `2` | Bounded retries for provider HTTP calls |
| `PROOFBRIDGE_HTTP_TIMEOUT_SECONDS` | `60.0` | Per-request timeout |

## OCR

| Variable | Default | Meaning |
| --- | --- | --- |
| `PROOFBRIDGE_OCR_ENABLED` | `false` | `true` allows OCR when Tesseract is installed |
| `PROOFBRIDGE_TESSERACT_CMD` | — | Path to the Tesseract binary (optional) |
| `PROOFBRIDGE_OCR_LANGUAGE` | `eng` | OCR language |

See [OCR_SETUP.md](OCR_SETUP.md).

## File limits (security)

| Variable | Default | Meaning |
| --- | --- | --- |
| `PROOFBRIDGE_MAX_FILE_SIZE_BYTES` | `10485760` (10 MB) | Upload size limit |
| `PROOFBRIDGE_MAX_PDF_PAGES` | `100` | PDF page limit |
| `PROOFBRIDGE_MAX_IMAGE_PIXELS` | `25000000` | Image pixel limit |
| `PROOFBRIDGE_MAX_DOCUMENT_CHARS` | `200000` | Extracted text cap |

## Similarity thresholds

| Variable | Default | Meaning |
| --- | --- | --- |
| `PROOFBRIDGE_SIMILARITY_SUPPORTED_THRESHOLD` | `0.60` | Score floor for "supported" relevance |
| `PROOFBRIDGE_SIMILARITY_PARTIAL_THRESHOLD` | `0.40` | Score floor for "partially supported" relevance |
| `PROOFBRIDGE_SIMILARITY_MAX_CANDIDATES` | `5` | Top evidence candidates kept per claim |

Relevance scores decide which evidence is matched to which claim — never
whether a claim is true or whether a refund is due. The supported
threshold must be >= the partial threshold (validated).

## Programmatic settings

```python
from proofbridge_ai import Settings

settings = Settings(
    demo_mode=True,
    similarity_partial_threshold=0.35,
    similarity_supported_threshold=0.65,
)
```

`Settings` instances can be passed to any public function or to
`ProofBridgeAIFacade(settings)`.
