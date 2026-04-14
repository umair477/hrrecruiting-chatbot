# Talent Spark HR Chatbot

Talent Spark is an HR and recruiting chatbot project with:

- A React/Tailwind frontend in [talent-spark](/home/unitedsol/hrrecruiting-chatbot/talent-spark)
- A FastAPI backend in [backend](/home/unitedsol/hrrecruiting-chatbot/backend)
- Shared HR workflow logic in [hr_chatbot](/home/unitedsol/hrrecruiting-chatbot/hr_chatbot)

The product supports two core workflows:

1. Leave management for employees
2. Recruitment screening for candidates
3. Admin dashboard management for HR managers
4. Employee-only account activation and sign-in for pre-registered staff

## What Is Implemented

### Backend

- FastAPI API service
- SQLModel-based data models
- PostgreSQL-ready configuration
- Docker Compose for API + Postgres
- JWT authentication with `ADMIN`, `EMPLOYEE`, and `CANDIDATE` roles
- CORS enabled for `http://localhost:3000` and `http://localhost:5173`
- WebSocket chat endpoint for live conversation updates
- Mock HRIS sync endpoints for Workday and BambooHR
- Messaging integration scaffolding for Slack Bolt and Microsoft Teams
- Dedicated employee auth flow backed by the `employee` table
- Employee account activation endpoint: `POST /api/auth/employee/signup`
- Employee login, profile, and logout endpoints:
  - `POST /api/auth/employee/login`
  - `GET /api/auth/employee/me`
  - `POST /api/auth/employee/logout`
- Cookie-based employee sessions with JWT blacklist-backed logout
- Employee login lockout after repeated failed attempts
- Admin dashboard APIs protected by JWT role checks for `ADMIN` users only
- AI-assisted admin job creation with `POST /api/admin/jobs`
- Admin job CRUD endpoints:
  - `GET /api/admin/jobs`
  - `POST /api/admin/jobs`
  - `PATCH /api/admin/jobs/{job_id}`
  - `DELETE /api/admin/jobs/{job_id}`
- Admin candidate pipeline endpoints:
  - `GET /api/admin/candidates`
  - `GET /api/admin/candidates/{candidate_id}`
- Admin leave management endpoints:
  - `GET /api/admin/leaves`
  - `PATCH /api/admin/leaves/{leave_id}`
  - `GET /api/admin/employees/leave-quota`
- Public recruitment jobs endpoint for candidates: `GET /api/recruitment/jobs`

### AI and Workflow Logic

- Leave slot-filling workflow with:
  - date collection
  - reason capture
  - handover capture
  - urgency capture
  - privacy filtering for sensitive medical details
  - structured HR report generation
- Recruitment scoring workflow with:
  - resume text parsing
  - OpenAI-backed or heuristic CV skim analysis against the job description
  - structured insight extraction
  - dynamic interview question generation tailored to the CV and role
  - candidate scorecard generation
  - per-answer interview grading layered on top of the skim-generated questions
- LangGraph-compatible workflow wrappers with deterministic fallback behavior

### Frontend

- Chat screen connected to the backend over WebSockets
- Leave management screen connected to live FastAPI data
- Recruitment screen connected to live candidate data
- Resume upload form that posts files to the recruitment endpoint
- Analytics dashboard connected to backend metrics
- Protected admin routes:
  - `/admin/jobs`
  - `/admin/candidates`
  - `/admin/leaves`
- Sidebar-based HR manager dashboard for job, candidate, and leave operations
- AI-generated job draft modal with editable preview before HR finalization
- Candidate pipeline table with job filter, recommendation badges, and transcript detail view
- Leave requests table with approve/reject actions and a quota sub-tab
- Candidate jobs landing page now backed by live open jobs from the backend
- Employee auth pages:
  - `/employee/signup`
  - `/employee/login`
  - `/employee/dashboard`
- Global employee auth context with session rehydration via `/api/auth/employee/me`
- Employee sessions use httpOnly cookies instead of `localStorage`

## Project Structure

```text
hrrecruiting-chatbot/
├── backend/
│   ├── app/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── docs/
│   ├── hr_chatbot_solution.md
│   └── sprint_integration_plan.md
├── hr_chatbot/
├── talent-spark/
│   ├── src/
│   └── .env.example
├── tests/
├── docker-compose.yml
├── sprint_chatbot.md
└── sprint_integration.md
```

## Core Backend Files

- [main.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/main.py)
  FastAPI entrypoint, startup lifecycle, router registration, and CORS setup.

- [models.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/models.py)
  SQLModel database entities for users, employees, jobs, candidates, leave requests, leave quotas, and token blocklist records.

- [auth.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/api/routes/auth.py)
  General auth plus employee-specific signup, login, profile, logout, rate limiting, and cookie session management.

- [chat.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/api/routes/chat.py)
  WebSocket endpoint used by the live chat UI.

- [recruitment.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/api/routes/recruitment.py)
  Resume upload, candidate scoring API, and public open-jobs listing.

- [leave.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/api/routes/leave.py)
  Leave moderation, balance lookup, and approval endpoints.

- [admin.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/api/routes/admin.py)
  HR manager dashboard endpoints for jobs, candidates, leave requests, and leave quota visibility.

- [agentic.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/services/agentic.py)
  LangGraph-compatible orchestration wrapper for leave and recruitment workflows.

## Demo Credentials

Seeded demo users:

- Admin:
  - email: `admin.hr@talentspark.dev`
  - password: `admin123`
- Candidate:
  - email: `candidate@talentspark.dev`
  - password: `user123`

Pre-registered employee records for signup testing:

- `raj.patel@talentspark.dev`
- `sarah.mitchell@talentspark.dev`
- `tom.anderson@talentspark.dev`

Employees should use `/employee/signup` first, then `/employee/login`.
Admin and candidate demo entry points are still available for local development.

## How To Run With Docker

### 1. Start the backend and database

From the repository root:

```bash
docker compose up --build
```

This starts:

- PostgreSQL on `localhost:5432`
- FastAPI on `localhost:8000`
- The `hr_chatbot` database
- Auto-created application tables and checkpoint tables on API startup
- Auto-seeded dummy data on first startup

### 2. Start the frontend

In a new terminal:

```bash
cd talent-spark
npm install
npm run dev
```

The frontend will normally run on `http://localhost:5173`.

## Database Setup Guide

This project does not need a separate migration command for the demo setup.
When the FastAPI app starts, it runs:

- `create_db_and_tables()` from [main.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/main.py)
- `seed_database()` from [seed.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/seed.py)

That means the backend will automatically:

- create the business tables
- create the chatbot persistence tables
- insert dummy records if the database is empty

### Tables Created Automatically

When the backend starts against the `hr_chatbot` database, it creates these core tables:

- `user`
- `employee`
- `jobs`
- `candidate`
- `leaverequest`
- `leave_quota`
- `token_blocklist`
- `checkpoints`
- `checkpoint_writes`

## Step By Step: Create Tables In PostgreSQL Database `hr_chatbot`

### Option A: Using Docker Compose

This is the easiest setup.

1. Make sure Docker Desktop or Docker Engine is running.
2. Open a terminal in the project root: `/home/unitedsol/hrrecruiting-chatbot`
3. Start Postgres and the API:

```bash
docker compose up --build
```

4. Docker Compose creates a PostgreSQL container with:

```text
Database: hr_chatbot
User: postgres
Password: postgres
Port: 5432
```

5. Wait until the API finishes startup.
   During startup, FastAPI runs the lifespan block in [main.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/main.py), which creates tables and seeds demo data.

6. Open PostgreSQL inside the running container:

```bash
docker exec -it hr-chatbot-postgres psql -U postgres -d hr_chatbot
```

7. List the tables:

```sql
\dt
```

8. Check that demo data exists:

```sql
SELECT * FROM employee;
SELECT * FROM "user";
SELECT * FROM candidate;
SELECT * FROM leaverequest;
SELECT * FROM checkpoints;
SELECT * FROM checkpoint_writes;
```

### Option B: Using Your Local PostgreSQL Server

Use this if you want to run Postgres outside Docker.

1. Create the database:

```bash
psql -U postgres -c "CREATE DATABASE hr_chatbot;"
```

2. Update [backend/.env](/home/unitedsol/hrrecruiting-chatbot/backend/.env) so `DATABASE_URL` points to your local PostgreSQL server. Example:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/hr_chatbot
```

3. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

4. Install backend dependencies:

```bash
pip install -r backend/requirements.txt
```

5. Export the backend environment variables into your shell:

```bash
set -a
source backend/.env
set +a
```

6. Start the backend:

```bash
uvicorn backend.app.main:app --reload
```

7. On startup, the backend connects to `hr_chatbot`, creates the tables, and inserts dummy data if no users exist yet.

8. Verify the tables from your terminal:

```bash
psql -U postgres -d hr_chatbot
```

Then run:

```sql
\dt
SELECT COUNT(*) FROM employee;
SELECT COUNT(*) FROM "user";
SELECT COUNT(*) FROM candidate;
SELECT COUNT(*) FROM leaverequest;
```

## Step By Step: Insert Dummy Data

Dummy data is inserted automatically by [seed.py](/home/unitedsol/hrrecruiting-chatbot/backend/app/seed.py).

### What gets inserted

On a fresh database, the seed process inserts:

- 3 employees
- 3 candidates
- 3 users
- 2 leave requests

Seeded login accounts:

- `admin.hr@talentspark.dev` / `admin123`
- `employee@talentspark.dev` / `user123`
- `candidate@talentspark.dev` / `user123`

### Important behavior

The seed script only runs when the database is empty enough that no `user` record exists yet.
If at least one user is already present, the dummy data is skipped to avoid duplicate rows.

### How to load dummy data into a fresh database

1. Make sure `DATABASE_URL` points to the `hr_chatbot` database.
2. Start the backend once:

```bash
set -a
source backend/.env
set +a
uvicorn backend.app.main:app --reload
```

Or with Docker:

```bash
docker compose up --build
```

3. The startup lifecycle will insert the seed data automatically.
4. Verify it with SQL:

```sql
SELECT id, name, department, leave_balance FROM employee;
SELECT id, email, full_name, role FROM "user";
SELECT id, name, email, role_title, ai_score FROM candidate;
SELECT id, employee_id, start_date, end_date, reason, status FROM leaverequest;
```

## How To Reset And Reseed Dummy Data

If you want to recreate the tables and dummy data from scratch, use one of these approaches.

### Docker reset

This removes the Postgres data volume and gives you a brand-new `hr_chatbot` database:

```bash
docker compose down -v
docker compose up --build
```

### Local PostgreSQL reset

If you are using your own local PostgreSQL server:

1. Open PostgreSQL:

```bash
psql -U postgres -d hr_chatbot
```

2. Drop and recreate the public schema:

```sql
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
```

3. Start the backend again:

```bash
set -a
source backend/.env
set +a
uvicorn backend.app.main:app --reload
```

4. The backend will recreate all tables and insert the dummy data again.

## How To Run Without Docker

### Backend

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
set -a
source backend/.env
set +a
uvicorn backend.app.main:app --reload
```

Default local behavior:

- Uses SQLite if `DATABASE_URL` is not set
- Uses PostgreSQL if `DATABASE_URL` points to Postgres
- Creates tables on startup
- Uses seeded demo data on startup if no users exist
- Exposes the API at `http://localhost:8000`

### Frontend

```bash
cd talent-spark
cp .env.example .env
npm install
npm run dev
```

## API Overview

### Auth

- `POST /api/auth/login`
- `POST /api/auth/signup`
- `GET /api/auth/me`

### Leave

- `GET /api/leave/requests`
- `PATCH /api/leave/requests/{id}`
- `GET /api/leave/balance/me`
- `POST /api/leave/balance/sync/{provider}/{employee_id}`

### Recruitment

- `GET /api/recruitment/candidates`
- `GET /api/recruitment/status`
- `POST /api/recruitment/apply`
- `POST /api/recruitment/score-resume`

### Analytics

- `GET /api/analytics/overview`

### Integrations

- `GET /api/integrations/messaging/platforms`
- `POST /api/integrations/hris/{provider}/sync/{employee_id}`

### Chat

- `WS /api/ws/chat?token=<jwt>`

### Admin

- `GET /api/admin/all-leaves`
- `GET /api/admin/users`
- `POST /api/admin/users/{user_id}/promote`
- `POST /api/admin/leave/{leave_request_id}/approve`

## Frontend Integration Notes

The frontend now uses:

- `fetch()` for REST endpoints
- WebSockets for the main chat screen
- auto-login with seeded demo users for local development

Frontend environment variables:

- `VITE_API_BASE_URL`
- `VITE_WS_BASE_URL`

See [talent-spark/.env.example](/home/unitedsol/hrrecruiting-chatbot/talent-spark/.env.example).

## Recruitment AI Flow

1. Open the Recruitment Hub
2. Enter candidate details
3. Paste a job description
4. Upload a `.pdf` or `.txt` resume
5. Submit the form
6. The backend extracts CV text from the upload
7. The recruitment skim layer compares CV text and job description
8. If `OPENAI_API_KEY` is configured, the backend calls the OpenAI Responses API to produce:
   - matched skills
   - skim insights
   - likely gaps or risks
   - four tailored interview questions
9. If OpenAI is unavailable, the backend falls back to deterministic heuristics and still generates dynamic questions
10. The existing interview scoring system grades each answer and updates the weighted candidate score live
11. The Recruitment Hub shows the skim insights, generated questions, interview transcript, and current scores

## OpenAI Recruitment Configuration

The recruitment intake flow now supports a dedicated AI skim-reading layer before the interview starts.

Recommended backend environment variables:

- `OPENAI_API_KEY`
- `OPENAI_RECRUITMENT_MODEL`
- `OPENAI_EVALUATOR_MODEL`

Example:

```env
OPENAI_API_KEY=your_real_openai_api_key
OPENAI_RECRUITMENT_MODEL=gpt-5-mini
OPENAI_EVALUATOR_MODEL=gpt-5-mini
```

Behavior:

- `OPENAI_RECRUITMENT_MODEL` is used for the CV skim and question-generation step
- `OPENAI_EVALUATOR_MODEL` is used for per-answer grading during the interview
- if no valid OpenAI key is present, the app keeps working with local heuristic fallback logic

## Leave Chat Flow

1. Open the main chat screen
2. Send a leave-related message such as `I need next Tuesday off`
3. The backend classifies the workflow
4. The leave engine asks for missing slots
5. Once dates, reason, and handover details are collected, the backend stores a pending leave request
6. Sensitive medical details are redacted before persistence

## Privacy and Security Notes

- JWT-based auth is enabled
- roles are enforced on admin, employee, and candidate routes
- Sensitive medical leave reasons are filtered before storage
- candidate users can only see their own application status
- candidate users are blocked from the employee chatbot and leave flows until promoted
- CORS is enabled for local frontend development
- External messaging and HRIS integrations are scaffolded but still mock implementations

This is still a sprint implementation, not a fully production-hardened system.

## AI Provider Checkpoint

The integration sprint requested provider keys at the AI integration stage.

To move from deterministic fallback logic to live model-backed behavior, provide one of:

- `OPENAI_API_KEY`
- `GEMINI_API_KEY`

Until then, the workflows remain functional with local logic and seeded data.

## Sprint Documents

- [hr_chatbot_solution.md](/home/unitedsol/hrrecruiting-chatbot/docs/hr_chatbot_solution.md)
- [sprint_integration_plan.md](/home/unitedsol/hrrecruiting-chatbot/docs/sprint_integration_plan.md)
