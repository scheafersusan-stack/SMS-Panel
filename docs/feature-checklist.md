# Feature checklist

Every feature id from the design spec section 8 (`docs/superpowers/specs/2026-11-14-payamakyar-panel-design.md`).
A box is ticked only when the feature is fully delivered; a note says what is partial or deferred. Each phase's plan
ends by ticking the ids it completes. Phase numbers are the spec's delivery phases.

Phase 1 (foundation) ticks: `F1.8`, `F9.20`, `F13.2`, `F13.5`, `F13.8`. Partially delivered (unticked, with notes): `F1.1`, `F1.2`, `F1.3`, `F1.4`, `F1.6`, `F8.14`, `F8.15`, `F12.1`, `F13.1`, `F13.7`.

## 8.1 Accounts and identity

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F1.1 | Registration (person/company), mobile verification by OTP | 1 | Partial: registration and OTP verification work; the OTP SMS only reaches the outbox (operator delivery: Phase 2). |
| [ ] | F1.2 | Login with password; second factor TOTP (ga) or SMS; login notice SMS | 1 | Partial: password login with TOTP/SMS second factor works; login notice and SMS factor messages only reach the outbox (operator delivery: Phase 2). |
| [ ] | F1.3 | Password reset by SMS/email; password policy | 1 | Partial: reset by SMS and the password policy are done; the email channel is not. |
| [ ] | F1.4 | Account gates: registered → profile complete → identity matched → documents approved; each gate unlocks send… | 1, 6 | Partial: gate model and `registered`/`profile_complete` exist; identity and documents gates come with Phase 6. |
| [ ] | F1.5 | Identity match national code ↔ mobile ↔ birth date (Shahkar via Jibit/Zohal/simulator); service error goes to… | 6 |  |
| [ ] | F1.6 | Person and company fields (national code, company national id, economic code, CEO) | 1 | Partial: person/company fields exist in the schema and profile API; registration does not take identity/company fields and the web has no UI for them yet. |
| [ ] | F1.7 | Document upload by type (person: national card, face photo, SIM ownership; company: CEO card, gazette, …), ≤… | 6 |  |
| [x] | F1.8 | Allowed IPs and login hours; sessions list and revoke | 1 |  |
| [ ] | F1.9 | API keys: create (shown once), scope, IP allowlist, revoke, last used; separate webservice credentials and… | 5 |  |

## 8.2 Sending

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F2.1 | Send wizard: sender, text, recipients (Excel, TXT, phonebook, manual/paste), duplicate handling… | 2 |  |
| [ ] | F2.2 | Direct vs bulk threshold (configurable, default 10) — bulk waits in moderation when required | 2 |  |
| [ ] | F2.3 | Bulk send with title, draft save, four recipient sources, statuses | 2 |  |
| [ ] | F2.4 | Send from file (CSV/XLSX) plus extra recipients | 2 |  |
| [ ] | F2.5 | Peer-to-peer from two-column Excel (header skipped, `;` multi-numbers) or manual boxes; allow duplicates… | 2 |  |
| [ ] | F2.6 | Variable send: `#1#` ordinal, Excel column names with "add to text", `{ex_B}`/`{ex_<fieldId>}` | 2 |  |
| [ ] | F2.7 | Send to phonebook: all with start/size slice, or selected contacts | 2 |  |
| [ ] | F2.8 | Scheduling and cancel (until 5 min before; configurable) | 2 |  |
| [ ] | F2.9 | Recurring and occasion sends: once, daily, weekly, monthly (instalment), yearly (birthday) from a phonebook… | 2 |  |
| [ ] | F2.10 | Draft groups (title ≤200, ≤20 groups) and drafts (≤1400 chars, ≤200) | 3 |  |
| [ ] | F2.11 | Price estimate per recipient operator (mci/other) and parts | 2 |  |
| [ ] | F2.12 | Outbox: text, time, sender, recipient, status, per-recipient delivery icon; resend failed; details and… | 2 |  |
| [ ] | F2.13 | Batch stats: blacklist, failed, pending, sent, delivered by operator and language | 2 |  |
| [ ] | F2.14 | Send by link (GET with apikey or username/password; alias parameter names) | 5 |  |
| [ ] | F2.15 | Link tracker: short link insertion, per-recipient token, clicks and visits, downloadable report | 5 |  |
| [ ] | F2.16 | Voice message: uploaded audio, recipients, retry, pro-forma with duration, operator approval | 5 |  |
| [ ] | F2.17 | Flash SMS (display on screen) | 5 |  |
| [ ] | F2.18 | Batch state machine (IPPanel's 10 states mapped) and per-recipient states (§8.10 model) | 2 |  |
| [ ] | F2.19 | Pre-send pipeline with distinct reject codes, in order: account active, identity, sending open, line… | 2 |  |

## 8.3 Lines, patterns, OTP

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F3.1 | Prefix catalog with digit rules (1000: 6–14, MCI SIM holder only; 2000: 6–12; 3000: 8/9/10/12/14; 5000: 9–15) | 2 |  |
| [ ] | F3.2 | Line order: custom digits or digit count, for self or another user, availability check, immediate debit… | 2, 6 |  |
| [ ] | F3.3 | Landline as sender with documents (≤500 KB each) | 6 |  |
| [ ] | F3.4 | Line list: number, class, alias, can receive, 66-char flag; default line; "all numbers" = random | 2 |  |
| [ ] | F3.5 | Line flags: expiry, type, priority, return blacklist, send to blacklist, check filter, delivery-based, try… | 2 |  |
| [ ] | F3.6 | Shared line cannot receive; keyword ownership on a line | 2, 5 |  |
| [ ] | F3.7 | Assign line to user with separate send/receive rights | 7 |  |
| [ ] | F3.8 | Make line «خدماتی» (company only, promissory note), link permission flag | 6 |  |
| [ ] | F3.9 | Pattern create: title, description, share with sub-users, message with `%name%`, website, typed variables… | 3 |  |
| [ ] | F3.10 | Pattern review: pending → active/inactive, admin comment and reject text, result by SMS; edit creates a… | 3, 6 |  |
| [ ] | F3.11 | Send by pattern: code, params, exactly one recipient; no human review after approval | 3 |  |
| [ ] | F3.12 | Pattern text rules: brand/service named, ≥1 param, ≤10 placeholders; method to list a pattern's params | 3 |  |
| [ ] | F3.13 | Voice OTP (`votp`), own tariff row | 5 |  |
| [ ] | F3.14 | Pattern with fallback route (send method, fallback method, primary/secondary line, switch TTL, voice message) | 5 |  |
| [ ] | F3.15 | Managed OTP: `verify` and `verify/check`, code 4–10 chars, TTL, attempts, single use, statuses… | 3 |  |

## 8.4 Inbound and two-way

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F4.1 | Inbox: from, line, text, type, time, seen; `from_id` incremental fetch | 5 |  |
| [ ] | F4.2 | Opt-out replies («off», «۱», configurable) add to that customer's stoplist | 3 |  |
| [ ] | F4.3 | Secretary (auto-reply): title, receive line, reply line, date range, reply text; active/expired; replies… | 5 |  |
| [ ] | F4.4 | Keyword secretary: per-keyword reply, default reply, multi-step flow, bulk upload from Excel, expiry | 5 |  |
| [ ] | F4.5 | Analyser actions: forward to owner mobile, save to phonebook, copy to email and URL, cancel later scheduled… | 5 |  |
| [ ] | F4.6 | Rule conditions (equals, starts, ends, contains, any, >, <, national code, equals phonebook field) and… | 5 |  |
| [ ] | F4.7 | Forward to URL per line for inbound and for DLR, with try count and active flag | 5 |  |
| [ ] | F4.8 | Keyword subscription: join/leave keywords, members, queued message to members, duration and expiry message | 5 |  |
| [ ] | F4.9 | Poll / contest / lottery: lines, chart logo, duplicates, dates; options with keyword, reply line, colour… | 5 |  |
| [ ] | F4.10 | Numbering: start, step, end, reply with `#code#`, exhausted text, duplicate text, phonebook-only, add sender… | 5 |  |

## 8.5 Contacts and targeting

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F5.1 | Phonebooks: title ≤200, options, count, import/export status; create, edit, bulk delete, paged list | 3 |  |
| [ ] | F5.2 | Contact: number, prefix, name, email, options, tags, send/receive blacklist flags; bulk add returns… | 3 |  |
| [ ] | F5.3 | Custom fields typed int/string/date/title | 3 |  |
| [ ] | F5.4 | Excel import (async), sample file per phonebook, dedupe on save | 3 |  |
| [ ] | F5.5 | Number cleaning: valid/invalid/duplicate before every send; dedupe within group or across groups; accept 09…… | 2 |  |
| [ ] | F5.6 | Customer stoplist (and per-line blocked list with reason, exists check) | 3 |  |
| [ ] | F5.7 | Postal-code bank: all/white, postal 2–5 digits, gender, age range, per-operator start/size… | 3 |  |
| [ ] | F5.8 | Regional/age/gender bank: province (required), county, city, prefix; count per operator; 50001 only, no… | 3 |  |
| [ ] | F5.9 | Jobs bank: 8 categories with subcategories, per-operator start/size, count | 3 |  |
| [ ] | F5.10 | Send from map (17 cities, neighbourhoods), count, operator, order, pro-forma | 3 |  |
| [ ] | F5.11 | Cell tower / location send request (minimums, 72 working-hours lead time) | 3 |  |

## 8.6 Money

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F6.1 | Balance: credit, yesterday's credit, gift and gift expiry | 4 |  |
| [ ] | F6.2 | Ledger rows with the ten reasons (manual admin, panel purchase/renewal, receipt, online payment, line… | 2, 4 |  |
| [ ] | F6.3 | Tariff table by line class × language × operator group; voice tier | 2 |  |
| [ ] | F6.4 | Volume price groups (min/max messages, base price, tax decrease, agent ratio, private, default; ratios per… | 4 |  |
| [ ] | F6.5 | Online payment Zarinpal v4 and Zibal (101/201 = success, verify on return and by sweeper, charge exactly… | 4 |  |
| [ ] | F6.6 | Bank receipt (date, amount, tracking no, destination account; approve/reject/pending); failed online payments… | 4 |  |
| [ ] | F6.7 | VAT 10% and per-SMS levy as settings, shown on invoices | 4 |  |
| [ ] | F6.8 | Automatic refund worker; batch marked "sent and refunded"; `return` in batch report | 2 |  |
| [ ] | F6.9 | Low-credit alarm (threshold, one SMS per crossing, charged) | 4 |  |
| [ ] | F6.10 | Packages (role, price, discount, minimum SMS charge, expiry, status, signup type, user/reseller) | 4 |  |
| [ ] | F6.11 | Invoices / pro-forma, downloadable | 4 |  |
| [ ] | F6.12 | Cost formula: recipients per operator × upstream ratio × price group ratio × parts; early-percent capture… | 2 |  |

## 8.7 Resellers and sub-users

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F7.1 | User tree and parent chain | 7 |  |
| [ ] | F7.2 | Create sub-user (required/optional fields), inactive on identity mismatch | 7 |  |
| [ ] | F7.3 | Three independent locks (status, send block, document block) + special discount + expiry | 7 |  |
| [ ] | F7.4 | List and filters (username, name, national code, role, mobile, reseller, doc lock, created/expiry range… | 6, 7 |  |
| [ ] | F7.5 | Role as a sellable package with per-service prices | 7 |  |
| [ ] | F7.6 | Per-account limits (max admins, users, phone numbers, panel price, expiry) | 7 |  |
| [ ] | F7.7 | Credit transfer to sub-user (amount, description, with tax) | 7 |  |
| [ ] | F7.8 | Sub-client in API (credit, plan, lines, use parent lines, min credit, link enable, can charge, IP) | 7 |  |
| [ ] | F7.9 | Sharing with sub-users: patterns, lines, contact groups | 7 |  |
| [ ] | F7.10 | White-label domain: logo, favicon, title, footer, slides, description, keywords, company name, own prices | 7 |  |
| [ ] | F7.11 | SSO hand-off (`external-login?token=`) | 7 |  |
| [ ] | F7.12 | Reseller responsibility: reviews sub-user documents and monitors their sends | 7 |  |
| [ ] | F7.13 | Credit reservation across the parent chain; every message stores its chain | 7 |  |

## 8.8 Admin back office

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F8.1 | Users: search, advanced edit, person/company fields, separate login/send/identity flags, expiry, login stats… | 6 |  |
| [ ] | F8.2 | Documents queue by type with reviewer comment | 6 |  |
| [ ] | F8.3 | Documents catalog (data-driven: needs file, count, expires after, show on profile, sample files) | 6 |  |
| [ ] | F8.4 | Pattern queue with revision diff, approve/reject with comment, SMS notice | 6 |  |
| [ ] | F8.5 | Send moderation queue: "awaiting send approval" for batches and schedules, users' manual outbox, auto-approve… | 6 |  |
| [ ] | F8.20 | Guard policy: exemption rules (users, reseller subtree, lines, class, recipient count < N, tier, dates)… | 6 |  |
| [ ] | F8.6 | Content filter word/regex table, check-filter flag per line, "filtered" status, pre-test of a text | 2, 6 |  |
| [ ] | F8.7 | Line inventory: define, assign, renew, status, keywords, relays | 6 |  |
| [ ] | F8.8 | Upstreams: name, type (sms/voice/email), send/receive/bulk enabled, send window, queue length, SMPP flag… | 6 |  |
| [ ] | F8.9 | Routes per operator with own credentials and queue; operator table with prefix regex (MCI, Irancell, Rightel… | 2, 6 |  |
| [ ] | F8.10 | Pricing: global service price, user special price, price group, fa/en rates per operator and upstream | 6 |  |
| [ ] | F8.11 | Finance: manual credit +/−, receipt approval, all users' transactions, bank accounts and gateway terminals… | 6 |  |
| [ ] | F8.12 | System settings: tax, levy, system SMS texts (receipt, login, low credit, signup, expiry, payment, password… | 6 |  |
| [ ] | F8.13 | Tickets: subject, category/subcategory, priority, description, SMS notice, attachments (zip/jpg/png ≤10 MB)… | 6 |  |
| [ ] | F8.14 | Event log: warning/error/action, source, text, IP, browser; login stats | 1, 6 | Partial: audit log, chain verification and login events viewer are done; warning/error event sources and the admin screen come with Phase 6. |
| [ ] | F8.15 | Permission matrix of named services; staff roles moderation/finance/support | 1, 6 | Partial: permission matrix, roles and the RBAC admin API are done; the roles screen comes with Phase 6. |
| [ ] | F8.16 | Reject reasons visible to admin (credit, parent credit, line inactive/expired/invalid, user inactive/expired… | 2 |  |
| [ ] | F8.17 | Traffic and queue view per lane and upstream, kill switches (account, line, upstream, message class)… | 6 |  |
| [ ] | F8.18 | Announcements and in-app notifications | 6 |  |
| [ ] | F8.19 | Admin dashboard KPIs | 6 |  |

## 8.9 Rules the software enforces

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F9.1 | Identity match before activation | 6 |  |
| [ ] | F9.2 | Documents by person type; no line without complete documents | 6 |  |
| [ ] | F9.3 | Promotional lines do not reach blacklisted numbers; blacklist is its own status (Magfa 27/28, IPPanel 4… | 2 |  |
| [ ] | F9.4 | No promotion from a service line (classify text; reject or hold) | 2 |  |
| [ ] | F9.5 | Links only with the line's link permission; links extracted from text | 2 |  |
| [ ] | F9.6 | Opt-out suffix per line, added before counting and pricing | 2 |  |
| [ ] | F9.7 | Promotional send window per upstream and line type; out-of-window held and released at window start | 2 |  |
| [ ] | F9.8 | Forbidden content list (gambling, bank/agency impersonation, phishing, prize, unlicensed medical, immoral)… | 2 |  |
| [ ] | F9.9 | Upstream content-filter response is final and refundable | 2 |  |
| [ ] | F9.10 | Patterns non-promotional and pre-approved; typed, length-capped variables; one recipient | 3 |  |
| [ ] | F9.11 | Sender identifiable in text (configurable mandatory signature per account) | 2 |  |
| [ ] | F9.12 | Character and segment counting on final text (after variables and suffix), per-line sizes | 2 |  |
| [ ] | F9.13 | Billing language: text starting Persian counts Persian; latin ratio from tariff | 2 |  |
| [ ] | F9.14 | Segment cap (e.g. 256) | 2 |  |
| [ ] | F9.15 | Recipients per request split to the upstream's cap (Asanak 100, Kavenegar 200) | 2 |  |
| [ ] | F9.16 | No double send: client reference id per message (Magfa uids, Ghasedak client ref) | 2 |  |
| [ ] | F9.17 | Price per destination operator by prefix | 2 |  |
| [ ] | F9.18 | Tax and levy settings | 4 |  |
| [ ] | F9.19 | Refund rules (blacklist, delivery-based, upstream-rejected), separate ledger rows | 2 |  |
| [x] | F9.20 | Password policy | 1 |  |
| [ ] | F9.21 | Three message classes: promotional, service, transactional | 2 |  |

## 8.10 Customer API

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F10.1 | Simple and bulk send (sender, recipients, text, time, client reference id); response with id, cost and parts… | 5 |  |
| [ ] | F10.2 | Peer-to-peer send (array of recipient/text) | 5 |  |
| [ ] | F10.3 | Pattern send and pattern management (create, list, params) | 5 |  |
| [ ] | F10.4 | Status by panel id or client id (list, ≤100) | 5 |  |
| [ ] | F10.5 | Cancel scheduled | 5 |  |
| [ ] | F10.6 | Outbox report (date range, sender, paging) | 5 |  |
| [ ] | F10.7 | Inbox (line, read flag, paging) | 5 |  |
| [ ] | F10.8 | Account info, credit and config (default sender, min credit alarm, resend failed, daily report) | 5 |  |
| [ ] | F10.9 | Price estimate and sender lines | 5 |  |
| [ ] | F10.10 | Phonebooks and contacts | 5 |  |
| [ ] | F10.11 | Voice (TTS call, votp) | 5 |  |
| [ ] | F10.12 | Sub-users and credit | 7 |  |
| [ ] | F10.13 | Compatibility: single GET send; username/password or key-as-username; default sender; WooCommerce-style… | 5 |  |
| [ ] | F10.14 | Stoplist management and text pre-test (`hasFilter`) | 5 |  |
| [ ] | F10.15 | Status model (accepted, pending_review, scheduled, queued, sending, sent, delivered, undelivered… | 2 |  |
| [ ] | F10.16 | Auth: login token (10 h) for sensitive actions, non-expiring API keys, three-step login (method, send OTP… | 5 |  |
| [ ] | F10.17 | Errors: real HTTP codes and `{code, title, detail, source.pointer}`; idempotency key; cursor paging… | 5 |  |
| [ ] | F10.18 | Webhooks: message.sent, message.finalized, message.received; envelope with attempt; signature over timestamp… | 5 |  |
| [ ] | F10.19 | OTP verify and verify/check | 3 |  |
| [ ] | F10.20 | SMPP 3.4 server: bind tx/rx/trx, system_id ≤15, password ≤8, data_coding 8 for Persian, UDH concatenation… | 8 |  |
| [ ] | F10.21 | OpenAPI contract committed under `docs/api/panel-customer-api.yaml`, Persian developer guide | 5 |  |

## 8.11 External connections

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F11.1 | Magfa HTTP v2 (send, statuses, mid/{uid}, messages, balance; status and error codes classified) | 8 |  |
| [ ] | F11.2 | Asanak v1 REST (sendsms ≤100, msgstatus ≤100, getcredit, 4 h finality, inbound GET) | 8 |  |
| [ ] | F11.3 | Asanak v2 (sendsms with send_to_black_list, template) | 8 |  |
| [ ] | F11.4 | Rahyab Payamgostaran 50001 (GET, «Send OK.», statuses, first poll after 5 min) | 8 |  |
| [ ] | F11.5 | Rahyab Rayaneh-Gostar 1000 (XML batch; v1 SendSMS_Single) | 8 |  |
| [ ] | F11.6 | Kavenegar (send, sendarray, lookup, status, receive, account, tts) | 8 |  |
| [ ] | F11.7 | Ghasedak (single, bulk, pair, OTP with params, status) | 8 |  |
| [ ] | F11.8 | Identity match: Jibit and Zohal | 6 |  |
| [ ] | F11.9 | Payment: Zarinpal v4, Zibal; driver interface for more | 4 |  |
| [ ] | F11.10 | Bale OTP (token, send_otp, error mapping) | 5 |  |
| [ ] | F11.11 | msgway (sms/messenger/ivr, otp/verify, status) | 5 |  |
| [ ] | F11.12 | Fixed egress IP for connector traffic | 8 |  |
| [ ] | F11.13 | Link shortener on the platform's own domain with per-recipient token and kill switch | 5 |  |
| [ ] | F11.14 | sms-guard client (HMAC, idempotency, poll, cancel, health) | 2 |  |
| [ ] | F11.15 | Simulator for every connector type, with scripted outcomes for tests and demos | 2 |  |

## 8.12 Architecture items

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F12.1 | Entities: user, api_key, line, line_class, tariff_rate, batch, message, dlr_event, pattern (+revision)… | 1–2 | Partial: user, audit_event, job and RBAC/session tables exist; the remaining entities arrive in Phase 2 onward. |
| [ ] | F12.2 | Workers listed under Architecture → Workers | 2–5 |  |
| [ ] | F12.3 | DLR reconciliation (append-only receipts, parked early receipts, finality sweeper) | 2 |  |
| [ ] | F12.4 | Archive after 48 h to cold tables; exports | 5 |  |

## 8.13 Security and non-functional

| Done | Id | Feature | Phase | Note |
|---|---|---|---|---|
| [ ] | F13.1 | Two-factor login; SMS to owner after each login | 1 | Partial: two-factor login works; the SMS to the owner only reaches the outbox (operator delivery: Phase 2). |
| [x] | F13.2 | IP and login-hours restriction | 1 |  |
| [ ] | F13.3 | API keys hashed, shown once, several with scope/IP | 5 |  |
| [ ] | F13.4 | Separate API credentials and enable switch | 5 |  |
| [x] | F13.5 | Brute-force detection, max failed tries | 1 |  |
| [ ] | F13.6 | Per-user hourly send cap; anomaly hold (first bulk, volume jump, new link) | 2 |  |
| [ ] | F13.7 | Sender IP on every batch; login stats | 1, 2 | Partial: login stats and client IP capture are done; the sender IP on batches is Phase 2. |
| [x] | F13.8 | Content and secret masking in logs | 1 |  |
| [ ] | F13.9 | Kill switches (account, line, upstream, class) | 6 |  |
| [ ] | F13.10 | Continuity: pause by message class with queue-expiry rule | 6 |  |
| [ ] | F13.11 | Evidence retention per message | 2 |  |
| [ ] | F13.12 | Admin controls: 2FA + IP for staff, immutable audit with before/after and reason, visible impersonation… | 6 |  |
| [ ] | F13.13 | Contacts encrypted at rest, export limits and log, masked numbers for support; backups with PITR | 3, 8 |  |
| [ ] | F13.14 | Metrics (throttling_error_count, charging_error_count, queue depth, guard wait time, DLR lag) | 8 |  |
