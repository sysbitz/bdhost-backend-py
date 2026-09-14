# bdhost Backend (Python / FastAPI)

High-performance, multi-tenant static site hosting backend built with **Python 3.14** and **FastAPI** (`fastapi[standard]`). Users can register, create apps, and upload static files (HTML, CSS, JS, assets) or zip bundles to instantly deploy sites live at `{subdomain}.bdappshub.com`.

Deployed on VPS via **Coolify**, with DNS/TLS on **Cloudflare**, and object storage on **Cloudflare R2**.

---

## Architecture Overview

```text
                         ┌─────────────────────────┐
  Browser ──HTTPS──────▶ │   Cloudflare (proxied)   │
                         │  *.bdappshub.com         │  Universal SSL covers
                         │  api.bdappshub.com       │  1 level of wildcard
                         │  app.bdappshub.com       │  automatically
                         └────────────┬─────────────┘
                                      │ Full (strict) — Origin CA cert
                                      ▼
                         ┌──────────────────────────────────────────┐
                         │         VPS — Coolify (Traefik)          │
                         │                                          │
   app.bdappshub.com ───▶│  [dashboard]    (React / Vite frontend)  │
   api.bdappshub.com ───▶│  [api]          FastAPI — CRUD / auth    │
  *.bdappshub.com    ───▶│  [app-runtime]  FastAPI — tenant edge    │
                         │                                          │
                         │  [postgres]     [redis]                  │
                         └──────────────────────────────────────────┘
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │   Cloudflare R2 (bucket) │
                         │   apps/{app_id}/{path}   │
                         └──────────────────────────┘
```

The monorepo contains three independent services:

| Service | Role | Port (Local) | Domain (Prod) | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **`api`** | Auth, app management, file uploads / zip deployments, billing & quotas | `8000` | `api.bdappshub.com` | Talks to Postgres, Redis, and R2 |
| **`app-runtime`** | High-QPS tenant resolver & asset streaming edge from R2 | `8001` | `*.bdappshub.com` | Read-mostly edge; isolated from `api` logic for a seamless future Go migration |
| **`worker`** | Background task queue (`arq`) | Internal | Internal | Reconciles storage quotas and sends async notifications |

---

## Tech Stack

- **Language / Runtime:** Python 3.14 (managed via [`uv`](https://github.com/astral-sh/uv))
- **Web Framework & CLI:** `fastapi[standard]` (run via official `fastapi` CLI)
- **Database:** PostgreSQL 16
- **ORM / Migrations:** SQLAlchemy 2.0 (async + `asyncpg`) + Alembic
- **Caching & Revocation:** Redis 7 (subdomain resolution cache, token revocation, rate limiting)
- **Object Storage:** Cloudflare R2 (S3-compatible via `aioboto3`)
- **Task Queue:** `arq` (asyncio-native, Redis-backed)
- **Authentication:** Argon2id password hashing + short-lived JWT access tokens + rotating httpOnly refresh tokens
- **Validation & Settings:** Pydantic v2 + `pydantic-settings`
- **Linting & Testing:** `ruff`, `mypy`, `pytest`, `pytest-asyncio`

---

## Repository Layout

```text
bdhost-backend-py/
├── pyproject.toml              # Dependencies and tooling config (ruff, mypy, pytest)
├── uv.lock                     # Deterministic dependency lockfile
├── alembic.ini                 # Alembic migration configuration
├── docker-compose.yml          # Local infra: Postgres, Redis
├── .env.example                # Example environment variables
├── Dockerfile.api              # Multi-stage slim container for api (Python 3.14)
├── Dockerfile.app-runtime      # Multi-stage slim container for app-runtime (Python 3.14)
├── Dockerfile.worker           # Multi-stage slim container for worker (Python 3.14)
├── migrations/                 # Database migrations (asyncpg)
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py
├── shared/                     # Shared models, config, and clients (kept thin)
│   ├── config.py               # pydantic-settings config (DB, Redis, R2, Cloudflare)
│   ├── constants.py            # Platform regex, reserved subdomains
│   ├── enums.py                # AppStatus (PROVISIONING, ACTIVE, SUSPENDED, DELETING, DELETED, FAILED), UserRole
│   ├── utils/                  # Path sanitization and traversal prevention
│   ├── db/                     # Base declarative models (User, App, Plan, Payment, RefreshToken)
│   ├── cache/                  # Redis client with typed app:{subdomain} caching
│   └── storage/                # aioboto3 R2 client (put, get, delete, quota calc)
├── src/
│   ├── api/                    # API service (Control Plane)
│   │   ├── main.py             # FastAPI application
│   │   ├── deps.py             # DB session and authentication dependencies
│   │   ├── core/               # Security (Argon2, JWT) and rate limiting
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── services/           # App, file, quota, Cloudflare DNS, and AI placeholder services
│   │   │   └── cloudflare/     # Cloudflare client, DNS service, and typed exceptions
│   │   ├── routers/            # auth, admin, apps, files, billing, account routers
│   │   └── tests/              # API, Admin setup, and Cloudflare DNS test suite
│   └── app_runtime/            # App runtime edge service (Data Plane)
│       ├── main.py             # Tenant resolution, path security, and static file streaming
│       ├── resolver.py         # Strict Host validation & Redis/Postgres caching
│       └── tests/              # Tenant resolution, host validation, and traversal security test suite
├── worker/                     # Background worker
│   ├── main.py                 # arq WorkerSettings and cron jobs
│   └── tasks.py                # recalc_quota and send_email
└── scripts/
    ├── seed.py                 # Seeds default hosting plans (no pre-seeded admin)
    ├── check_cloudflare.py     # Cloudflare connectivity and wildcard DNS verification CLI
    └── dev_up.sh               # Quickstart helper script
```

---

## Getting Started (Local Development)

### Prerequisites

- [Python 3.14](https://www.python.org/)
- [`uv`](https://github.com/astral-sh/uv) (package manager)
- [Docker](https://www.docker.com/) & Docker Compose

### 1. Installation

Clone the repository and install all dependencies using `uv`:

```bash
uv sync
```

### 2. Environment Configuration

Copy the sample environment file:

```bash
cp .env.example .env
```

Review `.env` parameters and configure your Cloudflare R2 credentials:
- `R2_ENDPOINT_URL`: `https://<cloudflare_account_id>.r2.cloudflarestorage.com`
- `R2_ACCESS_KEY_ID`: Your Cloudflare R2 Access Key ID
- `R2_SECRET_ACCESS_KEY`: Your Cloudflare R2 Secret Access Key
- `R2_BUCKET`: `bdappshub-apps`

### 3. Start Local Infrastructure Containers

Start PostgreSQL and Redis in the background:

```bash
docker compose up -d postgres redis
```

> **Note on Docker downloads:** On the first launch, Docker downloads the Alpine images for PostgreSQL 16 and Redis 7. Once cached, they start instantly.

### 4. Run Database Migrations

Apply the database schema:

```bash
uv run alembic upgrade head
```

### 5. Seed Initial Data

Seed default hosting plans (`Free`, `Pro`, `Enterprise`):

```bash
uv run python scripts/seed.py
```

> **Note on Admin Account:** There is no hardcoded or pre-seeded admin account. The first admin is configured dynamically via the one-time setup API (`POST /auth/setup-admin`), after which the setup route permanently disables itself.

---

## Running the Services

Run each service directly using the official `fastapi` CLI:

### API Service (`api`)
```bash
uv run fastapi dev src/api/main.py --port 8000
```
- Interactive Swagger docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health check: [http://localhost:8000/health](http://localhost:8000/health)

### App Runtime Service (`app-runtime`)
```bash
uv run fastapi dev src/app_runtime/main.py --port 8001
```
- Health check: [http://localhost:8001/health](http://localhost:8001/health)
- Tenant resolution: Send requests with a `Host` header (e.g. `curl -H "Host: my-app.bdappshub.com" http://localhost:8001/`)

### Background Worker (`worker`)
```bash
uv run arq worker.main.WorkerSettings --watch worker
```

> **Windows PowerShell Tip:** If you see character encoding warnings on Windows consoles with `fastapi dev` rich output, run `$env:PYTHONUTF8="1"` beforehand.

---

## Initial Admin Setup & Panel Flow

1. **Check Setup Status:**
   - Call `GET /auth/setup-status`
   - Returns `{"admin_setup_required": true}` if no administrator exists in the database yet.
2. **One-Time Admin Setup:**
   - Call `POST /auth/setup-admin` with your chosen email and password:
     ```json
     {
       "email": "owner@bdappshub.com",
       "password": "your-secure-password"
     }
     ```
   - Creates the initial `ADMIN` user, sets the secure httpOnly refresh cookie, and returns access token + user details.
   - **Single-use lock:** Any future requests to `/auth/setup-admin` are permanently blocked with `403 Forbidden` (`{"detail": "Initial admin has already been configured"}`).
3. **Admin Panel Access:**
   - Use the obtained Bearer token to access the protected admin panel endpoints:
     - `GET /admin/overview`: System metrics (total users, total apps, active apps, total storage used).
     - `GET /admin/users`: List all registered users across the platform.
     - `GET /admin/apps`: List all deployed applications across all users.

---

## API Endpoints Overview

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | API service health check | No |
| `GET` | `/auth/setup-status` | Check if initial admin setup is required | No |
| `POST` | `/auth/setup-admin` | **One-time** first admin creation (locks after use) | No (Disabled once admin exists) |
| `POST` | `/auth/register` | Register new user account | No (Rate limited) |
| `POST` | `/auth/login` | Log in and receive JWT + refresh cookie | No (Rate limited) |
| `POST` | `/auth/refresh` | Rotate refresh token and get new access token | Cookie |
| `POST` | `/auth/logout` | Revoke refresh token and clear cookie | Cookie |
| `GET` | `/auth/me` | Current authenticated user profile | Bearer Token |
| `GET` | `/admin/overview` | Platform metrics & aggregate storage stats | Bearer Token (Admin only) |
| `GET` | `/admin/users` | List all platform users | Bearer Token (Admin only) |
| `GET` | `/admin/apps` | List all platform apps across all tenants | Bearer Token (Admin only) |
| `GET` | `/apps` | List current user's apps | Bearer Token |
| `POST` | `/apps` | Create a new app (subdomain reservation & quota check) | Bearer Token |
| `GET` | `/apps/{id}` | Get single app details | Bearer Token |
| `PATCH` | `/apps/{id}` | Update custom index, SPA fallback, or status | Bearer Token |
| `DELETE` | `/apps/{id}` | Delete app and its R2 storage files | Bearer Token |
| `GET` | `/apps/{id}/files` | List hosted files under app | Bearer Token |
| `POST` | `/apps/{id}/files` | Upload a single file (multipart) | Bearer Token |
| `POST` | `/apps/{id}/deploy` | Deploy zip archive (validates quota before upload) | Bearer Token |
| `DELETE` | `/apps/{id}/files?path=...` | Delete a single hosted file | Bearer Token |
| `GET` | `/billing/plans` | List available hosting plans | No |
| `GET` | `/billing/subscription` | Current plan details & quotas | Bearer Token |
| `GET` | `/account` | User account summary and resource usage statistics | Bearer Token |
| `PATCH` | `/account` | Update user profile details | Bearer Token |

---

## Quality Checks & Testing

The codebase enforces strict linting, formatting, type-checking, and test coverage:

```bash
# 1. Run full test suite (in-memory SQLite + mocked R2/Redis fixtures)
uv run pytest -v

# 2. Linting check
uv run ruff check .

# 3. Formatting check
uv run ruff format --check .

# 4. Static type check
uv run mypy shared src/api src/app_runtime worker
```

---

## Key Features & Business Rules

1. **Subdomain Lifecycle:**
   - Validated against slug regex: `^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$`.
   - Reserved slugs rejected (`api`, `app`, `www`, `admin`, `cdn`, `mail`, `status`, etc.).
   - Sites are live immediately once `index.html` is uploaded — no manual DNS provisioning required.
2. **File & Deployment Security:**
   - Permitted file extensions: `html, css, js, mjs, json, svg, png, jpg, jpeg, gif, webp, ico, woff, woff2, ttf, map, txt, md, xml`.
   - Zip deploy validates all entries, rejects path traversal attempts (`../`), and checks total uncompressed size against plan quota before writing anything to R2.
3. **App Runtime & SPA Routing:**
   - Caches subdomain lookups in Redis (`app:{subdomain}`) with 60s TTL.
   - Negative-caches non-existent domains to prevent database thrashing.
   - Supports Single Page Applications via `spa_fallback: True` (falls back to custom index on 404).
   - Serves conditional HTTP `ETag` / `304 Not Modified` headers.
4. **Designed for Future Portability:**
   - `app-runtime` and `api` communicate exclusively via PostgreSQL, Redis, and R2 contracts.
   - Zero business logic leaks into `app-runtime`, ensuring it can be rewritten in Go for extreme concurrency without modifying the rest of the stack.
5. **Cloudflare DNS Automation & Wildcard Setup:**
   - **Control Plane vs Data Plane Separation:** Individual per-tenant DNS records are **never** created. Cloudflare routes all tenant subdomains to the app runtime via a single wildcard `*.bdappshub.com` A record.
   - **PostgreSQL as Source of Truth:** PostgreSQL (accelerated by Redis) decides if a subdomain exists and which app it resolves to.
   - **Idempotent Wildcard Provisioning:** `CloudflareDNSService.ensure_wildcard_record()` provisions `* -> APP_RUNTIME_IP` idempotently without duplicates.
   - **Runtime Host Hardening:** The resolver validates the `Host` header against `BASE_DOMAIN`, rejects multi-level subdomains, foreign hosts, and reserved names.
   - **Path Traversal Protection:** Static paths and `custom_index` are sanitized and normalized; keys never escape `apps/{app_id}/`.
   - **Cloudflare Verification CLI:** Run `uv run python scripts/check_cloudflare.py` to test credentials, zone access, and wildcard record status.

---

## Production Deployment (Coolify)

Each service has its own dedicated Dockerfile:
- `Dockerfile.api` → Deploy with custom domain `api.bdappshub.com`
- `Dockerfile.app-runtime` → Deploy with wildcard domain `*.bdappshub.com`
- `Dockerfile.worker` → Deploy as a background worker (no public domain)

Set environment variables in Coolify matching `.env.example` with production secrets, PostgreSQL, Redis, and Cloudflare R2 credentials.
