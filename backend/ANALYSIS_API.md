# Evidence Analysis API

This document describes the implemented project-scoped evidence analysis
endpoints. The analysis itself is performed by Person 3's existing
`proofbridge_ai` package; the backend adapts project data, validates every
output with that package's Pydantic models, and persists the result.

## Authorization

All endpoints require a Bearer JWT and an authorized role:

- `client`
- `freelancer`
- `reviewer`

The caller must also be the project's client or assigned freelancer, or a
reviewer. Unrelated authenticated users receive `403`; missing or invalid
tokens receive `401`.

## Endpoints

### `POST /projects/{project_id}/analysis`

Runs the evidence analysis for the project.

Query parameters:

- `force` (boolean, default `false`) — run again even when the latest
  snapshot matches the current project inputs.

Responses:

- `201 Created` — a new snapshot was created.
- `200 OK` — the latest snapshot already matches the current inputs and was
  reused without another AI call.
- `400` — invalid AI input.
- `401` / `403` — authentication or project authorization failure.
- `404` — project not found.
- `409` — the result could not be saved.
- `413` — evidence exceeds the configured size limit.
- `415` — unsupported evidence type.
- `422` — a document could not be extracted.
- `500` — configuration/analysis failure or a rejected output.
- `501` — an AI service is not implemented.
- `502` — provider failure, invalid AI output, missing requirement
  assessment, or evidence reference outside the project.
- `503` — OCR was requested but is unavailable.

### `GET /projects/{project_id}/analysis`

Returns the newest stored analysis snapshot. `404` if none exists.

### `GET /projects/{project_id}/analysis/history`

Returns compact history entries, newest first.

Query parameters:

- `limit` (1–50, default `20`)
- `offset` (default `0`)

Response:

```json
{
  "items": [
    {
      "report_id": 1,
      "project_id": 1,
      "case_id": "project-1",
      "status": "completed",
      "generated_at": "2026-11-11T08:15:04Z",
      "created_at": "2026-11-11T08:15:04Z",
      "ai_package_version": "0.2.0",
      "human_review_required": true,
      "input_fingerprint": "...",
      "requirement_count": 1,
      "evidence_count": 1,
      "analysis_result_count": 1,
      "supported_requirement_count": 1,
      "human_attention_requirement_count": 0
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### `GET /projects/{project_id}/analysis/{report_id}`

Returns one full snapshot. A report that belongs to another project is
reported as `404`.

## Response shape

`ProjectAnalysisResponse` contains:

- `report_id`, `project_id`, `case_id`, `created_at`
- `status` — `completed` or `completed_with_warnings`
- `input_fingerprint` — hash of the exact project/evidence/provider inputs
- `input_summary` — requirements, evidence, skipped evidence, processed count
- `requirement_findings` — one entry per project requirement
- `comparison` — grouped requirement and evidence attention IDs
- `analysis` — Person 3's `SupportCaseAnalysisResult`
- `report` — Person 3's `InvestigationReport`
- `analysis_result_ids` — persisted `AnalysisResult` row IDs
- `human_review_required` and `final_decision_notice`

Each requirement finding copies Person 3's actual assessment:

- `status` — `supported`, `partially_supported`, `unverified`,
  `insufficient_evidence`, or `contradicted`
- `confidence`, `rationale`, `analysis_method`, `source_kind`
- backend evidence IDs for supporting, contradicting, and cited evidence
- `requires_human_review`

The comparison groups those findings into:

- supported / verified
- partially supported
- unverified
- insufficient evidence
- contradicted
- missing evidence (requirements with no relevant evidence)
- uncertain requirements
- requirements needing human attention
- backend evidence IDs needing human attention

## Persistence

Each run writes one immutable `reports` snapshot and, for every backend
requirement, one `analysis_results` row containing:

- `project_id`, `requirement_id`, `evidence_id`
- `classification` and `status`
- `confidence`
- `similarity` (maximum actual evidence similarity score, or `null`)
- `explanation`
- `report_id`
- `details` (the complete Person 3 `ClaimAssessment` plus backend evidence
  references)
- `created_at`

The report and rows are committed in one transaction. AI failures never
store partial results.

The new `analysis_results` columns are nullable and were added with an
additive ALTER migration at startup; existing rows remain valid.

## Duplicate and concurrent requests

The analysis input fingerprint covers project fields, requirements,
evidence metadata and file sizes/timestamps, the AI package version, and
provider/OCR/threshold settings.

- If the latest snapshot has the same fingerprint, POST returns it with
  `200` and does not call the AI again.
- `force=true` creates a new snapshot and calls the AI again.
- A per-project process lock prevents two concurrent requests in the same
  process from running the same analysis twice. A multi-worker deployment
  would need a database-backed job/lock for cross-process deduplication.

## Product boundary

The AI output is advisory decision support only. Every result requires
human review, and no endpoint decides a dispute, approves a payment, or
executes a refund.

## Configuration

Default and test configuration uses Person 3's offline mock providers
(`PROOFBRIDGE_DEMO_MODE=true`). To use external providers, set the
documented `PROOFBRIDGE_*` provider and API-key environment variables; the
API reports only missing variable names and never returns secret values.
OCR is disabled by default and requires `pytesseract` plus the Tesseract
engine when enabled.
