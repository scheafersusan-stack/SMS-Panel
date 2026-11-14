# Dev runbook

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/); Node 22 and npm
- Docker with the compose plugin (only for the full stack)
- For the test suite without Docker: PostgreSQL 16 binaries (`initdb`, `pg_ctl`) and `redis-server`
  on the machine, or `PAYAMAKYAR_TEST_DATABASE_URL` / `PAYAMAKYAR_TEST_REDIS_URL` pointing at
  running servers. Integration tests skip when neither is available.

## Everyday gates

```
make install        # uv sync (locked)
make ci             # ruff, mypy --strict, pytest (unit + integration + e2e smoke)
make web-ci         # npm ci, eslint, tsc, vitest, next build (+ CSP hash step)
make ci-all         # both
```

`make test-unit` runs without Postgres/Redis. `make test-integration` runs only the `integration`
marker. The end-to-end smoke test is `tests/e2e/test_smoke.py`.

## Full stack (Docker)

```
cp infra/env/.env.example infra/.env      # optional: every value has a dev default
make dev                                  # docker compose -f infra/docker-compose.yml up --build
```

Services: `postgres` (16), `redis` (7), `migrate` (one-shot `alembic upgrade head`), `api`
(uvicorn on :8000, internal), `worker` (job worker) and `caddy` (the only published ports).
Open `https://localhost:8443` (accept Caddy's internal CA certificate). Browse the HTTPS URL
directly: the HTTP port only redirects to 443, which is wrong when the host port is remapped.

`make down` stops it (`make down ARGS=-v` also drops the database volume).

### Edge and client IP

Caddy serves the static web export with SPA fallback and proxies `/panel/*` to `api:8000`.
uvicorn runs with `proxy_headers=False`; `X-Forwarded-For` is honoured only from peers inside
`PAYAMAKYAR_TRUSTED_PROXIES`. Compose pins the network to `172.28.0.0/24` and sets that value;
if you change one, change the other (`tests/test_infra.py` checks they agree). Never widen it to
a range clients can reach.

CSP: `npm run build` (postbuild step `scripts/csp-hashes.mjs`) hashes the inline scripts of the
Next export and writes `apps/panel-web/.csp/csp.caddy`; the caddy image bakes it in. The pre-paint
theme script is the static file `public/theme-init.js`. If the snippet is missing, Caddy falls
back to a strict `script-src 'self'` and the page will not hydrate (fail closed).

## Migrations

`make migrate` runs `alembic upgrade head` against `PAYAMAKYAR_DATABASE_URL` from your shell
(or `.env`). Inside the stack the `migrate` service does it before `api` and `worker` start.
Equivalent: `python -m payamakyar.api migrate`.

## Bootstrap the first admin

```
make create-admin USERNAME=ali MOBILE=09121234567     # against the compose stack
# or locally:
uv run python -m payamakyar.api create-admin --username ali --mobile 09121234567
```

It prints a strong one-time password exactly once and records the audit event
`user.create_admin`. The admin can log in, but every `/panel/admin/v1/*` route answers
`MFA_REQUIRED` until the account enables TOTP (profile, security, authenticator app; the
account password is required to confirm). Log in again with the 6-digit code to reach the admin
API. Change the one-time password after first login.

## Worker and system SMS

OTPs, login notices and similar messages are written to `system_messages` and queued as
`system_sms.send` jobs. `python -m payamakyar.api worker` consumes them. In Phase 1 the handler
only logs a masked "would send" line (and leaves the message `pending`); with
`PAYAMAKYAR_ENV=prod` it fails the job so nothing is silently dropped. Real operator dispatch
arrives in a later phase. In dev, read an OTP straight from the table:

```
docker compose -f infra/docker-compose.yml exec postgres \
  psql -U payamakyar -c "select to_mobile, body from system_messages order by created_at desc limit 3"
```

## Troubleshooting

- `MFA_REQUIRED` on admin routes: enable TOTP first (above).
- Client IP shows the proxy address: `PAYAMAKYAR_TRUSTED_PROXIES` does not cover the compose network.
- Blank page behind Caddy: the CSP snippet is stale or missing; rebuild (`make dev` rebuilds images).
