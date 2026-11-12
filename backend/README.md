# ProofBridge Backend

ProofBridge is an evidence-intelligence and fulfillment-verification
platform for freelance and client work. Clients record what was agreed,
freelancers submit delivery evidence, Person 3's AI/ML module analyses the
evidence, and an authorized human reviewer makes the final case decision.

> **Product boundary:** ProofBridge is **not** an escrow service. The
> backend never holds, releases, transfers, refunds, or captures money.
> AI output is advisory decision support and always requires human review.
> PayPal integration is limited to authorized, read-only retrieval of
> transaction and order information.

This repository contains the FastAPI backend and the existing Person 3
`proofbridge_ai` package. It does not contain the frontend.

- Frontend contract: [FRONTEND_INTEGRATION_GUIDE.md](FRONTEND_INTEGRATION_GUIDE.md)
- AI analysis API notes: [ANALYSIS_API.md](ANALYSIS_API.md)
- Final verification report: [FINAL_BACKEND_ACCEPTANCE_REPORT.md](FINAL_BACKEND_ACCEPTANCE_REPORT.md)
- Person 3 AI documentation: [ai_module/ai_module/docs/ai/README.md](ai_module/ai_module/docs/ai/README.md)

---

## 1. Purpose and architecture

The backend provides:

1. JWT authentication and role/project authorization.
2. Project, requirement, agreement, and evidence management.
3. An adapter around Person 3's `proofbridge_ai` package for evidence
   extraction, claim analysis, and investigation reports.
4. Persistent analysis snapshots and report snapshots.
5. A reviewer-only human-review workflow with immutable decisions.
6. An append-only case timeline built from status, analysis, report, and
   review records.
7. Read-only PayPal transaction and order-information storage.
8. A consistent error envelope, health checks, CORS, and OpenAPI docs.

Request flow:

```text
HTTP request
   -> FastAPI router (authentication, role, project authorization)
   -> service layer (business rules, transactions)
   -> SQLAlchemy models
   -> SQLite (default) or PostgreSQL (supported by SQLAlchemy)

Analysis request
   -> app/services/ai_analysis.py adapter
   -> proofbridge_ai facade (Person 3's real package)
   -> validated AI output
   -> Report + AnalysisResult rows in one transaction
```

AI code is isolated in `ai_module/ai_module/proofbridge_ai/`. The backend
adapter translates project rows into the AI module's documented input
models and validates the returned Pydantic models; it does not implement a
second AI pipeline.

---

## 2. Features and backend capabilities

| Area | Capability |
|---|---|
| Authentication | Register client/freelancer, OAuth2 password login, JWT bearer auth, `/auth/me`, stateless logout |
| Roles | `client`, `freelancer`, `reviewer`; reviewer-only review endpoints |
| Projects | Create/list/get/update projects; client ownership; freelancer assignment |
| Status | Validated transitions and append-only status history |
| Requirements | Client-owned create/list/get/update; no delete endpoint |
| Agreements | Client-owner upload, participant/reviewer download, atomic replacement |
| Evidence | Assigned-freelancer upload, participant/reviewer list/download, content-based type detection |
| AI analysis | Run/reuse snapshots, history, per-project scoping, provider preflight, stale-input detection |
| Reports | Stored investigation reports, latest/list/get, no AI call during report generation |
| Human review | Reviewer pending list, context, append-only decisions, status transition, 405 for mutation |
| Case history | Unified read-only timeline: status, analysis, report, human review |
| PayPal | Configuration status, transaction and order sync, stored list/get; read-only only |
| Operations | `/health`, `/health/db`, OpenAPI `/openapi.json`, Swagger `/docs`, ReDoc `/redoc` |

All AI findings include `requires_human_review: true` and a
`final_decision_notice`. There is no endpoint that approves or executes a
payment.

---

## 3. Technology stack

| Component | Version used and verified |
|---|---|
| Python | 3.14.7 in this workspace; project code requires 3.10+ |
| FastAPI | 0.162.2 |
| Starlette | 1.10.0 |
| SQLAlchemy | 2.1.8 |
| Pydantic | 2.14.3 |
| pydantic-settings | 2.16.2 |
| PyJWT | 2.15.1 |
| bcrypt | 5.0.0 |
| Uvicorn | 0.54.0 |
| HTTP client | httpx 0.28.1 |
| Database | SQLite (default); PostgreSQL schema-compatible, no driver installed |
| AI package | `proofbridge-ai` 0.2.0, using numpy, PyMuPDF, python-docx, Pillow |
| Tests | pytest 9.2.0, FastAPI TestClient/httpx |

---

## 4. Project folder structure

```text
proofbridge-backend/
├── app/
│   ├── main.py                 FastAPI app, lifespan, routers, CORS
│   ├── config.py               Backend environment settings
│   ├── database.py             Engine, sessions, init_db, additive migration
│   ├── models.py               Nine SQLAlchemy models
│   ├── schemas.py              Request/response Pydantic schemas
│   ├── security.py             Password hashing, JWT, role dependencies
│   ├── errors.py               Consistent error envelope
│   ├── routers/                HTTP endpoints by feature
│   └── services/               Business logic and AI/PayPal/storage adapters
├── ai_module/ai_module/
│   ├── proofbridge_ai/         Person 3's AI/ML package
│   ├── docs/ai/                AI architecture, schemas, configuration
│   ├── examples/               Offline demo and FastAPI reference
│   └── tests/                  AI package tests
├── tests/                      Backend API tests
├── uploads/                    Runtime upload root (gitignored)
├── requirements.txt            Development/test freeze
├── requirements-ai.txt         Editable Person 3 package install
├── requirements-prod.txt       Runtime-only production dependencies
├── .env.example                Safe environment template
├── pytest.ini                  pytest configuration
├── ANALYSIS_API.md
├── FRONTEND_INTEGRATION_GUIDE.md
└── FINAL_BACKEND_ACCEPTANCE_REPORT.md
```

Runtime data (`proofbridge.db`, `uploads/`, `.env`) is intentionally not
part of the source tree and is excluded by `.gitignore`.

---

## 5. Python environment setup

From the repository root (Windows examples; use the equivalent
`source venv/bin/activate` on Linux/macOS):

```bash
python -m venv venv
venv/Scripts/python.exe -m pip install --upgrade pip
```

Python 3.10 or newer is required by the AI package. The workspace was
verified on Python 3.14.7.

### Dependency installation

Development and tests:

```bash
venv/Scripts/python.exe -m pip install -r requirements.txt
venv/Scripts/python.exe -m pip install -r requirements-ai.txt
```

Production runtime only:

```bash
venv/Scripts/python.exe -m pip install -r requirements-prod.txt
```

`requirements-ai.txt` installs the local Person 3 package in editable
mode. `requirements-prod.txt` installs it non-editable and pins its
runtime dependencies.

Optional OCR support:

```bash
venv/Scripts/python.exe -m pip install "pytesseract>=0.3.10"
```

OCR also requires the Tesseract engine installed on the host.

Optional PostgreSQL driver:

```bash
venv/Scripts/python.exe -m pip install "psycopg[binary]>=3.2,<4"
```

---

## 6. Environment variable configuration

Copy the safe template and edit it. Never commit the resulting `.env`.

> **Warning:** if a real `.env` already exists, do **not** overwrite it.
> Back it up first and merge the missing keys manually. The commands below
> are for a fresh checkout only.

```bash
copy .env.example .env        # Windows, fresh checkout only
cp .env.example .env          # Linux/macOS, fresh checkout only
```

The backend reads `.env` from the repository root regardless of the
current directory. The AI package also reads `.env` from the process
working directory, so **start the application from the repository root**
when using a single shared file.

### Backend variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | no | `sqlite:///./proofbridge.db` | SQLAlchemy database URL; relative SQLite paths resolve from repo root |
| `SECRET_KEY` | **yes** | — | JWT HS256 signing secret; use 32+ random characters |
| `ACCESS_TOKEN_MINUTES` | no | `1440` | Access-token lifetime |
| `LOG_LEVEL` | no | `INFO` | Backend logging level |
| `CORS_ORIGINS` | no | `http://localhost:3000,http://localhost:5173` | Comma-separated explicit browser origins |
| `CORS_ALLOW_CREDENTIALS` | no | `true` | Cannot be combined with `*` origins |
| `UPLOAD_DIR` | no | `uploads` | Upload root; relative paths resolve from repo root |
| `MAX_UPLOAD_BYTES` | no | `10485760` | Backend upload limit (10 MB) |
| `PAYPAL_CLIENT_ID` | no | — | PayPal app client id; lookup disabled when blank |
| `PAYPAL_CLIENT_SECRET` | no | — | PayPal app secret; never logged or stored |
| `PAYPAL_API_BASE` | no | `https://api-m.sandbox.paypal.com` | Sandbox or live API base |
| `PAYPAL_TIMEOUT_SECONDS` | no | `15` | PayPal HTTP timeout |

`APP_NAME` and `APP_VERSION` have defaults and normally need no override.

### Person 3 AI variables

| Variable | Default | Purpose |
|---|---|---|
| `PROOFBRIDGE_ENV` | `development` | `development`, `production`, or `demo` |
| `PROOFBRIDGE_DEMO_MODE` | `false` | `true` forces offline mock providers |
| `PROOFBRIDGE_LOG_LEVEL` | `INFO` | AI package logging |
| `PROOFBRIDGE_LLM_PROVIDER` | `mock` | `mock` or `openai` |
| `PROOFBRIDGE_LLM_API_KEY` | blank | LLM key (SecretStr, never logged) |
| `PROOFBRIDGE_LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `PROOFBRIDGE_LLM_MODEL` | `gpt-4o-mini` | LLM model name |
| `PROOFBRIDGE_LLM_TEMPERATURE` | `0.0` | Sampling temperature |
| `PROOFBRIDGE_EMBEDDINGS_PROVIDER` | `mock` | `mock` or `openai` |
| `PROOFBRIDGE_EMBEDDINGS_API_KEY` | blank | Embeddings key |
| `PROOFBRIDGE_EMBEDDINGS_BASE_URL` | `https://api.openai.com/v1` | Embeddings base URL |
| `PROOFBRIDGE_EMBEDDING_MODEL` | `text-embedding-3-small` | Embeddings model |
| `PROOFBRIDGE_VISION_PROVIDER` | `mock` | `mock` or `openai` |
| `PROOFBRIDGE_VISION_API_KEY` | blank | Vision key |
| `PROOFBRIDGE_VISION_BASE_URL` | `https://api.openai.com/v1` | Vision base URL |
| `PROOFBRIDGE_VISION_MODEL` | `gpt-4o-mini` | Multimodal model |
| `PROOFBRIDGE_OCR_ENABLED` | `false` | Allow OCR when Tesseract is installed |
| `PROOFBRIDGE_TESSERACT_CMD` | blank | Optional Tesseract binary path |
| `PROOFBRIDGE_OCR_LANGUAGE` | `eng` | OCR language |
| `PROOFBRIDGE_MAX_FILE_SIZE_BYTES` | `10485760` | AI-side file limit |
| `PROOFBRIDGE_MAX_PDF_PAGES` | `100` | PDF page limit |
| `PROOFBRIDGE_MAX_IMAGE_PIXELS` | `25000000` | Image pixel limit |
| `PROOFBRIDGE_MAX_DOCUMENT_CHARS` | `200000` | Extracted-text cap |
| `PROOFBRIDGE_HTTP_TIMEOUT_SECONDS` | `60` | Provider request timeout |
| `PROOFBRIDGE_MAX_RETRIES` | `2` | Provider retry bound |
| `PROOFBRIDGE_SIMILARITY_SUPPORTED_THRESHOLD` | `0.60` | Supported relevance threshold |
| `PROOFBRIDGE_SIMILARITY_PARTIAL_THRESHOLD` | `0.40` | Partial relevance threshold |
| `PROOFBRIDGE_SIMILARITY_MAX_CANDIDATES` | `5` | Evidence candidates per claim |

The AI package validates ranges at startup. The supported similarity
threshold must be greater than or equal to the partial threshold.

**Default behavior is offline and deterministic.** With
`PROOFBRIDGE_DEMO_MODE=true` or all providers set to `mock`, no external
AI calls are made. Selecting `openai` without the corresponding key
causes a configuration error rather than a silent fallback.

---

## 7. Database setup and initialization

### SQLite (default)

No database server is needed. The default URL is
`sqlite:///./proofbridge.db`, resolved to the repository root. Start the
app once and the database file is created.

### PostgreSQL (optional, not switched in this repository)

The models compile to PostgreSQL DDL for all nine tables. PostgreSQL was
**not runtime-tested** in this workspace because no PostgreSQL server or
driver is installed. Before using it:

1. Install `psycopg[binary]`.
2. Set `DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname`.
3. Review `app/database.py` startup schema behavior.
4. Validate in a staging database first.
5. Do not point the existing production SQLite deployment at PostgreSQL
   without a planned data migration.

### Startup schema behavior

On startup, `app/main.py` calls `init_db()`:

- `Base.metadata.create_all()` creates only missing tables.
- `_add_missing_analysis_result_columns()` adds only nullable columns that
  are missing from an existing `analysis_results` table.
- It never drops tables, deletes rows, or rewrites existing data.

A verification run in this workspace confirmed that calling `init_db()`
left all row counts and row hashes unchanged, with SQLite
`integrity_check = ok` and no foreign-key violations.

### Migration strategy

There is **no Alembic migration directory in this repository yet**. The
current strategy is additive-only and safe for the existing schema:

- New tables: created automatically.
- New nullable `analysis_results` columns: added automatically.
- Future renames, type changes, non-nullable columns, or data backfills:
  **not handled automatically**.

Before any schema change that is not additive, introduce Alembic:

1. Add Alembic to the deployment environment.
2. Generate a baseline revision against the current schema.
3. Stamp the existing production database with the baseline revision
   (does not alter tables).
4. Create the next revision with `alembic revision --autogenerate`.
5. Review every generated operation manually; reject drops/rewrites that
   are not intentional.
6. Back up the database, run `alembic upgrade head` in staging, verify
   data, then apply in production.

Do not run destructive migrations against the real database as part of
routine startup.

### Backups

Back up the database **and** `UPLOAD_DIR` together. Evidence rows point to
files under the upload root; restoring only one side leaves broken
downloads.

---

## 8. Starting the FastAPI development server

From the repository root:

```bash
venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Health checks:

```http
GET http://127.0.0.1:8000/health
GET http://127.0.0.1:8000/health/db
```

Interactive documentation:

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>

The API currently defines 31 paths and 40 operations.

A real Uvicorn startup against a temporary SQLite database was verified:
`/health` returned `200`, `/health/db` returned `200`,
`/openapi.json` returned `200` with 31 paths, and `/docs` returned `200`.

---

## 9. Running tests

Backend suite (uses an isolated temporary SQLite database and temporary
upload directory; the real database is not used):

```bash
venv/Scripts/python.exe -m pytest -q
```

Person 3 AI package suite:

```bash
cd ai_module/ai_module
../../venv/Scripts/python.exe -m pytest -q
```

Latest actual results in this workspace:

| Suite | Result |
|---|---|
| Backend | **212 passed**, 2 warnings |
| Person 3 AI package | **238 passed, 3 skipped** |

The tests force mock AI providers and never require paid external API
calls or real PayPal credentials. See
[FINAL_BACKEND_ACCEPTANCE_REPORT.md](FINAL_BACKEND_ACCEPTANCE_REPORT.md)
for the full verification matrix.

---

## 10. Upload storage configuration

- `UPLOAD_DIR` is the single upload root, resolved from the repository
  root when relative.
- Stored layout:
  - `agreements/<project_id>/<uuid>.<ext>`
  - `evidence/<project_id>/<uuid>.<ext>`
- Display filenames are sanitized; stored filenames are random and are
  never returned by the API.
- Files are written atomically through a temporary file and `os.replace`.
- A database failure removes the newly stored file.
- Downloads are served only through authenticated project-scoped
  endpoints with containment-checked paths and `X-Content-Type-Options:
  nosniff`.
- Allowed content: PDF, DOCX, PNG, JPEG, WEBP, detected from file bytes.
- Backend limit: `MAX_UPLOAD_BYTES` (10 MB default).
- AI-side limit: `PROOFBRIDGE_MAX_FILE_SIZE_BYTES` (10 MB default).

Production storage guidance:

- Put `UPLOAD_DIR` on a persistent volume, not a container's ephemeral
  filesystem.
- Back it up with the database.
- Restrict filesystem permissions to the application account.
- Do not serve `uploads/` directly from a web server; use the API
  download endpoints.
- If running multiple instances, use shared storage or a single writer;
  local disk alone will not work across hosts.
- Consider malware scanning and retention policies for uploaded
  documents.

---

## 11. AI/ML integration requirements

Person 3's package is a real dependency, not a reimplementation:

```bash
pip install -r requirements-ai.txt
```

The backend integration lives in `app/services/ai_analysis.py` and uses
the package's `ProofBridgeAIFacade`, Pydantic schemas, and exceptions.
It extracts text from PDF/DOCX and images, analyses requirements against
evidence, and generates an investigation report.

Modes:

- **Mock/demo (default in tests):** no network calls. Outputs are labeled
  mock/heuristic and include `human_review_required: true`.
- **Real providers:** set the provider to `openai` (or another
  OpenAI-compatible endpoint) and provide keys. This sends document text
  and images to that external provider. Obtain privacy/legal approval
  before enabling it with real user documents.
- **OCR:** disabled by default; requires Tesseract plus the optional
  `pytesseract` package.
- **Vision:** only used when evidence includes images and a vision
  provider is configured.

Required external credentials for real AI processing:

- `PROOFBRIDGE_LLM_API_KEY` when the LLM provider is `openai`.
- `PROOFBRIDGE_EMBEDDINGS_API_KEY` when embeddings use `openai`.
- `PROOFBRIDGE_VISION_API_KEY` when images and the vision provider use
  `openai`.

No paid external AI calls were made during development or verification.

---

## 12. PayPal transaction and order-information configuration

PayPal is optional and **read-only**:

- OAuth client-credentials token request.
- `GET /v2/payments/captures/{transaction_id}` for capture information.
- `GET /v2/checkout/orders/{order_id}` for order information.
- No create, capture, authorize, void, refund, payout, transfer, or release
  endpoint exists. Person 4's payment-execution endpoints were reviewed but
  intentionally not mounted because they conflict with the product boundary.
- Payer identity and sensitive fields are removed before storage.
- Credentials are never returned, logged, or stored in the database.

Configuration:

```dotenv
PAYPAL_CLIENT_ID=your-paypal-app-client-id
PAYPAL_CLIENT_SECRET=your-paypal-app-client-secret
PAYPAL_API_BASE=https://api-m.sandbox.paypal.com
PAYPAL_TIMEOUT_SECONDS=15
```

Use a PayPal app that can read transactions. Use sandbox credentials for
development. Leave both credentials blank to keep lookup disabled; the
status endpoint reports `configured: false`, and sync returns `503`.

Endpoints:

- `GET /projects/{project_id}/paypal/status`
- `POST /projects/{project_id}/paypal/transactions/sync` (client owner)
- `POST /projects/{project_id}/paypal/orders/sync` (client owner)
- `GET /projects/{project_id}/paypal/transactions`
- `GET /projects/{project_id}/paypal/transactions/{transaction_id}`

Order sync stores the sanitized order status, intent, normalized
`payment_state` (`PENDING_APPROVAL`, `APPROVED`, `HELD`, `PAID`, `VOIDED`,
`EXPIRED`, or `FAILED`), authorization/capture identifiers, and case
reference. It reuses the `paypal_transactions` table; no schema migration is
required. A payment recorded as an order and later as a capture (or vice
versa) is rejected with `409` so duplicate transaction records are not
created.

Required external credentials: PayPal client id/secret and a sandbox or
live API base. No PayPal credentials are included in this repository.

---

## 13. Security considerations

- Passwords use bcrypt with a 72-byte limit; hashes are never returned.
- Login uses the same error and comparable bcrypt work for unknown emails
  and wrong passwords.
- JWTs are HS256 signed with `SECRET_KEY`, require `exp` and `sub`, and
  reject invalid/expired/unsigned tokens.
- Role checks and project-level checks are enforced in routers and
  services; nested resources from another project return `404`.
- Reviewers can read all projects by design; only reviewers can submit
  human decisions.
- Reviewer notes are not copied into status/history responses that
  clients and freelancers can read.
- Reports and reviews reject stale analyses after requirements or
  evidence change (`409`).
- Uploads are content-sniffed, size-bounded, sanitized, atomically
  stored, and path-contained.
- Validation errors do not echo input values.
- Unhandled errors return a generic `500` envelope; details stay in
  server logs.
- CORS rejects wildcard origins combined with credentials.
- Settings redacts secrets from `repr`; startup warns about short
  secrets without printing them.
- `.env`, `uploads/`, and `*.db` are gitignored.

Operational security still required:

- Use a long random `SECRET_KEY` and a TLS-terminating reverse proxy.
- Set explicit production CORS origins; never use `*` with credentials.
- Restrict database and upload-directory permissions.
- Rotate PayPal/LLM keys and keep them out of logs and source control.
- Add rate limiting/lockout at the edge until it is implemented in the
  application.
- Treat uploaded documents as sensitive personal data.

Known security limitations are listed in the acceptance report and the
frontend guide: no rate limiting/lockout, no token revocation/refresh,
stateless logout, no reviewer self-registration, and 24-hour default
token lifetime.

---

## 14. Deployment instructions and limitations

### Production dependencies

```bash
pip install -r requirements-prod.txt
```

### Production startup

Run from the repository root so the AI package and `.env` resolve
consistently:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --workers 1 --proxy-headers --no-access-log
```

Use **one worker** until the per-project analysis lock is replaced with a
cross-process lock. Multiple workers can otherwise run duplicate analyses
for the same project. Scale horizontally only after adding a shared
lock/idempotency mechanism and shared upload storage.

A process manager or container restart policy should keep the process
alive. Put a TLS-terminating reverse proxy in front of Uvicorn and set
`X-Forwarded-*` handling deliberately.

### Production checklist

1. Create `.env` from `.env.example`; set a strong `SECRET_KEY` and
   explicit `CORS_ORIGINS`.
2. Choose and back up the database. For PostgreSQL, install the driver
   and validate in staging first.
3. Put `UPLOAD_DIR` on persistent storage and back it up with the
   database.
4. Configure AI providers and keys only after privacy approval; keep
   mock/demo mode for non-production testing.
5. Configure PayPal read-only credentials only if needed.
6. Set a reverse-proxy request-body limit slightly above
   `MAX_UPLOAD_BYTES` because the application size check occurs after
   multipart receipt.
7. Verify `/health` (liveness) and `/health/db` (readiness) after startup.
8. Send logs to stdout/stderr or a central collector; keep
   `LOG_LEVEL=INFO` unless debugging.
9. Run the test suite in the deployment environment before release.
10. Do not run destructive schema migrations at startup; use the
    migration strategy in section 7.

### Deployment limitations

- No Dockerfile, systemd unit, or cloud manifest is included; deployment
  was **not performed**.
- SQLite is single-writer and suitable for small/single-instance
  deployments; use PostgreSQL for concurrent production workloads after
  staging validation.
- Uploads use local filesystem storage; multi-host deployment needs
  shared storage or an object-store adapter that is not implemented.
- No Alembic migration framework is present yet.
- No application-level rate limiting, account lockout, or request-ID
  tracing.
- No email/notification service.
- No background queue; analysis runs synchronously in the request.
- AI provider integrations are real but were verified only with mocks. Real
  provider calls require credentials and privacy review.
- PayPal read-only capture and order information was verified with mocked
  HTTP responses, not a live PayPal account.
- Person 4's money-moving PayPal flows (create/capture/authorize/void) are
  not integrated; they require an explicit product and legal decision.

---

## 15. Test and acceptance references

- Backend tests: `tests/`
- Full end-to-end workflow: [tests/test_e2e_workflow.py](tests/test_e2e_workflow.py)
- Security regression tests: [tests/test_security_audit.py](tests/test_security_audit.py)
- Final acceptance matrix: [FINAL_BACKEND_ACCEPTANCE_REPORT.md](FINAL_BACKEND_ACCEPTANCE_REPORT.md)
- Frontend endpoint contracts: [FRONTEND_INTEGRATION_GUIDE.md](FRONTEND_INTEGRATION_GUIDE.md)

The final acceptance report distinguishes **PASS**, **PARTIAL**,
**FAIL**, and **NOT APPLICABLE** items and lists every remaining manual
setup or external credential requirement.
