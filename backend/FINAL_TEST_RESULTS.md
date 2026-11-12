# ProofBridge Backend — Final Test Results

**Date:** 2026-11-11
**Environment:** Windows 10, Python 3.14.7, virtual environment at
`venv/`, SQLite, Person 3 AI package version 0.2.0.
**Test isolation:** Backend tests use a temporary SQLite database and
temporary upload directory created by `tests/conftest.py`. The live server
check used separate temporary files (`audit_tmp.db`,
`audit_tmp_uploads/`). The development database `proofbridge.db` was not
written to.

---

## 1. Exact commands and results

### 1.1 Compilation

From `C:\Users\hp\Desktop\proofbridge-backend`:

```text
venv/Scripts/python.exe -m compileall -q app tests ai_module/ai_module/proofbridge_ai
```

Result: **exit code 0**, no syntax/compilation errors.

### 1.2 Import checks

```text
venv/Scripts/python.exe -c "import app.main; import proofbridge_ai; print('IMPORT_APP_OK'); print('AI_VERSION', proofbridge_ai.__version__)"
```

Result:

```text
IMPORT_APP_OK
AI_VERSION 0.2.0
```

### 1.3 Backend test collection

```text
venv/Scripts/python.exe -m pytest --collect-only -q
```

Result: **197 tests collected in 0.34s**.

### 1.4 Full backend test suite

```text
venv/Scripts/python.exe -m pytest -q
```

Result:

```text
197 passed, 2 warnings in 155.76s (0:02:35)
```

Passed: **197**
Failed: **0**
Skipped: **0**
Blocked: **0**

Warnings:

1. `StarletteDeprecationWarning`: the installed `fastapi.testclient`
   reports that using `httpx` with `starlette.testclient` is deprecated in
   favor of `httpx2`. This is a test-client dependency warning, not a
   backend behavior failure.
2. `InsecureKeyLengthWarning` from `tests/test_security_audit.py::test_token_with_wrong_signature_is_rejected`:
   the forged-token test intentionally uses a short HMAC key. Production
   startup separately warns if `SECRET_KEY` is shorter than 32 characters.

### 1.5 AI module test collection

From `C:\Users\hp\Desktop\proofbridge-backend\ai_module\ai_module`:

```text
../../venv/Scripts/python.exe -m pytest --collect-only -q
```

Result: **241 tests collected in 0.30s**.

### 1.6 Full AI module test suite

```text
../../venv/Scripts/python.exe -m pytest -q -rs
```

Result:

```text
238 passed, 3 skipped in 2.16s
```

Passed: **238**
Failed: **0**
Skipped: **3**
Blocked: **0**

Skip reasons:

```text
SKIPPED [1] tests/test_ocr_service.py:43: Tesseract is not installed
SKIPPED [1] tests/test_ocr_service.py:52: Tesseract is not installed
SKIPPED [1] tests/test_ocr_service.py:59: Tesseract is not installed
```

These are OCR integration tests that require the external Tesseract engine.
All non-OCR AI tests passed.

### 1.7 Dependency consistency

```text
venv/Scripts/python.exe -m pip check
```

Result:

```text
No broken requirements found.
```

Installed production versions match `requirements-prod.txt`, including:

```text
fastapi 0.162.2
uvicorn 0.54.0
SQLAlchemy 2.1.8
pydantic 2.14.3
pydantic-settings 2.16.2
PyJWT 2.15.1
bcrypt 5.0.0
httpx 0.28.1
pymupdf 2.1
numpy 2.5.4
python-docx 1.2.0
pillow 13.0.0
```

AI package metadata and runtime version both report **0.2.0**.

---

## 2. Test coverage by file

Backend test definitions by file (143 `def test_` functions; 197 collected
cases including parameters):

| File | Test functions |
|---|---|
| `tests/test_auth.py` | 18 |
| `tests/test_ai_integration.py` | 16 |
| `tests/test_case_history.py` | 3 |
| `tests/test_e2e_workflow.py` | 1 full workflow |
| `tests/test_files.py` | 16 |
| `tests/test_foundation.py` | 23 |
| `tests/test_human_reviews.py` | 6 |
| `tests/test_paypal.py` | 7 |
| `tests/test_projects.py` | 14 |
| `tests/test_reports.py` | 6 |
| `tests/test_requirements.py` | 10 |
| `tests/test_security_audit.py` | 23 |

AI module test definitions by file (207 functions; 241 collected cases):

`test_config`, `test_conversation_analyzer`, `test_cross_source_verifier`,
`test_document_extractor`, `test_embeddings_client`,
`test_evidence_extractor`, `test_exceptions`, `test_facade`,
`test_file_validation`, `test_llm_client`, `test_mock_provider`,
`test_ocr_service`, `test_policy_evaluator`, `test_policy_extractor`,
`test_product_analyzer`, `test_report_generator`, `test_scenarios`,
`test_similarity_engine`, `test_support_case_analyzer`,
`test_text_normalizer`, `test_ticket_analyzer`, `test_vision_analyzer`.

---

## 3. Live application execution

### 3.1 Startup command

```text
DATABASE_URL="sqlite:///./audit_tmp.db" \
UPLOAD_DIR="audit_tmp_uploads" \
SECRET_KEY="<temporary audit-only value>" \
PROOFBRIDGE_DEMO_MODE="true" \
venv/Scripts/python.exe -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8765 --log-level info
```

The server log confirmed:

```text
Starting ProofBridge AI API v1.0.0
Database ready (2.3 ms).
Application startup complete.
Uvicorn running on http://127.0.0.1:8765
```

No startup exception, router-registration error, or database error occurred.

### 3.2 Real HTTP request matrix

| Method and path | Result |
|---|---|
| `GET /` | 200 |
| `GET /health` | 200 |
| `GET /health/db` | 200 |
| `GET /openapi.json` | 200 (31 paths) |
| `GET /docs` | 200 |
| `POST /auth/register` (client) | 201 |
| `POST /auth/register` (freelancer) | 201 |
| `POST /auth/register` (outsider client) | 201 |
| `POST /auth/register` (duplicate email) | 409 |
| `POST /auth/login` | 200 |
| `GET /auth/me` | 200 |
| `GET /projects` (anonymous) | 401 |
| `GET /projects` (invalid token) | 401 |
| `POST /projects` | 201 |
| `GET /projects/{id}` (outsider) | 403 |
| `POST /projects/{id}/requirements` | 201 |
| `POST /projects/{id}/agreement` | 201 |
| `POST /projects/{id}/analysis` (no evidence) | 201, honest `insufficient_evidence` result |
| `POST /projects/{id}/evidence` | 201 |
| `POST /projects/{id}/analysis` | 201 |
| `POST /projects/{id}/analysis` again | 200 (reused matching snapshot) |
| `POST /projects/{id}/reports` | 201 |
| `GET /projects/{id}/evidence/{evidence_id}/download` | 200 (`%PDF` content) |
| Same evidence download as outsider | 403 |
| `PATCH /projects/{id}/status` (`in_progress`) | 200 |
| `PATCH /projects/{id}/status` (`under_review`) | 200 |
| `GET /projects/{id}/history` | 200 (status/analysis/report events present) |
| `GET /reviews/pending` as client | 403 |
| `POST /auth/logout` | 200 |

Final live-check marker: **`LIVE_CHECK_OK`**.

### 3.3 Live database evidence

The temporary database contained all nine tables:

```text
analysis_results, case_status_log, evidence, human_reviews,
paypal_transactions, projects, reports, requirements, users
```

Checks:

```text
INTEGRITY ok
FK_VIOLATIONS []
```

Persisted analysis/report metadata:

```text
ROW 1 kind=project_ai_analysis status=completed_with_warnings
      ai=0.2.0 human_review=True
      providers={'llm':'mock','embeddings':'mock','vision':'unused','ocr':'disabled'}
      external=False
ROW 2 kind=project_ai_analysis status=completed
      ai=0.2.0 human_review=True
      providers={'llm':'mock','embeddings':'mock','vision':'unused','ocr':'disabled'}
      external=False
ROW 3 kind=project_investigation_report status=completed_with_warnings
      ai=0.2.0 human_review=True
```

This confirms the backend executed the real Person 3 pipeline with the
offline mock providers and persisted validated output.

---

## 4. Existing database verification

Read-only checks against `proofbridge.db`:

| Check | Result |
|---|---|
| Tables | 9 / 9 |
| Columns | Every model column present; none unexpected |
| Foreign keys | Present as defined by the models |
| `PRAGMA integrity_check` | `ok` |
| `PRAGMA foreign_key_check` | No rows |
| Row counts | 1 existing user; all other tables empty |
| SHA-256 before and after audit | Identical |

The real `.env` was not read, printed, overwritten, or modified. Its
metadata remained unchanged (143 bytes, last modified 2026-11-09 23:10).

---

## 5. PostgreSQL and migration checks

- All nine model tables compiled successfully using the SQLAlchemy
  PostgreSQL dialect: **9 / 9**.
- `psycopg`/`psycopg2` is not installed and no PostgreSQL server is
  available.
- PostgreSQL runtime connectivity, DDL application, and query behavior were
  therefore **not executed** and are marked BLOCKED.
- No Alembic history exists. The application uses additive-only startup
  schema initialization; no destructive migration was run.

---

## 6. Fixes applied

No backend source changes were required during this audit. The full suites
above were executed against the final existing source.

One temporary live-check assumption was corrected: an analysis request
with no evidence is expected to return `201` with an honest
`insufficient_evidence`/`completed_with_warnings` result, not a `4xx`
rejection. This matches the existing documented and tested behavior and did
not require a product change.

Temporary audit files (`audit_live_check.py`, `audit_tmp.db`,
`audit_tmp_uploads/`, `audit_server.log`) were removed after verification.
No production uploads or database records were deleted.

---

## 7. Final test summary

| Suite | Passed | Failed | Skipped | Blocked |
|---|---:|---:|---:|---:|
| Backend (`pytest -q`) | 197 | 0 | 0 | 0 |
| Person 3 AI (`pytest -q -rs`) | 238 | 0 | 3 | 0 |
| Live HTTP smoke flow | All checks | 0 | 0 | 0 |
| Compilation/import | PASS | 0 | — | — |
| Dependency check | PASS | 0 | — | — |

**No executed test failed.** The only unverified areas are those requiring
external resources: live AI provider credentials/privacy approval, live
PayPal credentials, PostgreSQL runtime, and Tesseract OCR.
