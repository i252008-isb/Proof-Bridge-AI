# Schemas — ProofBridge AI

The complete data contract lives in `proofbridge_ai/schemas.py`. All
models are Pydantic v2 with `extra="forbid"` (public models) or
`extra="ignore"` (LLM-boundary models), whitespace-stripped strings, and
validated enums. Serialize with `model_dump(mode="json")`.

## Enums

| Enum | Values |
| --- | --- |
| `IssueType` | `damaged_product`, `defective_product`, `wrong_product_received`, `missing_item`, `product_not_as_described`, `missing_accessories`, `incorrect_order`, `delivery_complaint`, `late_delivery`, `other` |
| `VerificationStatus` | `supported`, `partially_supported`, `contradicted`, `unverified`, `insufficient_evidence` |
| `EvidenceInventoryStatus` | `collected`, `processing`, `processed`, `needs_review`, `failed` |
| `EvidenceCategory` | `purchase_record`, `order_record`, `product_image`, `product_listing`, `conversation`, `delivery_record`, `return_policy`, `other` |
| `EvidenceKind` | `image`, `pdf`, `docx`, `text`, `source_code`, `other` |
| `RecommendationOutcome` | `refund_recommended`, `request_more_information`, `escalate_to_human`, `refund_not_supported_by_provided_policy`, `alternative_resolution_suggested`, `insufficient_policy_information` |
| `PolicyEvaluationStatus` | `policy_not_provided`, `policy_requires_human_interpretation`, `evaluated` |
| `PolicyRuleCategory` | `eligible_reason`, `return_window`, `defective_product`, `damaged_on_arrival`, `proof_requirement`, `packaging_requirement`, `replacement_option`, `repair_option`, `refund_exception`, `warranty`, `other` |
| `RuleAssessment` | `met`, `partially_met`, `not_met`, `not_assessable` |
| `VisionStatus` | `analyzed`, `mock`, `failed`, `not_applicable` |
| `ImageQuality` | `sufficient`, `unclear`, `product_not_visible` |
| `VisualIssueType` | `visible_physical_damage`, `crack`, `broken_component`, `scratch`, `missing_visible_part`, `deformation`, `color_difference`, `appearance_difference`, `other_irregularity` |
| `ConversationSpeaker` | `customer`, `seller`, `support_agent`, `system`, `unknown` |
| `AnalysisSource` | `llm`, `heuristic` |
| `SimilarityMethod` | `embeddings`, `lexical` |

## Input models (backend supplies)

- `SupportTicket` — `case_id`, `complaint` (required); optional
  `product_name`, `order_id`, `purchase_date`, `delivery_date`,
  `requested_resolution`, `seller_contacted`, and human-corrected
  `claims` (used verbatim, never overwritten).
- `EvidenceInput` / `EvidenceUpload` — upload metadata + bytes.
- `EvidenceItem` — processed evidence (backend may supply pre-processed
  items; `evidence_id` preserved verbatim).
- `RefundPolicy` — backend-supplied or extracted policy.
- `OrderInformation` / `PaymentInformation` — order-system and
  payment-provider data (all fields optional; used verbatim;
  informational only).
- `CaseContext` / `CaseEvent` — backend case history (events feed the
  report timeline; timestamps optional, never invented).

## Intermediate results

- `TicketAnalysisResult` — issue type, summary, requested resolution,
  `extracted_claims` (UNVERIFIED, `source="customer_ticket"`), warnings.
- `EvidenceBatchResult` — `items` + per-item `failures` (isolated).
- `DocumentExtractionResult` — text, normalization, method, OCR flag.
- `VisualAnalysisResult` — `status` (`analyzed`/`mock`/`failed`),
  observations, `image_quality`, possible issues, limitations, warnings.
- `ConversationAnalysis` — messages with speakers, `refund_promises`.
- `PurchaseInformation` — receipt facts; every field `None` when the
  document does not state it.
- `RefundPolicy` — rules with verbatim `source_quote`.
- `PolicyEvaluationResult` — `status`, `rule_assessments`,
  `unmet_conditions`, `missing_information`, `explanation`.
- `ClaimSimilarityResult` — relevance scores (method + limitations).
- `CrossSourceFinding` / `Contradiction` / `MissingInformation` —
  cross-source verification output.
- `ClaimAssessment` — per-claim `status`, confidence, rationale,
  supporting/contradicting evidence IDs, cited passages, similarity
  scores.

## Final results

### SupportCaseAnalysisResult

`schema_version="2.0"`, `case_id`, `issue_type`, `requested_resolution`,
`claims` (list of `ClaimAssessment`), `purchase_information`,
`visual_analysis`, `conversation_analysis`, `cross_source_findings`,
`contradictions`, `missing_information`, `policy_evaluation`,
`recommendation` (`RefundRecommendation` with `outcome`, `reasoning`,
evidence IDs, missing info, policy rule IDs, `confidence`,
`requires_human_review=True`), `limitations`, `source_summary`.

### InvestigationReport

`schema_version="2.0"`, title "ProofBridge AI — Customer Support Case
Investigation Report", `final_decision_notice`, `human_review_required`
(always True), plus: `case_overview`, `customer_complaint`,
`product_information`, `requested_resolution`, `customer_claims`,
`purchase_and_order_information`, `order_information`,
`payment_information`, `evidence_inventory` (`ReportEvidenceEntry`s),
`ocr_findings`, `visual_analysis`, `conversation_analysis`,
`refund_policy_summary`, `cross_source_verification`,
`supporting_findings`, `contradictions`, `missing_information`,
`policy_assessment`, `recommended_outcome`, `recommendation_reasoning`,
`recommendation`, `evidence_references`, `timeline` (dated events
chronologically sorted, undated events after — timestamps never
invented), `neutral_summary` (deterministic,
`generation_method="heuristic"`), `limitations`, `status_counts`,
`unresolved_evidence_ids`, `source_summary`.

Findings are copied verbatim from the analysis stage — the report never
edits them. If generation fails, a deterministic fallback report
preserves the findings and flags the fallback in `limitations`.
