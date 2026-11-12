# Limitations — ProofBridge AI

Honest limitations of the current implementation. These are design
decisions and environment constraints, not hidden defects; the module
degrades gracefully and labels every limitation in its output.

## AI capability limits

- **Mock providers (offline demo)**: with no real API keys, the LLM,
  vision, and embeddings stages produce deterministic placeholder output,
  always labeled (`status="mock"`, `mock_*` warnings, limitations).
  Mock vision output can never complete a "photographic proof" policy
  condition — the demo therefore honestly reports `partially_met`.
- **Vision cannot establish cause, timing, or authenticity**: a
  photograph cannot show when or how damage occurred, whether the product
  is genuine, or a definitive product mismatch. These limitations are
  attached to every vision result.
- **LLM values are verified against source text**: dates, receipt facts,
  and policy quotes that do not literally appear in the source document
  are dropped with warnings. This trades recall for honesty.
- **Heuristic fallbacks**: when no LLM is configured or the LLM fails,
  deterministic keyword/sentence heuristics run instead, labeled via
  `source=heuristic` and warnings. Heuristics understand less than a
  model and may miss nuance.
- **Semantic similarity establishes relevance only**: a high score means
  evidence appears relevant to a claim; it never establishes that the
  claim is true. Claim verification uses independently extracted document
  facts, never similarity alone.
- **Contradictions are factual, not moral**: the module reports
  inconsistencies without accusing any party of dishonesty or fraud.

## Environment limits

- **OCR requires Tesseract**: without the Tesseract engine, image and
  scanned-PDF text extraction raises `OCRNotAvailableError` (or is
  reported per-item in batch). Text-file evidence always works. See
  [OCR_SETUP.md](OCR_SETUP.md).
- **No paid APIs or internet in tests**: the test suite uses scripted
  fake providers only.

## Scope limits (by design)

- The module never issues, rejects, or transfers payments.
- It never invents refund policies or timestamps; missing policy →
  `insufficient_policy_information`; missing dates stay missing.
- It never makes a final decision: `human_review_required=True` and the
  final-decision notice are on every analysis and every report.
- It never creates database records, authenticates users, or calls
  PayPal APIs.
- "Not supported by policy" outcomes are explicitly labeled as **not a
  definitive rejection**.
- The neutral summary and report are deterministic compositions
  (`generation_method="heuristic"`), not LLM prose.
