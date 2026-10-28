# AICTE Integrated Institution Complaint Monitoring System

Full-stack local prototype for Smart India Hackathon Problem Statement 26264.

## Stack
- React + TypeScript + Vite + Recharts + Lucide React
- FastAPI + SQLModel + SQLite
- Persistent database: `backend/data/aicte_complaints.db`

## Start the backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.seed
uvicorn app.main:app --reload
```
API documentation: http://127.0.0.1:8000/docs

## Start the frontend (new terminal)
```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```
Open the Vite URL printed in the terminal, normally http://localhost:5173.

## Demo credentials
- Email: `admin@demo.local`
- Password: `Demo@12345`

All seeded institutions and complaints are fictional demonstration records. This prototype is not connected to official AICTE systems.

## Included in this starter
Authentication, persistent SQLModel/SQLite storage, dashboard summaries and charts, institution listing and creation, complaint creation and status updates, case transfers and history, rule-based cross-bureau overlap scan and review, coordination records, notifications, bureau workload, CSV export, audit log, and responsive layout.

## Not yet production-complete
Semantic embedding similarity, scheduled deadline reminder worker, file uploads, full officer account CRUD, configurable settings persistence, complete role-scope policies for every Bureau/region, and a comprehensive automated test suite need further implementation. Do not deploy this prototype with real sensitive complaint data without a security and privacy review.
