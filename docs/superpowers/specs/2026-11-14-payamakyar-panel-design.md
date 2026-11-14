# Payamakyar SMS panel — design

Date: 2026-11-14. Repository `scheafersusan-stack/sms-panel` (new, empty). Status: draft for the owner's approval.

## Intent and why

The owner wants the whole customer-facing SMS panel, «پیامک‌یار», built end to end, with
**no feature left out**. It is the product that sits in front of sms-guard: customers (and
resellers and their sub-users) send SMS through it, and the platform's staff run it from an admin
back office. Its defining property is the one sms-guard already enforces on its side: **nothing
reaches an operator (upstream line owner) without a final `ALLOW` from sms-guard**. Rejected
messages are shown to the customer with the reason, and their reserved credit comes back.

Two earlier outputs in this project define "everything":

- the clickable prototype `/mnt/project-files/ui-kit/payamakyar-prototype.html` (44 screens: 24
  customer, 18 admin, 2 auth; listed in §9) and its design system
  `/mnt/project-files/ui-kit/design-system/` (tokens, `bundle.css`, 31 components, 36 icons);
- the requirements inventory «نیازمندی‌های ساخت پنل پیامکی» (research thread, 14 sections,
  ~120 features with sources). Every row of it is a line in §8 of this document, with an id.

§8 is the completeness contract: a feature is done only when its id is checked off with a test
and, where it has a screen, the screen works against the real API.

## Goals

- Every screen of the prototype, working against a real backend, Persian and RTL, desktop and
  phone, light and dark, following the design system's content rules (Persian digits, Jalali
  dates, LTR phone numbers and ids, errors that say how to fix them).
- Every feature of the requirements inventory, including those it marked optional (number bank,
  voice, SMPP server, link tracker, polls/contests, white-label domains, SSO).
- Fail-closed holding queue in front of every upstream send, integrated with sms-guard exactly as
  `docs/api/panel-integration-fa.md` and `docs/api/panel-api.yaml` specify (HMAC, idempotency,
  polling with the advised cadence, cancel).
- A money ledger that is append-only and never loses or double-counts a rial: reserve on accept,
  capture on upstream acceptance, refund as a separate row per the line's rules.
- A customer REST API (plus the legacy GET/username-password compatibility forms), signed
  webhooks, and an SMPP 3.4 server for enterprise customers.
- Real connectors for the upstreams, payment gateways and identity check named in the research,
  each paired with a simulator so the whole product runs and is tested without real credentials.

## Non-goals

- Signing contracts with line owners, getting credentials, or deciding prices: those are the
  owner's. The panel stores them as settings.
- Building our own SMSC or carrier link. Upstreams are HTTP/SOAP providers (and optionally an
  SMPP client to one, as a connector).
- Supplying number-bank data (postal code, age/gender, jobs, map areas). The feature is built;
  admins import the data.
- Changing sms-guard itself. The panel is a client of its public panel API only.

## Anti-goals (failure even if it "works")

- Any path — retry, timeout, unknown verdict, scheduled release, OTP/pattern fast path, SMPP,
  admin resend — that sends to an upstream without a final `ALLOW` for that exact content.
- A balance that can be changed without a ledger row, or a refund issued twice.
- Upstream credentials, API keys, OTP codes or full message bodies in logs.
- A screen in the prototype that is a dead mock in the product.

## Constraints

- Lives in its own repository, `sms-panel` (the owner's pick), as a uv workspace plus a Next.js
  app, with its own PostgreSQL database (`payamakyar`) and Redis. It knows sms-guard only as an
  external HTTP service at a configured base URL with an API key, HMAC secret and root CA file.
- Same stack and quality gates as sms-guard, set up from scratch here (sms-guard's Makefile, ruff,
  mypy and CI layout are the model): Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async,
  Alembic, Redis; ruff, mypy `--strict`, pytest with coverage gates; Next.js 16 static export,
  React 19, TypeScript strict, Vitest, Playwright; Makefile targets mirrored in CI.
- Legal/regulatory values that sources disagree on are settings, not constants: opt-out suffix
  («لغو۱۱» vs «لغو۱»), promotional send window (21–8 vs 22–8), Persian/Latin segment sizes per
  line (70/67 vs 66, 160/153), tax (10%) and per-SMS levy (40 vs 30 rial), latin/persian price
  ratio, DLR finality timeout (4 h Asanak, 24 h Jasmin).
- Three message classes are modelled from day one: promotional, service (خدماتی), transactional
  (OTP/pattern) — the September 2026 line-separation directive.

## Approaches considered

1. **Inside the sms-guard repo, as separate apps with a separate database.**
   Reuses the workspace, lint/type/test gates, CI, compose profiles, the dashboard's frontend
   toolchain and the design tokens; the only coupling is the documented HTTP contract. Cost: the
   repo grows; mitigated by keeping every panel member under a `panel-` prefix.
2. **A new repository (chosen by the owner).** Cleanest product separation; every tool and gate
   is set up here from zero, modelled on sms-guard's.
3. **Server-rendered monolith** (FastAPI + templates over the prototype's HTML). Fastest to first
   screen, but the prototype is highly interactive (wizards, live cost, phone preview, charts) and
   it would not share anything with the existing dashboard toolchain.

Pick: 2, by the owner. sms-guard is reached only over its documented panel API.

## Architecture

```
apps/panel-api        FastAPI: web session API (/panel/web/v1), admin API (/panel/admin/v1),
                      customer REST API (/panel/api/v1), legacy compat (/panel/api/send-url…),
                      inbound/DLR/payment callbacks (/panel/hooks/…), white-label host routing
apps/panel-worker     job runners (one process type, roles chosen by env), see "Workers"
apps/panel-smpp       SMPP 3.4 server (asyncio) for enterprise customers; same send pipeline
apps/panel-web        Next.js static export SPA: all 42 screens; served by Caddy
packages/panel-core   pure domain: phone normalisation, operator detection, segment counting,
                      pricing, state machines, ledger rules, rule engine, template rendering
packages/panel-db     SQLAlchemy models, Alembic migrations, session factory, job queue
packages/panel-connectors
                      upstream SMS (simulator, Magfa v2, Kavenegar, Asanak v1+v2, Rahyab 50001,
                      Rahyab 1000, Ghasedak, msgway; optional SMPP client), voice/TTS, Bale OTP,
                      payment (simulator, Zarinpal v4, Zibal, extensible), identity match
                      (simulator, Jibit, Zohal), sms-guard client
```

- **Source of truth is PostgreSQL.** Work is driven by a transactional job table
  (`SELECT … FOR UPDATE SKIP LOCKED`, leases, retry schedule with jitter, dead-letter state),
  written in the same transaction as the state change that causes it (outbox pattern). Redis only
  holds rate-limit buckets, OTP attempt counters, session cache and pub/sub for live screens; losing
  Redis loses no money and no message.
- **Fail-closed holding queue.** A batch moves
  `draft → accepted → prechecks → guard_pending → (guard_review) → approved → scheduled|queued →
  sending → done`; exits `rejected(reason)`, `canceled`, `insufficient_credit`, `failed`. The
  router accepts only batches whose guard state is `ALLOWED` with `decision.final.is_final=true`
  and `verdict=ALLOW` *and* whose content hash equals the hash that was registered. Any other
  value, missing field or unknown enum from sms-guard leaves the batch held.
- **sms-guard integration.** One guard registration per *content unit*: the batch text for
  single/bulk/phonebook sends; each distinct rendered text for peer-to-peer and variable sends
  (deduplicated; recipients counted per unit); a pattern's text at pattern approval time, and
  per-send only when a variable value contains a URL, a phone number or exceeds its type rules.
  Registration uses `Idempotency-Key = panel content unit id`, `account` (customer id, name,
  tier, and `tags` carrying `reseller:<id>` for each ancestor and `class:<message class>`, since
  sms-guard's `Account` accepts no extra fields), `sender.line` and `sender.line_type`
  (`advertising` for promotional, `service`, `transactional`), `recipients.count` and masked
  sample. Texts over sms-guard's 2000-character cap are refused at precheck with a clear error.
  **Approval validity:** a scheduled or recurring send is registered again at release when the
  rendered text differs from the approved one (always for `[R]`-token sends) or when the
  approval is older than a setting (default 24 h); otherwise the existing `ALLOW` is used.
  Poll cadence 5 s, 15 s, then 60 s, honouring `Retry-After`, until a final state. `BLOCK` →
  batch rejected with the guard's reason codes rendered in Persian, reservation released.
  `MANUAL_REVIEW`/`UNDER_REVIEW` → shown as «در حال بررسی». Customer cancel before decision →
  guard cancel. If sms-guard is unreachable the batch waits (and the admin traffic screen says so).
- **Ledger.** `wallet_transaction` is append-only (type, reason, amount, balance after, reference,
  reseller benefit, actor). Balance is a materialised column updated in the same transaction with
  a row lock. Reservation is per batch and across the reseller parent chain
  (`AdminCreditNotEnough`). Capture on upstream acceptance per message; refund rows per the line
  profile: blacklisted always if `return_blacklist`; undelivered only for delivery-based lines;
  upstream-rejected always; guard-rejected and canceled release the reservation.
- **Routing.** A customer line belongs to one upstream (its owner); fallback routes apply only to
  shared lines and pattern/OTP traffic. Route table: ordered rules with user/group/destination
  operator/content/time filters and strategy static, random round-robin, or failover. Three lanes
  (pattern/OTP, service, campaign) with separate queues so campaigns never delay OTP. Campaign
  chunker splits into chunks sized to the upstream's per-request cap and round-robins customers.
- **Delivery reports.** Upstream message ids stored on send; every receipt written first to
  append-only `dlr_event`, then applied forward-only; receipts that arrive before the id is stored
  are parked and retried; a sweeper marks `sent` as `unconfirmed` after the line's finality
  timeout; late receipts can still upgrade. Multipart counts delivered parts.
- **Connector contract.** `send_batch`, `query_status`, `parse_callback`, `fetch_inbound`,
  `balance`, plus declared capabilities (max recipients per call, client reference ids, push
  status, templates, blacklist switch, first-poll delay, finality timeout). Errors are classified
  `retryable`, `account_fatal` (opens a circuit breaker and alerts), `message_fatal`,
  `blacklisted`. Outbound traffic leaves from a configured fixed egress IP.

### Workers (roles of `panel-worker`)

precheck (rules of §8.9 then guard registration), guard-poller, scheduler (due sends, recurring
and occasion sends, re-running prechecks at release), chunker, router, per-upstream sender (rate
limit and batching per connector), dlr-fetcher, dlr-applier, settlement/refund, inbound parser and
rule engine, webhook dispatcher (signed, retries, fallback URL), exporter (Excel/CSV, archive),
importer (Excel/CSV/TXT contacts), payment sweeper, notifier (system SMS, email, in-app,
low-credit alarm once per crossing), expiry jobs (lines, accounts, gifts, packages), number-bank
counter.

### Security

Argon2id passwords (policy: ≥8 with upper, lower, digit, special; configurable), lockout and IP
brute-force throttling, TOTP or SMS second factor, login SMS notice to owner, per-user allowed
IPs and login hours, sessions with idle/absolute timeouts, CSRF on the cookie API. API keys shown
once, stored hashed, several per account with scope and IP allowlist; separate API credentials
from panel login; regenerating revokes. Per-user hourly send cap and anomaly hold (first bulk
send, sudden volume jump, first-seen link). Kill switches per account, line, upstream and message
class with queue-expiry rule. Admin: 2FA required, IP allowlist, permission matrix (named
services, not fixed roles), immutable audit with before/after and reason, visible impersonation,
two-person approval above a manual-credit threshold and for making a line «خدماتی». Evidence
retention per message: account, reseller chain, IP, key id, text, guard decision, approval
history, identity file. Contacts encrypted at rest; exports limited and logged; numbers masked
for support staff. Log masking follows sms-guard's `observability.masking` rules (ported, not imported).

### Frontend

`apps/panel-web` mirrors sms-guard's `apps/dashboard` (Next.js static export + client router, React Query,
openapi-fetch typed from this repo's `docs/api/*.yaml`). It imports the design system's `tokens.css` and
`bundle.css` (copied into the app as the source of truth) and wraps its components as React
components. Routes keep the prototype's names (`u-send`, `a-kyc`, …). White-label domains swap
logo, title, colors tokens and footer at runtime from `/panel/web/v1/brand`.

## Testing

TDD per task (superpowers:test-driven-development). Unit tests for every pure rule in
`panel-core` (segment tables, operator prefixes, pricing formula, ledger invariants, state machine
transitions, rule engine). API tests against an ephemeral Postgres (testcontainers-free: the
compose `postgres` service, as sms-guard's integration suite does; plus a local sms-guard test double that implements its panel API contract). Connector tests against
recorded/fake HTTP servers built from each provider's documented contract. Property tests for the
ledger (no sequence of events changes balance without rows; refunds idempotent). A fail-closed
suite that drives every guard response shape (unknown enum, missing field, interim only, 5xx,
timeout, content hash mismatch) and asserts zero upstream calls. Frontend: Vitest + MSW per
screen; Playwright e2e of the main journeys against the dev stack with the simulators and
sms-guard's own `mock-panel`-style test double; axe accessibility checks.

## Delivery plan (one PR per phase, each green on all gates)

1. Foundation: repository scaffold (uv workspace, Makefile, CI, compose), workspace members, DB schema v1, settings, auth (register, login, 2FA, password
   reset), permissions matrix, audit, web shell + auth screens, compose wiring.
2. Send core: normalisation, segments, operators, tariffs, ledger, lines, sms-guard client and
   holding queue, simulator upstream, router, senders, DLR, quick/bulk/file/phonebook/P2P/variable
   sends, scheduling and cancel, outbox and batch detail, refunds.
3. Contacts and content: phonebooks, custom fields, import/export, stoplist and opt-out replies,
   drafts, patterns and review, OTP/pattern send and verify/check, number bank.
4. Money: wallet, Zarinpal/Zibal/simulator, bank receipts, invoices with tax and levy, packages,
   gifts, tariffs page, low-credit alarm.
5. Two-way and API: customer REST API and legacy forms, API keys, webhooks, inbox, rule engine
   (secretary, keyword secretary, analyser, forwarding, subscriptions, polls/contests/lottery,
   numbering), link shortener and tracker, voice message and voice OTP, flash SMS, Bale/msgway.
6. Admin back office: every admin screen and queue (KYC with identity match, documents catalog,
   patterns, moderation, line orders, users, tickets, traffic and kill switches, upstreams and
   routes, lines, finance, pricing, system SMS and announcements, roles, audit, settings),
   impersonation, two-person approvals; customer tickets and notifications.
7. Resellers: tree, sub-user creation and three locks, limits, credit transfer, sharing, white-
   label domains with their own prices, SSO hand-off, chain reservation.
8. Real connectors (Magfa, Kavenegar, Asanak, Rahyab ×2, Ghasedak), SMPP server, prod compose,
   runbooks, full e2e and the §8 completeness audit.

## What is left to the builder

Table and column names, exact endpoint paths, component file layout, chunk sizes, retry
schedules' exact values (configurable), chart library (none: the prototype's SVG charts are
ported), Jalali date library choice.

## Calls I made (owner can overturn)

- External services get real connectors plus a simulator each; nothing needs real keys to run.
- Online payment and the customer API are in from the start; so are all "optional" rows.
- Number-bank data is admin-imported.
- PostgreSQL job table instead of Redis Streams for panel work (money and holds need
  transactional enqueue; sms-guard's ADR 0001 reasoning does not carry over).
- Guard registration per content unit as described above, including the pattern fast path.
- sms-guard field mapping (`line_type` values, reseller chain and class in `tags`), 2000-char
  refusal and the 24 h approval validity for scheduled sends.
- Provider connectors are built from their public documentation and contract-built fakes; each is
  marked "unverified" until the owner supplies sandbox or live keys and it passes a live smoke test.

## 8. Feature inventory (completeness contract)

Ids are `F<section>.<n>`. Sections follow the requirements inventory. "Screen" names prototype
routes (§9). Phase is the delivery phase above.

### 8.1 Accounts and identity
| Id | Feature | Screen | Phase |
|---|---|---|---|
| F1.1 | Registration (person/company), mobile verification by OTP | auth-register | 1 |
| F1.2 | Login with password; second factor TOTP (ga) or SMS; login notice SMS | auth-login, u-profile | 1 |
| F1.3 | Password reset by SMS/email; password policy | auth-login | 1 |
| F1.4 | Account gates: registered → profile complete → identity matched → documents approved; each gate unlocks send / buy line / service line+links | u-profile, a-kyc | 1, 6 |
| F1.5 | Identity match national code ↔ mobile ↔ birth date (Shahkar via Jibit/Zohal/simulator); service error goes to manual review, not "mismatch" | a-kyc | 6 |
| F1.6 | Person and company fields (national code, company national id, economic code, CEO) | u-profile, a-user | 1 |
| F1.7 | Document upload by type (person: national card, face photo, SIM ownership; company: CEO card, gazette, …), ≤ size limits | u-profile | 6 |
| F1.8 | Allowed IPs and login hours; sessions list and revoke | u-profile | 1 |
| F1.9 | API keys: create (shown once), scope, IP allowlist, revoke, last used; separate webservice credentials and switch | u-api | 5 |

### 8.2 Sending
| Id | Feature | Screen | Phase |
|---|---|---|---|
| F2.1 | Send wizard: sender, text, recipients (Excel, TXT, phonebook, manual/paste), duplicate handling (unique/all/only duplicates), final review with valid/invalid/duplicate counts, cost, language, test send | u-send, u-bulk | 2 |
| F2.2 | Direct vs bulk threshold (configurable, default 10) — bulk waits in moderation when required | u-send, u-bulk, a-moderation | 2 |
| F2.3 | Bulk send with title, draft save, four recipient sources, statuses | u-bulk | 2 |
| F2.4 | Send from file (CSV/XLSX) plus extra recipients | u-bulk | 2 |
| F2.5 | Peer-to-peer from two-column Excel (header skipped, `;` multi-numbers) or manual boxes; allow duplicates option; one batch id per text in API | u-bulk | 2 |
| F2.6 | Variable send: `#1#` ordinal, Excel column names with "add to text", `{ex_B}`/`{ex_<fieldId>}` | u-bulk | 2 |
| F2.7 | Send to phonebook: all with start/size slice, or selected contacts | u-bulk | 2 |
| F2.8 | Scheduling and cancel (until 5 min before; configurable) | u-scheduled | 2 |
| F2.9 | Recurring and occasion sends: once, daily, weekly, monthly (instalment), yearly (birthday) from a phonebook date field; `[R]` days-remaining token; consecutive daily option | u-scheduled | 2 |
| F2.10 | Draft groups (title ≤200, ≤20 groups) and drafts (≤1400 chars, ≤200) | u-templates | 3 |
| F2.11 | Price estimate per recipient operator (mci/other) and parts | u-send, u-bulk | 2 |
| F2.12 | Outbox: text, time, sender, recipient, status, per-recipient delivery icon; resend failed; details and replies; folders; advanced search; soft delete and "deleted"; move; Excel export; print | u-outbox, u-batch | 2 |
| F2.13 | Batch stats: blacklist, failed, pending, sent, delivered by operator and language | u-batch | 2 |
| F2.14 | Send by link (GET with apikey or username/password; alias parameter names) | u-api | 5 |
| F2.15 | Link tracker: short link insertion, per-recipient token, clicks and visits, downloadable report | u-send, u-batch | 5 |
| F2.16 | Voice message: uploaded audio, recipients, retry, pro-forma with duration, operator approval | u-send | 5 |
| F2.17 | Flash SMS (display on screen) | u-send | 5 |
| F2.18 | Batch state machine (IPPanel's 10 states mapped) and per-recipient states (§8.10 model) | u-outbox | 2 |
| F2.19 | Pre-send pipeline with distinct reject codes, in order: account active, identity, sending open, line valid/not expired, line type vs message class, normalise+dedupe, stoplist, segments and cap, opt-out suffix, content filter, time window, price by operator, reserve credit, hold rules, sms-guard, queue | — | 2 |

### 8.3 Lines, patterns, OTP
| Id | Feature | Screen | Phase |
|---|---|---|---|
| F3.1 | Prefix catalog with digit rules (1000: 6–14, MCI SIM holder only; 2000: 6–12; 3000: 8/9/10/12/14; 5000: 9–15) | u-lines, a-lines | 2 |
| F3.2 | Line order: custom digits or digit count, for self or another user, availability check, immediate debit, reject if profile incomplete, activation status, request list with search | u-lines, a-line-orders | 2, 6 |
| F3.3 | Landline as sender with documents (≤500 KB each) | u-lines, a-line-orders | 6 |
| F3.4 | Line list: number, class, alias, can receive, 66-char flag; default line; "all numbers" = random | u-lines | 2 |
| F3.5 | Line flags: expiry, type, priority, return blacklist, send to blacklist, check filter, delivery-based, try count, public/shared, default, usage shape (single/mask/range), upstream | a-lines | 2 |
| F3.6 | Shared line cannot receive; keyword ownership on a line | u-lines, u-rules | 2, 5 |
| F3.7 | Assign line to user with separate send/receive rights | a-lines, u-resellers | 7 |
| F3.8 | Make line «خدماتی» (company only, promissory note), link permission flag | a-lines | 6 |
| F3.9 | Pattern create: title, description, share with sub-users, message with `%name%`, website, typed variables (string/integer, length) | u-templates, u-otp | 3 |
| F3.10 | Pattern review: pending → active/inactive, admin comment and reject text, result by SMS; edit creates a pending revision with diff | a-patterns | 3, 6 |
| F3.11 | Send by pattern: code, params, exactly one recipient; no human review after approval | u-otp | 3 |
| F3.12 | Pattern text rules: brand/service named, ≥1 param, ≤10 placeholders; method to list a pattern's params | u-templates | 3 |
| F3.13 | Voice OTP (`votp`), own tariff row | u-otp | 5 |
| F3.14 | Pattern with fallback route (send method, fallback method, primary/secondary line, switch TTL, voice message) | u-templates | 5 |
| F3.15 | Managed OTP: `verify` and `verify/check`, code 4–10 chars, TTL, attempts, single use, statuses pending/approved/canceled/max_attempts_reached/expired | u-otp, u-api | 3 |

### 8.4 Inbound and two-way
| Id | Feature | Screen | Phase |
|---|---|---|---|
| F4.1 | Inbox: from, line, text, type, time, seen; `from_id` incremental fetch | u-inbox | 5 |
| F4.2 | Opt-out replies («off», «۱», configurable) add to that customer's stoplist | u-inbox, u-stoplist | 3 |
| F4.3 | Secretary (auto-reply): title, receive line, reply line, date range, reply text; active/expired; replies report | u-rules | 5 |
| F4.4 | Keyword secretary: per-keyword reply, default reply, multi-step flow, bulk upload from Excel, expiry | u-rules | 5 |
| F4.5 | Analyser actions: forward to owner mobile, save to phonebook, copy to email and URL, cancel later scheduled sends | u-rules | 5 |
| F4.6 | Rule conditions (equals, starts, ends, contains, any, >, <, national code, equals phonebook field) and actions (add/remove group, forward mobile/URL/email, reply, send to group) — one engine, keyword priority, no line exclusivity | u-rules | 5 |
| F4.7 | Forward to URL per line for inbound and for DLR, with try count and active flag | u-rules, u-api | 5 |
| F4.8 | Keyword subscription: join/leave keywords, members, queued message to members, duration and expiry message | u-rules | 5 |
| F4.9 | Poll / contest / lottery: lines, chart logo, duplicates, dates; options with keyword, reply line, colour, reply, correct flag; lottery among correct or random; three charts; live chart embed code | u-rules | 5 |
| F4.10 | Numbering: start, step, end, reply with `#code#`, exhausted text, duplicate text, phonebook-only, add sender to phonebook | u-rules | 5 |

### 8.5 Contacts and targeting
| Id | Feature | Screen | Phase |
|---|---|---|---|
| F5.1 | Phonebooks: title ≤200, options, count, import/export status; create, edit, bulk delete, paged list | u-contacts | 3 |
| F5.2 | Contact: number, prefix, name, email, options, tags, send/receive blacklist flags; bulk add returns added/errors/existing | u-contacts | 3 |
| F5.3 | Custom fields typed int/string/date/title | u-contacts | 3 |
| F5.4 | Excel import (async), sample file per phonebook, dedupe on save | u-import | 3 |
| F5.5 | Number cleaning: valid/invalid/duplicate before every send; dedupe within group or across groups; accept 09…, 9…, +98…, 0098…, Persian digits | u-import, u-send | 2 |
| F5.6 | Customer stoplist (and per-line blocked list with reason, exists check) | u-stoplist | 3 |
| F5.7 | Postal-code bank: all/white, postal 2–5 digits, gender, age range, per-operator start/size, random/sequential, from row, count | u-numberbank | 3 |
| F5.8 | Regional/age/gender bank: province (required), county, city, prefix; count per operator; 50001 only, no refund, advised cap | u-numberbank | 3 |
| F5.9 | Jobs bank: 8 categories with subcategories, per-operator start/size, count | u-numberbank | 3 |
| F5.10 | Send from map (17 cities, neighbourhoods), count, operator, order, pro-forma | u-numberbank | 3 |
| F5.11 | Cell tower / location send request (minimums, 72 working-hours lead time) | u-numberbank, a-moderation | 3 |

### 8.6 Money
| Id | Feature | Screen | Phase |
|---|---|---|---|
| F6.1 | Balance: credit, yesterday's credit, gift and gift expiry | u-wallet | 4 |
| F6.2 | Ledger rows with the ten reasons (manual admin, panel purchase/renewal, receipt, online payment, line purchase, service activation, failed-send refund, SMS send, user deletion) | u-transactions, a-finance | 2, 4 |
| F6.3 | Tariff table by line class × language × operator group; voice tier | u-tariffs, a-pricing | 2 |
| F6.4 | Volume price groups (min/max messages, base price, tax decrease, agent ratio, private, default; ratios per upstream, operator, message type) | a-pricing | 4 |
| F6.5 | Online payment Zarinpal v4 and Zibal (101/201 = success, verify on return and by sweeper, charge exactly once; reseller domains pay via platform domain) | u-wallet | 4 |
| F6.6 | Bank receipt (date, amount, tracking no, destination account; approve/reject/pending); failed online payments list | u-wallet, a-finance | 4 |
| F6.7 | VAT 10% and per-SMS levy as settings, shown on invoices | u-transactions | 4 |
| F6.8 | Automatic refund worker; batch marked "sent and refunded"; `return` in batch report | u-batch | 2 |
| F6.9 | Low-credit alarm (threshold, one SMS per crossing, charged) | u-profile, u-dashboard | 4 |
| F6.10 | Packages (role, price, discount, minimum SMS charge, expiry, status, signup type, user/reseller) | u-wallet, a-pricing | 4 |
| F6.11 | Invoices / pro-forma, downloadable | u-transactions | 4 |
| F6.12 | Cost formula: recipients per operator × upstream ratio × price group ratio × parts; early-percent capture option | — | 2 |

### 8.7 Resellers and sub-users
| Id | Feature | Screen | Phase |
|---|---|---|---|
| F7.1 | User tree and parent chain | u-resellers, a-resellers | 7 |
| F7.2 | Create sub-user (required/optional fields), inactive on identity mismatch | u-resellers | 7 |
| F7.3 | Three independent locks (status, send block, document block) + special discount + expiry | u-resellers, a-user | 7 |
| F7.4 | List and filters (username, name, national code, role, mobile, reseller, doc lock, created/expiry range, never logged in, direct/indirect) | u-resellers, a-users | 6, 7 |
| F7.5 | Role as a sellable package with per-service prices | a-roles | 7 |
| F7.6 | Per-account limits (max admins, users, phone numbers, panel price, expiry) | u-resellers | 7 |
| F7.7 | Credit transfer to sub-user (amount, description, with tax) | u-resellers | 7 |
| F7.8 | Sub-client in API (credit, plan, lines, use parent lines, min credit, link enable, can charge, IP) | u-api | 7 |
| F7.9 | Sharing with sub-users: patterns, lines, contact groups | u-templates, u-lines, u-contacts | 7 |
| F7.10 | White-label domain: logo, favicon, title, footer, slides, description, keywords, company name, own prices | u-resellers | 7 |
| F7.11 | SSO hand-off (`external-login?token=`) | u-resellers | 7 |
| F7.12 | Reseller responsibility: reviews sub-user documents and monitors their sends | u-resellers | 7 |
| F7.13 | Credit reservation across the parent chain; every message stores its chain | — | 7 |

### 8.8 Admin back office
| Id | Feature | Screen | Phase |
|---|---|---|---|
| F8.1 | Users: search, advanced edit, person/company fields, separate login/send/identity flags, expiry, login stats, impersonation | a-users, a-user | 6 |
| F8.2 | Documents queue by type with reviewer comment | a-kyc | 6 |
| F8.3 | Documents catalog (data-driven: needs file, count, expires after, show on profile, sample files) | a-settings | 6 |
| F8.4 | Pattern queue with revision diff, approve/reject with comment, SMS notice | a-patterns | 6 |
| F8.5 | Send moderation queue: "awaiting send approval" for batches and schedules, users' manual outbox, auto-approve bulk flag per upstream, reject comment; sms-guard review status visible | a-moderation | 6 |
| F8.6 | Content filter word/regex table, check-filter flag per line, "filtered" status, pre-test of a text | a-settings, a-moderation | 2, 6 |
| F8.7 | Line inventory: define, assign, renew, status, keywords, relays | a-lines | 6 |
| F8.8 | Upstreams: name, type (sms/voice/email), send/receive/bulk enabled, send window, queue length, SMPP flag, credentials, links, default number, balance | a-upstreams | 6 |
| F8.9 | Routes per operator with own credentials and queue; operator table with prefix regex (MCI, Irancell, Rightel, Taliya, …) | a-upstreams | 2, 6 |
| F8.10 | Pricing: global service price, user special price, price group, fa/en rates per operator and upstream | a-pricing | 6 |
| F8.11 | Finance: manual credit +/−, receipt approval, all users' transactions, bank accounts and gateway terminals, refunds | a-finance | 6 |
| F8.12 | System settings: tax, levy, system SMS texts (receipt, login, low credit, signup, expiry, payment, password reset), max failed tries, signup defaults (status, role, parent, credit), max SMS count, per-hour limit, regulatory values listed in Constraints | a-settings, a-system-sms | 6 |
| F8.13 | Tickets: subject, category/subcategory, priority, description, SMS notice, attachments (zip/jpg/png ≤10 MB), private reply, refer to department, satisfaction score, five states | u-tickets, u-ticket, a-tickets | 6 |
| F8.14 | Event log: warning/error/action, source, text, IP, browser; login stats | a-audit | 1, 6 |
| F8.15 | Permission matrix of named services; staff roles moderation/finance/support | a-roles | 1, 6 |
| F8.16 | Reject reasons visible to admin (credit, parent credit, line inactive/expired/invalid, user inactive/expired, parent inactive/expired, no rate, send error, user cancel, out of service, invalid send time, filtered text) | a-moderation, u-batch | 2 |
| F8.17 | Traffic and queue view per lane and upstream, kill switches (account, line, upstream, message class), sms-guard health | a-traffic | 6 |
| F8.18 | Announcements and in-app notifications | a-system-sms, u-notifications | 6 |
| F8.19 | Admin dashboard KPIs | a-dashboard | 6 |

### 8.9 Rules the software enforces
| Id | Rule | Phase |
|---|---|---|
| F9.1 | Identity match before activation | 6 |
| F9.2 | Documents by person type; no line without complete documents | 6 |
| F9.3 | Promotional lines do not reach blacklisted numbers; blacklist is its own status (Magfa 27/28, IPPanel 4, Rahyab −1) | 2 |
| F9.4 | No promotion from a service line (classify text; reject or hold) | 2 |
| F9.5 | Links only with the line's link permission; links extracted from text | 2 |
| F9.6 | Opt-out suffix per line, added before counting and pricing | 2 |
| F9.7 | Promotional send window per upstream and line type; out-of-window held and released at window start | 2 |
| F9.8 | Forbidden content list (gambling, bank/agency impersonation, phishing, prize, unlicensed medical, immoral): hold, reject, case file | 2 |
| F9.9 | Upstream content-filter response is final and refundable | 2 |
| F9.10 | Patterns non-promotional and pre-approved; typed, length-capped variables; one recipient | 3 |
| F9.11 | Sender identifiable in text (configurable mandatory signature per account) | 2 |
| F9.12 | Character and segment counting on final text (after variables and suffix), per-line sizes | 2 |
| F9.13 | Billing language: text starting Persian counts Persian; latin ratio from tariff | 2 |
| F9.14 | Segment cap (e.g. 256) | 2 |
| F9.15 | Recipients per request split to the upstream's cap (Asanak 100, Kavenegar 200) | 2 |
| F9.16 | No double send: client reference id per message (Magfa uids, Ghasedak client ref) | 2 |
| F9.17 | Price per destination operator by prefix | 2 |
| F9.18 | Tax and levy settings | 4 |
| F9.19 | Refund rules (blacklist, delivery-based, upstream-rejected), separate ledger rows | 2 |
| F9.20 | Password policy | 1 |
| F9.21 | Three message classes: promotional, service, transactional | 2 |

### 8.10 Customer API
| Id | Feature | Phase |
|---|---|---|
| F10.1 | Simple and bulk send (sender, recipients, text, time, client reference id); response with id, cost and parts per recipient | 5 |
| F10.2 | Peer-to-peer send (array of recipient/text) | 5 |
| F10.3 | Pattern send and pattern management (create, list, params) | 5 |
| F10.4 | Status by panel id or client id (list, ≤100) | 5 |
| F10.5 | Cancel scheduled | 5 |
| F10.6 | Outbox report (date range, sender, paging) | 5 |
| F10.7 | Inbox (line, read flag, paging) | 5 |
| F10.8 | Account info, credit and config (default sender, min credit alarm, resend failed, daily report) | 5 |
| F10.9 | Price estimate and sender lines | 5 |
| F10.10 | Phonebooks and contacts | 5 |
| F10.11 | Voice (TTS call, votp) | 5 |
| F10.12 | Sub-users and credit | 7 |
| F10.13 | Compatibility: single GET send; username/password or key-as-username; default sender; WooCommerce-style gateway shape | 5 |
| F10.14 | Stoplist management and text pre-test (`hasFilter`) | 5 |
| F10.15 | Status model (accepted, pending_review, scheduled, queued, sending, sent, delivered, undelivered, unconfirmed, blacklisted, rejected, failed, canceled, insufficient_credit) with upstream mappings | 2 |
| F10.16 | Auth: login token (10 h) for sensitive actions, non-expiring API keys, three-step login (method, send OTP, confirm) | 5 |
| F10.17 | Errors: real HTTP codes and `{code, title, detail, source.pointer}`; idempotency key; cursor paging; rate-limit headers | 5 |
| F10.18 | Webhooks: message.sent, message.finalized, message.received; envelope with attempt; signature over timestamp and body; 5-min window; 2xx within 2 s; 3 tries then fallback URL; per-line callback URL (GET or POST) | 5 |
| F10.19 | OTP verify and verify/check | 3 |
| F10.20 | SMPP 3.4 server: bind tx/rx/trx, system_id ≤15, password ≤8, data_coding 8 for Persian, UDH concatenation (esm_class 0x40), window ≤10, deliver_sm receipts | 8 |
| F10.21 | OpenAPI contract committed under `docs/api/panel-customer-api.yaml`, Persian developer guide | 5 |

### 8.11 External connections
| Id | Feature | Phase |
|---|---|---|
| F11.1 | Magfa HTTP v2 (send, statuses, mid/{uid}, messages, balance; status and error codes classified) | 8 |
| F11.2 | Asanak v1 REST (sendsms ≤100, msgstatus ≤100, getcredit, 4 h finality, inbound GET) | 8 |
| F11.3 | Asanak v2 (sendsms with send_to_black_list, template) | 8 |
| F11.4 | Rahyab Payamgostaran 50001 (GET, «Send OK.», statuses, first poll after 5 min) | 8 |
| F11.5 | Rahyab Rayaneh-Gostar 1000 (XML batch; v1 SendSMS_Single) | 8 |
| F11.6 | Kavenegar (send, sendarray, lookup, status, receive, account, tts) | 8 |
| F11.7 | Ghasedak (single, bulk, pair, OTP with params, status) | 8 |
| F11.8 | Identity match: Jibit and Zohal | 6 |
| F11.9 | Payment: Zarinpal v4, Zibal; driver interface for more | 4 |
| F11.10 | Bale OTP (token, send_otp, error mapping) | 5 |
| F11.11 | msgway (sms/messenger/ivr, otp/verify, status) | 5 |
| F11.12 | Fixed egress IP for connector traffic | 8 |
| F11.13 | Link shortener on the platform's own domain with per-recipient token and kill switch | 5 |
| F11.14 | sms-guard client (HMAC, idempotency, poll, cancel, health) | 2 |
| F11.15 | Simulator for every connector type, with scripted outcomes for tests and demos | 2 |

### 8.12 Architecture items
| Id | Item | Phase |
|---|---|---|
| F12.1 | Entities: user, api_key, line, line_class, tariff_rate, batch, message, dlr_event, pattern (+revision), inbound_message, inbound_rule, wallet_transaction, payment, contact, contact_group, custom_field, stoplist, route, upstream_connector, webhook_endpoint, webhook_delivery, ticket, document, audit_event, job | 1–2 |
| F12.2 | Workers listed under Architecture → Workers | 2–5 |
| F12.3 | DLR reconciliation (append-only receipts, parked early receipts, finality sweeper) | 2 |
| F12.4 | Archive after 48 h to cold tables; exports | 5 |

### 8.13 Security and non-functional
| Id | Item | Phase |
|---|---|---|
| F13.1 | Two-factor login; SMS to owner after each login | 1 |
| F13.2 | IP and login-hours restriction | 1 |
| F13.3 | API keys hashed, shown once, several with scope/IP | 5 |
| F13.4 | Separate API credentials and enable switch | 5 |
| F13.5 | Brute-force detection, max failed tries | 1 |
| F13.6 | Per-user hourly send cap; anomaly hold (first bulk, volume jump, new link) | 2 |
| F13.7 | Sender IP on every batch; login stats | 1, 2 |
| F13.8 | Content and secret masking in logs | 1 |
| F13.9 | Kill switches (account, line, upstream, class) | 6 |
| F13.10 | Continuity: pause by message class with queue-expiry rule | 6 |
| F13.11 | Evidence retention per message | 2 |
| F13.12 | Admin controls: 2FA + IP for staff, immutable audit with before/after and reason, visible impersonation, two-person approvals | 6 |
| F13.13 | Contacts encrypted at rest, export limits and log, masked numbers for support; backups with PITR | 3, 8 |
| F13.14 | Metrics (throttling_error_count, charging_error_count, queue depth, guard wait time, DLR lag) | 8 |

## 9. Prototype screens (all must work)

Customer: u-dashboard, u-send, u-bulk, u-otp, u-numberbank, u-scheduled, u-outbox, u-batch,
u-inbox, u-rules, u-contacts, u-import, u-stoplist, u-templates, u-lines, u-api, u-resellers,
u-wallet, u-transactions, u-tariffs, u-tickets, u-ticket, u-notifications, u-profile.
Admin: a-dashboard, a-kyc, a-patterns, a-moderation, a-line-orders, a-users, a-user, a-resellers,
a-tickets, a-traffic, a-upstreams, a-lines, a-finance, a-pricing, a-system-sms, a-roles, a-audit,
a-settings. Auth: auth-login, auth-register. (Plus the index/landing route.)
