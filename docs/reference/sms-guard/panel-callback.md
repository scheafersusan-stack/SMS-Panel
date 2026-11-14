# Panel callback contract (sms-guard → panel)

SPEC §4.4 as decided in OPEN_QUESTIONS A7, D2, D3, D7, D8 and ADRs 0017, 0018, 0020. The body
model is `smsguard.core.models.callback.DecisionEvent`; the same object is the `decision` of
the poll response (`GET /api/v1/messages/{guard_id}`, see `panel-api.yaml`). Delivery is done
by the outbox dispatcher in the `api-jobs` process; workers never call the panel.

## Request

`POST <callback_url>` — the URL snapshotted when the message was accepted (the request's
`callback_url`, or the client's default), re-checked against the client's allowlist at send
time. TLS is verified, redirects are never followed, each attempt times out after 10 s.

| Header | Value |
|---|---|
| `Authorization` | `Bearer <outbound api key>` issued to the panel for callbacks |
| `X-Guard-Event-Id` | `event_id` of the body (lowercase UUID) |
| `Idempotency-Key` | the same `event_id` string |
| `X-Guard-Timestamp` | Unix epoch seconds of **this attempt** (canonical decimal) |
| `X-Guard-Signature` | `hmac-sha256=<64 lowercase hex>` |
| `Content-Type` | `application/json` |

Every header appears exactly once, and `X-Guard-Event-Id == Idempotency-Key == str(event_id)`.

### Signing (byte-exact)

The body is exactly `DecisionEvent.canonical_bytes()`: canonical JSON of the wire dump —
object keys sorted at every level, separators `,` and `:` without spaces, non-ASCII
characters (Persian text) written as raw UTF-8, no trailing newline. The payload is frozen
when the decision is committed, so every retry of an event sends the same bytes; only the
timestamp (and therefore the signature) changes between attempts.

```
signature = "hmac-sha256=" + hex(HMAC_SHA256(key = ASCII bytes of the outbound HMAC secret,
                                             msg = X-Guard-Timestamp + "." + raw_body))
```

The panel must verify over the **raw bytes it received** (never over a re-serialised
object), compare in constant time, accept hex in either case, and reject timestamps more
than 300 s from its clock. Replay protection on the panel side = the timestamp window plus
`event_id` dedupe (below).

### Outbound credential rotation

sms-guard rotates the outbound api key and HMAC secret with `smsguard-api rotate-secrets
--client NAME --direction outbound --grace-seconds N` (`scripts/README.md`). The callback
carries no key id, so the switch is time-based:

- The operator hands the new pair to the panel team together with the **switch instant** the
  command prints (rotation time + `N` seconds, UTC).
- Until the switch instant every callback is still sent with the **previous** pair; from the
  switch instant on, every callback (retries included) is sent with the **new** pair. The pair
  is chosen per attempt, so a retry after the switch carries the new pair.
- During the overlap the panel accepts **both** pairs: the `Authorization` bearer may be either
  key, and `X-Guard-Signature` is valid if it verifies under either secret (each compared in
  constant time). Install the new pair before the switch instant, remove the previous one
  after it (allow for clock skew and the 300 s timestamp window).
- `N = 0` switches at once. Nothing else in the request or the signing changes.
- A second outbound rotation inside the overlap discards the pair the panel was just given:
  the panel must then install the newest pair (and its new switch instant) instead.

## Body

Every key is always present, with `null` where the table says nullable — except
`operator_note`, which is **omitted** (not `null`) unless an operator wrote one.

| Field | Type | Notes |
|---|---|---|
| `event` | `decision.interim` \| `decision.final` | |
| `event_id` | UUID | Unique per event; the dedupe key. |
| `guard_id` | UUID | From the 202 of `POST /api/v1/messages`. |
| `message_id` | string | The panel's own id. |
| `sequence` | integer ≥ 1 | Per `guard_id`, starting at 1, +1 per event (new vs SPEC). |
| `verdict` | `ALLOW` \| `BLOCK` \| `MANUAL_REVIEW` | `MANUAL_REVIEW` exactly on interim events. |
| `is_final` | boolean | `true` exactly for `decision.final`. |
| `risk_score` | integer 0–100, nullable | `null` for fail-safe and watchdog decisions. |
| `confidence` | number 0–1, nullable | `null` when no model contributed (all of Phase 1). |
| `reason_code` | string | Stable machine code (`smsguard.core.reason_codes`). |
| `reason` | string (Persian) | One-sentence operator-facing reason. |
| `explanation` | string (Persian) | Evidence-based explanation. |
| `rule_hits[]` | `{rule_id, name, severity, action, version}` | Matched rules; may be empty. |
| `signals[]` | `{type, value, weight, confidence, source}` | `source` (new vs SPEC example): `rule`, `classifier`, `llm`, `link`, `ti`, `sandbox`, `vlm`, `system`; `confidence` nullable. |
| `links[]` | `{original, final, redirects, verdict}` | Empty until link analysis (Phase 4); `final` nullable. |
| `evidence_url` | string, nullable | Review page in the dashboard: `{SMSGUARD_DASHBOARD_PUBLIC_URL}/review/{guard_id}` on every event from Phase 3 (`null` when the deployment has no dashboard URL). |
| `decided_at` | date-time (UTC) | |
| `decided_by` | `{type: system\|operator, id}` | System ids: `policy-engine`, `watchdog`, `fail-safe`; operator ids are opaque (a user UUID) — no staff name leaves sms-guard. |
| `operator_note` | string, conditional | Only when `decided_by.type = operator` and a note exists. |
| `versions` | `{policy, ruleset, text_model, vision_model, prompt}` | Model/prompt entries nullable (`null` in Phase 1). |

### Event combinations

- `decision.interim` always carries `MANUAL_REVIEW` and `is_final: false`; at most **one**
  interim per message (deadline exceeded, a subsystem failure, or a review-band score).
- `decision.final` always carries `ALLOW` or `BLOCK` and `is_final: true`; at most one per
  message. After an interim it comes from an operator (`decided_by.type = operator`).
- A final **without** a preceding interim is normal (most messages). A final may also arrive
  after an interim that was never delivered (dead-lettered): the panel must accept it.
- **Cancel sends no callback.** A cancelled message's undelivered events are superseded and
  never sent; the panel already has the cancel's `200` response.

### Example

A final BLOCK from a deterministic rule (canonical key order, pretty-printed for reading —
the wire form is the compact single line):

```json
{
  "confidence": null,
  "decided_at": "2026-10-15T06:42:06.512000+00:00",
  "decided_by": {
    "id": "policy-engine",
    "type": "system"
  },
  "event": "decision.final",
  "event_id": "e0000000-0000-4000-8000-000000000001",
  "evidence_url": "https://guard.internal.example/review/0d2f7b1e-6a0c-4a9e-9d1f-2f3a7e9b1c44",
  "explanation": "قاعده‌ی «درخواست رمز دوم یا CVV2» در متن پیام درخواست اطلاعات محرمانه را تشخیص داد: «رمز دوم». هیچ بانک یا نهاد معتبری چنین اطلاعاتی را از طریق پیامک درخواست نمی‌کند.",
  "guard_id": "0d2f7b1e-6a0c-4a9e-9d1f-2f3a7e9b1c44",
  "is_final": true,
  "links": [],
  "message_id": "panel-msg-8841237",
  "reason": "پیام از گیرنده اطلاعات محرمانه‌ی بانکی یا حساب کاربری مانند رمز، رمز دوم یا کد تأیید یک‌بارمصرف را درخواست می‌کند.",
  "reason_code": "PHISHING_CREDENTIAL_REQUEST",
  "risk_score": 100,
  "rule_hits": [
    {
      "action": "BLOCK",
      "name": "درخواست رمز دوم یا CVV2",
      "rule_id": "R-PHI-002",
      "severity": "CRITICAL",
      "version": 1
    }
  ],
  "sequence": 1,
  "signals": [
    {
      "confidence": 1.0,
      "source": "rule",
      "type": "rule.phishing",
      "value": {
        "quote": "رمز دوم",
        "span": [
          41,
          48
        ]
      },
      "weight": 100
    }
  ],
  "verdict": "BLOCK",
  "versions": {
    "policy": "1.0.0",
    "prompt": null,
    "ruleset": "2026-10-15T06:00:00Z#1",
    "text_model": null,
    "vision_model": null
  }
}
```

Sent with the outbound HMAC secret `example-outbound-hmac-secret` (an illustration, never a
real credential) at attempt time 1792046527, the headers are:

```http
POST /panel/callback HTTP/1.1
Authorization: Bearer <outbound api key>
X-Guard-Event-Id: e0000000-0000-4000-8000-000000000001
Idempotency-Key: e0000000-0000-4000-8000-000000000001
X-Guard-Timestamp: 1792046527
X-Guard-Signature: hmac-sha256=6c6ef56b91646fcdd829c1a24d67028c4a7c6fed36f7a8b366156e6e80a8f26d
Content-Type: application/json
```

(`tests/unit/test_api_docs.py` validates the example with `DecisionEvent.model_validate_json`
and verifies this signature over its canonical bytes.)

### Operator final

After a `decision.interim`, the message waits for an operator in the dashboard. The operator's
approval or rejection is a `decision.final` (normally `sequence: 2`) written in one
transaction with the review closure and its audit row (ADR 0028). Its fields:

| Field | Operator final |
|---|---|
| `verdict` / `reason_code` | `ALLOW` + `OPERATOR_APPROVED`, or `BLOCK` + `OPERATOR_REJECTED` |
| `reason` | the code's fixed Persian sentence |
| `explanation` | the code's template with the operator's catalogue reason, then « یادداشت اپراتور: «…»» when the operator wrote a panel note |
| `risk_score`, `rule_hits`, `signals`, `links`, `versions` | copied verbatim from the interim (the evidence the operator saw; nothing is re-evaluated) |
| `confidence` | `1.0` (the operator bears the reason) |
| `decided_by` | `{"type": "operator", "id": "<opaque user id>"}` |
| `operator_note` | the panel-facing note when written (≤ 500 characters, control/bidi characters removed); **omitted** otherwise. Internal notes never leave sms-guard. |
| `evidence_url` | the review page, as on every event |

A final may arrive although its interim was never delivered (dead-lettered): apply it. A panel
`cancel` after an operator final answers `409 ALREADY_FINAL`; an operator decision after a
cancel is refused in the dashboard — a message gets at most one of the two.

Example (canonical key order, pretty-printed):

```json
{
  "confidence": 1.0,
  "decided_at": "2026-10-15T07:03:41.207000+00:00",
  "decided_by": {
    "id": "6f1c2d4e-9a7b-4c3d-8e2f-1a2b3c4d5e6f",
    "type": "operator"
  },
  "event": "decision.final",
  "event_id": "e0000000-0000-4000-8000-000000000002",
  "evidence_url": "https://guard.internal.example/review/0d2f7b1e-6a0c-4a9e-9d1f-2f3a7e9b1c44",
  "explanation": "اپراتور پیام را بررسی کرد و مجوز ارسال آن را صادر کرد. دلیل: تشخیص اشتباه سامانه. یادداشت اپراتور: «فرستنده و متن پیام بررسی شد.»",
  "guard_id": "0d2f7b1e-6a0c-4a9e-9d1f-2f3a7e9b1c44",
  "is_final": true,
  "links": [],
  "message_id": "panel-msg-8841237",
  "operator_note": "فرستنده و متن پیام بررسی شد.",
  "reason": "پیام توسط اپراتور بررسی و برای ارسال تأیید شد.",
  "reason_code": "OPERATOR_APPROVED",
  "risk_score": 58,
  "rule_hits": [
    {
      "action": "REVIEW",
      "name": "تبلیغ انبوه",
      "rule_id": "R-ADV-003",
      "severity": "MEDIUM",
      "version": 1
    }
  ],
  "sequence": 2,
  "signals": [
    {
      "confidence": 1.0,
      "source": "rule",
      "type": "rule.advertising",
      "value": {
        "quote": "تخفیف ویژه",
        "span": [
          12,
          22
        ]
      },
      "weight": 58
    }
  ],
  "verdict": "ALLOW",
  "versions": {
    "policy": "1.0.0",
    "prompt": null,
    "ruleset": "2026-10-15T06:00:00Z#1",
    "text_model": null,
    "vision_model": null
  }
}
```

Sent with the same illustration secret at attempt time 1792047127:

```http
POST /panel/callback HTTP/1.1
Authorization: Bearer <outbound api key>
X-Guard-Event-Id: e0000000-0000-4000-8000-000000000002
Idempotency-Key: e0000000-0000-4000-8000-000000000002
X-Guard-Timestamp: 1792047127
X-Guard-Signature: hmac-sha256=7f44518f6699ddfaff43e29313e71e0dc4f309413f6a39c6ce937b39ec59cd81
Content-Type: application/json
```

(`tests/unit/test_api_docs.py` validates this example as an operator final and verifies its
signature.)

## Panel response and retries

- **Any `2xx` = delivered.** The response body is ignored.
- **Anything else = retry:** 3xx (not followed), every 4xx (including 400, 401, 409), 5xx,
  timeouts, connection, DNS and TLS errors. A panel `Retry-After` (seconds or HTTP-date) is
  honoured up to 1 h.
- Backoff after attempts 1–8: `1s, 5s, 30s, 2m, 10m, 30m, 1h, 2h` (±10 % jitter,
  `SMSGUARD_OUTBOX_RETRY_SCHEDULE`). **After 9 failed attempts the event is dead-lettered**
  (`callback_outbox.status = DEAD`) and an alert fires; an operator can retry it manually.
  The panel can always poll `GET /api/v1/messages/{guard_id}` instead.
- Local failures that no retry can fix (callback URL no longer allowlisted, private host,
  missing credentials, inactive client) dead-letter immediately.

## Ordering and dedupe rules for the panel

1. **Dedupe on `event_id`.** The same event can arrive more than once (a timeout after the
   panel processed it). Answer `2xx` to a duplicate without re-applying it.
2. **Per guard, events are sent in `sequence` order**: a later event is not sent while an
   earlier one is still pending, retrying or in flight. A dead-lettered event does not
   block later ones, so a gap (e.g. sequence 2 without 1) is possible.
3. **Apply the highest `sequence` per `guard_id`**; ignore an event whose `sequence` is not
   greater than the last applied one. A `decision.final` is terminal: nothing after it
   changes the outcome.
4. **Send the SMS only on a `decision.final` with `verdict: ALLOW`.** Anything else — BLOCK,
   MANUAL_REVIEW, a missing callback, a signature failure — means do not send.
