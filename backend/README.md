# AICTE Complaint Monitoring API

This is a local demonstration prototype. All seeded institution, officer, and complaint records are fictional and are not official AICTE data.

## Setup (Ubuntu/Linux)
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.seed
uvicorn app.main:app --reload
```
API docs: http://127.0.0.1:8000/docs  
Health: http://127.0.0.1:8000/api/health

Demo login: `admin@demo.local` / `Demo@12345`

Database: `backend/data/aicte_complaints.db`. It is created automatically and persists across restarts. Seed script is safe to rerun for existing demo data.

## Important prototype limitations
The semantic sentence-embedding service, scheduled deadline worker, full officer/user administration mutations, document uploads, and production-grade deployment hardening are not implemented in this starter. Cross-bureau overlap detection is rule-based and requires human review. Change the development secret in `.env` before using beyond local demos.
