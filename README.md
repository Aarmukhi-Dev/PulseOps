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

The worker also requires `WORKER_LOCK_DATABASE_URL`. For local development, it can use the same local PostgreSQL URL as `DATABASE_URL`; production must use a direct Neon connection for this session-level lock.

The worker checks enabled HTTP/HTTPS targets such as `https://status.example.com/health` and TCP targets such as `db.example.com:5432` (or `tcp://db.example.com:5432`). It uses each service's configured interval and timeout. The concurrency limit can also be provided with `--max-concurrent-checks`.

Authenticated account access, owner-scoped service management, incident history, and monitoring analytics are implemented. Incident acknowledgement workflows and account recovery are still future work.

## Create a local development user

There is no public registration endpoint. With local PostgreSQL running and the migrations already applied, create one development user from the `backend` directory:

```powershell
.\.venv\Scripts\Activate.ps1
python -m app.cli.create_dev_user
```

The command prompts for an email and display name, then asks for a password twice without echoing it. It hashes the password with Argon2 before saving it. If the normalized email already exists, the command leaves that account and password unchanged. Log in at the dashboard with this account; service ownership is assigned by the API from the signed-in user.

For non-interactive local use, the command also reads `PULSEOPS_DEV_USER_EMAIL`, `PULSEOPS_DEV_USER_DISPLAY_NAME`, and `PULSEOPS_DEV_USER_PASSWORD`. Prefer the hidden interactive password prompt; do not save the password in scripts or shell profiles. This development-only command refuses to run unless `DATABASE_URL` points to a loopback host.

For a production account, run `python -m app.cli.create_user` from a trusted operator shell after migrations are applied. It prompts for the password without echoing it and never accepts a password from an environment variable. Restrict access to this command and do not expose account creation through a public endpoint.

## Production deployment preparation

The production frontend is on Vercel, the FastAPI API and supervised monitoring worker share one SnapDeploy container, and PostgreSQL is on Neon. The API requires login for service changes, and worker targets are restricted to public addresses with DNS pinning and redirect validation. Keep the worker in this API deployment; SnapDeploy requires an HTTP listener and does not run a worker-only container without one.

### Neon connection URLs

Set the values in SnapDeploy's environment settings; do not commit Neon URLs or paste them into source files. Copy the URLs from the Neon Console's **Connect** dialog for the same branch, database, and role:

- `DATABASE_URL`: use the **pooled** endpoint (hostname contains `-pooler`) for the API and worker. Keep the Neon TLS query parameter `sslmode=require`.
- `MIGRATION_DATABASE_URL`: use the **direct** endpoint (hostname does not contain `-pooler`) for Alembic only. Keep `sslmode=require` here too.
- `WORKER_LOCK_DATABASE_URL`: use a direct Neon endpoint (no `-pooler`) for the session-level worker singleton lock. Worker service queries and writes still use pooled `DATABASE_URL`.

The app accepts Neon/PostgreSQL URLs and normalizes the scheme to SQLAlchemy's `postgresql+psycopg://` driver. This project uses psycopg 3. The API URL is validated as pooled for Neon; migration and worker-lock URLs are validated as direct. If `MIGRATION_DATABASE_URL` is not set, Alembic falls back to `DATABASE_URL`; production should set the direct URL explicitly.

Optional SQLAlchemy client-pool settings are `DATABASE_POOL_SIZE` (default `5`), `DATABASE_MAX_OVERFLOW` (default `5`), `DATABASE_POOL_TIMEOUT_SECONDS` (default `30`), and `DATABASE_CONNECT_TIMEOUT_SECONDS` (default `10`). The advisory lock uses one dedicated direct connection and does not use the application pool.

### SnapDeploy API and monitoring worker

Configure the existing SnapDeploy service with:

| Setting | Value |
|---|---|
| Root Directory | `backend` |
| Region | Singapore, to keep the service near the Neon project |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python start.py` |
| Health Check Path | `/health` |

`start.py` runs `alembic upgrade head` before starting either child process, then supervises FastAPI and the monitoring worker. FastAPI remains the real HTTP listener. SnapDeploy's platform-provided `PORT` is used (default `8000`).

Set these environment variables on the web service:

- `DATABASE_URL`: Neon pooled URL.
- `MIGRATION_DATABASE_URL`: Neon direct URL, used by startup Alembic migrations.
- `WORKER_LOCK_DATABASE_URL`: Neon direct URL dedicated to the PostgreSQL advisory lock; do not use a pooled URL here.
- `CORS_ORIGINS`: set by the Blueprint to the exact existing production origin `https://pulse-theta-two.vercel.app`. Add a custom frontend domain explicitly if used. Do not use `*` or a wildcard Vercel preview origin.
- `APP_ENV=production`.
- `JWT_SECRET_KEY`: at least 32 random characters; generate a unique secret and store it only in SnapDeploy's secret environment settings. Never reuse the local development secret.
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`: optional, defaults to 30 (allowed range 5–1440).
- `API_RATE_LIMIT_PER_MINUTE` and `LOGIN_RATE_LIMIT_PER_MINUTE`: optional process-local request limits, defaults 120 and 5.
- `SERVICE_MUTATIONS_ENABLED=true`: authenticated owners can manage their own services; set this to `false` to disable service mutations.
- `MONITORING_WORKER_ENABLED=true`: the launcher starts the worker only when explicitly enabled. Set it to `false` to keep the API read-only with respect to monitoring checks.
- `PULSEOPS_MAX_CONCURRENT_CHECKS=1`: start conservatively; increase only after reviewing API responsiveness and Neon usage.
- The optional `DATABASE_*` pool settings above, if you need to tune them.

Before startup migrations run against an existing Neon database, verify the target branch and current Alembic revision and create a backup. Startup fails closed if migrations fail. Do not use the development-user CLI against Neon.

The worker holds a PostgreSQL session-level advisory lock over `WORKER_LOCK_DATABASE_URL`. During an overlapping SnapDeploy deployment, the replacement process waits for that lock and performs no checks until the previous worker releases it. Unexpected worker exits are logged and restarted with bounded backoff; API shutdown stops both children and escalates to termination if needed.

### Vercel Vite frontend

For the existing Vercel project, keep its production domain and set Root Directory to `frontend`. The committed `frontend/vercel.json` configures Vite output, SPA route fallback, and browser security headers. Set `VITE_API_URL` in Vercel's Production environment to the SnapDeploy API origin; it is public configuration, not a secret. Do not put database URLs, JWT keys, or passwords in any `VITE_*` variable.

Use these project settings:

| Setting | Value |
|---|---|
| Root Directory | `frontend` |
| Framework Preset | Vite |
| Build Command | `npm run build` |
| Output Directory | `dist` |

Set `VITE_API_URL` for the Vercel Production environment to the SnapDeploy API base URL (no trailing slash). Add it separately for Preview if previews should call a non-production backend. `VITE_API_URL` is compiled into browser code and must contain no secrets. Redeploy after changing Vercel environment values.

Add the deployed Vercel production origin and any custom frontend origin to the API's exact `CORS_ORIGINS` list. Preview deployments have varying origins; this backend intentionally rejects wildcard origins, so add only specific preview origins you intend to trust.

### Security behavior and limitations

New users can create an account at `/register`; registration validates and normalizes email, requires a 12-character password and confirmation, hashes it with Argon2, and returns the same short-lived bearer-token shape as login. There is no email verification, password reset, MFA, role system, or incident mutation workflow. `/health` remains public for platform health checks; the dashboard keeps bearer tokens in memory, so a page reload requires another login. Each account can access only its own services, check history, incidents, and event timelines. Use strong, unique passwords; trusted operators can also provision accounts with `python -m app.cli.create_user`.

The monitoring worker rejects localhost, private, reserved, link-local, metadata targets, and HTTP target URLs with common credential query keys; it rejects mixed public/private DNS answers, connects to the validated numeric address to resist DNS rebinding, and revalidates every HTTP redirect. It sends no credentials to targets. DNS lookup itself uses the operating system resolver and is not hard-timed by Python; keep worker concurrency bounded and use network egress rules as an additional defense. The worker can still contact any public host/port, so restrict service creation to trusted authenticated users and apply outbound network policy where available.

Rate limits and the declared `Content-Length` body cap run in each API process. Chunked request bodies still depend on the hosting proxy's request-size limit; configure that limit at the edge. Rate limits reset on restart and are not shared across API instances; for multiple instances, put a shared limiter/WAF at the edge. The API uses the ASGI peer address and does not trust arbitrary `X-Forwarded-For` input, so verify how the SnapDeploy proxy chain is represented before relying on per-client limits. CORS allows only configured exact HTTPS production origins; it is browser policy, not authorization. Production API docs are disabled. Tokens are HMAC-SHA256 signed and expire; rotate `JWT_SECRET_KEY` to invalidate all outstanding tokens.

The SnapDeploy launcher binds FastAPI to the platform-provided `PORT`; the Vercel setting uses the Vite build output. See [SnapDeploy Docker hosting](https://snapdeploy.dev/docker-hosting), [Vercel Vite](https://vercel.com/docs/frameworks/frontend/vite), and [Neon connection pooling](https://neon.tech/docs/connect/connection-pooling) for platform-specific details.
