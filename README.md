# PulseOps
An intelligent operations monitoring and incident management platform.

## Phase 1 setup (Windows)

Requirements: Python 3.12 or newer, Node.js 20 or newer, and Docker Desktop.

From PowerShell, in this repository:

```powershell
copy .env.example .env
copy frontend\.env.example frontend\.env
docker compose up -d
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
pytest
uvicorn app.main:app --reload --port 8000
```

Leave that API terminal open. In a second PowerShell window:

```powershell
cd frontend
npm install
npm test
npm run dev
```

Open http://localhost:5173. The page calls http://localhost:8000/health.

`GET /health` returns `{"status":"ok","database":"ok"}` when PostgreSQL is reachable, and HTTP 503 when it is not.

To run the separate service availability worker after applying the database migrations, open another PowerShell window in `backend` and run:

```powershell
$env:PULSEOPS_MAX_CONCURRENT_CHECKS = "10"
.\.venv\Scripts\Activate.ps1
python -m app.monitoring.worker
```

The worker checks enabled HTTP/HTTPS targets such as `https://status.example.com/health` and TCP targets such as `db.example.com:5432` (or `tcp://db.example.com:5432`). It uses each service's configured interval and timeout. The concurrency limit can also be provided with `--max-concurrent-checks`.

Authentication, incident management workflows, and analytics are still future work.

## Create a local development user

The service API requires `created_by` to reference a user row. There is no public registration endpoint. With local PostgreSQL running and the migrations already applied, create one development user from the `backend` directory:

```powershell
.\.venv\Scripts\Activate.ps1
python -m app.cli.create_dev_user
```

The command prompts for an email and display name, then asks for a password twice without echoing it. It hashes the password with Argon2 before saving it. If the normalized email already exists, the command leaves that account and password unchanged and prints its UUID. The UUID can be used as `created_by` in Swagger.

For non-interactive local use, the command also reads `PULSEOPS_DEV_USER_EMAIL`, `PULSEOPS_DEV_USER_DISPLAY_NAME`, and `PULSEOPS_DEV_USER_PASSWORD`. Prefer the hidden interactive password prompt; do not save the password in scripts or shell profiles. This development-only command refuses to run unless `DATABASE_URL` points to a loopback host.
