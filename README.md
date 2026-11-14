# sms-panel — پیامک‌یار

Customer-facing SMS panel («پیامک‌یار») that sends only after a final `ALLOW` from
[sms-guard](https://github.com/scheafersusan-stack/sms-guard). Work in progress; the design lives on
the development branch under `docs/superpowers/specs/`.

Phase 1 (foundation) delivers the uv workspace, database schema and migrations, registration, login
with TOTP/SMS second factor, sessions, password reset, profile, the permission matrix, the audit
log, the web shell with auth screens, and the compose stack. See `docs/feature-checklist.md` for
what is done per spec feature id.

## Quick start

```
make install && make ci        # python gates
make web-ci                    # web gates
cp infra/env/.env.example infra/.env   # dev-only settings; compose refuses to start without them
make dev                       # full stack in Docker: https://localhost:8443
make create-admin USERNAME=ali MOBILE=09121234567
```

| Command | What it does |
|---|---|
| `make migrate` | `alembic upgrade head` on `PAYAMAKYAR_DATABASE_URL` |
| `python -m payamakyar.api serve` | run the API |
| `python -m payamakyar.api worker` | run the job worker (system SMS) |
| `python -m payamakyar.api create-admin --username U --mobile M` | create an admin, print a one-time password |

Layout: `packages/panel-core` (domain helpers), `packages/panel-db` (models, migrations, jobs),
`apps/panel-api` (FastAPI), `apps/panel-web` (Next static export), `infra/` (compose, Caddy,
env example), `tests/e2e` (smoke). More in `docs/runbooks/dev.md`.
