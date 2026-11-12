# Error Handling — ProofBridge AI

## Exception hierarchy

All exceptions derive from `ProofBridgeAIError` (never logs or exposes
secrets):

```
ProofBridgeAIError
  InputValidationError           invalid arguments/inputs -> 400
  ConfigurationError             provider selected but misconfigured -> 500
  FileTooLargeError              file exceeds size limit -> 413
  UnsupportedFileTypeError       unknown format -> 415
  DocumentExtractionError        unreadable/corrupt file -> 422
  OCRNotAvailableError           image input but Tesseract missing -> 503
  ProviderError                  provider call failed -> 502
  ProviderResponseValidationError provider returned invalid JSON -> 502
  AnalysisError                  internal analysis failure -> 500
  ServiceNotImplementedError     reserved functionality -> 501
```

## Errors vs warnings

- **Errors** are raised for input problems the backend must fix (invalid
  ticket, unsupported file, file too large) and for batch-level misuse.
- **Warnings** (`ExtractionWarning(code, message)`) are attached to
  results when the module degraded gracefully: mock providers used,
  LLM fallback to heuristics, dropped unverifiable LLM values, empty
  policy text, etc. The backend must persist and display warnings.

## Graceful degradation (never raises)

| Situation | Behavior |
| --- | --- |
| Mock LLM/vision/embeddings | Labeled placeholder output + warning |
| LLM extraction failure | Deterministic heuristic fallback + warning |
| LLM invents a date/quote | Value dropped + `llm_date_dropped`/`llm_quote_dropped` warning |
| Vision provider unavailable/fails | `status="failed"` result with limitation |
| Unreadable image | `status="failed"` + `image_unreadable`; other evidence unaffected |
| One upload fails in a batch | Isolated failure entry; the batch continues |
| Policy empty/unreadable | Policy with zero rules + warning (evaluator flags human interpretation) |
| Report generation fails | Deterministic fallback report preserving findings |

## Error isolation in the pipeline

`analyze_support_case` wraps every evidence item in its own try/except:
a failing item adds a limitation ("could not be processed ...; the
investigation continued with the remaining evidence") and processing
continues. One unreadable upload never loses the investigation.

## HTTP mapping (FastAPI reference)

See `examples/fastapi_integration.py` — a single exception handler maps
`ProofBridgeAIError` subclasses to HTTP statuses:

```python
_STATUS_BY_ERROR = {
    "InputValidationError": 400,
    "FileTooLargeError": 413,
    "UnsupportedFileTypeError": 415,
    "DocumentExtractionError": 422,
    "ServiceNotImplementedError": 501,
    "ProviderError": 502,
    "ProviderResponseValidationError": 502,
    "OCRNotAvailableError": 503,
    "ConfigurationError": 500,
    "AnalysisError": 500,
}
```

## Safe logging

Logs use the structured `logging_utils` logger with case/evidence IDs
only — never complete customer documents, chat contents, receipts, or
API keys.
