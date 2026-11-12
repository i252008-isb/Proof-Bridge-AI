# ProofBridge integrated app

This folder contains the ProofBridge React/Vite frontend and FastAPI backend wired together. The frontend calls the backend at `http://localhost:8000`; the backend runs with SQLite and deterministic mock AI by default. AI findings are advisory and human review remains the final decision. PayPal functionality, if configured, is read-only.

## Requirements

- Python 3.10 or newer
- Node.js 18 or newer and npm

## Run on Windows

Open two PowerShell windows.

### 1. Start the backend

```powershell
cd .\backend
Copy-Item .env.example .env
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-ai.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

The first startup creates the SQLite database. Keep the backend terminal open. API docs are at <http://localhost:8000/docs> and health status is at <http://localhost:8000/health>.

### 2. Start the frontend

```powershell
cd .\frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Open the local URL printed by Vite, usually <http://localhost:5173>.

## First use

1. Create a client account and a freelancer account from the sign-up screen. Passwords must have at least 8 characters.
2. The account ID is shown in the top bar. Use the freelancer's ID when the client creates a project.
3. The client uploads the agreement, enters specific requirements of at least 10 characters, and marks work in progress.
4. The freelancer logs in and uploads evidence. The client then runs AI analysis and submits the project for review.
5. Reviewer accounts cannot self-register; an operator must provision them. Sign in with a provisioned reviewer account to record a final decision.

The backend does not extract requirement rows from uploaded agreements, so requirements are entered in the Agreement screen. The frontend uses real API data; it does not silently switch to sample data when the backend is unavailable.

## Configuration

The included `.env.example` files are safe templates. Never copy real secrets into the project archive. The backend's default AI providers are deterministic mocks, so no AI API keys are needed. To enable external providers or PayPal lookups, follow the backend README and review its privacy/security notes first. Keep `CORS_ORIGINS` explicit; the template already includes the local Vite origin.
