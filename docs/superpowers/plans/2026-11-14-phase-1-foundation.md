# Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A runnable, fully gated repository with the panel's accounts, sign-in, permissions,
audit, job queue and web shell, so phases 2–8 only add features.

**Architecture:** uv workspace with the Python namespace package `payamakyar` (members
`packages/panel-core`, `packages/panel-db`, `apps/panel-api`) and a Next.js static-export SPA in
`apps/panel-web`. PostgreSQL is the source of truth (Alembic migrations, a transactional job
table); Redis holds rate-limit counters only. Tests start throw-away local PostgreSQL 16 and
Redis servers when no URL is given, so `make test` needs no Docker.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2 + pydantic-settings, SQLAlchemy 2 async +
asyncpg, Alembic, redis-py 8, argon2-cffi, pyotp, cryptography (Fernet); pytest, pytest-asyncio,
httpx; ruff, mypy --strict. Node 22, Next.js 16 static export, React 19, TypeScript strict,
Vitest, Testing Library, MSW.

**Spec:** `docs/superpowers/specs/2026-11-14-payamakyar-panel-design.md` (features F1.1–F1.4,
F1.6, F1.8, F8.14, F8.15, F9.20, F13.1, F13.2, F13.5, F13.7 login part, F13.8, F12.1 partial,
web shell for all §9 routes).

## Global Constraints

- Python `>=3.12,<3.13`; Node `>=22 <23`. Pin every dependency range as sms-guard does
  (`pkg>=X,<Y`); lock with `uv lock` and `package-lock.json`.
- Namespace package: no `src/payamakyar/__init__.py` in any member (lint guard).
- Env prefix `PAYAMAKYAR_`; secrets never have defaults outside `PAYAMAKYAR_ENV=dev|test`.
- ruff config and rule set copied from sms-guard's `pyproject.toml` (`select = [E,F,W,I,N,UP,B,A,C4,SIM,RUF,ANN,S]`, same `allowed-confusables`), line length 100; mypy `strict = true`.
- Every API error body: `{"error": {"code": str, "title": str, "detail": str, "source": {"pointer": str} | null}}` with a real HTTP status (spec F10.17).
- Persian, RTL UI; Persian digits with «٬» thousands separator; Jalali dates
  (`Intl.DateTimeFormat('fa-IR-u-ca-persian')`); phone numbers, ids, keys LTR (design-system README).
- Logs never carry passwords, OTP codes, TOTP secrets, API keys or full mobile numbers (F13.8).
- Password policy default: ≥ 8 chars with upper, lower, digit and special (F9.20); min length a setting.
- Commits end with the two attribution lines from the session; branch `claude/project-thread-nwtpjo`.

## Review Focus

1. Mobile numbers typed with Persian/Arabic digits, spaces, `+98`, `0098`, `9…` or `09…` must all
   normalise to one canonical `989xxxxxxxxx` (Task 2 test `test_normalize_mobile_variants`).
2. Two concurrent workers must never claim the same job (Task 5 `test_claim_skip_locked_concurrent`).
3. Wrong password, unknown user and locked user must be indistinguishable to the caller (same
   code `INVALID_CREDENTIALS`, same status 401) except the lockout itself, which says when to retry
   (Task 9 `test_login_errors_indistinguishable`).
4. An OTP code is single use and dies after 5 wrong tries or 120 s (Task 8
   `test_otp_single_use_and_attempts`).
5. Editing or deleting an audit row is detected by `verify_chain` (Task 6
   `test_tamper_detected`).

---

## File structure

```
pyproject.toml  uv.lock  Makefile  .gitignore  .github/workflows/ci.yml
infra/docker-compose.yml  infra/Caddyfile  infra/env/.env.example  apps/panel-api/Dockerfile
packages/panel-core/src/payamakyar/core/{settings.py,phone.py,ids.py,masking.py,logging.py,
    passwords.py,totp.py,crypto.py,national_id.py,gates.py,permissions.py}
packages/panel-core/tests/…
packages/panel-db/src/payamakyar/db/{base.py,engine.py,models/{users.py,auth.py,rbac.py,
    audit.py,settings.py,jobs.py,system_messages.py},jobs.py,audit.py,settings_store.py,
    alembic.ini,alembic/env.py,alembic/versions/0001_foundation.py,testing.py}
packages/panel-db/tests/…
apps/panel-api/src/payamakyar/api/{app.py,__main__.py,cli.py,errors.py,deps.py,csrf.py,
    ratelimit.py,notifier.py,sessions.py,routes/{health.py,auth.py,account.py,admin_rbac.py,
    admin_audit.py}}
apps/panel-api/tests/…
apps/panel-web/{package.json,next.config.ts,tsconfig.json,vitest.config.ts,eslint.config.mjs,
    src/{App.tsx,routes.ts,nav.ts,styles/{tokens.css,bundle.css,app.css},icons/*.svg,
    lib/{format.ts,api.ts,phone.ts},shell/{Shell.tsx,Sidebar.tsx,Topbar.tsx},
    ui/{Button.tsx,TextField.tsx,Alert.tsx,Card.tsx,Toast.tsx,…},
    views/auth/{Login.tsx,Register.tsx,ForgotPassword.tsx},views/user/ProfileSecurity.tsx,
    views/Placeholder.tsx}}
```

---

### Task 1: Repository scaffold and gates

**Files:**
- Create: `pyproject.toml`, `Makefile`, `.gitignore`, `.github/workflows/ci.yml`,
  `packages/panel-core/pyproject.toml`, `packages/panel-db/pyproject.toml`,
  `apps/panel-api/pyproject.toml`, one `README.md` per member,
  `packages/panel-core/tests/test_import.py` (and the same for db, api),
  `tests/test_repo_layout.py`

**Interfaces:**
- Produces: `make install | lint | typecheck | test | test-unit | test-integration | ci |
  web-install | web-lint | web-typecheck | web-test | web-build | web-ci | ci-all | dev | down |
  migrate`. Pytest markers `integration` (needs Postgres/Redis), `ui`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_repo_layout.py
def test_no_namespace_init():
    assert not list(Path(".").glob("*/*/src/payamakyar/__init__.py"))

def test_members_have_readme_and_tests():
    for m in ["packages/panel-core", "packages/panel-db", "apps/panel-api"]:
        assert (Path(m) / "README.md").is_file() and (Path(m) / "tests").is_dir()

# packages/panel-core/tests/test_import.py
def test_import(): import payamakyar.core  # noqa: F401
```

- [ ] **Step 2: Run `uv run pytest tests packages -q`** — Expected: FAIL (no workspace).
- [ ] **Step 3: Write the workspace.** Root `pyproject.toml` mirrors sms-guard's (workspace
  members `packages/*`, `apps/*`, exclude `apps/panel-web`; dev group with ruff 0.17, mypy 2.4,
  pytest 9, pytest-cov 7, pytest-asyncio 1.4, httpx, bandit, pip-audit). Member build backend
  `uv_build` with `module-name = "payamakyar.core"` etc. CI: job `python` on ubuntu-latest with
  `services: postgres:16` and `redis:7`, env `PAYAMAKYAR_TEST_DATABASE_URL`,
  `PAYAMAKYAR_TEST_REDIS_URL`, runs `make install ci`; job `web` runs `make web-ci`. Actions pinned
  by SHA as in sms-guard's workflow.
- [ ] **Step 4: Run `make install && make lint typecheck test`** — Expected: all pass.
- [ ] **Step 5: Commit** `chore: workspace scaffold, gates and CI`.

### Task 2: Core primitives — settings, phone, ids, masking, logging

**Files:**
- Create: `packages/panel-core/src/payamakyar/core/{settings.py,phone.py,ids.py,masking.py,logging.py}`
- Test: `packages/panel-core/tests/{test_settings.py,test_phone.py,test_masking.py}`

**Interfaces:**
- Produces:
  - `class PanelSettings(BaseSettings)` (prefix `PAYAMAKYAR_`): `env: Literal["dev","test","prod"]`,
    `database_url: str`, `redis_url: str`, `secret_key: SecretStr` (Fernet key, required in prod),
    `public_base_url: str`, `csrf_cookie_name="pk_csrf"`, `session_cookie_name="pk_session"`.
    `get_settings()` cached. Session lifetimes are not env settings: they are settings-store keys
    (`session.idle_seconds=1800`, `session.absolute_seconds=43200`, settings store, Task 7).
  - `to_ascii_digits(s: str) -> str` (Persian ۰–۹ and Arabic ٠–٩).
  - `normalize_mobile(raw: str) -> str` returns `"989XXXXXXXXX"`; raises `InvalidMobile`.
  - `format_mobile_local(canon: str) -> str` returns `"09XXXXXXXXX"`.
  - `new_id() -> uuid.UUID` (uuid7 via `uuid.uuid7` if present else time-ordered fallback).
  - `mask_mobile(s) -> "0912***4567"`, `mask_secret(s) -> "****<last4>"`,
    `redact(obj: Any) -> Any` (recursively masks keys matching
    `password|secret|token|otp|code|api_key|authorization` and any mobile-looking value).
  - `configure_logging(level: str) -> None` (JSON lines; a `logging.Filter` that applies `redact`
    to `record.args` and extras).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("raw", ["09123456789", "9123456789", "+989123456789", "00989123456789",
                                 "۰۹۱۲۳۴۵۶۷۸۹", "٠٩١٢٣٤٥٦٧٨٩", " 0912 345 6789 ", "0912-345-6789"])
def test_normalize_mobile_variants(raw): assert normalize_mobile(raw) == "989123456789"

@pytest.mark.parametrize("raw", ["", "0812345678", "091234567", "0912345678901", "abc"])
def test_normalize_mobile_rejects(raw):
    with pytest.raises(InvalidMobile): normalize_mobile(raw)

def test_redact_masks_nested():
    out = redact({"password": "x", "user": {"mobile": "09123456789", "otp": "1234"}})
    assert out == {"password": "****", "user": {"mobile": "0912***6789", "otp": "****"}}

def test_settings_prod_requires_secret(monkeypatch): ...  # env=prod, no secret -> ValidationError
```

- [ ] **Step 2: Run `uv run pytest packages/panel-core -q`** — FAIL (imports).
- [ ] **Step 3: Implement the signatures above.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(core): settings, phone normalisation, ids, masking, logging`.

### Task 3: Core security — passwords, TOTP, secret box, national id, gates

**Files:**
- Create: `packages/panel-core/src/payamakyar/core/{passwords.py,totp.py,crypto.py,national_id.py,gates.py}`
- Test: matching `test_*.py`

**Interfaces:**
- Produces:
  - `password_problems(pw: str, min_length: int = 8) -> list[str]` returning codes from
    `{"TOO_SHORT","NO_UPPER","NO_LOWER","NO_DIGIT","NO_SPECIAL"}` (Persian letters count as
    neither upper nor lower; require Latin upper/lower).
  - `hash_password(pw) -> str`, `verify_password(hash, pw) -> bool`, `needs_rehash(hash) -> bool`
    (argon2id, memory 19456 KiB, iterations 2, parallelism 1 — sms-guard's defaults).
  - `new_totp_secret() -> str`, `totp_uri(secret, account, issuer="Payamakyar") -> str`,
    `verify_totp(secret, code, *, valid_window=1) -> bool`.
  - `class SecretBox(key: bytes)` with `seal(str) -> str`, `open(str) -> str` (Fernet).
  - `is_valid_national_code(code: str) -> bool`, `is_valid_company_id(code: str) -> bool`.
  - `@dataclass Gates(registered, profile_complete, identity_matched, documents_approved)` and
    `Capabilities(can_send, can_buy_line, can_use_service_line_and_links)`;
    `capabilities(g: Gates) -> Capabilities` — send needs identity_matched; buy line needs
    profile_complete and identity_matched; service line/links need documents_approved (F1.4).

- [ ] **Step 1: Failing tests**

```python
def test_password_policy():
    assert password_problems("Ab1!xyzw") == []
    assert set(password_problems("abc")) == {"TOO_SHORT","NO_UPPER","NO_DIGIT","NO_SPECIAL"}
def test_national_code():
    assert is_valid_national_code("0499370899") and not is_valid_national_code("1111111111")
    assert not is_valid_national_code("0499370898")
def test_company_id(): assert is_valid_company_id("10380284790") and not is_valid_company_id("10380284791")
def test_capabilities_ladder(): ...  # each gate unlocks exactly its capability, in order
def test_totp_roundtrip(): s = new_totp_secret(); assert verify_totp(s, pyotp.TOTP(s).now())
```

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** National code: 10 ASCII digits, not all equal;
  `r = sum(int(d[i])*(10-i) for i in range(9)) % 11`; valid iff `d[9] == (r if r < 2 else 11-r)`.
  Company id (11 digits): `k = int(d[9]) + 2`; `s = sum((int(d[i]) + k) * w[i] for i in range(10))`
  with `w = [29,27,23,19,17,29,27,23,19,17]`; `r = s % 11`, `r = 0 if r == 10 else r`; valid iff
  `r == int(d[10])`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(core): password policy, argon2, TOTP, secret box, national id, gates`.

### Task 4: Database foundation and first migration

**Files:**
- Create: `packages/panel-db/src/payamakyar/db/{base.py,engine.py,testing.py,models/*.py,alembic.ini,alembic/env.py,alembic/versions/0001_foundation.py}`
- Create: `packages/panel-db/tests/{conftest.py,test_migrations.py,test_models.py}`

**Interfaces:**
- Produces:
  - `create_engine(url: str) -> AsyncEngine`, `session_factory(engine) -> async_sessionmaker`,
    `class Base(DeclarativeBase)` with naming convention.
  - Models (tables): `users` (id uuid pk, kind `person|company`, username unique citext,
    mobile unique, email, password_hash, status `active|inactive`, send_blocked bool,
    document_blocked bool, identity_state `none|pending|matched|mismatch|manual_review`,
    documents_state `none|pending|approved|rejected`, first_name, last_name, national_code,
    birth_date, company_name, company_national_id, economic_code, ceo_name, ceo_national_code,
    phone, postal_code, address, parent_id fk users nullable, expires_at, mfa_method
    `none|totp|sms`, totp_secret_sealed, login_notice bool, allowed_ips cidr[] , login_hours
    jsonb `[{"days":[0-6],"from":"08:00","to":"18:00"}]`, failed_logins int, locked_until,
    last_login_at, created_at, updated_at);
    `sessions` (id, user_id, token_hash unique, csrf_hash, ip inet, user_agent, created_at,
    last_seen_at, expires_at, revoked_at, impersonator_id nullable);
    `otp_challenges` (id, purpose `register|login|reset|mobile_change`, mobile, user_id null,
    code_hash, attempts, max_attempts=5, expires_at, consumed_at, created_ip);
    `login_events` (id, user_id null, username_tried, ip, user_agent, outcome, at);
    `permissions` (code pk, title_fa, group), `roles` (id, name unique, title_fa, is_staff,
    is_sale_package bool, price numeric null), `role_permissions`, `user_roles`;
    `audit_events` (id bigserial, at, actor_id, actor_ip, action, target_type, target_id,
    before jsonb, after jsonb, reason, prev_hash, hash);
    `settings` (key pk, value jsonb, updated_by, updated_at);
    `system_messages` (id, to_mobile, template_key, body, status `pending|sent|failed`,
    created_at, sent_at);
    `jobs` (id, kind, payload jsonb, dedupe_key unique null, state
    `ready|running|done|dead`, run_at, attempts, max_attempts, lease_until, last_error,
    created_at, updated_at; index on (state, run_at)).
  - `payamakyar.db.testing`: pytest fixtures `pg_url` (session scope: uses
    `PAYAMAKYAR_TEST_DATABASE_URL` or runs `initdb`/`pg_ctl` from `/usr/lib/postgresql/16/bin`
    (or `pg_config --bindir`) on a temp dir and free port), `db_session` (fresh database per test
    module, migrated to head), `redis_url` (env or temp `redis-server --port <free> --save ""`).
  - CLI used by `make migrate`: `python -m payamakyar.db upgrade|downgrade <rev>`.

- [ ] **Step 1: Failing tests** — `test_upgrade_and_downgrade_clean` (upgrade head on an empty
  DB, assert all 12 tables exist; downgrade base leaves none); `test_username_case_insensitive_unique`.
- [ ] **Step 2: Run `uv run pytest packages/panel-db -q`** — FAIL.
- [ ] **Step 3: Implement models and migration 0001** (enable `citext`; enums as `text` + CHECK).
  Seed nothing here (permissions are seeded in Task 11's migration).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(db): engine, models and foundation migration`.

### Task 5: Transactional job queue

**Files:**
- Create: `packages/panel-db/src/payamakyar/db/jobs.py`; Test: `packages/panel-db/tests/test_jobs.py`

**Interfaces:**
- Produces:
  - `async def enqueue(s: AsyncSession, kind: str, payload: dict, *, run_at: datetime | None = None, dedupe_key: str | None = None, max_attempts: int = 8) -> UUID | None` (returns None on dedupe hit; never commits — caller's transaction).
  - `async def claim(s, kinds: Sequence[str], *, limit: int, lease_seconds: int) -> list[Job]`
    (`FOR UPDATE SKIP LOCKED`, sets running + lease; also reclaims rows whose lease expired).
  - `async def complete(s, job_id) -> None`, `async def fail(s, job_id, error: str, *, retry_schedule: Sequence[float] = (1,5,30,120,600,1800,3600,7200), jitter: float = 0.1) -> None`
    (→ ready with backoff, or `dead` after max_attempts).
  - `class Worker(kinds, handler: Callable[[AsyncSession, Job], Awaitable[None]], *, concurrency, poll_interval)` with `run_once() -> int` and `run_forever()`.

- [ ] **Step 1: Failing tests** — `test_enqueue_dedupe`, `test_claim_skip_locked_concurrent`
  (two sessions claim with limit 10 over 10 jobs: disjoint sets, union = 10),
  `test_expired_lease_reclaimed`, `test_fail_backoff_then_dead`, `test_enqueue_rolls_back_with_caller`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(db): transactional job queue with leases and dead letters`.

### Task 6: Append-only audit with hash chain

**Files:**
- Create: `packages/panel-db/src/payamakyar/db/audit.py`; migration `0002_audit_guard.py`
  (trigger that raises on UPDATE/DELETE of `audit_events`); Test: `test_audit.py`

**Interfaces:**
- Produces: `async def record(s, *, actor_id: UUID | None, actor_ip: str | None, action: str, target_type: str, target_id: str | None, before: dict | None = None, after: dict | None = None, reason: str | None = None) -> int`
  (takes `pg_advisory_xact_lock(7701)`, `hash = sha256(prev_hash + canonical_json(row))`, values
  passed through `redact`); `async def verify_chain(s, *, since_id: int = 0) -> int | None`
  (first bad id or None).

- [ ] **Step 1: Failing tests** — `test_chain_links`, `test_update_rejected_by_trigger`,
  `test_tamper_detected` (disable trigger as superuser in the test, alter a row, expect that id),
  `test_secrets_redacted_in_after`.
- [ ] **Steps 2–4: Run FAIL → implement → PASS.**
- [ ] **Step 5: Commit** `feat(db): hash-chained append-only audit log`.

### Task 7: API skeleton — app factory, errors, CSRF, rate limit, notifier, settings store

**Files:**
- Create: `apps/panel-api/src/payamakyar/api/{app.py,__main__.py,errors.py,deps.py,csrf.py,ratelimit.py,notifier.py,routes/health.py}`,
  `packages/panel-db/src/payamakyar/db/settings_store.py`
- Test: `apps/panel-api/tests/{conftest.py,test_health.py,test_errors.py,test_ratelimit.py,test_settings_store.py}`

**Interfaces:**
- Produces:
  - `create_app(settings: PanelSettings | None = None) -> FastAPI`; routers mounted under
    `/panel/web/v1` (session cookie API) and `/panel/admin/v1`; `GET /panel/health` → `{"status":"ok"}`.
  - `class ApiError(Exception)(status: int, code: str, title: str, detail: str = "", pointer: str | None = None)`; handlers map `RequestValidationError` to 422 `VALIDATION_FAILED` with `source.pointer` = JSON pointer of the first bad field.
  - `RateLimiter(redis).hit(key: str, limit: int, window_s: int) -> RateResult(allowed, retry_after)`; on exceed the dependency raises 429 `RATE_LIMITED` with `Retry-After`.
  - CSRF: double-submit — cookie `pk_csrf` (not HttpOnly) must equal header `X-CSRF-Token` on
    every non-GET under `/panel/web/v1` and `/panel/admin/v1` except `auth/login`,
    `auth/register/*`, `auth/reset/*`; failure 403 `CSRF_FAILED`.
  - `class SystemNotifier(Protocol): async def send_sms(self, s, to_mobile: str, template_key: str, params: dict[str, str]) -> None`;
    `OutboxNotifier` renders `settings["system_sms.<key>"]` (defaults below) and inserts
    `system_messages` + enqueues job `system_sms.send` (phase 2 delivers it through the pipeline).
    Default templates (Persian, fixed copy):
    `otp`: «کد تأیید پیامک‌یار: {code}\nاین کد را به کسی ندهید.»;
    `login_notice`: «ورود به حساب پیامک‌یار شما در {time} از نشانی {ip} انجام شد.»;
    `password_changed`: «رمز عبور حساب پیامک‌یار شما تغییر کرد.».
  - `SettingsStore`: `get(key, default)`, `set(key, value, actor_id, reason)` (writes audit),
    defaults registry `DEFAULTS: dict[str, Any]` containing at least
    `auth.max_failed_tries=5`, `auth.lockout_seconds=900`, `auth.password_min_length=8`,
    `auth.login_rate_per_ip_per_min=20`, `otp.ttl_seconds=120`, `otp.max_attempts=5`,
    `otp.resend_seconds=60`, `system_sms.*` above.

- [ ] **Step 1: Failing tests** — health 200; unknown route returns the error envelope;
  validation pointer `/mobile`; 21st hit in a minute → 429 with `Retry-After`; CSRF missing → 403;
  settings default then override then audit row exists.
- [ ] **Steps 2–4.** **Step 5: Commit** `feat(api): app skeleton, error envelope, CSRF, rate limit, notifier, settings`.

### Task 8: Registration with mobile OTP

**Files:**
- Create: `apps/panel-api/src/payamakyar/api/{otp.py,routes/auth.py}` (register part); Test: `test_register.py`, `test_otp.py`

**Interfaces:**
- Consumes: `normalize_mobile`, `password_problems`, `hash_password`, `OutboxNotifier`, `RateLimiter`, `audit.record`.
- Produces:
  - `otp.issue(s, purpose, mobile, user_id=None, ip) -> (challenge_id, code)` (6 digits,
    `secrets.randbelow`, stores sha256(code+challenge_id)); `otp.check(s, challenge_id, code, purpose) -> OtpChallenge` raising `ApiError(400,"OTP_INVALID")`, `("OTP_EXPIRED")`, `("OTP_TOO_MANY_ATTEMPTS")`.
  - `POST /panel/web/v1/auth/register/start` `{mobile, kind}` → 202 `{challenge_id, resend_after}`; 409 `MOBILE_TAKEN`; per-mobile resend limit `otp.resend_seconds`.
  - `POST /panel/web/v1/auth/register/complete` `{challenge_id, code, username, password, first_name, last_name | company_name, email?}` → 201 `{user_id}` and a session (same cookies as login); new user gets role `customer`, status active, identity_state none; 422 `PASSWORD_WEAK` with `detail` listing problem codes; 409 `USERNAME_TAKEN`.

- [ ] **Step 1: Failing tests** — happy path creates user + session cookie + audit `user.register`;
  `test_otp_single_use_and_attempts`; expired code after 121 s (freeze clock via injectable
  `clock` dependency); weak password; duplicate mobile; the OTP text never appears in logs
  (caplog).
- [ ] **Steps 2–4.** **Step 5: Commit** `feat(api): registration with mobile OTP`.

### Task 9: Login, second factor, sessions, lockout, IP and hours restriction

**Files:**
- Create: `apps/panel-api/src/payamakyar/api/sessions.py`; extend `routes/auth.py`; Test: `test_login.py`, `test_sessions.py`

**Interfaces:**
- Produces:
  - `POST /auth/login` `{username, password}` (username may also be the mobile) →
    200 `{status:"ok", user}` + cookies; or 200 `{status:"mfa_required", method:"totp"|"sms", mfa_token}`;
    401 `INVALID_CREDENTIALS`; 423 `ACCOUNT_LOCKED` with `detail` = ISO time it unlocks;
    403 `LOGIN_IP_NOT_ALLOWED`, 403 `LOGIN_OUTSIDE_HOURS`, 403 `ACCOUNT_INACTIVE`, 403 `ACCOUNT_EXPIRED`.
  - `POST /auth/mfa/sms/send {mfa_token}` → 202; `POST /auth/mfa/confirm {mfa_token, code}` → 200 + cookies.
  - `POST /auth/logout`; `GET /account/sessions`; `DELETE /account/sessions/{id}`.
  - `sessions.create(s, user, ip, ua, impersonator_id=None) -> (token, csrf)`; `sessions.resolve(s, token) -> Session | None` (idle and absolute expiry, touch at most every 60 s).
  - `deps.current_user` (401 `NOT_AUTHENTICATED`), `deps.current_session`.
  - Rules: failed_logins ≥ `auth.max_failed_tries` → `locked_until = now + auth.lockout_seconds`
    (doubling per further lock up to 86400); per-IP limit `auth.login_rate_per_ip_per_min`;
    `login_events` row for every attempt; login notice SMS when `login_notice`; `last_login_at`;
    `mfa_token` is a sealed `{user_id, exp: now+300}`.

- [ ] **Step 1: Failing tests** — `test_login_errors_indistinguishable`; lockout after 5 and
  the 6th correct password still 423; TOTP flow; SMS flow; allowed_ips `10.0.0.0/8` blocks
  `192.168.1.1` (client IP from `request.client.host`; trusted proxies list setting
  `PAYAMAKYAR_TRUSTED_PROXIES`); login_hours Saturday 08–18 Tehran time blocks Friday 20:00;
  idle expiry; revoke a session; login notice written to `system_messages` with masked log.
- [ ] **Steps 2–4.** **Step 5: Commit** `feat(api): login, MFA, sessions, lockout, IP and hours`.

### Task 10: Password reset and account security settings

**Files:**
- Extend: `routes/auth.py`; create `routes/account.py`; Test: `test_reset.py`, `test_account_security.py`

**Interfaces:**
- Produces:
  - `POST /auth/reset/start {mobile}` → always 202 (no user enumeration);
    `POST /auth/reset/complete {challenge_id, code, new_password}` → 204; revokes all sessions;
    SMS `password_changed`.
  - `POST /account/password {current_password, new_password}` → 204.
  - `POST /account/mfa/totp/setup` → `{secret, otpauth_uri}`; `POST /account/mfa/totp/enable {code}`;
    `POST /account/mfa/sms/enable`; `POST /account/mfa/disable {password}`.
  - `PUT /account/security {login_notice, allowed_ips: list[str], login_hours: list[LoginWindow]}` (validates CIDRs; an empty list = no restriction; refuses a list that excludes the caller's current IP with 422 `WOULD_LOCK_YOU_OUT`).
  - All write audit rows.

- [ ] **Steps 1–4** (tests: reset for unknown mobile is 202 and sends nothing; reset revokes
  sessions; TOTP enable needs a valid code; lockout-yourself guard).
- [ ] **Step 5: Commit** `feat(api): password reset and account security settings`.

### Task 11: Permission matrix and staff roles

**Files:**
- Create: `packages/panel-core/src/payamakyar/core/permissions.py`, migration `0003_rbac_seed.py`,
  `apps/panel-api/src/payamakyar/api/routes/admin_rbac.py`; Test: `test_rbac.py`

**Interfaces:**
- Produces:
  - `PERMISSIONS: tuple[Permission, ...]` where `Permission(code, title_fa, group)`; the full
    catalog of named services used by all phases (codes, groups): users.view, users.edit,
    users.impersonate, users.credit.adjust, kyc.review, documents.catalog, patterns.review,
    moderation.review, line_orders.review, lines.manage, upstreams.manage, routes.manage,
    pricing.manage, finance.view, finance.receipts.approve, finance.refund, tickets.view,
    tickets.reply, system_sms.manage, announcements.manage, roles.manage, audit.view,
    settings.manage, guard_policy.manage, traffic.view, traffic.kill_switch, resellers.manage,
    content_filter.manage, number_bank.manage; customer-side: send.single, send.bulk,
    send.pattern, contacts.manage, templates.manage, inbox.view, rules.manage, api.manage,
    wallet.pay, tickets.create, resellers.subusers.
  - Seeded roles: `customer`, `reseller`, `staff_moderation`, `staff_finance`, `staff_support`,
    `admin` (all permissions).
  - `deps.require(*codes: str)` → 403 `FORBIDDEN`; staff routes also require `mfa_method != none`
    → 403 `MFA_REQUIRED`.
  - Admin API: `GET/POST/PUT/DELETE /panel/admin/v1/roles`, `PUT /panel/admin/v1/users/{id}/roles`,
    `GET /panel/admin/v1/permissions` — each change audited with before/after.

- [ ] **Steps 1–4** (tests: customer gets 403 on admin route; admin without MFA gets
  `MFA_REQUIRED`; role edit audit row has before/after; seed contains every code above).
- [ ] **Step 5: Commit** `feat: permission matrix, staff roles and RBAC admin API`.

### Task 12: Profile, account gates and audit viewer

**Files:**
- Extend `routes/account.py`; create `routes/admin_audit.py`; Test: `test_profile.py`, `test_admin_audit.py`

**Interfaces:**
- Produces:
  - `GET /account/me` → user fields + `gates` + `capabilities` (Task 3 types) + roles + permissions.
  - `PUT /account/profile` — person: first/last name, national_code (checksum), birth_date
    (ISO `YYYY-MM-DD` only; the web converts from Jalali), email, phone, postal_code (10 digits),
    address; company: company_name, company_national_id (checksum), economic_code, ceo_name,
    ceo_national_code. Changing national_code/birth_date resets identity_state to `none`.
    `profile_complete` = all required fields of the kind present and valid.
  - `GET /panel/admin/v1/audit?actor&action&target_type&from&to&cursor` (cursor paging, 50/page),
    `GET /panel/admin/v1/audit/verify` → `{ok, first_bad_id}`; `GET /panel/admin/v1/login-events`.

- [ ] **Steps 1–4** (tests: invalid national code → 422 pointer `/national_code`; gates flip
  to profile_complete; audit filter and cursor; non-staff 403).
- [ ] **Step 5: Commit** `feat(api): profile, account gates and audit viewer`.

### Task 13: Web app scaffold, design system and shell with every route

**Files:**
- Create: `apps/panel-web/**` per file structure; copy `/mnt/project-files/ui-kit/design-system/tokens.css`,
  `components/bundle.css` and `assets/Icons/*.svg` into `src/styles` and `src/icons` (read the
  design-system `README.md` and each component `README.md` first).
- Test: `src/lib/format.test.ts`, `src/nav.test.ts`, `src/shell/Shell.test.tsx`

**Interfaces:**
- Produces:
  - `faDigits(n: number | string) -> string`, `faNumber(n) -> string` («۱٬۲۴۰»),
    `jalaliDate(d: Date | string) -> string` («۱۴۰۵/۰۸/۲۱»), `jalaliDateTime`, `money(rials, unit="ریال"|"تومان")`.
  - `api<T>(method, path, body?) -> Promise<T>` that sends `X-CSRF-Token` from the `pk_csrf`
    cookie, parses the error envelope into `ApiError {status, code, title, detail, pointer}`.
  - `ROUTES` and `NAV` exactly as the prototype's `NAV` object (user and admin sections, labels,
    icons) plus `auth-login`, `auth-register`, `auth-forgot`; hash routing `#u-dashboard`.
  - `<Shell role="user"|"admin">` with right-hand sidebar, topbar with credit pill placeholder,
    theme toggle (`data-theme` on `<html>`), mobile drawer; every route not yet built renders
    `<Placeholder route=…/>` showing the screen title.
  - React wrappers for the design system classes: `Button, TextField, Select, Alert, Card,
    Badge, Toast, Modal, Tabs, Table, Pagination, EmptyState, Skeleton, Stepper` (class names from
    `bundle.css`, no restyling).

- [ ] **Step 1: Failing tests** — `faNumber(1240) === "۱٬۲۴۰"`; `jalaliDate("2026-11-12") === "۱۴۰۵/۰۸/۲۱"`;
  NAV has 24 user routes + 18 admin routes and every `ROUTES` key renders without throwing;
  `<html dir="rtl" lang="fa">`.
- [ ] **Step 2: Run `npm test`** — FAIL. **Step 3: Implement.** **Step 4: `make web-ci`** — PASS
  (lint, typecheck, test, build produces `apps/panel-web/dist/index.html`).
- [ ] **Step 5: Commit** `feat(web): app scaffold, design system and shell`.

### Task 14: Auth and security screens

**Files:**
- Create: `src/views/auth/{Login.tsx,Register.tsx,ForgotPassword.tsx}`, `src/views/user/ProfileSecurity.tsx`, tests next to each; `src/test/msw.ts`

**Interfaces:**
- Consumes: Task 8–10 endpoints, Task 13 `api`, UI wrappers.
- Produces: screens matching the prototype's `auth-login` and `auth-register` (person/company
  toggle, mobile step, OTP step with resend countdown, username/password step showing policy
  problems in Persian), forgot-password flow, MFA step (TOTP code or SMS code), and the security
  part of `u-profile` (change password, enable TOTP with QR from `otpauth_uri` using
  `qrcode-generator`, SMS 2FA, login notice, allowed IPs, login hours, sessions list with revoke).
  Error copy per code, e.g. `INVALID_CREDENTIALS` → «نام کاربری یا رمز عبور درست نیست.»,
  `ACCOUNT_LOCKED` → «حساب شما تا {time} قفل است؛ پس از آن دوباره تلاش کنید.»,
  `OTP_INVALID` → «کد واردشده درست نیست.», `PASSWORD_WEAK` lists each problem
  (`TOO_SHORT` «دست‌کم ۸ نویسه», `NO_UPPER` «یک حرف بزرگ لاتین», `NO_LOWER` «یک حرف کوچک لاتین»,
  `NO_DIGIT` «یک رقم», `NO_SPECIAL` «یک نویسهٔ ویژه مانند ! یا @»).

- [ ] **Steps 1–4** (Vitest + MSW: login ok → navigates `#u-dashboard`; mfa_required → code
  step; locked shows time in Jalali; register three steps; resend disabled until countdown ends).
- [ ] **Step 5: Commit** `feat(web): auth and account security screens`.

### Task 15: Compose stack, migrations command and end-to-end smoke

**Files:**
- Create: `infra/docker-compose.yml` (postgres:16, redis:7, api, caddy serving
  `apps/panel-web/dist` and proxying `/panel/*` to api), `infra/Caddyfile` (CSP, HSTS,
  `X-Content-Type-Options`, `Referrer-Policy`), `infra/env/.env.example`, `apps/panel-api/Dockerfile`,
  `tests/e2e/test_smoke.py` (marker `integration`), `docs/runbooks/dev.md`, update root `README.md`.

**Interfaces:**
- Produces: `make dev` (compose up), `make migrate`, `python -m payamakyar.api serve`,
  `python -m payamakyar.api create-admin --username --mobile` (prints a one-time password).

- [ ] **Step 1: Failing test** — `test_smoke` against `create_app` with real Postgres/Redis:
  register (OTP read from `system_messages` via a test-only helper) → login → `/account/me`
  → create admin via CLI function → admin enables TOTP → admin lists audit and sees the
  `user.register` event.
- [ ] **Steps 2–4.** `make ci && make web-ci` — all green.
- [ ] **Step 5: Commit** `chore(infra): compose stack, admin bootstrap and smoke test`.

---

## Phases after this plan

Phases 2–8 of the spec each get their own plan file in `docs/superpowers/plans/`, written when the
previous phase merges, and each ends with the §8 ids it covers checked off in
`docs/feature-checklist.md` (created in Task 15 with every id from spec §8, all unchecked except
those this phase completes).
