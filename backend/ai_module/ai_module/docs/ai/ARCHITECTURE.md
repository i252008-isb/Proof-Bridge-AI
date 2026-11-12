# Architecture — ProofBridge AI

## Central principle

**Customers submit the proof. ProofBridge AI investigates the proof.
Human support agents make the final decisions.**

The AI module never issues, rejects, or transfers payments; never invents
refund policies; never claims a defect with certainty from a photograph;
never makes fraud accusations; and never creates database records or an
authentication system. Every result carries `requires_human_review=True`.

## Pipeline (analyze_support_case)

```
SupportTicket + EvidenceItems/EvidenceUploads (+ policy, order info, case context)
        |
1.  validate ticket                 InputValidationError on bad input
2.  extract claims                  ticket_analyzer (LLM + heuristic fallback)
3.  process evidence                evidence_extractor per item, error-isolated
4.  OCR where appropriate           document_extractor / ocr_service (images, PDFs)
5.  vision where appropriate        vision_analyzer (independent of OCR)
6.  purchase/product details        product_analyzer (receipts) + conversations
7.  seller conversation analysis    conversation_analyzer
8.  refund policy processing        policy_extractor (backend-supplied policy used verbatim)
9.  cross-source comparison         cross_source_verifier (order IDs, dates, prices...)
10. contradiction identification    same stage, factual wording only
11. missing information             same stage + claim assessment
12. policy evaluation               policy_evaluator (rule-by-rule assessments)
13. refund recommendation           support_case_analyzer._recommend (fully reasoned)
14. validated Pydantic result       SupportCaseAnalysisResult
        |
        v
generate_investigation_report -> InvestigationReport (21 sections, fallback-safe)
```

## Module map

```
proofbridge_ai/
  config.py            pydantic-settings, env prefix PROOFBRIDGE_, demo mode
  schemas.py           complete data contract (enums + models + report schema)
  exceptions.py        ProofBridgeAIError hierarchy
  logging_utils.py     safe structured logging (never full documents/secrets)
  providers/
    base.py            BaseLLMProvider / BaseEmbeddingsProvider / BaseVisionProvider
    mock_providers.py  deterministic offline stand-ins (always labeled)
    openai_providers.py OpenAI-compatible LLM/embeddings/vision clients
    factories.py       get_llm_provider / get_embeddings_provider / get_vision_provider
  services/
    ticket_analyzer.py       complaint -> issue type + UNVERIFIED claims
    evidence_extractor.py    upload -> EvidenceItem (summary, facts, warnings)
    document_extractor.py    PDF/DOCX/TXT/image -> text (OCR for images)
    ocr_service.py           Tesseract wrapper (is_ocr_available)
    vision_analyzer.py       photo inspection / image comparison (honest degradation)
    product_analyzer.py      receipt/order/payment facts (never invented)
    conversation_analyzer.py chat export -> messages, refund promises
    policy_extractor.py      policy text/document -> rules with verbatim quotes
    policy_evaluator.py      rule-by-rule assessment vs case evidence
    similarity_engine.py     claim<->evidence relevance scores
    cross_source_verifier.py field consistency across sources
    support_case_analyzer.py orchestration, claim assessment, recommendation
    report_generator.py      structured InvestigationReport (+ fallback)
    file_validation.py       size/type/pixel limits, safe parsing
    text_normalizer.py       whitespace/control normalization, truncation
  integration/
    facade.py           ProofBridgeAIFacade + get_facade + module-level functions
```

## Provider abstraction

- `BaseLLMProvider`: `chat(...)`, `generate_json(system_prompt, user_prompt,
  response_model)`, `name`, `is_mock`.
- `BaseEmbeddingsProvider`: `embed_texts`, `embed_query`, `dimensions`.
- `BaseVisionProvider`: `analyze_images(images, system_prompt, user_prompt,
  response_model)` (+ `analyze_image` convenience), with `VisionImage(
  image_bytes, media_type, label)`.
- Factories are cached per configuration; with `demo_mode=true` (or
  `provider="mock"`) every factory returns the deterministic mock. Mock
  output is always labeled (`status="mock"`, warnings, limitations).

## Honest degradation rules

1. Mock providers produce labeled placeholder output, never fabricated
   analysis.
2. Provider failure produces a structured `status="failed"` result with a
   limitation; the pipeline continues with the remaining evidence.
3. LLM extraction failure falls back to deterministic heuristics, labeled
   with a warning.
4. LLM values are verified against their source text (dates must appear
   in the complaint; receipt facts must appear in the document; policy
   quotes must be verbatim substrings). Unverifiable values are dropped
   with warnings — nothing is invented.
5. Semantic similarity decides relevance only; it never establishes
   truth. Claim verification uses independently extracted document facts
   (order numbers/dates from receipts and order data — never the ticket
   itself, which is the allegation under investigation).
6. Contradictions are stated factually ("does not imply wrongdoing by
   either party"); no dishonesty accusations.
7. If report generation fails, a deterministic fallback report preserves
   the structured findings.

## Trust boundaries

Customer chats, documents, receipts, images, and policy files are
untrusted inputs. The LLM is instructed to analyze them, never to follow
instructions embedded in them. Files are validated (type, size, pixel
limits) before parsing; uploads are never executed. API keys come from
environment variables only. Logging never includes complete customer
documents or secrets.
