# Phase 1 — decisions and deferred items

Record of the rulings made while building Phase 1 (foundation) and the review findings deferred to later phases. Later phase plans must read this file.

## Rulings

- T4 migration test asserts the 12 tables listed in the task (+alembic_version), not "14" — the count was a typo — cost if wrong: none.
- T8 needs a session on register/complete before T9 exists; T8 creates `sessions.py` with `create`/`resolve` minimal per T9's Interfaces, T9 extends it — cost: small rework.
- keep push trigger on claude/** so the dev branch gets CI before a PR exists — cost: duplicate runs)
- T2 finding 5 (plan-mandated `code` substring) — match whole key segments (split on _ - and camelCase); bare `code` masked only when its value is a 4–10 digit string (OTP-like), compounds otp_code/verification_code/mfa_code always — spec requires error.code visible and OTPs hidden — cost if wrong: an odd key leaks or is over-masked.
- fold T2 minor 9 (strip U+200C/U+200E/U+200F) into fix round 1 — Review Focus 1 (pasted Persian numbers) — cost: none.
- carry into Task 8/9: max password length 128 at API layer (PASSWORD_TOO_LONG via validation) and TOTP replay protection (store last used time-step per user) in login MFA — security, reviewer-flagged — cost: small.
- accepted, brief signature omitted it — cost none)
- T9 adds auth/mfa/* to CSRF exemption — no pk_csrf before a session exists; mfa_token (sealed) authenticates instead — cost if wrong: login-CSRF on mfa confirm (low; token is secret).
- session idle/absolute move to settings keys session.idle_seconds 1800 / session.absolute_seconds 43200 in T9 — cost: none.
- T9 minor 1 (403 after correct password confirms password from restricted IP/hours) — keep order: checking restrictions before password would reveal account existence and the lockout throttles guessing — cost if wrong: password confirmable from a disallowed IP, bounded by lockout.
- removed — settings store is the single source).
- pending TOTP secret in Redis TTL 600 preferred over migration; WOULD_LOCK_YOU_OUT also for login_hours excluding now.
- T10 finding 2 (plan-mandated) — totp/enable and sms/enable require {password} (always) via _reauthenticate and send an mfa_changed SMS notice on enable/disable — spec's account-security intent outranks the brief's body listing; swapping a factor is as sensitive as disabling — cost if wrong: one extra field in the web form.
- T10 reset for inactive/expired users follows the unknown-mobile path (nothing sent) — login refuses them anyway — cost: support must reactivate first.
- seed role→permission mapping chosen by controller (see dispatch); system roles undeletable; last-admin and self roles.manage guard.
- exact pins + lockfile accepted, stricter); asset paths assume root (Task 15 Caddy serves at /).
- add minimal auth guard now in T14 round 1 — u-*/a-* routes check GET /account/me and redirect to #auth-login on 401 — the app is unusable without it and no later Phase 1 task owns it — cost: small.
- server OTP_RESEND_TOO_SOON detail uses Latin digits → fix server copy to Persian digits in T14 round 1 — global constraint — cost: none.
- move inline theme script to static file for CSP script-src 'self'; dev worker with masked log handler for system_sms.send in Phase 1.
- F1.1, F1.2, F13.1, F1.6 unticked as partial (SMS dispatch is Phase 2; profile identity UI pending) — honest checklist — cost: none.
- admin gate requires a session that passed the second factor (sessions.mfa_at via migration 0004, set in mfa_confirm/TOTP-login; enabling MFA marks nothing) — staff access must be proven per session — cost: staff must re-login after enabling TOTP.
- PUT /account/security requires {password} via _reauthenticate and sends an SMS notice (new security_changed template) — same sensitivity as MFA change — cost: one more field in the form.
- account enumeration — accept register/start MOBILE_TAKEN (plan contract, per-IP throttled) and login 423 for Phase 1; revisit in Phase 2 (always-202 start, report taken after OTP) — cost if wrong: registered-number probing at 10/h/IP.
- account kind vocabulary unified to person|company across API and web (register/start accepts "person"; "individual" kept as accepted alias for one phase) — cost: none.
- API image defaults PAYAMAKYAR_ENV=prod; dev compose sets dev explicitly — fail safe if ENV forgotten — cost: none.

## Deferred review findings (by task)

- Task 2: minor (deferred): free-text mobile masking only with prefix (document+test separators); JsonFormatter field overwrite; is_secret_key helper; settings empty-string/positive validation & URL in errors; mask_secret short secrets; new_id rollover test; settings failure match=.
- Task 2: minor (deferred): blunt plural stripping (status->statu)
- Task 3: minor (deferred): totp _SEP literal invisibles; SecretBox.open non-str; inline import in test; capabilities docstring re registered
- Task 4: minor (deferred): redis_url fixture yields without readiness check -> fold in round 1; make_url for DB URL -> fold; fixed migration test DB name -> fold; fileConfig dead; citext downgrade comment; weak test asserts in test_models; CLI untested
- Task 5: minor (deferred): dedupe_key permanence doc; detached rows comment — folded into round 1 with 6,7,8
- Task 5: minor (deferred): TimeoutError label; lease<=10 floor; concurrent test lost state asserts
- Task 6: minor (deferred): tail deletion undetectable (document; external head anchoring in phase 6)
- Task 7: minor (deferred): non-field error pointer for body/query locs (e.g. /7) — decide in final review; fixed-window 2x boundary burst — document.
- Task 7: minor (deferred): get_route_path imported from private starlette._utils (no Starlette pin) — add comment/root_path test; notifier traversal test passes payload as value not template.
- Task 8: minor (deferred): kind in Redis (OTP_EXPIRED if evicted) — consider column; otp.check commits caller session (hazard for T9+); sessions idle_seconds hardcoded + resolve ignores user status (T9); otp.ttl read twice. Trailer Sonnet line accepted (earlier ruling).
- Task 9: minor (deferred): 423 reveals account existence (brief contract) — option: track unknown-username failures in Redis.
- Task 9: minor (deferred): mfa jti consumed before session creation (failure burns token, fail-closed); plan line 128 still lists removed PanelSettings session_* fields (Ruling: removed — settings store is the single source).
- Task 10: minor (deferred): decoy tests don't assert no jobs/audit rows survive; ::ffff: CIDR entries no longer match; decoy takes audit lock 7701; same-password change allowed; wrong code on real challenge writes attempt count (timing).
- Task 11: minor (deferred): roles.manage-only delegate cannot assign customer (customer perms not subset) — product decision; effective_route_contexts internal in gate test.
- Task 11: minor (deferred): set_user_roles locks admin row twice (no-op).
- Task 12: minor (deferred): Phase 6 must verify provider result matches current identity values; company identity-match fields to decide in Phase 6 plan; /audit/verify full scan; is_complete presence-only.
- Task 12: minor (deferred): username_tried masked only when whole value is a mobile; dead mapping in test_company_identity_reset.
- Task 13: minor (deferred): admin bell → #u-notifications (prototype); exact npm pins vs range wording (Ruling: exact pins + lockfile accepted, stricter); asset paths assume root (Task 15 Caddy serves at /).
- Task 13: minor (deferred): money doc comment rounding wording; drawer close via link/scrim leaves focus on hidden link; restoreTheme dead code.
- Task 14: minor (deferred): terms checkbox and +98 addon from prototype; toast timers cleanup.
- Task 14: minor (deferred): CUSTOMER_SIDE hard-coded in web session.ts (expose is_staff from /account/me later); guard doesn't recheck /me on session expiry with cached success.
- Task 15: minor (deferred): base images floating tags (Phase 8 prod compose pins digests); API Dockerfile layer cache.
- Task 15: minor (deferred): dev DB password check not percent-decoded; make down needs infra/.env.
- Final fix wave: no test that turning off only login_notice sends security_changed; logout 401 may leave a stale return route.

## Triage target (from the final whole-branch review)

- Phase 2 (system SMS dispatch, send pipeline, API keys): T2 log/masking helpers, T5 worker nits, T7 starlette._utils import + fixed-window burst docs, T8 kind-in-Redis / otp.check commit hazard, T9 jti order + 423 existence (see enumeration ruling), T10 decoy/timing nits and ::ffff: CIDRs, T12 username_tried masking.
- Phase 6 (identity/KYC/audit hardening): T12 provider result vs current identity, company identity fields, /audit/verify full scan, is_complete presence-only; T6 audit tail anchoring; T11 delegate vs customer role.
- Phase 7 / UI polish: T13 drawer focus, admin bell, money doc, dead restoreTheme; T14 terms checkbox, +98 addon, toast timers, CUSTOMER_SIDE duplication (expose is_staff from /account/me); T3/T4/T2 test and doc nits.
- Phase 8 (production deployment): T15 image digests, Dockerfile layer cache, percent-decoded dev-password check, make down needs infra/.env; run the compose stack once on a Docker host.
