# ProofBridge Backend — Frontend Integration Guide

This guide describes the API as it exists in this repository after the
Prompt 10 integration and security audit. It is written for the frontend
team and reflects actual request/response schemas and the tests that verify
them.

- Application name: **ProofBridge AI API**
- API version: **1.0.0**
- AI package version reported by analysis/report responses: **0.2.0**
- Default local base URL: **http://localhost:8000**
- Interactive docs: **http://localhost:8000/docs**
- ReDoc: **http://localhost:8000/redoc**
- Machine-readable schema: **http://localhost:8000/openapi.json**

> **Product boundary:** ProofBridge is an evidence-intelligence and
> fulfillment-verification platform. It is **not** an escrow service.
> Backend endpoints never hold, release, transfer, refund, or capture money.
> AI output is advisory and always requires a human decision. PayPal
> endpoints only retrieve and store read-only transaction and order
> information.

---

## 1. Running the backend locally

```bash
# From the repository root
python -m venv venv
venv/Scripts/pip install -r requirements.txt -r requirements-ai.txt

# Create local configuration (never commit .env)
copy .env.example .env

# Start the API
venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

On startup the backend creates missing tables and runs a database health
check. Configuration is read from environment variables or `.env`.

Key settings:

| Setting | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./proofbridge.db` | SQLite path is resolved from the repository root |
| `SECRET_KEY` | required | Use at least 32 random characters outside local dev |
| `ACCESS_TOKEN_MINUTES` | `1440` | Access-token lifetime (24 hours) |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated explicit origins |
| `CORS_ALLOW_CREDENTIALS` | `true` | `*` cannot be combined with credentials |
| `MAX_UPLOAD_BYTES` | `10485760` (10 MB) | Application-level upload limit |
| `UPLOAD_DIR` | `uploads` | Resolved from the repository root |
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` | unset | Only needed for PayPal lookup |
| `PAYPAL_API_BASE` | sandbox URL | `sandbox` vs `live` is inferred from the host |
| `PROOFBRIDGE_DEMO_MODE` | unset | `true` forces Person 3's deterministic mock AI providers |

Health endpoints:

```http
GET /health
GET /health/db
```

`GET /health` returns liveness. `GET /health/db` returns `200` when the
database is ready and `503` with `missing_tables` when it is degraded.

---

## 2. Authentication

### 2.1 Register

`POST /auth/register` — public. JSON body. Field values are validated and
unknown fields are rejected.

```json
{
  "name": "Ada Client",
  "email": "ada@example.com",
  "password": "correct-horse",
  "role": "client"
}
```

- `name`: 2–150 characters
- `password`: 8–72 **bytes** (UTF-8; bcrypt limit)
- `role`: `client` or `freelancer` only

Response `201`:

```json
{
  "id": 2,
  "name": "Ada Client",
  "email": "ada@example.com",
  "role": "client",
  "created_at": "2026-11-11T09:46:20.668803"
}
```

Response fields never include the password or password hash.

Notes:

- Emails are normalized to lowercase.
- Duplicate email returns `409 conflict`.
- **Reviewer accounts cannot be self-registered.** They are provisioned by
  an operator directly in the database. The frontend should not show a
  public “reviewer” registration option.

### 2.2 Login

`POST /auth/login` — public. This endpoint uses the OAuth2 password form
encoding (`application/x-www-form-urlencoded`), **not JSON**. The email is
sent in the `username` field.

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=ada@example.com&password=correct-horse"
```

Response `200`:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

Unknown email and wrong password produce the same `401` response:

```json
{
  "error": {
    "code": "unauthorized",
    "message": "Incorrect email or password."
  }
}
```

### 2.3 Sending the token

Every protected endpoint expects:

```http
Authorization: Bearer <access_token>
```

A missing, malformed, expired, or incorrectly signed token returns `401`.
Tokens contain `sub` (user id), `iat`, and `exp`; `exp` and `sub` are
required on decode.

### 2.4 Current user and logout

```http
GET  /auth/me       -> current user profile
POST /auth/logout   -> { "message": "Logged out. Discard the access token on the client." }
```

Logout is stateless. The backend does not revoke the token; the frontend
must delete it from storage. There is no refresh-token endpoint.

---

## 3. Error format

Every error response uses one envelope:

```json
{
  "error": {
    "code": "conflict",
    "message": "The project is already in status 'completed'.",
    "details": null
  }
}
```

`details` is optional. Validation errors include structured details but
**never echo input values** (so passwords are not reflected back).

| HTTP | `error.code` | Typical cause |
|---|---|---|
| 400 | `bad_request` | Invalid non-schema request (for example empty upload) |
| 401 | `unauthorized` | Missing/invalid/expired token, bad credentials |
| 403 | `forbidden` | Authenticated but wrong role or not a project participant |
| 404 | `not_found` | Resource missing, or not scoped to the requested project |
| 405 | `method_not_allowed` | Unsupported method (reviews are append-only) |
| 409 | `conflict` | Duplicate email, invalid status transition, stale analysis |
| 413 | `payload_too_large` | Upload exceeds `MAX_UPLOAD_BYTES` |
| 415 | `unsupported_media_type` | Upload content is not a supported type |
| 422 | `validation_error` | Request body/query failed schema validation |
| 429 | `too_many_requests` | Reserved; rate limiting is not implemented yet |
| 500 | `internal_server_error` | Unexpected server error (generic message) |
| 502 | `bad_gateway` | PayPal upstream failure or invalid upstream payload |
| 503 | `service_unavailable` | Database unavailable or PayPal not configured |

Example validation error:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [
      {
        "type": "string_too_short",
        "loc": ["body", "password"],
        "msg": "String should have at least 8 characters"
      }
    ]
  }
}
```

---

## 4. Roles and project-level access

Roles are `client`, `freelancer`, and `reviewer`.

- A **client** owns projects it creates.
- A **freelancer** is assigned to a project by `freelancer_id`.
- A **reviewer** is allowed to read every project. Reviewer *write* access
  is limited to human-review endpoints.

Project participants are the project's client and assigned freelancer.

| Capability | Client owner | Other client | Assigned freelancer | Other freelancer | Reviewer |
|---|---|---|---|---|---|
| List projects | own only | own only | assigned only | assigned only | all |
| Create project | yes | yes (creates own) | no | no | no |
| Read project / status | yes | 403 | yes | 403 | yes |
| Update project details | yes | 403 | no | no | no |
| Change project status | yes | 403 | no | no | no |
| Write requirements | yes | 403 | no | no | no |
| Read requirements | yes | 403 | yes | 403 | yes |
| Upload agreement | yes | 403 | no | no | no |
| Download agreement | yes | 403 | yes | 403 | yes |
| Upload evidence | no | no | yes | 403 | no |
| List/download evidence | yes | 403 | yes | 403 | yes |
| Run/read analysis | yes | 403 | yes | 403 | yes |
| Generate/read reports | yes | 403 | yes | 403 | yes |
| Human-review endpoints | no | no | no | no | yes |
| Read case history | yes | 403 | yes | 403 | yes |
| PayPal read status/list/get | yes | 403 | yes | 403 | yes |
| PayPal transaction sync | yes | 403 | no | no | no |
| PayPal order sync | yes | 403 | no | no | no |

A resource belonging to another project returns `404`, not `403`, to avoid
confirming that the resource exists.

---

## 5. Endpoints by feature

All endpoints below except `/auth/register`, `/auth/login`, `/`, and
`/health*` require a bearer token.

### 5.1 Projects

#### Create a project — `POST /projects` (client only)

```json
{
  "title": "Landing page delivery",
  "description": "Delivered work is incomplete.",
  "freelancer_id": 3
}
```

- `title`: 3–255 characters
- `description`: optional, up to 5000 characters
- `freelancer_id`: must reference an existing user with role `freelancer`

Response `201`:

```json
{
  "id": 1,
  "title": "Landing page delivery",
  "description": "Delivered work is incomplete.",
  "status": "created",
  "freelancer_id": 3,
  "client_id": 2,
  "agreement_name": null,
  "created_at": "2026-11-11T09:46:21.834614"
}
```

Stored file paths are never returned.

#### List projects — `GET /projects`

Returns a JSON array of `ProjectResponse`. Scoping follows the table in
section 4.

#### Get one project — `GET /projects/{project_id}`

Returns one `ProjectResponse`, or `403` for outsiders and `404` if missing.

#### Update project — `PATCH /projects/{project_id}` (client owner only)

```json
{
  "title": "Landing page delivery — revised",
  "description": "Updated scope."
}
```

Both fields are optional, but at least one must be supplied. The project
must not be `completed` or `cancelled`.

#### Get status history — `GET /projects/{project_id}/status`

```json
{
  "project_id": 1,
  "status": "under_review",
  "history": [
    {
      "status": "created",
      "note": "Project created.",
      "changed_by": 2,
      "created_at": "2026-11-11T09:46:21.838967"
    },
    {
      "status": "in_progress",
      "note": "Status changed from 'created' to 'in_progress'.",
      "changed_by": 2,
      "created_at": "2026-11-11T09:46:22.674886"
    }
  ]
}
```

#### Change status — `PATCH /projects/{project_id}/status` (client owner only)

```json
{
  "status": "in_progress",
  "note": "Work started."
}
```

`note` is optional and limited to 1000 characters. Allowed transitions:

| Current | Allowed next |
|---|---|
| `created` | `in_progress`, `cancelled` |
| `in_progress` | `under_review`, `cancelled` |
| `under_review` | `completed`, `in_progress`, `cancelled` |
| `completed` | none (terminal) |
| `cancelled` | none (terminal) |

Setting the same status or an invalid transition returns `409`.

`completed` and `cancelled` projects are immutable: project edits,
requirements, agreements, and evidence uploads are rejected with `409`.

### 5.2 Requirements

#### Create — `POST /projects/{project_id}/requirements` (client owner)

```json
{
  "text": "Deliver a responsive landing page with a contact form.",
  "category": "deliverable",
  "source_quote": "Optional quote from the agreement"
}
```

- `text`: 10–2000 characters, required
- `category`: optional, up to 100 characters
- `source_quote`: optional, up to 2000 characters

Response `201`:

```json
{
  "id": 1,
  "project_id": 1,
  "text": "Deliver a responsive landing page with a contact form.",
  "category": "deliverable",
  "source_quote": null
}
```

#### Read — `GET /projects/{project_id}/requirements` and
`GET /projects/{project_id}/requirements/{requirement_id}`

Both return requirement objects. A requirement id from another project
returns `404`.

#### Update — `PATCH /projects/{project_id}/requirements/{requirement_id}`
(client owner)

Any of `text`, `category`, `source_quote`; at least one field must be
present. Requirements cannot be deleted.

### 5.3 Agreement upload and download

Upload (client owner): `POST /projects/{project_id}/agreement`

`multipart/form-data` with field name **`file`**:

```bash
curl -X POST http://localhost:8000/projects/1/agreement \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@contract.pdf"
```

Response `201`:

```json
{
  "project_id": 1,
  "agreement_name": "contract.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 48213,
  "replaced_existing": false
}
```

Uploading a new agreement replaces the previous file; the response then
has `"replaced_existing": true`. The replacement is atomic.

Download (any participant or reviewer):
`GET /projects/{project_id}/agreement/download`

Returns the file with `Content-Disposition: attachment` and
`X-Content-Type-Options: nosniff`. If no agreement exists, returns `404`.

### 5.4 Evidence

Upload (assigned freelancer only, project must be mutable):
`POST /projects/{project_id}/evidence`

`multipart/form-data` with field name **`file`**:

```bash
curl -X POST http://localhost:8000/projects/1/evidence \
  -H "Authorization: Bearer $FREELANCER_TOKEN" \
  -F "file=@receipt.pdf"
```

Response `201`:

```json
{
  "id": 1,
  "project_id": 1,
  "uploaded_by": 3,
  "filename": "receipt.pdf",
  "mime_type": "application/pdf",
  "created_at": "2026-11-11T09:46:22.393268"
}
```

List (participants or reviewer): `GET /projects/{project_id}/evidence`
returns an array of the same object.

Download: `GET /projects/{project_id}/evidence/{evidence_id}/download`.
The evidence id must belong to the project, otherwise `404`.

Upload rules:

| Rule | Behavior |
|---|---|
| Allowed content | PDF, DOCX, PNG, JPEG, WEBP — detected from file bytes, not the client MIME type |
| Empty file | `400 bad_request` |
| Unsupported/renamed file | `415 unsupported_media_type` |
| Larger than `MAX_UPLOAD_BYTES` | `413 payload_too_large` |
| Filename | Sanitized to a display name; stored names are random UUIDs |
| Storage | Atomic temp-file write; DB failure removes the stored file |
| Response | Never exposes `stored_path` |

The application-level size check runs after the multipart request has been
received. For production, also set a request-body limit on the reverse
proxy.

### 5.5 AI analysis

Run analysis (participants or reviewer): `POST /projects/{project_id}/analysis`

Optional query: `?force=true` to create a new snapshot even when the
latest snapshot already matches the current inputs.

- `201` — new analysis snapshot created
- `200` — latest snapshot reused because the input fingerprint matches
- `409` — not applicable to the analysis call; stale checks happen on
  report generation and human review

Response (top-level fields; full nested schema is in `/docs`):

```json
{
  "kind": "project_ai_analysis",
  "schema_version": "1.1",
  "status": "completed",
  "project_id": 1,
  "case_id": "project-1",
  "generated_at": "2026-11-11T09:46:22.541974Z",
  "ai_package_version": "0.2.0",
  "human_review_required": true,
  "final_decision_notice": "This is an AI-generated investigation recommendation. An authorized human support agent must make the final decision.",
  "provider_modes": {
    "llm": "mock",
    "embeddings": "mock",
    "vision": "unused",
    "ocr": "disabled"
  },
  "external_processing": false,
  "input_fingerprint": "fc2eb63c238daf70e5197c9728cc5634b06a787453f0f9242381c26a3be85c72",
  "input_summary": {
    "requirement_ids": [1],
    "evidence_ids": [1],
    "skipped_evidence_ids": [],
    "evidence_files_processed": 1
  },
  "integration_warnings": [],
  "comparison": {
    "verified_requirement_ids": [],
    "supported_requirement_ids": [],
    "partially_supported_requirement_ids": [],
    "unverified_requirement_ids": [],
    "insufficient_evidence_requirement_ids": [1],
    "contradicted_requirement_ids": [],
    "missing_evidence_requirement_ids": [1],
    "uncertain_requirement_ids": [1],
    "human_attention_requirement_ids": [1],
    "evidence_needing_attention_ids": []
  },
  "analysis_result_ids": [1],
  "report_id": 1
}
```

`status` is `completed` or `completed_with_warnings`. Warnings are listed
in `integration_warnings` (for example, a project with no requirements or
no evidence still returns a valid analysis with warnings).

Per-requirement findings:

```json
{
  "requirement_id": 1,
  "requirement_text": "Deliver a responsive landing page with a contact form.",
  "status": "insufficient_evidence",
  "confidence": 1.0,
  "rationale": "No evidence relevant to this claim was found among the supplied evidence items.",
  "supporting_evidence_ids": [],
  "contradicting_evidence_ids": [],
  "cited_evidence_ids": [],
  "analysis_method": "heuristic",
  "source_kind": "heuristic",
  "requires_human_review": true
}
```

Verification statuses:

- `supported`
- `partially_supported`
- `contradicted`
- `unverified`
- `insufficient_evidence`

Every finding has `requires_human_review: true`. There is no status that
approves or executes payment.

Read endpoints:

- `GET /projects/{project_id}/analysis` — latest snapshot (`404` if none)
- `GET /projects/{project_id}/analysis/history?limit=20&offset=0` —
  paginated compact history, newest first (`limit` 1–50)
- `GET /projects/{project_id}/analysis/{report_id}` — one snapshot; a
  snapshot from another project returns `404`

History response:

```json
{
  "items": [
    {
      "report_id": 1,
      "project_id": 1,
      "case_id": "project-1",
      "status": "completed",
      "generated_at": "2026-11-11T09:46:22.541974Z",
      "created_at": "2026-11-11T09:46:22.543569",
      "ai_package_version": "0.2.0",
      "human_review_required": true,
      "input_fingerprint": "fc2e...",
      "requirement_count": 1,
      "evidence_count": 1,
      "analysis_result_count": 1,
      "supported_requirement_count": 0,
      "human_attention_requirement_count": 1
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### 5.6 Investigation reports

Generate a stored report (participants or reviewer):
`POST /projects/{project_id}/reports`

Optional query: `?analysis_report_id=<id>` selects a specific stored
analysis snapshot. Defaults to the latest snapshot.

- `201` — report generated and stored
- `404` — no analysis exists (or selected snapshot is not in this project)
- `409` — requirements or evidence changed after the selected analysis;
  run a new analysis first

Generating a report **does not run the AI**, does not change case status,
and never authorizes payment.

Response (top-level fields):

```json
{
  "kind": "project_investigation_report",
  "schema_version": "1.0",
  "status": "completed_with_warnings",
  "project": {
    "project_id": 1,
    "title": "Landing page delivery",
    "description": "Delivered work is incomplete.",
    "status": "created",
    "client_id": 2,
    "freelancer_id": 3,
    "created_at": "2026-11-11T09:46:21.834614"
  },
  "analysis_report_id": 1,
  "analysis_generated_at": "2026-11-11T09:46:22.541974Z",
  "ai_package_version": "0.2.0",
  "generated_at": "2026-11-11T09:46:22.633343Z",
  "human_review_required": true,
  "final_decision_notice": "This is an AI-generated investigation recommendation. An authorized human support agent must make the final decision.",
  "advisory_notice": "AI observations in this report are advisory only. A human reviewer makes the final case decision. ProofBridge does not hold, move, release, or refund money and does not control PayPal funds.",
  "report_id": 2,
  "created_at": "2026-11-11T09:46:22.638748"
}
```

The report also contains `requirement_findings`, `evidence_inventory`,
`missing_information`, `inconsistencies`,
`uncertain_requirement_ids`, `contradicted_requirement_ids`,
`missing_evidence_requirement_ids`, `human_review_recommendations`,
`limitations`, and `source_warnings`.

Report requirement finding:

```json
{
  "requirement_id": 1,
  "requirement_text": "Deliver a responsive landing page with a contact form.",
  "status": "insufficient_evidence",
  "confidence": 1.0,
  "rationale": "No evidence relevant to this claim was found among the supplied evidence items.",
  "supporting_evidence_ids": [],
  "contradicting_evidence_ids": [],
  "cited_evidence_ids": [],
  "missing_evidence": true,
  "uncertain": true,
  "requires_human_review": true,
  "human_review_reason": "AI found insufficient evidence for this requirement; a human reviewer should assess or request the missing evidence."
}
```

Evidence inventory entry:

```json
{
  "evidence_id": 1,
  "filename": "receipt.pdf",
  "kind": "pdf",
  "status": "processed",
  "summary": "PDF evidence: extracted text begins: \"RECEIPT\\nOrder #ORD-1234\\nDate: 2026-11-01\\nTotal: $49.99\"",
  "needs_attention": false,
  "extraction_warning_codes": []
}
```

Read endpoints:

- `GET /projects/{project_id}/reports/latest`
- `GET /projects/{project_id}/reports?limit=20&offset=0`
- `GET /projects/{project_id}/reports/{report_id}`

Reports intentionally **exclude human-review notes**. Reviewer decisions
are only available through reviewer-only review endpoints and the case
timeline summary (which contains the decision but not the notes).

### 5.7 Human review (reviewer only)

Only reviewers can call these endpoints. Clients and freelancers receive
`403`, including for projects they own.

- `GET /reviews/pending` — cases currently in `under_review` **and** with
  at least one stored analysis. Projects in `under_review` without an
  analysis are omitted, so the UI should direct the client to run analysis
  before the case can appear for review.
- `GET /projects/{project_id}/reviews/context` — project, latest analysis,
  evidence, status history, and prior reviews.
- `POST /projects/{project_id}/reviews` — submit a decision.
- `GET /projects/{project_id}/reviews` — append-only review history.
- `GET /projects/{project_id}/reviews/{review_id}` — one review.

The project must be in `under_review`; otherwise `409`.

Request:

```json
{
  "decision": "verified",
  "notes": "Evidence matches the agreed deliverable."
}
```

- `decision`: `verified`, `partially_verified`, `rejected`,
  `needs_more_evidence`
- `notes`: 10–5000 characters, required

Decision effects:

| Decision | Resulting project status |
|---|---|
| `verified` | `completed` |
| `partially_verified` | `completed` |
| `rejected` | `cancelled` |
| `needs_more_evidence` | `in_progress` |

Response `201`:

```json
{
  "review": {
    "id": 1,
    "project_id": 1,
    "reviewer_id": 4,
    "decision": "verified",
    "notes": "Evidence matches the agreed deliverable.",
    "created_at": "2026-11-11T09:46:23.131055"
  },
  "project_status": "completed"
}
```

Rules:

- Reviews are append-only. There is no update or delete endpoint
  (`405 method_not_allowed`).
- If requirements or evidence changed after the latest analysis, the
  review is rejected with `409` until a new analysis is run.
- Reviewer notes are **not** copied into status history or the case
  timeline, since clients and freelancers can read those endpoints.
- A `needs_more_evidence` decision moves the project back to
  `in_progress`; it can be sent back to `under_review` later for a new
  review.

### 5.8 Case timeline

`GET /projects/{project_id}/history` — participants or reviewer.

```json
{
  "project_id": 1,
  "current_status": "completed",
  "events": [
    {
      "event_type": "status",
      "occurred_at": "2026-11-11T09:46:21.838967",
      "actor_id": 2,
      "summary": "Project created.",
      "status": "created",
      "reference_id": 1
    },
    {
      "event_type": "analysis",
      "occurred_at": "2026-11-11T09:46:22.543569",
      "actor_id": null,
      "summary": "AI analysis snapshot 1 was generated. It is advisory and requires human review.",
      "status": null,
      "reference_id": 1
    },
    {
      "event_type": "report",
      "occurred_at": "2026-11-11T09:46:22.638748",
      "actor_id": null,
      "summary": "Investigation report 2 was generated from a stored AI analysis snapshot.",
      "status": null,
      "reference_id": 2
    },
    {
      "event_type": "human_review",
      "occurred_at": "2026-11-11T09:46:23.131055",
      "actor_id": 4,
      "summary": "A human reviewer recorded decision 'verified'.",
      "status": null,
      "reference_id": 1
    }
  ]
}
```

`event_type` values: `status`, `analysis`, `report`, `human_review`.
Events are append-only and sorted by occurrence. Reviewer notes are not
included.

### 5.9 PayPal transaction and order information (read-only)

Configuration status — participant or reviewer:

`GET /projects/{project_id}/paypal/status`

```json
{
  "configured": false,
  "environment": "sandbox",
  "lookup_mode": "read_only_transaction_information",
  "money_control_notice": "PayPal is an external payment provider. ProofBridge only retrieves and stores transaction information that PayPal returns. Stored transaction data does not mean ProofBridge holds, controls, or can move those funds."
}
```

Retrieve and store a transaction — **client owner only**:

`POST /projects/{project_id}/paypal/transactions/sync`

```json
{
  "transaction_id": "CAPTURE-123"
}
```

Response `201` (new) or `200` (already stored for this project):

```json
{
  "created": true,
  "transaction": {
    "id": 1,
    "project_id": 1,
    "paypal_transaction_id": "CAPTURE-123",
    "amount": 49.99,
    "currency": "USD",
    "status": "COMPLETED",
    "provider": "paypal",
    "raw_data": {
      "id": "CAPTURE-123",
      "status": "COMPLETED",
      "amount": { "currency_code": "USD", "value": "49.99" },
      "final_capture": true,
      "create_time": "2026-11-01T10:00:00Z",
      "update_time": "2026-11-01T10:01:00Z"
    },
    "money_control_notice": "PayPal is an external payment provider. ProofBridge only retrieves and stores transaction information that PayPal returns. Stored transaction data does not mean ProofBridge holds, controls, or can move those funds.",
    "created_at": "2026-11-11T09:46:22.000000"
  }
}
```

Retrieve and store an order (read-only) — **client owner only**:

`POST /projects/{project_id}/paypal/orders/sync`

```json
{
  "order_id": "ORDER-123"
}
```

Response `201` (new) or `200` (already stored for this project):

```json
{
  "created": true,
  "transaction": {
    "id": 2,
    "project_id": 1,
    "paypal_transaction_id": "ORDER-123",
    "amount": 75.5,
    "currency": "USD",
    "status": "APPROVED",
    "information_type": "order",
    "intent": "AUTHORIZE",
    "payment_state": "APPROVED",
    "authorization_id": null,
    "authorization_status": null,
    "capture_id": null,
    "case_reference": "CASE-001",
    "provider": "paypal",
    "raw_data": {
      "id": "ORDER-123",
      "status": "APPROVED",
      "payment_state": "APPROVED",
      "intent": "AUTHORIZE",
      "reference_id": "CASE-001",
      "create_time": "2026-11-01T10:00:00Z",
      "update_time": "2026-11-01T10:01:00Z"
    },
    "money_control_notice": "PayPal is an external payment provider. ProofBridge only retrieves and stores transaction information that PayPal returns. Stored transaction data does not mean ProofBridge holds, controls, or can move those funds.",
    "created_at": "2026-11-11T09:46:22.000000"
  }
}
```

`payment_state` is one of `PENDING_APPROVAL`, `APPROVED`, `HELD`, `PAID`,
`VOIDED`, `EXPIRED`, or `FAILED`. `information_type` is `"order"` or
`"capture"`. Order rows are returned by the same list/get endpoints and use
`paypal_transaction_id` for the order identifier. Payer identity is not
stored or returned.

Read stored transactions and orders — participants or reviewer:

- `GET /projects/{project_id}/paypal/transactions`
- `GET /projects/{project_id}/paypal/transactions/{transaction_id}`

Rules and errors:

- The backend uses PayPal OAuth plus `GET /v2/payments/captures/{id}` and
  `GET /v2/checkout/orders/{id}` only. There are no create, capture,
  authorize, void, refund, payout, transfer, or release endpoints.
- Payer identity and other sensitive fields are removed from `raw_data`
  before storage and response.
- `503` — `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` not configured.
- `404` — PayPal does not know the transaction or order.
- `502` — PayPal authentication/upstream failure, network failure, or an
  incomplete/mismatched PayPal response.
- `409` — the transaction/order is already stored under a different
  project, or the same payment is already recorded as the other record
  type (order vs. capture).
- Duplicate sync for the same project returns `200` and does not call
  PayPal again.

---

## 6. End-to-end frontend flow

1. **Register/login.** Store the bearer token. On any `401`, clear the
   token and return to login.
2. **Client creates a project** with a freelancer id. Fetch freelancers
   from your own directory/API if available; there is no public user
   search endpoint in this backend.
3. **Client adds requirements** (each at least 10 characters) and may
   upload the agreement.
4. **Assigned freelancer uploads evidence** while the project is mutable.
5. **Any participant or reviewer runs analysis.**
   - Treat `201` and `200` the same: both return a usable snapshot.
   - Show `human_review_required` and `final_decision_notice`; never
     present AI as a final payment decision.
6. **Generate a report** from the stored analysis, then read
   `/reports/latest` or the report list. If you receive `409`, rerun
   analysis first.
7. **Client moves the project to `under_review`.**
8. **Reviewer** lists `/reviews/pending`, opens
   `/projects/{id}/reviews/context`, and submits a decision with notes.
9. **All participants** refresh project status and
   `/projects/{id}/history` to show the final human decision.

Suggested polling: pending reviews and project status change on human
action, so a short poll interval or manual refresh is sufficient. There is
no websocket/event stream.

---

## 7. CORS

- Origins must be listed explicitly in `CORS_ORIGINS`.
- Defaults: `http://localhost:3000` and `http://localhost:5173`.
- `CORS_ALLOW_CREDENTIALS` defaults to `true`.
- Starting the app with `CORS_ORIGINS=*` **and** credentials enabled is a
  configuration error.
- The API uses `Authorization` headers, so no cookies are required; if you
  disable credentials, the wildcard becomes allowed for token-only use.

---

## 8. Frontend implementation notes

- **Token storage:** prefer in-memory plus a secure storage strategy
  appropriate to your deployment. The token is valid until `exp`
  (default 24 hours) and logout does not revoke it.
- **Login encoding:** send `application/x-www-form-urlencoded`, not JSON.
- **Uploads:** use `FormData` with the field name `file`. Do not set the
  `Content-Type` manually; let the browser add the boundary.
- **Dates:** timestamps are ISO 8601 strings. Analysis/report
  `generated_at` values may end in `Z`; SQLite-backed `created_at` values
  may not include a timezone suffix. Parse as ISO and display in local
  time.
- **Pagination:** analysis history and reports accept
  `limit` (1–50, default 20) and `offset` (default 0). Responses include
  `total`, `limit`, and `offset`.
- **403 vs 404:** do not infer resource existence from a `403`; use the
  project list as the source of truth for what a user can see.
- **Report/review freshness:** when requirements or evidence change, old
  analyses remain readable, but generating a report or submitting a review
  returns `409` until a new analysis is run. Surface this as “Re-run
  analysis to continue.”
- **Privacy:** status/history/report endpoints never expose reviewer notes
  to clients or freelancers. Do not build UI that assumes those notes are
  present outside reviewer views.
- **No money movement:** do not build buttons for capture/refund/release.
  There are no such endpoints, by design.
- **Error handling:** always read `error.code` and `error.message`. The
  `details` array is intended for form-field mapping.

---

## 9. Known limitations and unresolved items

- No rate limiting, account lockout, CAPTCHA, or 429 behavior yet.
- No refresh tokens and no server-side revocation; logout is client-side
  token disposal.
- The default access-token lifetime is 24 hours (`ACCESS_TOKEN_MINUTES`).
- Reviewer accounts are provisioned outside the API; there is no admin
  user-management or reviewer-invite endpoint.
- The application upload-size check runs after the multipart body has been
  received. Add a reverse-proxy request-body limit for production.
- Reviewers can read all projects by design. If tenant isolation is
  required later, this policy must be revisited.
- Report/review staleness covers requirement text/identity and evidence
  identity. Project title/description edits do not invalidate an existing
  analysis/report/review.
- Analysis duplicate prevention uses a per-project lock in the API
  process. Run a single worker process or add a cross-process lock before
  horizontal scaling.
- No delete endpoints exist for projects, requirements, evidence, reports,
  or reviews. Reviews and status history are intentionally append-only.
- No email/notification infrastructure.

---

## 10. Verification status

The behaviours in this guide are covered by the automated suite:

- Backend API suite: **212 passed** (`python -m pytest -q`)
- Person 3 AI package suite: **238 passed, 3 skipped**
- `GET /openapi.json`: `200`, 31 paths / 40 operations
- `GET /docs`: `200`

For exact field-level schemas and interactive requests, use `/docs` or
`/openapi.json`; this guide is a narrative companion to that schema.
