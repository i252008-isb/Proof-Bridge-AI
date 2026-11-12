# ProofBridge AI — Backend + AI/ML Integration Audit

**Audit date:** 2026-11-10
**Scope:** Read-only inspection of the existing FastAPI backend and Person 3's `proofbridge_ai` module, both located inside `C:\Users\hp\Desktop\proofbridge-backend`.
**Mode:** AUDIT ONLY. No source file, test, database, schema, `.env`, or package was modified. Only this report was created.

---

## 0. How to read this report

Every major item is classified with one of:

| Label | Meaning |
| --- | --- |
| **VERIFIED COMPLETE** | Code/database/behaviour was directly inspected and (where possible) executed successfully. |
| **IMPLEMENTED BUT UNTESTED** | Source code exists but was not executed successfully during this audit. |
| **PARTIALLY IMPLEMENTED** | Some working parts exist; important pieces are missing. |
| **NOT IMPLEMENTED** | No supporting code was found. |
| **INCOMPATIBLE** | Exists but conflicts with the other side's domain, models, or runtime. |
| **REQUIRES HUMAN DECISION** | Cannot be answered from the code; the owner must choose. |

Findings are marked **(Verified)** when directly observed, **(Code reading)** when established by reading source, and **(Assumption)** when inferred but not proven.

---

## 1. Executive summary

### The headline

The backend and the AI module are **two real codebases that currently cannot run together**, for three independent reasons:

1. **The backend does not start at all.** `app/models.py` contains Pydantic schema classes (`ProjectCreate`, `ProjectUpdate`, `ProjectResponse`) at lines 264–302, but that file never imports `BaseModel`, `Field`, or `ConfigDict`. Importing the app raises `NameError: name 'BaseModel' is not defined` at `app/models.py:268`. Because `app/routers/auth.py` imports `User` from `app/models.py`, **every** endpoint — including login — is unreachable. **(Verified by execution)**
2. **The AI module's domain is different from the product's domain.** The product described in the brief is *freelancer/client project-delivery verification*: agreements → requirements → evidence → requirement-level findings. Person 3's module is a *customer-support and refund investigation* system: support ticket → customer claims → refund policy → refund recommendation. Its own handoff document states that "the previous freelancer/dispute functionality was replaced" (`ai_module/ai_module/docs/ai/HANDOFF_CHECKLIST.md:3-12`). **(Verified by code and docs)**
3. **The AI module is not installed or importable in the backend environment, and its dependencies are absent.** `import proofbridge_ai` fails with `ModuleNotFoundError`; `pip show proofbridge-ai` reports "not found"; Pillow, numpy, PyMuPDF, and python-docx are missing from the backend virtual environment. The AI test suite cannot even be collected (`ModuleNotFoundError: No module named 'PIL'`). **(Verified by execution)**

### What is genuinely good

- The **database schema is real and intact**: nine tables exist in `proofbridge.db`, matching the nine SQLAlchemy models. One user row exists; all other tables are empty. **(Verified, read-only SQLite inspection)**
- The **authentication code is well-written** (bcrypt, HS256 JWT with `exp`/`sub` required, uniform login error, role dependency). It is blocked only by the `models.py` import bug.
- The **AI module is substantial and carefully engineered**: provider abstraction, offline mock providers, document/OCR extraction, evidence processing, similarity scoring, cross-source verification, report generation with fallbacks, error hierarchy, and a clean facade. It explicitly follows the "AI advises, humans decide" boundary and never touches payments. **(Verified by code reading)**
- The **payments boundary is respected on both sides**: the backend only stores PayPal transaction records; the AI module only accepts `PaymentInformation` as informational evidence and never calls payment APIs.

### The single biggest decision you must make

**Which product is authoritative — freelancer delivery verification, or customer-support/refund investigation?** The backend models and the written product brief say freelancer. The delivered AI module says support/refund. Integration work is very different depending on the answer. This is marked **REQUIRES HUMAN DECISION** throughout the report.

### Counts at a glance

| Area | Result |
| --- | --- |
| Backend Python files | 9 (726 lines incl. blank lines) |
| Backend routers | 1 (`auth`) |
| Backend services | 0 files |
| Backend tests | 0 files (`tests/` is empty) |
| Backend can start? | **No** — `NameError` at `app/models.py:268` |
| Database tables | 9 (verified) |
| Database rows | `users`=1, all others=0 |
| AI module Python source | ~7,000 lines under `proofbridge_ai/` |
| AI test files | 22 |
| AI tests executed in this audit | **0** — dependencies missing |
| AI importable in backend venv | **No** |
| Syntax errors across both codebases | 0 (39 files compiled) |

---

## 2. Actual workspace folder structure

The workspace is **`C:\Users\hp\Desktop\proofbridge-backend`**. The AI module is nested inside it at `ai_module/ai_module/` (note the double nesting).

```
C:\Users\hp\Desktop\proofbridge-backend\
├── .env                         # backend secrets (NOT read; contents not disclosed)
├── .gitignore                   # venv, __pycache__, .env, uploads/, *.db
├── proofbridge.db               # SQLite database, 9 tables, 1 user row
├── requirements.txt             # exact-pinned backend dependencies
├── app\                         # = ORIGINAL BACKEND (Person 2)
│   ├── __init__.py
│   ├── config.py                # pydantic-settings (DATABASE_URL, SECRET_KEY)
│   ├── database.py              # SQLAlchemy engine/session/Base/get_db
│   ├── main.py                  # FastAPI app, auth router, / and /health
│   ├── models.py                # 9 SQLAlchemy models + STRAY Pydantic schemas
│   ├── schemas.py               # auth + project Pydantic schemas
│   ├── security.py              # bcrypt + JWT + get_current_user + require_role
│   ├── routers\
│   │   ├── __init__.py
│   │   └── auth.py              # /auth/register, /auth/login, /auth/me
│   └── services\                # EMPTY
├── tests\                       # EMPTY (no tests)
├── uploads\                     # EMPTY (no upload logic)
├── venv\                        # Python 3.14.7 virtual environment
└── ai_module\
    └── ai_module\               # = PERSON 3's AI/ML MODULE
        ├── README.md
        ├── pyproject.toml       # package metadata + dependencies
        ├── requirements.txt     # runtime deps (no pytest)
        ├── .env.example         # PROOFBRIDGE_* configuration template
        ├── docs\ai\             # 15 markdown docs + sample report
        ├── examples\            # run_demo.py, fastapi_integration.py, demo data
        ├── proofbridge_ai\      # the package
        │   ├── __init__.py
        │   ├── config.py
        │   ├── exceptions.py
        │   ├── logging_utils.py
        │   ├── schemas.py       # 1,041-line data contract
        │   ├── integration\facade.py
        │   ├── providers\       # base, mock, llm, embeddings, vision
        │   └── services\        # 15 service modules
        ├── tests\               # 22 test files + conftest + fakes
        └── proofbridge_ai.egg-info\   # evidence of a PRIOR editable install elsewhere
```

### Backend vs Person 3 — inventory

| Category | Original backend | Person 3 AI/ML |
| --- | --- | --- |
| Application code | `app/**` | `ai_module/ai_module/proofbridge_ai/**` |
| API layer | `app/routers/auth.py` only | None (library; example app in `examples/fastapi_integration.py`) |
| Data layer | `app/models.py`, `app/database.py` | None by design (AI never touches DB) |
| Documentation | None | `ai_module/ai_module/docs/ai/**` (15 files) + README |
| Dependencies | `requirements.txt` (exact pins) | `pyproject.toml` + separate `requirements.txt` |
| Configuration | `app/config.py`, root `.env` | `proofbridge_ai/config.py`, `.env.example` |
| Tests | **None** | 22 test files |
| Notebooks | None | None (docs contain a demo script, no `.ipynb`) |
| Demo data | None | `examples/demo_data/**` |

I can confidently distinguish the two parts: the root `app/` tree is the backend; everything under the double-nested `ai_module/ai_module/` is Person 3's. **Nothing was moved, renamed, deleted, or reorganised.**

---

## 3. Existing backend architecture

**Stack (verified from installed packages):** Python **3.14.7**, FastAPI **0.162.2**, Starlette 1.10.0, SQLAlchemy **2.1.8**, Pydantic **2.14.3**, pydantic-settings 2.16.2, bcrypt 5.0.0, PyJWT 2.15.1, pytest 9.2.0, httpx 0.28.1, Uvicorn 0.54.0.

**Layering:**

```
HTTP request
   ↓
FastAPI app (app/main.py)
   ↓  includes only auth router
app/routers/auth.py  ──uses──▶ app/schemas.py (request/response models)
   ↓                          app/security.py (bcrypt, JWT, get_current_user)
   ↓
app/database.py (engine, SessionLocal, Base, get_db)
   ↓
app/models.py (9 SQLAlchemy models)
   ↓
proofbridge.db (SQLite)
```

**What actually exists:**

- Application factory in `app/main.py:5`; only `auth.router` is included (`app/main.py:13`); only `/` (`main.py:16`) and `/health` (`main.py:21`) plus the auth routes.
- Config via `Settings` in `app/config.py:5`; requires `SECRET_KEY` (no default), `DATABASE_URL` defaults to `sqlite:///./proofbridge.db`, token lifetime defaults to 1440 minutes.
- Session/engine in `app/database.py:16`; `get_db` generator at `database.py:36`. SQLite gets `check_same_thread=False`.
- No startup table creation (`Base.metadata.create_all` is **not** called anywhere) and no migration tool. The DB was created out of band.
- No CORS middleware, no static file serving, no exception handlers, no logging configuration, no rate limiting.
- `uploads/` exists but no code reads or writes it.

**Architectural verdict:** a clean but very thin skeleton — authentication plus a database schema. The domain API (projects, requirements, evidence, analysis, reports, reviews, PayPal records) has **models only**, no endpoints, no services.

---

## 4. Existing backend file-by-file analysis

| File | Lines | What it contains | Status |
| --- | --- | --- | --- |
| `app/__init__.py` | 0 | Empty package marker | OK |
| `app/config.py` | 16 | `Settings(BaseSettings)` with `DATABASE_URL`, required `SECRET_KEY`, `ACCESS_TOKEN_MINUTES=1440`; reads `.env`; `extra="ignore"` | VERIFIED COMPLETE (code) |
| `app/database.py` | 42 | Engine (SQLite `check_same_thread=False`), `SessionLocal`, `DeclarativeBase` subclass `Base`, `get_db` | VERIFIED COMPLETE (code) |
| `app/main.py` | 23 | FastAPI app, auth router, `/`, `/health` | **BROKEN** transitively (imports `auth` → `models` → `NameError`) |
| `app/models.py` | 301 | 9 ORM models (lines 28–261) **plus duplicated Pydantic schemas (lines 264–302)** with missing imports | **BROKEN** — `NameError: BaseModel` at line 268 |
| `app/schemas.py` | 87 | `UserCreate`, `UserResponse`, `UserLogin`, `Token`, `ProjectCreate`, `ProjectUpdate`, `ProjectResponse` | IMPLEMENTED BUT UNTESTED; project schemas unused |
| `app/security.py` | 139 | bcrypt hash/verify (72-byte guard), HS256 JWT create/decode, `get_current_user`, `require_role` | IMPLEMENTED BUT UNTESTED; `require_role` unused |
| `app/routers/auth.py` | 118 | `POST /auth/register` (201), `POST /auth/login` (OAuth2 form), `GET /auth/me` | IMPLEMENTED BUT UNTESTED |
| `app/routers/__init__.py` | 0 | Empty | OK |
| `app/services/__init__.py` | 0 | Empty package; no service modules | NOT IMPLEMENTED |
| `tests/` | — | Empty directory | NOT IMPLEMENTED |
| `requirements.txt` | 34 | Exact pins for runtime packages | PARTIALLY IMPLEMENTED (see §16) |
| `.gitignore` | 6 | Ignores `venv/`, `__pycache__/`, `.env`, `uploads/`, `*.db`, `.pytest_cache/` | VERIFIED COMPLETE |

### 4.1 The blocking defect, precisely

`app/models.py:264-302` contains:

```python
class ProjectCreate(BaseModel):     # line 268
class ProjectUpdate(BaseModel):     # line 278
class ProjectResponse(BaseModel):   # line 291
```

The file's imports (lines 1–17) are SQLAlchemy-only; `BaseModel`, `Field`, `ConfigDict` are never imported. At import time the class statement evaluates `BaseModel` → `NameError`. Because `app/routers/auth.py:8` imports `User` from `app/models.py`, the failure propagates to `app.main`.

**Impact:** the entire API is unusable; not a single endpoint can be served. **(Verified by running `from app.main import app`)**

**Root cause:** these three schemas are copy-pasted from `app/schemas.py:54-87`, where the Pydantic imports *do* exist. They are duplicates that belong in `schemas.py` only.

### 4.2 Other backend defects and gaps

| # | Finding | Location | Severity |
| --- | --- | --- | --- |
| B1 | Duplicate Pydantic schemas inside the ORM module; causes import crash | `app/models.py:264-302` | **Critical** |
| B2 | No project/requirement/evidence/analysis/report/review routes | `app/routers/` | High |
| B3 | `app/services/` has no implementation | `app/services/` | High |
| B4 | Zero backend tests | `tests/` | High |
| B5 | No table creation or migrations; fresh installs have no schema | repo-wide | High |
| B6 | `ProjectCreate` requires `freelancer_id` but no `client_id`; creation semantics unclear (client = current user?) | `app/schemas.py:54-57` | Medium |
| B7 | `require_role` is defined but never used; no protected role routes | `app/security.py:125` | Medium |
| B8 | Registration only allows roles `freelancer`/`client`; no `reviewer`/`admin`, yet `HumanReview.reviewer_id` needs a reviewer | `app/schemas.py:15`, `app/models.py:226` | High (for human-review workflow) |
| B9 | `User.role` in DB is an unconstrained `String(30)`; only the Pydantic layer constrains values | `app/models.py:35` | Medium |
| B10 | Password max length is validated in *characters* (`max_length=72`) but bcrypt limit is *bytes*; a multi-byte UTF-8 password can reach `hash_password` and raise an unhandled `ValueError` (HTTP 500) | `app/schemas.py:14`, `app/security.py:23-24` | Low |
| B11 | Login timing differs for unknown email (no bcrypt work) vs wrong password | `app/routers/auth.py:91` | Low |
| B12 | No CORS configuration — a browser frontend on another origin will be blocked | `app/main.py` | Medium |
| B13 | No logout/token revocation/refresh; 24-hour bearer tokens cannot be invalidated | `app/security.py` | Medium |
| B14 | JWT has no `iss`/`aud`/`jti` claims | `app/security.py:56-62` | Low |
| B15 | SQLite foreign keys are **not enabled** (`PRAGMA foreign_keys=ON` never set); declared FKs are not enforced at runtime | `app/database.py:16-19` | High |
| B16 | No indexes on foreign-key columns (`project_id`, etc.), only on `id` | `proofbridge.db` schema | Medium (performance) |
| B17 | `requirements.txt` omits `email-validator` (required by `EmailStr`) although it is installed in the venv | `requirements.txt` vs `pip list` | Medium (reproducibility) |
| B18 | `reports` and `analysis_results` have no `created_at` for analyses; only `reports.created_at` | `app/models.py:155-174` | Low |
| B19 | `AnalysisResult` has no relationship to `Requirement`/`Evidence` (only to `Project`); deleting a requirement/evidence can orphan analysis rows | `app/models.py:161-167` | Medium |
| B20 | Naming inconsistency: `case_status_log` (singular) vs all other plural tables | `app/models.py:182` | Cosmetic |
| B21 | `PayPalTransaction.amount` is annotated `Mapped[float]` but column is `Numeric(12,2)` (returns `Decimal`); serialization assumptions may break | `app/models.py:252` | Low |
| B22 | No `updated_at`, no soft-delete, no optimistic locking anywhere | `app/models.py` | Low |

---

## 5. Verified completed functionality

Only what was actually executed or directly inspected is listed as verified.

| Feature | Evidence | Classification |
| --- | --- | --- |
| Nine-table database exists and matches models | Read-only SQLite query: 9 tables, expected columns/FKs/indexes | **VERIFIED COMPLETE** |
| Database contains data (1 user, everything else empty) | Row counts | **VERIFIED (state)** |
| All 39 Python files are syntactically valid | `compile()` over `app/**` and `proofbridge_ai/**` | **VERIFIED COMPLETE (syntax)** |
| Backend application imports and serves | `from app.main import app` → `NameError` | **BROKEN / NOT VERIFIED** |
| Auth endpoints work | Cannot start app; no tests | **IMPLEMENTED BUT UNTESTED** |
| Password/JWT primitives are correct by inspection | `app/security.py` code reading | **IMPLEMENTED BUT UNTESTED** |
| AI module imports | `pip show proofbridge-ai` not found; `import proofbridge_ai` fails | **NOT DEPLOYABLE HERE** |
| AI module tests pass | Collection fails on missing `PIL`; 0 tests executed | **NOT VERIFIED** |
| AI offline demo runs | Not executed (deps missing) | **NOT VERIFIED** |
| `services/` backend logic | Empty | **NOT IMPLEMENTED** |
| Backend tests | Empty | **NOT IMPLEMENTED** |

### Actual test results recorded during this audit

**Backend import check (executed):**

```
$ ./venv/Scripts/python.exe -c "from app.main import app"
...
  File "...\app\routers\auth.py", line 8, in <module>
    from app.models import User
  File "...\app\models.py", line 268, in <module>
    class ProjectCreate(BaseModel):
NameError: name 'BaseModel' is not defined
```

**Backend test discovery:** `tests/` contains zero files. `pytest tests` would collect 0 tests. No backend test result can be claimed.

**AI test suite (executed, failed to start):**

```
$ ./venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
ImportError while loading conftest '...\tests\conftest.py'
tests\conftest.py:8: in <module>
    from PIL import Image, ImageDraw
ModuleNotFoundError: No module named 'PIL'
```

**AI dependency probe (executed):**

| Module | Backend venv | System Python |
| --- | --- | --- |
| Pillow (`PIL`) | Missing | Missing |
| numpy | Missing | Present |
| PyMuPDF (`fitz`/`pymupdf`) | Missing | Missing |
| python-docx (`docx`) | Missing | Missing |
| pytesseract | Missing | Missing |
| pydantic / pydantic-settings | Present | Missing |
| pytest | Present | Missing |
| httpx | Present | Present |

**Result: 0 AI tests were executed and 0 passed in this environment.** The AI docs claim "238 passed, 3 skipped" (`docs/ai/TESTING.md:15`); that claim could not be reproduced here and is **not** treated as verified.

**Historical cache note (Verified):** `.pytest_cache/v/cache/nodeids` references test files that **no longer exist** — `tests/test_evidence_analyzer.py`, `tests/test_pipeline.py`, `tests/test_requirement_extractor.py`, `tests/test_schemas.py` — and `lastfailed` contains four stale failures. These files correspond to an **earlier, different AI design** focused on requirements/agreements. This is strong evidence the AI module was redesigned from the freelancer domain to the support/refund domain.

---

## 6. Person 3's AI/ML implementation analysis

### 6.1 Identity and scope

- Package: `proofbridge-ai`, import name `proofbridge_ai`, `requires-python >=3.10` (`pyproject.toml:10`).
- Declared version is inconsistent: `pyproject.toml:7` says `0.1.0`; `proofbridge_ai/__init__.py:113` says `0.2.0`; report schema is `2.0` (`schemas.py:37`).
- Stated purpose: "AI-powered **customer support & refund investigation**" (`README.md:3-9`).
- Explicit design statements: never touches the database, never authenticates users, never moves money, never calls PayPal APIs, always sets `human_review_required=True` (`README.md:68-76`, `docs/ai/ARCHITECTURE.md:3-11`).

### 6.2 Architecture

```
Backend supplies Pydantic inputs
   SupportTicket, EvidenceInput/EvidenceUpload, RefundPolicy,
   OrderInformation, CaseContext, PaymentInformation
        │
        ▼
proofbridge_ai.integration.facade
   module-level functions + ProofBridgeAIFacade(settings) + get_facade()
        │
        ▼
services/support_case_analyzer.analyze_support_case  (async wrapper over sync pipeline)
   1 validate ticket
   2 extract claims               ticket_analyzer (LLM or heuristic)
   3 process evidence             evidence_extractor (per-item isolation)
   4 OCR                          document_extractor + ocr_service (Tesseract)
   5 vision                       vision_analyzer (separate from OCR)
   6 purchase facts               product_analyzer (receipts)
   7 conversations                conversation_analyzer
   8 refund policy                policy_extractor (supplied policy wins)
   9 cross-source comparison      cross_source_verifier
  10 contradictions               cross_source_verifier
  11 missing information          pipeline + claim assessment
  12 policy evaluation            policy_evaluator
  13 recommendation               support_case_analyzer._recommend
  14 validated result             SupportCaseAnalysisResult
        │
        ▼
services/report_generator.generate_investigation_report
   → InvestigationReport (structured, ~25 fields, fallback-safe)
```

### 6.3 Component-by-component

| Component | File | What it does (beginner-friendly) | Status |
| --- | --- | --- | --- |
| Config | `proofbridge_ai/config.py:18-117` | Reads `PROOFBRIDGE_*` env vars, validates thresholds/limits, caches settings | IMPLEMENTED |
| Data contract | `schemas.py` (1,041 lines) | All Pydantic models/enums exchanged with the backend | IMPLEMENTED |
| Exceptions | `exceptions.py:10-77` | One base error plus typed sub-errors (file too large, OCR unavailable, provider failed, …) | IMPLEMENTED |
| Safe logging | `logging_utils.py:17-42` | Logs IDs/sizes/hashes, never document text or secrets | IMPLEMENTED |
| Provider abstraction | `providers/base.py:13-89` | Interfaces for LLM, embeddings, vision | IMPLEMENTED |
| Provider factories | `providers/__init__.py:20-116` | Chooses mock vs OpenAI-compatible client; demo mode forces mock | IMPLEMENTED |
| Mock providers | `providers/mock_provider.py:73-174` | Offline deterministic stand-ins; never pretend to be real analysis | IMPLEMENTED |
| LLM client | `providers/llm_client.py:30-193` | OpenAI-compatible chat + JSON-schema prompting, retries, no body logging | IMPLEMENTED |
| Embeddings client | `providers/embeddings_client.py` | OpenAI-compatible embeddings, chunking, reordering | IMPLEMENTED |
| Vision client | `providers/vision_provider.py:33-203` | Multimodal chat with base64 images, retries | IMPLEMENTED |
| File validation | `services/file_validation.py:105-167` | Magic-byte/type/size validation before parsing | IMPLEMENTED |
| Document extraction | `services/document_extractor.py:37-317` | PDF (PyMuPDF, page-by-page, scanned-page OCR), DOCX, TXT/MD/CSV/code, images via OCR | IMPLEMENTED |
| OCR | `services/ocr_service.py:34-137` | Tesseract wrapper; availability check; EXIF rotation; downscaling | IMPLEMENTED (Tesseract optional) |
| Evidence processing | `services/evidence_extractor.py:142-296` | File bytes → `EvidenceItem` (text, summary, deterministic facts, warnings); per-item batch isolation | IMPLEMENTED |
| Ticket/claim extraction | `services/ticket_analyzer.py:79-151` | Complaint → issue type + claims (always `unverified`); backend claims used verbatim | IMPLEMENTED |
| Purchase extraction | `services/product_analyzer.py:74-119` | Receipt → seller/product/order/date/price/quantity, only values present in text | IMPLEMENTED |
| Conversation analysis | `services/conversation_analyzer.py:82-168` | Chat export → messages, speakers, refund promises, contradictions | IMPLEMENTED |
| Policy extraction | `services/policy_extractor.py:125-230` | Refund policy → rules with verbatim quotes (unverifiable quotes dropped) | IMPLEMENTED |
| Policy evaluation | `services/policy_evaluator.py:49-191` | Rule-by-rule met/partially met/not met/not assessable | IMPLEMENTED |
| Similarity | `services/similarity_engine.py:37-109` | Claim↔evidence **relevance** scores (embeddings, else lexical) | IMPLEMENTED |
| Cross-source verification | `services/cross_source_verifier.py:90-369` | Order/product/date/price/currency/quantity consistency; factual contradictions | IMPLEMENTED |
| Orchestration | `services/support_case_analyzer.py:102-973` | Full pipeline + claim assessment + recommendation | IMPLEMENTED |
| Report | `services/report_generator.py:46-385` | Structured report, verbatim findings, timeline from supplied timestamps only, fallback report | IMPLEMENTED |
| Facade | `integration/facade.py:59-202` | Stable public surface | IMPLEMENTED |
| Requirement extraction | — | **No module exists** | NOT IMPLEMENTED |
| Agreement → requirements | — | **No module exists** (document extraction can read agreements, but nothing extracts requirements from them) | NOT IMPLEMENTED |

### 6.4 Models and algorithms actually used

- **No trained ML models.** No scikit-learn, torch, transformers, spaCy, or fine-tuned model is used or declared.
- **LLM:** optional OpenAI-compatible chat completions (`llm_client.py`), JSON-mode with schema validation and bounded retries. Default is **mock**.
- **Embeddings:** optional OpenAI-compatible embeddings; default is a deterministic hash-sign mock (384-dim) that is explicitly labeled mock (`mock_provider.py:111-135`).
- **Vision:** optional OpenAI-compatible multimodal model; default mock performs **no** image analysis (`mock_provider.py:138-174`).
- **Similarity:** cosine of embeddings, or a token-overlap lexical fallback (`similarity_engine.py:112-152`).
- **Extraction:** regex/heuristics (dates, order numbers, currency, emails, URLs) plus LLM with post-verification against source text.
- **OCR:** Tesseract via `pytesseract` (optional; not installed).
- **Recommendation:** deterministic rule engine over policy evaluations and contradictions (`support_case_analyzer.py:689-897`), not an LLM decision.

### 6.5 External services and environment variables

- Optional external APIs: any OpenAI-compatible endpoint for chat, embeddings, and vision.
- Optional system binary: Tesseract.
- Env vars (all prefixed `PROOFBRIDGE_`): demo mode, three providers + keys/base URLs/models, OCR settings, file/page/pixel/char limits, retry/timeout, similarity thresholds. Full list in `ai_module/ai_module/.env.example:1-49` and `docs/ai/CONFIGURATION.md`.
- **Default configuration requires no keys and no network** because all providers default to `mock`. However, mock embeddings still require **numpy** at call time (imported in `mock_provider.py:17`), and the package requires **Pillow at import time** (`ocr_service.py:13` imported by `document_extractor.py:25`, which the facade imports).

### 6.6 Input/output formats

Inputs are Pydantic models (`SupportTicket`, `EvidenceInput`, `EvidenceUpload`, `RefundPolicy`, `OrderInformation`, `CaseContext`, `PaymentInformation`). Outputs are Pydantic models; the backend is instructed to persist `report.model_dump(mode="json")`. All public models use `extra="forbid"` except LLM-boundary models.

Key contract locations:
- `SupportTicket` — `schemas.py:280-303`
- `EvidenceInput` / `EvidenceUpload` / `EvidenceItem` — `schemas.py:560-641`
- `ClaimAssessment` — `schemas.py:750-772`
- `SupportCaseAnalysisResult` — `schemas.py:858-884`
- `InvestigationReport` — `schemas.py:991-1041`
- `RefundRecommendation` — `schemas.py:834-852`
- `PaymentInformation` — `schemas.py:356-373`

### 6.7 Error handling and reliability

- Typed exception hierarchy rooted at `ProofBridgeAIError` (`exceptions.py:10`).
- HTTP-style mapping documented in `docs/ai/API_CONTRACT.md:207-219` and implemented in `examples/fastapi_integration.py:122-148`.
- Provider retries with bounded backoff; response bodies are never logged or included in errors.
- Per-item evidence isolation; vision failures return `status="failed"` instead of raising; report generation has a deterministic fallback.
- Honest labeling: mock output, heuristic fallbacks, dropped unverifiable values, and vision limitations are all surfaced as warnings/limitations.

### 6.8 Entry points and reusable functions

Public surface (`proofbridge_ai/__init__.py:31-45`, `integration/facade.py:41-56`):

`extract_document`, `extract_document_text`, `extract_ticket_claims`, `extract_evidence`, `extract_evidence_batch`, `analyze_visual_evidence`, `extract_refund_policy`, `compare_support_evidence`, `analyze_support_case`, `arun_support_case_analysis`, `generate_investigation_report`, plus `ProofBridgeAIFacade`, `get_facade`, `get_settings`.

### 6.9 Documentation accuracy problems

| Doc claim | Reality | Location |
| --- | --- | --- |
| Provider files `mock_providers.py`, `openai_providers.py`, `factories.py` | Actual files: `mock_provider.py`, `llm_client.py`, `embeddings_client.py`, `vision_provider.py`; factories live in `providers/__init__.py` | `docs/ai/ARCHITECTURE.md:45-49`, `docs/ai/MODULE_STRUCTURE.md` |
| Install with `pip install -e "ai_module[ocr]"` | The `pyproject.toml` is one level deeper; from the workspace root that path has no build file. Correct target: `ai_module/ai_module` | `README.md:14`, `docs/ai/INTEGRATION_GUIDE.md:11` |
| "21-section report" | `InvestigationReport` has ~25 fields | `README.md:38` |
| Version `0.1.0` | Package reports `0.2.0`; schema `2.0` | `pyproject.toml:7`, `__init__.py:113` |
| Tests "238 passed, 3 skipped" | Not reproducible here (0 executed) | `docs/ai/TESTING.md:15` |
| Prior freelancer tests exist | Those test files are gone; only cache entries remain | `.pytest_cache/v/cache/nodeids`, `lastfailed` |

---

## 7. AI/ML architecture and workflow (in plain terms)

1. **Ticket understanding.** The customer's complaint is turned into an issue type and a list of claims. Every claim starts as "unverified" because a complaint is an allegation, not proof (`ticket_analyzer.py:79-151`).
2. **Evidence intake.** Each uploaded file is validated (type/size), text is extracted (PDF/DOCX/TXT or OCR for images), normalized, summarized, and tagged with verifiable facts such as dates and order numbers (`document_extractor.py`, `evidence_extractor.py`).
3. **Vision.** Product photos are optionally inspected by a vision model. The module is explicit that a photo cannot prove when, how, or whether damage occurred, and mock vision never pretends to see anything (`vision_analyzer.py`).
4. **Purchase facts.** Receipts are parsed for seller, product, order number, date, price, currency, quantity — only values literally present in the text (`product_analyzer.py`).
5. **Conversations.** Chat exports are parsed into messages with speakers; refund promises are recorded but remain statements, not verified facts (`conversation_analyzer.py`).
6. **Refund policy.** Policy text/document becomes rules with verbatim quotes; unverifiable quotes are dropped (`policy_extractor.py`).
7. **Cross-source verification.** The same field is compared across ticket, receipt, order data, payment data, and chat. Differences become factual contradictions, never accusations (`cross_source_verifier.py`).
8. **Policy evaluation.** Each rule is marked met / partially met / not met / not assessable, with missing information listed separately (`policy_evaluator.py`).
9. **Recommendation.** A deterministic rule engine produces one of six outcomes: refund recommended, request more information, escalate to human, not supported by supplied policy, alternative resolution, insufficient policy information (`support_case_analyzer.py:689-897`).
10. **Report.** A structured report copies findings verbatim, builds a timeline only from supplied timestamps, and always includes `human_review_required=True` and a final-decision notice (`report_generator.py:46-170`).

**Critical observation:** this workflow is **refund/customer-support** shaped. It contains no concept of "project requirement", "agreement", "deliverable", or "fulfillment". `document_extractor.py:1` still says "agreements and evidence files", but nothing downstream extracts or evaluates requirements.

---

## 8. Backend / AI-ML compatibility matrix

| # | Person 3 component | Source file | Existing backend component | Compatibility | Required adaptation | Priority |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `SupportTicket` | `schemas.py:280-303` | `Project` (`models.py:55-109`) | **PARTIAL / INCOMPATIBLE** | Project has `title`,`description`; no `complaint`, `product_name`, `order_id`, purchase/delivery dates, requested resolution, seller-contacted flag. Need adapter + possibly new columns. | High |
| 2 | `EvidenceInput` / `EvidenceUpload` / `EvidenceItem` | `schemas.py:560-641` | `Evidence` (`models.py:132-148`) | **HIGH** | Map `evidence_id=str(Evidence.id)`, `filename`, `uploaded_at=created_at`, `content_type=mime_type`, `uploaded_by=str(uploaded_by)`. Category has no backend column (inference or new column). | High |
| 3 | `extract_document` / `extract_document_text` | `document_extractor.py:37-104` | Agreement upload (`Project.agreement_path`) and evidence files | **DIRECT REUSE** | Backend must read stored bytes and pass them; add Pillow/PyMuPDF/python-docx deps. | High |
| 4 | `extract_evidence` / `extract_evidence_batch` | `evidence_extractor.py:142-295` | `Evidence.extracted_text` | **DIRECT REUSE (for extraction)** | Persist `item.extracted_text`; store full `EvidenceItem` JSON if desired (no column yet). | High |
| 5 | `file_validation` | `file_validation.py:105-167` | No upload validation exists | **DIRECT REUSE** | Call before persisting uploads; also enforce path-safe storage names in backend. | High |
| 6 | `compare_support_evidence` | `similarity_engine.py:37-109` | `Requirement` vs `Evidence` comparison (`AnalysisResult.similarity`) | **PARTIAL** | Algorithm is reusable, but inputs are `CustomerClaim` (support claims), not `Requirement`. Needs a requirement-shaped input or a relabeling adapter; concept is close but not identical. | High |
| 7 | `ticket_analyzer.extract_ticket_claims` | `ticket_analyzer.py:79-151` | No requirement extractor | **INCOMPATIBLE (as requirement extractor)** | Extracts complaint claims, not project requirements. Cannot satisfy "agreement → requirements". | High |
| 8 | `policy_extractor` / `policy_evaluator` | `policy_extractor.py:125`, `policy_evaluator.py:49` | `Requirement` (agreed acceptance criteria) | **INCOMPATIBLE** | Refund-policy rule semantics (return window, damaged-on-arrival, proof requirement) do not map to project requirements. Do not integrate for the freelancer workflow. | High |
| 9 | `product_analyzer` | `product_analyzer.py:74-119` | None | **LOW RELEVANCE** | Useful only if receipts/payment proofs are evidence of delivery/payment. | Medium |
| 10 | `conversation_analyzer` | `conversation_analyzer.py:82-168` | Chat evidence (no category) | **DIRECT REUSE (mostly)** | Speaker labels default to customer/seller; freelancer/client mapping needs a relabeling decision. | Medium |
| 11 | `vision_analyzer` | `vision_analyzer.py:99-275` | Image evidence | **PARTIAL** | Issue vocabulary is damage-focused (`VisualIssueType`), not "deliverable matches spec". Useful for screenshots/photos but not generic deliverable verification. | Medium |
| 12 | `cross_source_verifier` | `cross_source_verifier.py:90-369` | Evidence consistency (`AnalysisResult`) | **PARTIAL** | Order/price/currency logic is commerce-specific. Date/reference consistency is reusable. Requirement-level consistency is missing. | Medium |
| 13 | `analyze_support_case` pipeline | `support_case_analyzer.py:102-259` | Workflow steps 7–10 in the brief | **PARTIAL / INCOMPATIBLE** | Recommendation outcomes are refund-centric. Cannot be used as the freelancer analysis pipeline without redesign. | High |
| 14 | `generate_investigation_report` | `report_generator.py:46-170` | `Report.content` JSON (`models.py:203-214`) | **HIGH (storage)** | JSON is storable as-is. Content sections are support/refund-oriented; frontend/domain labels must change or be adapted. | High |
| 15 | Provider layer (LLM/embeddings/vision) | `providers/**` | None | **DIRECT REUSE** | Add dependencies, configure keys, choose mock vs real. | High |
| 16 | Exception hierarchy | `exceptions.py:10-77` | FastAPI HTTP errors | **DIRECT REUSE** | Add a FastAPI exception handler mapping (example exists). | Medium |
| 17 | Safe logging | `logging_utils.py:17-42` | Default Uvicorn logging | **DIRECT REUSE** | Wire into backend logging config. | Low |
| 18 | `RefundRecommendation` | `schemas.py:834-852` | `HumanReview`, `AnalysisResult.classification` | **INCOMPATIBLE (domain)** | Recommendation is about refunds; backend decision is fulfillment/dispute. Human decision model can store any string, but semantics differ. | High |
| 19 | `PaymentInformation` | `schemas.py:356-373` | `PayPalTransaction` (`models.py:242-261`) | **COMPATIBLE** | Map transaction id, amount, currency, status, timestamp; keep read-only. | Medium |
| 20 | `CaseContext` / `CaseEvent` | `schemas.py:890-914` | `CaseStatusLog` (`models.py:180-196`) | **HIGH** | Map status log rows to `CaseEvent` for the report timeline. | Medium |

**Overall compatibility verdict:** the **infrastructure half** of the AI module (validation, extraction, OCR, providers, errors, logging, report storage) is highly reusable. The **domain half** (tickets, claims, refund policy, refund recommendation) does **not** match the freelancer product. Integration cannot be a simple wiring exercise.

---

## 9. Database schema audit

Database: `proofbridge.db`, SQLite, journal mode `delete`. Read-only inspection only.

| Model | Table | PK | FKs | Relationships / cascades | Constraints / defaults | Issues |
| --- | --- | --- | --- | --- | --- | --- |
| `User` | `users` | `id` | none | `projects_as_freelancer`, `projects_as_client` | `email` unique + indexed; `role` free `String(30)`; `created_at` default UTC | No DB-level role restriction; no `is_active`; no reviewer role provision |
| `Project` | `projects` | `id` | `freelancer_id→users.id`, `client_id→users.id` (NOT NULL) | children with `cascade="all, delete-orphan"` | `status` default `"created"`; agreement path/name nullable | No index on FKs; no `updated_at`; status not constrained; no complaint/order/refund fields |
| `Requirement` | `requirements` | `id` | `project_id→projects.id` (NOT NULL) | parent only | `text` NOT NULL; category/source_quote nullable | **No AI component extracts requirements**; no ordering/priority; no index on `project_id` |
| `Evidence` | `evidence` | `id` | `project_id`, `uploaded_by` (NOT NULL) | parent only | `filename`,`stored_path` NOT NULL; `extracted_text` nullable | No category, file size, checksum, upload status, or original MIME enforcement; no index on `project_id` |
| `AnalysisResult` | `analysis_results` | `id` | `project_id` NOT NULL; `requirement_id`, `evidence_id` nullable | parent only (no relationships to Requirement/Evidence) | `classification` NOT NULL free string; `similarity` float | No `created_at`; can orphan requirement/evidence rows; one row cannot hold the AI's rich findings |
| `CaseStatusLog` | `case_status_log` | `id` | `project_id`, `changed_by` | parent only | `status` NOT NULL | Table name singular; no index on `project_id` |
| `Report` | `reports` | `id` | `project_id` NOT NULL | parent only | `content` JSON NOT NULL; `created_at` | Good fit for `InvestigationReport` JSON; no version/report-type column |
| `HumanReview` | `human_reviews` | `id` | `project_id`, `reviewer_id` NOT NULL | parent only | `decision` NOT NULL free string | Not linked to a specific report/analysis snapshot; no reviewer role |
| `PayPalTransaction` | `paypal_transactions` | `id` | `project_id` NOT NULL | parent only | `paypal_transaction_id` unique+indexed; `amount Numeric(12,2)`; `currency`, `status` | `Mapped[float]` vs `Numeric` type mismatch; no index on `project_id`; read-only by design |

### 9.1 Referential integrity

SQLite does **not** enforce foreign keys unless `PRAGMA foreign_keys=ON` is set per connection. `app/database.py:16-19` does not set it. Therefore declared FKs are documentation only at runtime **(Verified by code reading; the pragma is absent)**. This matters for deleting projects/requirements/evidence.

### 9.2 Does the AI module require extra tables/fields?

**Yes, if the support/refund domain is adopted.** Missing backend storage:

- Ticket/complaint text, product name, order id, purchase/delivery dates, requested resolution.
- Claims and claim assessments (the AI's `ClaimAssessment` list).
- Refund policy (`RefundPolicy` + rules) — no table exists.
- Order information and payment information beyond the PayPal table.
- Evidence category and processing status.
- Cross-source findings, contradictions, missing information, policy evaluation, recommendation.
- Report type/version, analysis timestamps.
- Reviewer identity/role for human review.

**If the freelancer domain remains authoritative**, the schema is closer but still missing: requirement extraction provenance/priority, evidence category/checksum, per-requirement finding details (beyond one `classification`/`similarity`/`explanation` row), and report versioning.

**Do not change the schema during this audit. Any additive migration is REQUIRES HUMAN DECISION.**

### 9.3 Data preservation

The existing DB has 1 user. Recreating tables (`create_all` against a changed model or dropping the file) would risk that row. If migrations are added, use Alembic or an explicit additive script reviewed by you; never regenerate models over the live DB.

---

## 10. Authentication and authorization audit

### What is implemented

- **Password hashing/verification:** bcrypt with per-password salt; rejects >72 bytes (`security.py:20-46`).
- **JWT:** HS256, `sub`, `iat`, `exp`; secret from settings; decode requires `exp` and `sub` (`security.py:53-118`).
- **Current user:** bearer token → DB lookup; uniform 401 (`security.py:82-118`).
- **Registration:** email normalized to lowercase; duplicate check plus `IntegrityError` handling → 409 (`auth.py:33-71`).
- **Login:** OAuth2 password form (`username` carries email); identical error for unknown user and wrong password (`auth.py:78-107`).
- **`/auth/me`:** returns current user (`auth.py:114-118`).
- **Role dependency:** `require_role(*roles)` exists (`security.py:125-139`) but is **unused**.

### Findings

| # | Finding | Severity |
| --- | --- | --- |
| A1 | App cannot start due to `models.py` bug; all auth is inaccessible | Critical |
| A2 | No tests for register/login/JWT/roles | High |
| A3 | No reviewer/admin role can be registered; `HumanReview.reviewer_id` has no valid role path | High |
| A4 | No object-level authorization exists (no project/evidence endpoints yet); future endpoints must enforce ownership/role | High (future) |
| A5 | No token revocation, logout, refresh, or rotation; 24h tokens | Medium |
| A6 | No rate limiting / lockout / captcha; brute force and credential stuffing possible | Medium |
| A7 | No email verification, password reset, or password change | Medium |
| A8 | JWT lacks `iss`/`aud`/`jti`; no key rotation (`kid`) | Low |
| A9 | `require_role` exists but no route uses it — role enforcement is untested and unproven | Medium |
| A10 | Password length checked in characters, hashing limit is bytes; edge case → 500 | Low |
| A11 | Login timing differs for unknown email vs wrong password | Low |
| A12 | `User.role` not constrained at DB level | Medium |
| A13 | Secrets: `SECRET_KEY` comes from environment/.env (no hardcoded default) — good; `.env` is gitignored — good. Values were not read or disclosed. | Positive |
| A14 | No security headers / HTTPS enforcement / CORS policy | Medium |

### Authorization matrix for the intended workflow (currently absent)

| Action | freelancer | client | reviewer | Notes |
| --- | --- | --- | --- | --- |
| Create project | proposed | proposed | no | Must define who creates and who is the counterparty |
| Add requirements | proposed | proposed | no | Agreement owner? both? |
| Upload agreement | proposed | proposed | no | |
| Upload evidence | proposed | proposed | no | Brief says freelancer submits evidence |
| Run AI analysis | proposed | maybe | no | Should be backend-triggered, not free-form |
| Read AI report | own projects | own projects | all cases | |
| Record human decision | no | no | **yes** | Requires a reviewer role that does not exist |
| View PayPal records | own project | own project | read | Read-only |

---

## 11. Evidence upload and document processing audit

### Current backend state

- `uploads/` is empty and **no code references it** (grep for `UploadFile`, `File(`, `StaticFiles` found nothing).
- There is no upload endpoint, no size/type validation, no filename sanitization, no storage naming scheme, no checksum, no retention policy.
- `Evidence.stored_path` and `Evidence.extracted_text` exist as target columns (models.py:140-142).
- `Project.agreement_path` / `agreement_name` exist (models.py:66-67) but nothing writes them.

### AI module capabilities

- **Strong validation:** empty file, configured max size, magic-byte detection (content wins over MIME/extension), supported-format list (`file_validation.py:105-167`).
- **Safe parsing:** no execution; PDF page limits; image pixel limits with downscaling; DOCX via python-docx; text decoding with lossy-decode warning (`document_extractor.py`, `ocr_service.py`).
- **OCR:** Tesseract required; clear error when missing; scanned PDF pages fall back to OCR only when available.
- **Partial tolerance:** batch processing isolates per-file failures (`evidence_extractor.py:238-279`).
- **Untrusted-content posture:** prompts explicitly treat evidence as data, not instructions.

### Risks / gaps

| # | Risk | Location | Mitigation (future) |
| --- | --- | --- | --- |
| E1 | No backend upload validation yet | `uploads/`, `app/` | Reuse `validate_file_input`; also enforce a backend allow-list and max size at the HTTP layer |
| E2 | Path traversal / unsafe filenames when storage is implemented | future upload code | Never use client filenames as paths; generate UUID names; resolve and verify the target is inside `uploads/` |
| E3 | Pillow decompression bombs | `ocr_service.py:88-94` | Pillow guards are caught, but also enforce pixel limits before OCR (already done after load) |
| E4 | OCR engine absent → image evidence cannot be processed here | environment | Install Tesseract + `pytesseract`, or restrict image evidence to vision-only |
| E5 | Vision mock produces no genuine analysis | `mock_provider.py:138-174` | Keep labeled mock output; configure a real vision provider for meaningful results |
| E6 | Large PDFs/images can consume CPU/memory | limits exist in config | Keep limits, add request timeouts and background job execution |
| E7 | Duplicate uploads are not detected | no checksum column | Add SHA-256 column + unique (project_id, checksum) if desired |
| E8 | `Evidence.extracted_text` may store large text | DB column TEXT | Enforce `max_document_chars` and consider truncation storage strategy |
| E9 | Malware in uploads | no scanning | Do not execute files; optionally scan in production; store outside the web root |

---

## 12. AI analysis workflow audit (intended workflow vs reality)

The brief's 15-step workflow, checked against actual code:

| Step | Existing implementation | Person 3 component | Required integration | Expected input → output | DB component | Test method | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1. Create project | None (model only) | — | New project router/service | JSON → `Project` | `projects` | API test with auth | NOT IMPLEMENTED |
| 2. Add requirements | None | **None** | New requirement service | text → `Requirement` | `requirements` | API + DB test | NOT IMPLEMENTED |
| 3. Upload agreement | Fields exist, no endpoint | `extract_document` | Upload endpoint + storage | file bytes → `DocumentExtractionResult` | `projects.agreement_path` | Upload test, traversal test | PARTIAL |
| 4. Process agreement → requirements | **None** | **No requirement extractor** | New capability or product pivot | agreement text → `Requirement` list | `requirements` | Extraction fixtures | NOT IMPLEMENTED |
| 5. Submit evidence | None | `extract_evidence(_batch)` | Upload endpoint + storage | bytes+metadata → `EvidenceItem` | `evidence` | Upload + extraction tests | PARTIAL |
| 6. Validate/store evidence | None | `file_validation` | Validation + DB write | bytes → validated type | `evidence` | Security tests | PARTIAL |
| 7. Pass evidence to AI | None | `analyze_support_case` / services | Adapter | DB rows → Pydantic inputs | — | Adapter unit tests | NOT IMPLEMENTED |
| 8. AI analyzes evidence | Exists (support domain) | pipeline | Domain decision | evidence → claims/assessments | — | Demo tests | PARTIAL / INCOMPATIBLE |
| 9. Compare vs requirements | Only similarity primitive | `compare_support_evidence` | Requirement-shaped mapping | requirements+evidence → matches | `analysis_results` | Unit tests | PARTIAL |
| 10. Identify missing/conflicting info | Support-domain contradictions/missing info | `cross_source_verifier`, pipeline | Adapt to requirement domain | sources → contradictions/missing | `analysis_results` / report JSON | Scenario tests | PARTIAL |
| 11. Store structured results | Model only | `SupportCaseAnalysisResult` | Serialize into `analysis_results` / `reports` | analysis → DB | `analysis_results`, `reports` | DB integration test | NOT IMPLEMENTED |
| 12. Generate/store report | Model only | `generate_investigation_report` | Store JSON | analysis → report JSON | `reports` | Round-trip test | PARTIAL |
| 13. Human reviews | Model only | report's `human_review_required` | Review endpoint/UI contract | report → review | `human_reviews` | API test | NOT IMPLEMENTED |
| 14. Human records decision | Model only | Refund recommendation (advisory) | Review endpoint, reviewer role | decision+notes → `HumanReview` | `human_reviews` | API + authz test | NOT IMPLEMENTED |
| 15. Update case status | Model only | `CaseContext`/`CaseEvent` | Status transition service + log | status → row | `case_status_log` | API test | NOT IMPLEMENTED |

**Do not assume this workflow works. Steps 1, 2, 4, 7, 11, 13, 14, and 15 have no backend implementation; step 4 has no AI implementation in either domain.**

---

## 13. Reports and human review audit

- **Storage:** `Report.content` is `JSON NOT NULL` (`models.py:203-214`). The AI's `InvestigationReport` serializes cleanly with `model_dump(mode="json")`, so JSON storage is feasible. **(Code reading)**
- **Immutability/versioning:** no report version, no report type, no link from `HumanReview` to a specific report. A reviewer decision cannot be tied to the exact report version reviewed. Risk for auditability.
- **Human review model:** `HumanReview` has `decision` and `notes` but no structured outcome enum, no `report_id`, no `reviewed_at` separate from `created_at`, and no reviewer role support.
- **Boundaries:** the AI report always sets `human_review_required=True` and a final-decision notice; recommendation outcomes are advisory. This matches the product boundary. However, the report title/sections say "Customer Support Case Investigation Report" (`schemas.py:35`), which conflicts with a freelancer product.
- **Status history:** `CaseStatusLog` exists but no code writes it; there is no transition validation (any string accepted).
- **API:** no report retrieval endpoint, no review submission endpoint. **NOT IMPLEMENTED.**

---

## 14. PayPal boundary audit

**Boundary rules:** not escrow; AI never decides payments; backend never moves money; PayPal executes separately authorized transactions; `PayPalTransaction` stores retrieved information.

| Check | Result |
| --- | --- |
| Any code that creates/captures/refunds payments? | **No** — no PayPal SDK, no HTTP calls, no credentials (grep/code reading) |
| Payment execution in AI module? | **No** — explicit guarantees in `README.md:68-76`, `INTEGRATION_GUIDE.md:85-88` |
| AI accepts payment data? | Yes, `PaymentInformation` (`schemas.py:356-373`) as informational evidence only |
| Backend model fits retrieved data? | Yes: `paypal_transaction_id`, `amount`, `currency`, `status`, `raw_data` (`models.py:242-261`) |
| Read-only usage enforced? | No endpoint exists; future endpoints must be read-only |
| Cross-source use of payment data | `verify_cross_source` accepts it, but the main pipeline (`analyze_support_case`) does **not** pass it; only report generation receives `PaymentInformation` (`report_generator.py:46-54`). Gap if payment consistency checks are desired. |
| Recommendation could be read as a payment order? | Wording is advisory ("recommends", "human decides"); UI must also show `final_decision_notice`. |
| Risk | `raw_data` may contain sensitive payer information; restrict access and redact logs. |

**Verdict: boundary respected in both codebases.** The only integration requirement is to keep any future PayPal route read-only and to pass payment data only as evidence.

---

## 15. Security and reliability audit

| Area | Finding | Severity | Recommendation |
| --- | --- | --- | --- |
| Authentication | App cannot start (models.py) | Critical | Fix import/duplicate schemas |
| Authentication | No tests, no lockout, 24h tokens, no revocation | High | Add tests, shorter access tokens, refresh/revocation strategy |
| Authorization | No object-level checks (no domain endpoints yet); `require_role` unused | High | Enforce ownership and roles in every future route |
| Authorization | Reviewer role cannot be registered | High | Define role model (e.g., `reviewer`) and admin provisioning |
| File upload | No upload endpoint, no storage hardening | High | UUID names, resolve path containment, size/type checks |
| Path traversal | No current code; high future risk | High | Never trust filenames; use `Path.resolve()` containment checks |
| SQL injection | SQLAlchemy parameterized queries used | Low | Keep ORM usage; avoid raw SQL |
| Secrets | Env-based `SECRET_KEY`; `.env` gitignored; AI keys `SecretStr` | Low | Keep; add startup validation for missing/weak secret |
| Sensitive exposure | AI errors avoid response bodies; logging redacts | Low | Add backend request logging policy and PII redaction |
| Prompt injection | AI prompts mark evidence as untrusted data; output schema-validated | Low | Keep; never let LLM free-form text drive DB writes |
| Untrusted documents | Validated and parsed, never executed | Low | Add malware scanning in production if exposed publicly |
| External API failure | Retries, timeouts, structured failures | Low | Add circuit breaker/queue for production |
| Resource use | File/page/pixel/char limits; synchronous heavy work | Medium | Run analysis in background jobs/threadpool; cap concurrency |
| Error handling | AI maps errors to HTTP; backend has no handlers | Medium | Add a single `ProofBridgeAIError` handler |
| CORS | Not configured | Medium | Add explicit allowed origins |
| Dependency security | No lockfile/audit | Medium | Pin with hashes, run `pip-audit`, review transitive deps |
| DB integrity | SQLite FKs not enforced | High | Enable `PRAGMA foreign_keys=ON` per connection (after verifying data) |
| DB integrity | No backups/migrations | High | Add Alembic and a backup step before schema changes |
| Timezones | SQLite does not preserve tz; AI expects datetimes | Low | Standardize on UTC and serialize ISO-8601 |

---

## 16. Dependency compatibility audit

### Backend environment (verified)

`Python 3.14.7`; FastAPI 0.162.2; SQLAlchemy 2.1.8; Pydantic 2.14.3; pydantic-settings 2.16.2; bcrypt 5.0.0; PyJWT 2.15.1; httpx 0.28.1; pytest 9.2.0; email-validator 2.3.0 (installed but **not** in `requirements.txt`).

### AI module declared dependencies (`pyproject.toml:11-23`)

| Requirement | Declared | Backend venv | Compatibility |
| --- | --- | --- | --- |
| Python | `>=3.10` | 3.14.7 | Likely OK; **no upper bound** — verify wheels |
| pydantic | `>=2.10` | 2.14.3 | OK |
| pydantic-settings | `>=2.6` | 2.16.2 | OK |
| httpx | `>=0.27` | 0.28.1 | OK |
| numpy | `>=1.26` | **Missing** | Must install (needed for mock embeddings) |
| PyMuPDF | `>=1.24` | **Missing** | Must install; cp314 wheel availability must be checked |
| python-docx | `>=1.1` | **Missing** | Must install |
| Pillow | `>=10.0` | **Missing** | Must install; **needed at import time** |
| pytesseract (extra `ocr`) | `>=0.3.10` | **Missing** | Optional; Tesseract binary also needed |
| pytest (extra `dev`) | `>=8.0` | 9.2.0 | OK |

### Compatibility issues

1. **No shared dependency file.** `backend requirements.txt` and `ai_module/requirements.txt` are separate and the AI deps are absent from the backend. A clean `pip install -r requirements.txt` yields a backend that still cannot import the AI module.
2. **Pillow is a hard import dependency**, not just an OCR extra: `proofbridge_ai/services/ocr_service.py:13` imports PIL at module scope, `document_extractor.py:25` imports `ocr_service`, and `facade.py:21` imports `document_extractor`. So `import proofbridge_ai` fails without Pillow.
3. **numpy is required at call time** in default mock mode: `mock_provider.py:17` imports numpy, and `similarity_engine.py:67` builds the embeddings provider during every comparison.
4. **Python 3.14 is very new relative to some pinned minimums.** `>=` ranges should resolve to current versions, but PyMuPDF/numpy cp314 wheels must be confirmed before installation; do not assume.
5. **Install path is wrong in the docs.** `pip install -e "ai_module[ocr]"` targets a directory without `pyproject.toml`. Use `pip install -e ai_module/ai_module` (and `pip install -e "ai_module/ai_module[ocr]"` if needed).
6. **Not installed:** `pip show proofbridge-ai` → not found; `import proofbridge_ai` → `ModuleNotFoundError`.
7. **Two `Settings` classes coexist safely** because env prefixes differ (`PROOFBRIDGE_*` vs backend keys). Both read `.env`; AI uses `extra="ignore"`. No conflict found.
8. **AI `.env` location trap:** AI's `Settings` uses `env_file=".env"` relative to the **current working directory**. If the backend runs from the workspace root, an AI `.env` placed in `ai_module/ai_module/` will **not** be read. Put `PROOFBRIDGE_*` values in the root `.env` or pass a `Settings` instance explicitly.
9. **Version inconsistency** inside the AI package (0.1.0 vs 0.2.0 vs report schema 2.0) — harmless functionally, confusing for support.
10. **No dependency pinning/lockfile** in the AI module (`>=` only) — builds are not reproducible.

---

## 17. API and schema audit

### Existing HTTP API (verified from source)

| Method | Path | Auth | Request | Response | Status |
| --- | --- | --- | --- | --- | --- |
| GET | `/` | No | — | `{"message": ...}` | Defined; unreachable (import bug) |
| GET | `/health` | No | — | `{"status":"ok"}` | Defined; unreachable |
| POST | `/auth/register` | No | `UserCreate` JSON | `UserResponse` (201) | Defined; unreachable |
| POST | `/auth/login` | No | OAuth2 form (`username`=email, `password`) | `Token` | Defined; unreachable |
| GET | `/auth/me` | Bearer | — | `UserResponse` | Defined; unreachable |

### Defined-but-unused schemas

`ProjectCreate`, `ProjectUpdate`, `ProjectResponse` exist in `app/schemas.py:54-87` and are duplicated (broken) in `app/models.py:264-302`. No router uses them.

### Missing API surface for the stated product

Projects (CRUD), requirements (CRUD/bulk), agreement upload, evidence upload/list/download, analysis run/get, reports get, human review submit, case status history, PayPal transaction list/sync (read-only). **All NOT IMPLEMENTED.**

### Contract mismatches with the AI module

| Mismatch | Backend | AI | Impact |
| --- | --- | --- | --- |
| Case identity | `Project.id` int | `SupportTicket.case_id` str | Adapter must stringify; AI preserves it verbatim |
| Complaint | `Project.title/description` | `SupportTicket.complaint` (required) | Need a mapping rule or new column |
| Product/order/date fields | absent | `product_name`, `order_id`, `purchase_date`, `delivery_date` | Cannot populate meaningfully today |
| Evidence category | absent | `EvidenceCategory` | Inference or new column |
| Evidence id | int | str | Stringify; AI treats it as opaque |
| Timestamps | `created_at` (SQLite) | aware `datetime` preferred | Ensure UTC; AI tolerates None |
| Findings | one `classification`/`similarity`/`explanation` row | lists of assessments/findings/recommendation | Needs JSON storage or new tables |
| Errors | FastAPI `{"detail": ...}` | `{"error_code", "detail"}` example | Add a handler to standardize |
| Report | `Report.content` JSON | `InvestigationReport` | Compatible at storage level |
| Recommendation semantics | fulfillment/dispute decision | refund outcomes | **Domain conflict** |

---

## 18. Missing functionality

### Backend

1. Fix the `app/models.py` import crash (remove duplicated schemas or add imports — but see the restriction: no changes during audit).
2. Project CRUD, requirement management, agreement upload, evidence upload/download.
3. Analysis orchestration endpoint and service.
4. Report retrieval and storage.
5. Human review submission + reviewer role.
6. Case status transition service and log writes.
7. PayPal transaction read-only ingestion/listing.
8. Upload validation, safe storage, and file serving.
9. Table creation/migrations and DB integrity settings.
10. CORS, exception handlers, logging, rate limiting.
11. Entire test suite.

### AI module (relative to the freelancer product)

1. **Requirement extraction from agreements** — absent.
2. **Requirement-to-evidence assessment** in requirement terms — absent (only claim-oriented assessment).
3. **Missing/incomplete requirement detection** — absent as such.
4. **Freelancer-domain recommendation outcomes** (e.g., fulfilled / partially fulfilled / needs more proof / escalate) — absent; refund outcomes only.
5. **Report sections for requirements** — absent; report is support/refund oriented.
6. **Generic deliverable verification** (e.g., does the code/screenshot/document satisfy requirement X) — only damage/vision and document text extraction exist.

### Both

- No end-to-end integration tests.
- No shared configuration story.
- No versioned contract between backend and AI.

---

## 19. Integration risks

| # | Risk | Impact | Likelihood | Mitigation |
| --- | --- | --- | --- | --- |
| R1 | Backend remains unstartable if the models.py bug is not fixed first | Blocks everything | Certain today | Phase 0 fix + import test |
| R2 | Product/domain mismatch (freelancer vs support/refund) | Wasted work, wrong product | High | Human decision before coding |
| R3 | Schema changes to a live DB | Data loss / breakage | Medium | Additive migrations, backup, review |
| R4 | Dependency gaps / Python 3.14 wheel issues | Cannot install AI module | High | Verify wheels, pin, CI install test |
| R5 | AI module imported into API process performs blocking HTTP/OCR | Slow requests, timeouts | High | Run in threadpool/background worker; timeouts |
| R6 | No upload hardening → path traversal/RCE-adjacent risks | Security breach | Medium | UUID storage, containment checks, validation |
| R7 | Rich AI findings do not fit `AnalysisResult` | Lost information | High | Store JSON or add tables (decision) |
| R8 | Authorization gaps on new routes (IDOR) | Data leak | High | Ownership checks + tests |
| R9 | Mock providers mistaken for real analysis | Bad decisions | Medium | Surface `status`/warnings in UI; configure real providers |
| R10 | Reviewer role missing | Workflow cannot complete | High | Add role model + provisioning |
| R11 | Report/version not linked to review | Weak audit trail | Medium | Add `report_id`/version to review |
| R12 | AI `.env` in the wrong directory | Silent mock mode | Medium | Document root env or explicit Settings |
| R13 | No tests on either side of the seam | Regressions | High | Adapter contract tests |
| R14 | LLM prompt injection via documents | Manipulated findings | Low-Medium | Untrusted-data prompts, schema validation, human review |
| R15 | External API outages/rate limits | Failed analyses | Medium | Retries (exist), queue, graceful degradation (exists) |

---

## 20. Recommended integration architecture

### 20.1 The decision gate (answer this first)

**Option A — Keep the freelancer product (recommended if the written product brief is authoritative).**
- Reuse the AI module's *infrastructure*: document extraction, file validation, evidence processing, providers, similarity primitive, error hierarchy, logging, report scaffolding.
- Do **not** integrate refund policy evaluation/recommendation as the core workflow.
- Build two new AI capabilities: requirement extraction (agreement → requirements) and requirement-level evidence assessment + missing/incomplete detection.
- This is more work but preserves the stated product.

**Option B — Pivot the product to customer-support/refund investigation (lower AI effort, larger product change).**
- Keep the AI module as delivered.
- Extend the backend domain: complaint/ticket fields, order information, refund policy storage, claims, richer analysis/report storage.
- Rename/re-scope the product language away from freelancer project delivery.
- This is faster technically but changes what ProofBridge *is*.

**Option C — Adapter-only MVP (short-term demo).**
- Fix the backend, install the AI module, and integrate only evidence text extraction + a generic "analysis report" JSON for demos, with an explicit disclaimer that requirement analysis is not yet implemented.
- Useful for a milestone demo, not for the final product.

I recommend **A** if the brief is fixed, **B** if Person 3's pivot is accepted. Do not mix refund recommendations into a freelancer dispute product.

### 20.2 Target layering (either option)

```
FastAPI routers (projects, requirements, evidence, analysis, reports, reviews)
        │  auth + object-level authorization
        ▼
Service layer (app/services/)
   ├── storage_service      safe file storage, validation, hashing
   ├── project_service      CRUD, status transitions
   ├── evidence_service     persist Evidence, call AI extraction
   ├── analysis_service     build AI inputs, run pipeline, persist results
   └── ai_adapter           DB rows ⇄ proofbridge_ai Pydantic models
        │
        ▼
proofbridge_ai (library, no DB, no auth, no payments)
        │
        ▼
LLM / embeddings / vision providers (mock by default)
```

### 20.3 Adapter contract (conceptual; not implemented)

- **DB → AI:** build `SupportTicket`/`EvidenceInput` (or replacement requirement-domain models) from ORM rows; stringify IDs; pass UTC timestamps; pass policy/order/payment data only if stored.
- **AI → DB:** persist the full analysis JSON in `reports.content`; optionally project a few summary fields into `analysis_results` (`classification=status`, `similarity=top score`, `explanation=rationale`). Prefer preserving the complete JSON to losing findings.
- **Execution:** call the async pipeline via `starlette.concurrency.run_in_threadpool` or a background worker because the underlying provider/OCR calls are blocking (`docs/ai/INTEGRATION_GUIDE.md:89-95`).
- **Errors:** one FastAPI exception handler for `ProofBridgeAIError` using the documented mapping.
- **Settings:** build `proofbridge_ai.Settings` explicitly in the backend (do not rely on CWD `.env` discovery).

### 20.4 Persistence recommendation

- Store the complete AI result/report as JSON (already supported by `Report.content`).
- Avoid overloading one `AnalysisResult` row with lists; if querying findings is needed, add child tables (e.g., `analysis_findings`) — **additive migration, requires approval**.
- Link `HumanReview` to the reviewed report (`report_id`) and add a reviewer role.

---

## 21. Step-by-step integration roadmap

> Do not start this roadmap until the domain decision is made and you approve changes.

### Phase 0 — Unblock the backend (no AI yet)

| Item | Detail |
| --- | --- |
| What | Remove the duplicated Pydantic schemas from `app/models.py:264-302` (they belong only in `app/schemas.py`). Add an import smoke test. |
| Files likely affected | `app/models.py`, `tests/test_imports.py` (new) |
| Person 3 components | None |
| Dependencies | Existing |
| Testing | `python -c "from app.main import app"`; auth register/login/me tests with a temporary SQLite DB |
| Expected result | Backend starts; auth verified by tests |

### Phase 1 — Environment and dependency alignment

| Item | Detail |
| --- | --- |
| What | Install the AI package editable from the correct path; add Pillow, numpy, PyMuPDF, python-docx to a shared requirements set; verify cp314 wheels; add `email-validator` to `requirements.txt`. |
| Files likely affected | `requirements.txt`, new lock/constraints file, CI config |
| Person 3 components | `pyproject.toml` deps |
| Dependencies | Network access to install (not during this audit) |
| Testing | `import proofbridge_ai`; `python -m pytest ai_module/ai_module/tests -q`; import in backend venv |
| Expected result | AI module importable and its test suite reproducible |

### Phase 2 — Domain decision + data model

| Item | Detail |
| --- | --- |
| What | Choose Option A/B/C; define additive schema changes (ticket fields or requirement provenance), reviewer role, evidence category, report version. |
| Files likely affected | `app/models.py`, `app/schemas.py`, migration files |
| Person 3 components | `SupportTicket`, `EvidenceInput`, `ClaimAssessment` (or replacements) |
| Dependencies | Alembic (proposed) |
| Testing | Migration up/down on a copy of the DB; data preservation check |
| Expected result | Approved schema that can store AI outputs without data loss |

### Phase 3 — Projects, requirements, evidence APIs

| Item | Detail |
| --- | --- |
| What | Implement CRUD + agreement/evidence upload with safe storage, validation, and object-level authorization. |
| Files likely affected | `app/routers/projects.py`, `requirements.py`, `evidence.py`; `app/services/storage_service.py`, `project_service.py`, `evidence_service.py`; `app/schemas.py` |
| Person 3 components | `file_validation`, `extract_document`, `extract_evidence_batch` |
| Dependencies | Pillow/numpy/PyMuPDF/python-docx |
| Testing | API + DB integration tests; path traversal, oversized file, wrong MIME, IDOR |
| Expected result | Users can create projects, add requirements, upload agreement/evidence; text extraction persists |

### Phase 4 — Analysis orchestration and persistence

| Item | Detail |
| --- | --- |
| What | Build `ai_adapter` + `analysis_service`; run the pipeline in a threadpool/worker; persist analysis/report JSON. |
| Files likely affected | `app/services/ai_adapter.py`, `analysis_service.py`; `app/routers/analysis.py`, `reports.py` |
| Person 3 components | `analyze_support_case` or new requirement-domain pipeline; `generate_investigation_report` |
| Dependencies | Configured providers (mock acceptable) |
| Testing | Adapter contract tests with demo mocks; end-to-end analysis test; timeout/failure tests |
| Expected result | An evidence set produces a stored, retrievable structured report |

### Phase 5 — Human review, status history, PayPal read-only

| Item | Detail |
| --- | --- |
| What | Reviewer role; review submission linked to report; status transitions + `CaseStatusLog`; read-only PayPal record listing. |
| Files likely affected | `app/routers/reviews.py`, `status.py`, `paypal.py`; services; schemas |
| Person 3 components | `human_review_required`/notice; `CaseEvent` mapping; `PaymentInformation` |
| Dependencies | Existing |
| Testing | Authorization matrix tests; status transition tests; boundary tests proving no payment execution |
| Expected result | Human decision recorded; audit trail complete; payments remain read-only |

### Phase 6 — Hardening and release readiness

| Item | Detail |
| --- | --- |
| What | CORS, exception handlers, logging/redaction, rate limiting, token strategy, dependency audit, backups, CI. |
| Files likely affected | `app/main.py`, `app/config.py`, CI files |
| Person 3 components | Logging utils, error hierarchy |
| Dependencies | Optional security tooling |
| Testing | Security checklist, `pip-audit`, load test, restore drill |
| Expected result | Production-ready baseline |

---

## 22. Testing plan

### Backend (currently zero tests)

1. **Import smoke test** — app imports; routes registered.
2. **Auth unit tests** — hash/verify, >72-byte behavior, token create/decode, expired token, wrong signature, missing `sub`.
3. **Auth API tests** — register (success/duplicate/invalid email/short password), login (success/wrong password/unknown email), `/auth/me` (valid/missing/expired token).
4. **Authorization tests** — role enforcement and object ownership (IDOR) once routes exist.
5. **Database tests** — FK enforcement, cascades, unique constraints, migrations on a copy.
6. **Upload tests** — valid/invalid types, oversized, empty, renamed extensions, path traversal filenames, duplicate evidence.
7. **Integration tests** — project → requirement → evidence → analysis → report → review → status, using a temporary SQLite DB and demo-mode AI.
8. **Boundary tests** — no endpoint moves money; PayPal records read-only.

Use `pytest` + FastAPI `TestClient`/`httpx.AsyncClient`; override `get_db` with a temp DB; never touch `proofbridge.db`.

### AI module (in its own environment)

1. Install dependencies, then run `python -m pytest tests -q` and record the real pass/skip/fail counts.
2. Confirm the 3 OCR skips are due to missing Tesseract, then optionally install Tesseract and rerun.
3. Add contract tests for the adapter (DB row → AI model → JSON → DB row round trip).
4. Test mock-vs-real provider labeling, partial-evidence isolation, report fallback, and error-to-HTTP mapping.

### Test data

- Use synthetic fixtures (the AI module already provides demo data under `examples/demo_data/`).
- Never use the single existing user row for tests; create isolated rows in a temp DB.

---

## 23. Unresolved questions

1. **Which domain is authoritative: freelancer project-delivery verification or customer-support/refund investigation?** The brief and backend say freelancer; Person 3's module and handoff say support/refund. This determines everything below.
2. If freelancer: should requirement extraction be built new, or is there another Person 3 artifact not present in this workspace?
3. If support/refund: are you willing to add ticket/order/policy fields and tables to the backend and change the product language?
4. Who creates a project, and who is the client/freelancer in `ProjectCreate` (only `freelancer_id` is supplied today)?
5. Should reviewers be a new role (`reviewer`) or represented as a client/freelancer with elevated permissions?
6. Which AI provider will be used in production (mock/OpenAI-compatible/local), and who supplies keys?
7. Is Tesseract/OCR in scope, and on which OS will the backend run?
8. What file types and maximum sizes are allowed for agreements/evidence?
9. Should evidence be stored on local disk for production, or is object storage planned?
10. Is PayPal integration in scope for this phase (read-only sync), or only the data model for now?
11. How long must reports/evidence be retained, and what are the privacy requirements?
12. Should the AI's full JSON be stored verbatim, or only selected fields projected into relational tables?
13. Is `proofbridge.db` (with 1 user) the real dev database to preserve, or can a fresh DB be created for development?
14. Who is allowed to trigger AI analysis (any participant, or staff only)?

---

## 24. Beginner-friendly explanation of the findings

Think of ProofBridge as a **courtroom with three roles**:

- The **backend** is the *court clerk*: it registers users, files documents, keeps records, and enforces who can see what.
- The **AI module** is the *investigator*: it reads the documents, compares statements, and writes a report with evidence references.
- The **human reviewer** is the *judge*: only they decide the outcome. The investigator never sends money or makes the ruling.

Right now:

1. **The clerk's office is locked.** A small mistake — three form definitions were pasted into the wrong file without the tools they need — makes the whole backend fail when it starts. It's like a clerk who can't open the office because the key was copied into the wrong drawer. One small fix unblocks everything. We did not make that fix because this was an audit only.

2. **The investigator was trained for a different kind of case.** Your product says freelancers and clients argue about *whether the project was delivered*. The investigator was built to handle *shoppers asking for refunds* — receipts, damaged products, refund policies. Both jobs involve "evidence", but the questions are different: "Did the freelancer meet requirement 3?" versus "Does the refund policy cover a cracked item?" The investigator's toolbox (reading PDFs, OCR, comparing dates, writing structured reports) is excellent and reusable, but its *judgment rules* answer the wrong question.

3. **The investigator's equipment isn't in the building.** The AI code isn't installed in the backend's Python environment, and four libraries it needs (Pillow, numpy, PyMuPDF, python-docx) aren't installed. Its own tests couldn't even start. The code looks well-written, but we could not run it here, so we cannot honestly say its tests pass in this workspace.

4. **The records room is half built.** Nine database tables exist and look sensible, with one user row. But there are no doors yet: no API endpoints for projects, requirements, evidence, analysis, reports, or reviews. The tables are like empty filing cabinets with labels but no drawers.

5. **The rules you care about are respected.** Nobody moves money. The backend only *records* PayPal information. The AI module only *reads* payment data as another piece of evidence. The human always decides. That part of the design is healthy.

**The next safest step** is not to write integration code yet. It is to answer one question: *Is this product about freelancer delivery disputes, or about customer-support refunds?*

- If it is about freelancers, we should reuse the investigator's reading tools but build a new "compare deliverable to requirement" brain.
- If it is about refunds, we should change the backend's business fields and language to match the investigator you already have.

Only after that decision should we fix the backend startup bug, install the AI dependencies, and connect the two pieces — one tested step at a time.

---

## Appendix A — Exact commands and observations used

```text
# Workspace inventory
find ... -type f        → app/** (9 py), ai_module/ai_module/** (package/docs/tests), empty tests/, uploads/
find ... -type d        → double-nested ai_module/ai_module/

# Environment
./venv/Scripts/python.exe --version          → Python 3.14.7
pip list                                     → fastapi 0.162.2, sqlalchemy 2.1.8, pydantic 2.14.3, bcrypt 5.0.0, PyJWT 2.15.1, pytest 9.2.0, httpx 0.28.1
pip show proofbridge-ai                      → not found

# Backend import
from app.main import app                     → NameError: BaseModel (app/models.py:268)

# AI dependency probe
PIL/numpy/fitz/docx/pytesseract               → missing in backend venv
pydantic/pydantic_settings/pytest             → missing in system Python

# AI tests
python -m pytest tests -q -p no:cacheprovider → ImportError: No module named 'PIL' (conftest.py:8)

# Syntax
compile() over app/** and proofbridge_ai/**   → 39 files, 0 syntax errors

# Database (read-only URI)
tables                                        → 9
users=1; projects=0; requirements=0; evidence=0; analysis_results=0;
case_status_log=0; reports=0; human_reviews=0; paypal_transactions=0
PRAGMA foreign_keys                           → not enabled by application code
```

## Appendix B — Files inspected

Backend: `app/__init__.py`, `app/config.py`, `app/database.py`, `app/main.py`, `app/models.py`, `app/schemas.py`, `app/security.py`, `app/routers/__init__.py`, `app/routers/auth.py`, `app/services/__init__.py`, `requirements.txt`, `.gitignore`, `proofbridge.db` (schema/row counts only).

AI module: `README.md`, `pyproject.toml`, `requirements.txt`, `.env.example`, `proofbridge_ai/__init__.py`, `config.py`, `exceptions.py`, `logging_utils.py`, `schemas.py`, `integration/facade.py`, `providers/{__init__,base,llm_client,vision_provider,mock_provider}.py`, `services/{document_extractor,file_validation,ocr_service,evidence_extractor,similarity_engine,support_case_analyzer,report_generator,ticket_analyzer,policy_evaluator,cross_source_verifier}.py`, `examples/fastapi_integration.py`, `tests/conftest.py`, `.pytest_cache/v/cache/{nodeids,lastfailed}`, and docs `ARCHITECTURE.md`, `API_CONTRACT.md`, `INTEGRATION_GUIDE.md`, `LIMITATIONS.md`, `CONFIGURATION.md`, `TESTING.md`, `HANDOFF_CHECKLIST.md`, `SCHEMAS.md`, `MODULE_STRUCTURE.md`.

Not opened: `.env` (contents deliberately not read or disclosed).

---

**END OF AUDIT — no code, tests, database, schema, configuration, or environment was modified. Awaiting your explicit approval and the domain decision before any implementation.**
