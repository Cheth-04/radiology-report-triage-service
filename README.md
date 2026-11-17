# Radiology Report Triage Service

A small, **synthetic-data-only** radiology text triage demo built for a backend technical assessment. An authenticated radiologist submits report text; FastAPI persists a queued job and returns **HTTP 202** with a UUID immediately. A Celery worker uses a configured LLM (or a deterministic five-sample mock) to extract structured fields, validates them with Pydantic, stores results in PostgreSQL, and logs a critical triage alert where applicable. A protected job endpoint exposes processing status and results.

> **Not a clinical device.** This software is for evaluating asynchronous backend design only. Do not submit real patient information or use its classifications for medical decision-making. A successful JSON validation does not guarantee clinical correctness.

## Architecture

```text
Radiologist -> POST /reports [JWT] -> FastAPI -> PostgreSQL (queued)
                                          |  -> Redis broker (job UUID only)
                                          v
                                      HTTP 202 (job_id)
Redis -> Celery worker -> PostgreSQL (processing) -> LLM / mock -> Pydantic validation
                         -> PostgreSQL (result + done, or failed) -> critical log alert
Radiologist / Admin -> GET /jobs/{job_id} [JWT] -> PostgreSQL (ownership enforced)
```

PostgreSQL is the durable source of truth for statuses. Redis is the Celery transport and result backend. No report content is placed into Celery task arguments. Admins can read all reports/jobs; radiologists may access only their own. Admin-only account creation is intentional; the admin does not upload reports.

## Stack

Python 3.11 · FastAPI · Pydantic · SQLAlchemy · PostgreSQL 16 · Alembic · Redis 7 · Celery · JWT (PyJWT) · Argon2 (pwdlib) · OpenAI-compatible local LM Studio · pytest · Docker Compose.

## Quick start — local Docker (mock mode)

Prerequisites: Docker Desktop with Compose, available port **8000**, approximately 2 GB free memory for the small services. Commands run from the repository root.

```bash
cp .env.example .env
openssl rand -hex 32
```

Edit `.env`: replace `JWT_SECRET` with the generated value, and choose a non-default `POSTGRES_PASSWORD`. **Update the password in `DATABASE_URL` to match.** For special characters in database passwords, URL-encode them in `DATABASE_URL` or use a simple alphanumeric generated password for this demo. Keep `LLM_MODE=mock`. `.env` is ignored by Git.

```bash
docker compose up --build -d
docker compose ps
curl -f http://localhost:8000/ready
```

The Compose `migrate` one-shot service automatically runs `alembic upgrade head` after PostgreSQL is healthy. It exits with code 0 upon success; **that is expected**, not a failure. FastAPI and Celery start only after migrations succeed. The API is bound to `127.0.0.1:8000`. Swagger: http://localhost:8000/docs.

Create the first admin interactively (one-time bootstrap):

```bash
docker compose exec -it api python -m app.scripts.create_admin admin@example.com
```

Then use `POST /auth/login` (`username` is the admin email, as OAuth2 form data) and `POST /auth/users` with a bearer token to create a radiologist. Login as that radiologist and submit a sample with `POST /reports`. Poll `GET /jobs/{job_id}` for the final structured result. Use the interactive Swagger UI at
http://localhost:8000/docs to test authentication,
report submission, and job status retrieval.

**First-run clarification:** `docker compose up` starts the services and creates database schema; interactive admin bootstrap is intentionally separate. Mock mode requires no API key and no LM Studio process.

## API contract

| Method | Route | Authorization | Outcome |
|---|---|---|---|
| GET | `/health` | Public | Liveness response |
| GET | `/ready` | Public | PostgreSQL/Redis checks (503 if unavailable) |
| POST | `/auth/login` | Public | OAuth2 form login, JWT access token |
| GET | `/auth/me` | Signed-in user | Current account metadata |
| POST | `/auth/users` | Admin | Create a radiologist/admin account |
| POST | `/reports` | Radiologist | **202** `{ "job_id": "<uuid>", "status": "queued" }` |
| GET | `/reports` | Radiologist (own) / Admin (all) | Paginated report list |
| GET | `/reports/{report_id}` | Owner / Admin | One report |
| GET | `/jobs/{job_id}` | Owner / Admin | Queued, processing, done (+ result), or failed (+ error) |

Example `POST /reports` body:

```json
{"report_text":"Acute intraparenchymal hemorrhage in the left basal ganglia measuring 3.2 cm with 4 mm midline shift. Impression: Acute intracranial hemorrhage."}
```

Successful completed result includes `modality`, `body_part`, `findings` (array), `impression`, `is_critical` (JSON boolean), and `critical_reason` (required for critical findings). Invalid request text returns 422. Missing/invalid JWT returns 401. Role violation returns 403 for uploads/account creation; unknown/other-user jobs return 404 to prevent enumeration.

## LLM modes

- **Mock** (`LLM_MODE=mock`, recommended for automated checks): deterministic outputs **only** for the assignment's five synthetic samples. Unknown reports fail safely. This does not prove LLM clinical quality.
- **LM Studio** (`LLM_MODE=lmstudio`): load a local instruction-tuned model in LM Studio, start the OpenAI-compatible server on the Mac host (usually port 1234), obtain the exact model ID via `curl http://localhost:1234/v1/models`, and set `LLM_MODEL` accordingly. Within Docker Desktop, `LLM_BASE_URL=http://host.docker.internal:1234/v1`. Ensure host-side binding/network permissions permit access. Recreate API and worker after `.env` changes:

```bash
docker compose up -d --force-recreate api worker
```

LM Studio may require separate host startup; unlike mock mode, it is **not** started by Docker Compose. The OpenAI-compatible client is configured with no SDK retries; Celery retries transient HTTP failures and timeouts with exponential backoff. Malformed/invalid extraction is failed rather than silently classified noncritical. Avoid sending any real patient data to any model.

## Test suite

```bash
# All unit tests (no LLM API key required)
docker compose run --rm -v "$PWD/tests:/code/tests:ro" api python -m pytest -q tests/

# Real API → Redis → Celery → PostgreSQL → API smoke test, with mock extraction
python3 scripts/e2e_smoke.py --url http://localhost:8000 \
  --radiologist radiologist@example.com --admin admin@example.com

# Inspect alert logs (critical sample jobs only)
docker compose logs --tail=300 worker | grep 'CRITICAL TRIAGE ALERT'
```

The smoke script prompts for credentials (no passwords in shell history), submits all five assignment samples, polls job completion, checks output classifications and admin visibility. Also test isolation manually with a second radiologist. 

## Design decisions and trade-offs

1. **Fast API handoff:** The database commit and Redis task publication complete before `202`; expensive LLM inference happens only in the worker. These two operations are not atomic; a crash between them may leave a stranded queued job. A transactional outbox/reconciler would improve reliability.
2. **Persistent lifecycle:** `queued → processing → done / failed` is stored in PostgreSQL; task-result expiration in Redis does not affect job retrieval. Interrupted processing may leave a job in `processing`; stale-task recovery is not implemented.
3. **Defensive extraction:** Pydantic enforces types, required fields and critical reason consistency. It cannot establish diagnostic correctness. Transient model errors retry up to three times after the first attempt; invalid structured output fails closed.
4. **Access control:** Argon2 password hashes, signed expiring JWTs, user lookup on every protected call, role/owner checks, and sanitized failure messages. No refresh-token/identity-provider infrastructure is included.
5. **Alerts:** The worker logs a critical-event marker **after** result persistence, without patient text. Logging is sufficient for this assignment, but a process crash may lose an alert; production would need durable outbox delivery, audit trails and operational monitoring.
6. **Local scope:** Docker networking is constrained to loopback for the API. There is no HTTPS termination, rate limiter or clinical security/compliance certification; deploy only in a synthetic-data demo environment.

## Database migrations

Migration `0001_initial` creates `users`, `reports`, `report_results`, and Alembic's version table. Migrations run automatically on Compose startup; to inspect:

```bash
docker compose exec api alembic current
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
```

Do not run `docker compose down -v` unless you deliberately intend to delete local database and Redis volumes.

## Next improvements

Transactional outbox/requeue recovery; durable alert delivery with deduplication and audit; request rate limiting; richer metrics/tracing and structured redacted logs; standardized terminology and clinician-reviewed safety evaluation; more providers; stronger model evaluation; CI integration (a basic GitHub Actions workflow is provided as an optional demonstration).

