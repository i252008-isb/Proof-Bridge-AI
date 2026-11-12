# Policy Evaluation — ProofBridge AI

How refund policies are extracted, assessed, and turned into a
recommendation. The policy engine is decision support: its output is
never legally binding and never a definitive rejection.

## 1. Extraction (`extract_refund_policy`)

Input: raw `policy_text` or a policy document (`file_bytes`: PDF/DOCX/TXT;
screenshots via OCR). Output: `RefundPolicy` with `PolicyRule`s:

- `rule_id`, `condition`, `category`, `source_quote`, `requires_evidence`
- `source_quote` must be a verbatim substring of the source text
  (whitespace-normalized). LLM-supplied quotes that fail this check are
  dropped with warning `llm_quote_dropped` — policy clauses are never
  invented.
- LLM unavailable/failing → deterministic heuristic extraction
  (sentence-per-rule over recognized categories), labeled with
  `llm_unavailable_heuristic_used` / `llm_extraction_failed`.
- Empty or unreadable policy → zero rules + `policy_text_empty` warning.

Rule categories: `return_window`, `damaged_on_arrival`,
`defective_product`, `proof_requirement`, `packaging_requirement`,
`replacement_option`, `repair_option`, `refund_exception`,
`restocking_fee`, `warranty_claim`, `other`.

## 2. Evaluation (`evaluate_refund_policy`)

Each rule is assessed against the case evidence:

| Category | Logic |
| --- | --- |
| `return_window` | Extracts "N days" from the condition; anchors on the purchase date (or delivery date when the condition mentions delivery). `days_elapsed = reference_date - anchor`. MET / NOT_MET / NOT_ASSESSABLE (unknown anchor → missing information). |
| `damaged_on_arrival` / `defective_product` | Requires the ticket issue type to match; requires a readable customer photograph (`photo_supplied`); MET only when the vision analysis reported actual observations. Photo supplied without observations → PARTIALLY_MET. No photo → NOT_ASSESSABLE + missing information ("a readable customer photograph"). |
| `proof_requirement` | Matches required proof types (receipt/invoice vs photograph/video) against supplied evidence IDs. MET / PARTIALLY_MET / NOT_MET. |
| informational categories | NOT_ASSESSABLE with an explanation (a human interprets them). |

Assessment statuses: `met`, `not_met`, `partially_met`,
`not_assessable`. Missing information is returned as a separate list —
never embedded in explanations.

Evaluation statuses:

- `policy_not_provided` — no policy supplied. Never invented.
- `policy_requires_human_interpretation` — policy supplied but no rule
  could be deterministically evaluated (e.g. zero rules, or only
  informational clauses).
- `evaluated` — at least one deterministic assessment exists.

## 3. Recommendation (`_recommend` in support_case_analyzer)

Priority chain, in order:

1. Contradictions across sources → `escalate_to_human` (the AI cannot
   decide which source is correct).
2. `policy_not_provided` → `insufficient_policy_information`
   (seller chat refund promises are mentioned in the reasoning but never
   alone trigger a refund recommendation).
3. `policy_requires_human_interpretation` → `insufficient_policy_information`.
4. Any NOT_MET rule + missing information that could change the
   assessment → `request_more_information`.
5. NOT_MET rules without missing information →
   `refund_not_supported_by_provided_policy` — reasoning explicitly
   states this is **not a definitive rejection**; a human agent decides.
6. PARTIALLY_MET rules → `request_more_information`.
7. NOT_ASSESSABLE rules with missing information → `request_more_information`.
8. All evaluable rules MET:
   - customer requested "refund" → `refund_recommended`
   - requested replacement/repair → `alternative_resolution_suggested`
   - unclear request → `escalate_to_human`

A recommendation is never selected merely because the customer requested
a refund — it always follows the evidence and the policy. Every
recommendation carries `reasoning`, `supporting_evidence_ids`,
`contradicting_evidence_ids`, `missing_information`,
`relevant_policy_rule_ids`, `confidence`, and
`requires_human_review=True`.

## Honesty invariants

- Policy clauses are never invented; quotes are verbatim or dropped.
- A mock vision photo (no observations) can only reach PARTIALLY_MET —
  mock output can never complete a "photographic proof" condition.
- Backend-supplied policies are used verbatim and never overwritten.
- The evaluator never concludes fraud, dishonesty, or legal liability.
