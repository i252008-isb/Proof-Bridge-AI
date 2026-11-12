# ProofBridge AI Frontend

React + Vite. Runs on built-in sample data; connects to the FastAPI backend when `VITE_API_URL` is set.

## Run
    npm install
    npm run dev      # http://localhost:5173

Any email/password logs in (demo mode). Data is saved in browser localStorage; use "Reset demo data" on the Dashboard.

## Connect the backend
1. Copy `.env.example` to `.env` and set `VITE_API_URL=http://localhost:8000`
2. Edit paths/fields in `src/api.js` to match Person 2's API contracts. If a call fails, the app falls back to sample data.
3. Backend needs CORS enabled for http://localhost:5173.

## Structure
src/api.js (all backend calls) · src/store.jsx (state + sample data) · src/pages/* · src/components/*
