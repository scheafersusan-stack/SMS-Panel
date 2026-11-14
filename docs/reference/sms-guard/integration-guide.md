<div dir="rtl" lang="fa-IR">

# راهنمای یکپارچه‌سازی پنل با sms-guard

## خلاصه برای تیم پنل

این بخش خلاصهٔ فارسی راهنماست. متن کامل و دقیق، با نمونه‌های امضا و جدول خطاها، به انگلیسی و در ادامه آمده است. اگر میان این خلاصه و متن انگلیسی تفاوتی دیدید، متن انگلیسی و فایل `panel-api.yaml` مرجع است.

**قاعدهٔ اصلی: بسته‌ماندن در خطا.** پنل فقط وقتی پیامکی را ارسال می‌کند که برای همان پیام رویداد نهایی (`decision.final`) با تصمیم `ALLOW` دریافت کرده باشد. هر حالت دیگر یعنی ارسال نشود: تصمیم `BLOCK`، تصمیم موقت `MANUAL_REVIEW`، پایان مهلت، نبودِ پاسخ، هر خطای 5xx (از جمله `MAINTENANCE_MODE`)، امضای نامعتبر، callbackی که بدنه‌اش با طرح منتشرشده نمی‌خواند، و هر تصمیم ناشناخته. شک هرگز به ارسال نمی‌انجامد.

**گام‌های کار**

1. هر پیام را با `POST /api/v1/messages` ثبت کنید. پاسخ ۲۰۲ یعنی پیام پذیرفته شده و هنوز تصمیمی نیست.
2. هر درخواست با کلید API و امضای HMAC-SHA256 همراه است. امضا از `زمان + "." + بدنهٔ خام` با رمز مشترک ساخته می‌شود و زمان باید حداکثر ۳۰۰ ثانیه با ساعت سرور اختلاف داشته باشد. ساعت سرورهای پنل را با NTP همگام نگه دارید.
3. در `POST /api/v1/messages` سرآیند `Idempotency-Key` الزامی است. با همان کلید و همان بدنه می‌توانید با خیال راحت دوباره تلاش کنید؛ پیام دوبار ثبت نمی‌شود.
4. تصمیم از دو راه می‌رسد: callback امضاشده از طرف sms-guard، و استعلام `GET /api/v1/messages/{guard_id}`. اگر callback دیر کرد، استعلام کنید.
5. callback را قبل از هر کاری با بدنهٔ خامِ دریافتی و رمز خروجی راستی‌آزمایی کنید، بر پایهٔ `event_id` تکراری‌ها را حذف کنید و بالاترین `sequence` را اعمال کنید. بدنه را سخت‌گیرانه با طرح منتشرشده بسنجید: رویداد ناشناخته، فیلد اضافه یا ناشناخته، بدنهٔ ناخوانا یا ناسازگاری `is_final`، `event` و `verdict` یعنی رد کنید، پیامکی نفرستید و پاسخ غیر ۲xx بدهید. ارسال فقط با `event=decision.final`، `is_final: true` و `verdict=ALLOW` مجاز است. هر پاسخ ۲xx یعنی «دریافت شد»؛ با هر پاسخ دیگری sms-guard همان رویداد را دوباره می‌فرستد.
6. نشانی callback باید در فهرست مجاز مشتری ثبت شده باشد و `https` باشد. نشانی خارج از فهرست با خطای ۴۲۲ رد می‌شود.
7. برای لغو پیام از `POST /api/v1/messages/{guard_id}/cancel` استفاده کنید. لغو callback نمی‌فرستد.
8. پیش از راه‌اندازی، فهرست [Go-live checklist](#go-live-checklist) را روی محیط آزمایشی کامل کنید.

</div>

## Who this is for

This guide is for the team that operates the SMS panel and integrates it with sms-guard. It is the working procedure; the machine-readable contract is [`panel-api.yaml`](panel-api.yaml) (OpenAPI) and the callback body and delivery rules are in [`panel-callback.md`](panel-callback.md). Where this guide and those files differ, the files win; report the difference.

Every signature printed here is recomputed by a test (`tests/docs/test_integration_guide.py`) with the same signing function the server uses, so an example you copy verifies. The secrets in the examples are illustrations, never real credentials.

The reference client is the mock panel (`apps/mock-panel`, `GuardClient` in `guard_client.py` for requests and `callback_auth.py` for callback verification). Until the production panel API documentation is delivered, the adapter in the deployment is the mock-panel contract described here.

## Fail-closed rules for the panel

sms-guard decides; the panel sends. The contract is one sentence: **send an SMS only after a `decision.final` callback (or a poll that shows the same final decision) with verdict `ALLOW` for that message. Anything else, including no answer, means do not send.**

| Situation | What the panel does |
|---|---|
| `decision.final`, verdict `ALLOW` | Send. This is the only case. |
| `decision.final`, verdict `BLOCK` | Do not send. |
| `decision.interim`, verdict `MANUAL_REVIEW` | Do not send; wait for the final. An interim event is never `ALLOW`. |
| `Verdict` value the panel does not know | Do not send. |
| No callback by `decision_deadline_at` | Do not send. Poll. A late answer arrives as an interim `MANUAL_REVIEW`, never as an implicit `ALLOW`. |
| Timeout, connection error, TLS error on submit, poll or cancel | Do not send. Retry with the same `Idempotency-Key`, or poll. |
| `5xx`, including `503 MAINTENANCE_MODE` and `503 SERVICE_UNAVAILABLE` | Do not send. Retry after the wait. |
| A callback whose signature, timestamp, bearer key or event id header does not verify | Reject it (not `2xx`) and do not act on it. |
| A callback body that does not validate as `DecisionEvent`: not parseable, an unknown `event` or `verdict`, an unknown or extra field, a missing field, or `is_final`, `event` and `verdict` that disagree (for example a final with `is_final: false`, `MANUAL_REVIEW` on a final, `ALLOW` on an interim) | Reject it with a non-`2xx` answer (sms-guard retries it and, if it never validates, dead-letters it for the operators), do not act on it and do not send. |
| A cancel answered `200`, or a message with status `CANCELLED` | Do not send. |

A message that was never accepted (no `202`) has no decision, so it is never sent. The panel holds it and resubmits with the same `Idempotency-Key`.

Verdicts are `ALLOW`, `BLOCK` and `MANUAL_REVIEW`. Callback events are `decision.interim` (always `MANUAL_REVIEW`, at most one per message) and `decision.final` (`ALLOW` or `BLOCK`, at most one per message). After an interim, the final comes from a human operator in the guard dashboard and can take minutes or hours.

## Authentication and signing

Every `/api/v1/messages*` request carries:

| Header | Value |
|---|---|
| `Authorization` | `Bearer sg_<key_id>_<secret>`: the inbound API key issued to the panel, exactly one header. |
| `X-Guard-Timestamp` | Unix epoch seconds as a canonical decimal (no sign, no leading zero), within 300 s of the server's clock. Exactly one header. |
| `X-Guard-Signature` | `hmac-sha256=` followed by 64 hex characters. Exactly one header. |
| `Idempotency-Key` | `POST /api/v1/messages` only: 1 to 255 visible ASCII characters. |
| `Content-Type` | `application/json` on POST. `Content-Encoding` must be absent or `identity`. |
| `X-Request-Id` | Optional: 1 to 128 characters from `A-Z a-z 0-9 . _ : -`. Returned on every response and logged; quote it when you report a problem. |

The signature is

```
signature = "hmac-sha256=" + hex(HMAC_SHA256(key = ASCII bytes of the inbound HMAC secret,
                                             msg = X-Guard-Timestamp + "." + raw_body))
```

- `raw_body` is the exact bytes you send. Serialise once, sign those bytes, send those bytes. Never sign an object and let the HTTP library serialise it again.
- A `GET` has no body and signs `"<timestamp>."`.
- The key is the secret string itself, as ASCII bytes (it is not hex-decoded).
- Use a fresh timestamp and a fresh signature on every attempt, including retries.
- A signature may be used for one method and path only; the same signature sent to another path is `REPLAY_DETECTED`.

The checks run in a fixed order, so the first failing one is the answer you see: maintenance, body size (64 KiB), content type, API key, timestamp, signature, replay, rate limit, JSON syntax, field validation, conflicts. A signature failure has one error code and one message whatever the cause (a wrong secret, a wrong body and a wrong header shape are indistinguishable by design).

### Worked example

With the example inbound HMAC secret `example-secret-not-real-0000000000`, this request is signed at timestamp 1792570500. The body is one line, UTF-8, no trailing newline, written by the canonical serialiser (sorted keys, compact separators); any valid JSON bytes work as long as you sign the bytes you send. Note the Persian text is raw UTF-8, not `\u` escapes.

```http
POST /api/v1/messages HTTP/1.1
Host: guard.internal.example
Authorization: Bearer sg_EXAMPLEKEYID_example-api-key-not-real
X-Guard-Timestamp: 1792570500
X-Guard-Signature: hmac-sha256=899d62cde4a6c60686b5a79b7e0d1970761f79e9db917bde8d363bb6abca42b3
Idempotency-Key: panel-msg-20261021-0001
X-Request-Id: panel-7f3a21
Content-Type: application/json

{"account":{"id":"acc-1042","name":"فروشگاه نمونه","tags":["retail"],"tier":"standard"},"callback_url":"https://panel.example/guard/callback","context":{"campaign_id":"camp-9","channel":"web"},"message_id":"panel-msg-20261021-0001","recipients":{"count":1200,"list_id":"list-77","sample_masked":["0912***4567"]},"sender":{"line":"3000-EXAMPLE","line_type":"service"},"submitted_at":"2026-10-21T08:15:00+00:00","text":"فروشگاه نمونه: تا پایان هفته همه کالاها ۲۰ درصد تخفیف دارند."}
```

The `Authorization` value in the example is a placeholder shape, not a key. The signature does not cover it.

### Reference code

This is the complete signing and verification logic in standard-library Python. The test executes this exact block against every example in this guide.

```python
import hashlib
import hmac
import json
import re

WINDOW_SECONDS = 300
_TIMESTAMP = re.compile(r"[1-9][0-9]{0,19}", re.ASCII)
_SIGNATURE = re.compile(r"hmac-sha256=([0-9a-fA-F]{64})", re.ASCII)


def sign(secret: str, timestamp: str, raw_body: bytes) -> str:
    message = timestamp.encode("ascii") + b"." + raw_body
    digest = hmac.new(secret.encode("ascii"), message, hashlib.sha256).hexdigest()
    return "hmac-sha256=" + digest


def verify_signed(secret: str, headers: dict, raw_body: bytes, *, now: int) -> None:
    """Raise ValueError unless the request or callback is authentic and fresh."""
    lowered = {name.lower(): value for name, value in headers.items()}
    timestamp = lowered.get("x-guard-timestamp", "")
    if not _TIMESTAMP.fullmatch(timestamp):
        raise ValueError("TIMESTAMP_INVALID")
    if abs(now - int(timestamp)) > WINDOW_SECONDS:
        raise ValueError("TIMESTAMP_OUT_OF_WINDOW")
    match = _SIGNATURE.fullmatch(lowered.get("x-guard-signature", ""))
    expected = sign(secret, timestamp, raw_body)[len("hmac-sha256="):]
    if match is None or not hmac.compare_digest(expected, match.group(1).lower()):
        raise ValueError("SIGNATURE_INVALID")


_REQUIRED = frozenset({
    "event", "event_id", "guard_id", "message_id", "sequence", "verdict", "is_final",
    "risk_score", "confidence", "reason_code", "reason", "explanation", "rule_hits", "signals",
    "links", "evidence_url", "decided_at", "decided_by", "versions",
})
_OPTIONAL = frozenset({"operator_note"})
_SHAPES = {  # event -> (allowed verdicts, is_final)
    "decision.interim": ({"MANUAL_REVIEW"}, False),
    "decision.final": ({"ALLOW", "BLOCK"}, True),
}


def verify_callback(secret: str, api_key: str, headers: list, raw_body: bytes, *, now: int) -> dict:
    # Authenticate and strictly validate a callback; return the event or raise ValueError.
    # headers is a list of (name, value) pairs, so a repeated header is visible.
    # Whatever raises here is answered with a non-2xx status and never acted on.
    lowered = [(name.lower(), value) for name, value in headers]
    single = {}
    for name in ("authorization", "x-guard-timestamp", "x-guard-signature",
                 "x-guard-event-id", "idempotency-key"):
        values = [value for key, value in lowered if key == name]
        if len(values) != 1:
            raise ValueError("HEADER_NOT_EXACTLY_ONCE: " + name)
        single[name] = values[0]
    if not hmac.compare_digest(single["authorization"].encode(), ("Bearer " + api_key).encode()):
        raise ValueError("INVALID_API_KEY")
    verify_signed(secret, single, raw_body, now=now)  # raw bytes, never re-serialised JSON
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except ValueError:
        raise ValueError("INVALID_EVENT") from None
    if not isinstance(event, dict):
        raise ValueError("INVALID_EVENT")
    if not _REQUIRED <= event.keys() or not event.keys() <= _REQUIRED | _OPTIONAL:
        raise ValueError("INVALID_EVENT")
    kind, verdict = event["event"], event["verdict"]
    if not isinstance(kind, str) or not isinstance(verdict, str) or kind not in _SHAPES:
        raise ValueError("INVALID_EVENT")
    verdicts, is_final = _SHAPES[kind]
    if verdict not in verdicts or event["is_final"] is not is_final:
        raise ValueError("INVALID_EVENT")
    if single["x-guard-event-id"] != event["event_id"] or single["idempotency-key"] != event["event_id"]:
        raise ValueError("EVENT_ID_MISMATCH")
    return event


def may_send(event: dict) -> bool:
    """The only case in which the panel sends: a final ALLOW."""
    return (event["event"] == "decision.final" and event["is_final"] is True
            and event["verdict"] == "ALLOW")
```

To send a request, serialise the body once, take `timestamp = str(int(time.time()))`, set `X-Guard-Signature` to `sign(secret, timestamp, body)` and send `body` itself as the request content.

## Submit

`POST /api/v1/messages` (operation `submitMessage`) stores the message as `PENDING` and returns `202` at once. The decision arrives later by callback or poll.

Body (`IngestRequest`, extra fields are refused):

| Field | Rule |
|---|---|
| `message_id` | Required. The panel's own id, 1 to 128 characters, no control characters. |
| `account` | Required: `id` (1-64), `name` (1-200), `tier` (1-32), optional `tags` (up to 20, each up to 32). |
| `sender` | Required: `line` (1-32), `line_type` (1-32). |
| `recipients` | Required: `count` (1 to 10 000 000), optional `sample_masked` (up to 10 masked samples), optional `list_id`. Never send full recipient numbers. |
| `text` | Required, 1 to 2000 characters. |
| `submitted_at` | Required, ISO-8601 with an offset. |
| `scheduled_at` | Optional, ISO-8601 with an offset. |
| `context` | Optional; only `campaign_id`, `template_id`, `client_ip` and `channel` (each up to 128) are accepted. |
| `callback_url` | Optional absolute URL (up to 2048 characters). Defaults to the client's registered callback URL. Must pass the allowlist, see [Callbacks](#callbacks). |

The `202` body (`IngestAccepted`):

```json
{
  "guard_id": "0d2f7b1e-6a0c-4a9e-9d1f-2f3a7e9b1c44",
  "message_id": "panel-msg-20261021-0001",
  "status": "PENDING",
  "received_at": "2026-10-21T08:15:00.412000+00:00",
  "decision_deadline_at": "2026-10-21T08:30:00.412000+00:00",
  "poll_url": "/api/v1/messages/0d2f7b1e-6a0c-4a9e-9d1f-2f3a7e9b1c44"
}
```

Store `guard_id` next to your message. `decision_deadline_at` is the time after which sms-guard escalates a still-undecided message to manual review (default 900 s after receipt). It is not a permission to send.

### Idempotency keys

- Use a stable key per logical message, for example your `message_id`. A retry of the same request must reuse the key.
- Same key and the same request (compared by the canonical JSON of the validated request, so key order and whitespace do not matter): the original `202` body is replayed with `Idempotent-Replayed: true`. No second message is created.
- Same key and a different request: `409 IDEMPOTENCY_KEY_REUSED`. Never change a message under a key you already used. `details` carries `guard_id`, `status` and `poll_url` of the existing message.
- The same `message_id` under another key: `409 MESSAGE_ID_ALREADY_REGISTERED`, with the same `details`. Poll the `guard_id` it names.
- A missing key is `400 MISSING_IDEMPOTENCY_KEY`; a repeated or malformed one is `400 INVALID_IDEMPOTENCY_KEY`.

After a timeout or a connection error on submit you do not know whether the message was stored. Resubmit with the same key: you get either the original `202` or a fresh one. Never generate a new key for a retry.

## Poll

`GET /api/v1/messages/{guard_id}` (operation `pollMessage`) returns the latest state. The body signs the empty string, so the signed message is `"<timestamp>."`.

```http
GET /api/v1/messages/0d2f7b1e-6a0c-4a9e-9d1f-2f3a7e9b1c44 HTTP/1.1
Host: guard.internal.example
Authorization: Bearer sg_EXAMPLEKEYID_example-api-key-not-real
X-Guard-Timestamp: 1792570560
X-Guard-Signature: hmac-sha256=da896ad819c4939abbb854f8c143db7fd1aa8e1263c00a42fcb25872df319a1b
```

The response (`MessagePollResponse`) always has every key (`null` or `[]` when empty): `guard_id`, `message_id`, `status` (`PENDING`, `UNDER_REVIEW`, `ALLOWED`, `BLOCKED`, `CANCELLED`), `received_at`, `decision_deadline_at`, `finalized_at`, `decision` (the latest event, same structure as the callback body), `cancellation`, `callbacks` (delivery state of each event) and `timeline`.

Send only when `decision.event` is `decision.final`, `decision.is_final` is `true` and `decision.verdict` is `ALLOW` (status `ALLOWED`). `UNDER_REVIEW` and `PENDING` mean wait. A `guard_id` that does not exist for your client is `404 NOT_FOUND`.

Poll when a callback is late, not in a tight loop. Recommended (not part of the contract): back off, for example 5 s, then 15 s, then every 60 s, and respect the read rate limit. Polling is the safety net for a dead-lettered callback.

## Cancel

`POST /api/v1/messages/{guard_id}/cancel` (operation `cancelMessage`) withdraws a message that is `PENDING` or `UNDER_REVIEW`. The body repeats the `guard_id` and may give a reason (up to 256 characters):

```http
POST /api/v1/messages/0d2f7b1e-6a0c-4a9e-9d1f-2f3a7e9b1c44/cancel HTTP/1.1
Host: guard.internal.example
Authorization: Bearer sg_EXAMPLEKEYID_example-api-key-not-real
X-Guard-Timestamp: 1792571100
X-Guard-Signature: hmac-sha256=40c896cfacc011dba79053f9b75266ec4476113e6f8ae5f15b9eed5792125f4c
Content-Type: application/json

{"guard_id":"0d2f7b1e-6a0c-4a9e-9d1f-2f3a7e9b1c44","reason":"customer withdrew the campaign"}
```

- `200` returns the `CancelResponse` with status `CANCELLED`. Repeating the cancel returns the same `200`.
- A body `guard_id` that differs from the path is `422 GUARD_ID_MISMATCH`.
- A message whose final decision was already made is `409 ALREADY_FINAL`: poll for that final decision instead.
- **A cancel sends no callback.** Events not yet delivered are superseded. Your `200` is the confirmation.
- A cancelled message must not be sent. A human decision on a cancelled message is refused in the dashboard, so a message ends in exactly one of cancelled or decided.

## Callbacks

sms-guard calls the panel with each decision event: `POST <callback_url>` with the body `DecisionEvent`, delivered by the outbox in the `api-jobs` process. The full field list, the operator-final rules and the delivery schedule are in [`panel-callback.md`](panel-callback.md); this section is what the panel must implement.

### Headers sent to you

| Header | Value |
|---|---|
| `Authorization` | `Bearer <outbound api key>`: a different key from the inbound one. |
| `X-Guard-Event-Id` | The `event_id` of the body. |
| `Idempotency-Key` | The same `event_id` string. |
| `X-Guard-Timestamp` | Epoch seconds of this attempt. |
| `X-Guard-Signature` | `hmac-sha256=<64 hex>` over `timestamp + "." + raw_body` with the **outbound** HMAC secret. |
| `Content-Type` | `application/json` |

Every header appears exactly once, and `X-Guard-Event-Id` equals `Idempotency-Key` equals the body's `event_id`. The body is the canonical JSON of the event (sorted keys, compact, raw UTF-8, no trailing newline), frozen when the decision was committed: a retry sends the same bytes with a new timestamp and signature.

### Verify, in this order

1. Read the **raw** request body before any JSON parsing.
2. The bearer token equals your outbound API key (constant-time comparison).
3. Timestamp and signature with [`verify_callback`](#reference-code), using the outbound secret and a 300 s window. The reference function also checks steps 2 and 4, and that each header occurs once.
4. Validate the body strictly against the published schema ([`panel-callback.md`](panel-callback.md), `DecisionEvent`): it must parse, carry every field of the table and no field outside it (only `operator_note` is optional), have a known `event` and `verdict`, and be consistent: `decision.interim` has `is_final: false` and `MANUAL_REVIEW`; `decision.final` has `is_final: true` and `ALLOW` or `BLOCK`. Check that `X-Guard-Event-Id` and `Idempotency-Key` equal `event_id`. Anything else is refused.
5. Only then act on it. A callback that fails any step gets a non-2xx answer and changes nothing. The panel sends only when `event` is `decision.final`, `is_final` is `true` and `verdict` is `ALLOW`.

Example (the example outbound API key is `example-outbound-api-key-not-real` and the example outbound HMAC secret is `example-outbound-secret-not-real-0000`; this is the operator-approved final from `panel-callback.md`, sent at timestamp 1792047127):

```http
POST /guard/callback HTTP/1.1
Host: panel.example
Authorization: Bearer example-outbound-api-key-not-real
X-Guard-Event-Id: e0000000-0000-4000-8000-000000000002
Idempotency-Key: e0000000-0000-4000-8000-000000000002
X-Guard-Timestamp: 1792047127
X-Guard-Signature: hmac-sha256=6193d223f95a5f55bd7a3e8198350c5d94f3d8a0c3f3861f3253b605035f15d7
Content-Type: application/json

{"confidence":1.0,"decided_at":"2026-10-15T07:03:41.207000+00:00","decided_by":{"id":"6f1c2d4e-9a7b-4c3d-8e2f-1a2b3c4d5e6f","type":"operator"},"event":"decision.final","event_id":"e0000000-0000-4000-8000-000000000002","evidence_url":"https://guard.internal.example/review/0d2f7b1e-6a0c-4a9e-9d1f-2f3a7e9b1c44","explanation":"اپراتور پیام را بررسی کرد و مجوز ارسال آن را صادر کرد. دلیل: تشخیص اشتباه سامانه. یادداشت اپراتور: «فرستنده و متن پیام بررسی شد.»","guard_id":"0d2f7b1e-6a0c-4a9e-9d1f-2f3a7e9b1c44","is_final":true,"links":[],"message_id":"panel-msg-8841237","operator_note":"فرستنده و متن پیام بررسی شد.","reason":"پیام توسط اپراتور بررسی و برای ارسال تأیید شد.","reason_code":"OPERATOR_APPROVED","risk_score":58,"rule_hits":[{"action":"REVIEW","name":"تبلیغ انبوه","rule_id":"R-ADV-003","severity":"MEDIUM","version":1}],"sequence":2,"signals":[{"confidence":1.0,"source":"rule","type":"rule.advertising","value":{"quote":"تخفیف ویژه","span":[12,22]},"weight":58}],"verdict":"ALLOW","versions":{"policy":"1.0.0","prompt":null,"ruleset":"2026-10-15T06:00:00Z#1","text_model":null,"vision_model":null}}
```

### Answer, dedupe and order

- Answer **any `2xx`** once the event is safely recorded. The response body is ignored. Everything else is a failure and is retried: 3xx (redirects are never followed), every 4xx, every 5xx, timeouts and connection, DNS and TLS errors. Answer within 10 s: that is the per-attempt timeout.
- Retries follow `1s, 5s, 30s, 2m, 10m, 30m, 1h, 2h` (about ±10 % jitter). A `Retry-After` is honoured up to 1 h. After 9 failed attempts the event is dead-lettered and an operator is alerted; it can be retried by hand, and the panel can poll meanwhile.
- **Dedupe on `event_id`.** The same event can arrive twice (a timeout after you processed it). Answer `2xx` to a duplicate without applying it again.
- **Apply the highest `sequence` per `guard_id`.** Ignore an event whose `sequence` is not greater than the last one applied. A dead-lettered event does not block later ones, so a final can arrive without its interim: accept it.
- A `decision.final` is terminal. Cancel sends no callback.
- Send the SMS only on a `decision.final` with `is_final: true` and verdict `ALLOW` ([fail-closed rules](#fail-closed-rules-for-the-panel)).

### The callback URL allowlist

The callback target is checked twice: when the message is submitted (a bad `callback_url` is `422 VALIDATION_FAILED` with an error whose code is `CALLBACK_URL_NOT_ALLOWED`) and again at every delivery attempt. The allowlist belongs to your client and is set by the sms-guard operators when your client is created; ask them to change it. A request cannot widen it. A callback is **refused** and never sent when:

- the URL is not under an allowlist entry (same scheme, host and port, and the path equal to or below the entry's path; an entry `/cb/` does not match `/cb`);
- the scheme is not `https` (plain `http` is accepted only in development deployments);
- the URL is longer than 2048 characters, has userinfo (`user:pass@`), a fragment, whitespace or control characters, a backslash, an encoded slash (`%2f`, `%5c`) or a dot segment (`.`, `..`, `%2e`);
- the host is not a valid IDNA2008 name, or is an IP literal with a zone id;
- the host resolves to a non-public address (private, loopback, link-local, carrier-grade NAT, multicast, reserved, documentation ranges) or to an address in the operator's own blocked ranges. The name is resolved exactly once per attempt, every answer is checked, and the connection goes to that checked address (with your host name kept for TLS, so the certificate is verified against it). A mixed answer is refused as a whole.

Your callback endpoint therefore needs a public address, a valid certificate for its name (TLS is always verified) and a path that is stable. Refusals of this kind cannot be fixed by retrying: the event is dead-lettered at once, and the operators fix the allowlist and requeue it.

## Errors and retries

Every error body is `ErrorResponse`: `{"error_code", "message", "details", "request_id"}`, with `Cache-Control: no-store` and the `X-Request-Id` header. Branch on `error_code`, not on the message text.

Retry means: the same logical request, signed again with a fresh timestamp, may succeed later (after the stated wait or the stated fix). **In every row the message is not sent**, whatever the retry column says.

| error_code | HTTP | Retry | What to do |
|---|---|---|---|
| `MISSING_IDEMPOTENCY_KEY` | 400 | no | Add the `Idempotency-Key` header. |
| `INVALID_IDEMPOTENCY_KEY` | 400 | no | One header, 1-255 visible ASCII characters. |
| `UNSUPPORTED_CONTENT_ENCODING` | 400 | no | Send the body uncompressed. |
| `MALFORMED_JSON` | 400 | no | The body is not valid UTF-8 JSON. |
| `INVALID_API_KEY` | 401 | no | Key missing, repeated, malformed, unknown, inactive or past its rotation grace. Check the credentials with the operators. |
| `TIMESTAMP_INVALID` | 403 | no | One canonical-decimal `X-Guard-Timestamp` header. |
| `TIMESTAMP_OUT_OF_WINDOW` | 403 | yes | Fix the clock (NTP), then sign again with a fresh timestamp. |
| `SIGNATURE_INVALID` | 403 | no | Wrong secret, wrong bytes or malformed header; compare with the [worked example](#worked-example). |
| `REPLAY_DETECTED` | 403 | yes | That signature was used for another method or path. Sign again with a fresh timestamp. |
| `NOT_FOUND` | 404 | no | Unknown route, or a `guard_id` that is not yours. |
| `METHOD_NOT_ALLOWED` | 405 | no | Wrong method for the route. |
| `IDEMPOTENCY_KEY_REUSED` | 409 | no | Different body under a used key. Use `details.guard_id` and poll. |
| `MESSAGE_ID_ALREADY_REGISTERED` | 409 | no | Already registered under another key. Poll `details.guard_id`. |
| `ALREADY_FINAL` | 409 | no | Cancel came too late. Poll for the final decision. |
| `OUTBOX_NOT_RETRYABLE` | 409 | no | Development-only operator seam. Never returned on a panel route. |
| `PAYLOAD_TOO_LARGE` | 413 | no | The body is over 64 KiB. |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | no | `Content-Type` must be `application/json`. |
| `VALIDATION_FAILED` | 422 | no | `details.errors[]` lists `{field, code, message}`; code `CALLBACK_URL_NOT_ALLOWED` means the allowlist. |
| `GUARD_ID_MISMATCH` | 422 | no | The cancel body's `guard_id` differs from the path. |
| `RATE_LIMITED` | 429 | yes | Wait `Retry-After` seconds. |
| `INTERNAL_ERROR` | 500 | yes | Back off and retry with the same key; if it persists, quote `request_id`. |
| `MAINTENANCE_MODE` | 503 | yes | Wait `Retry-After` (60 s) and keep holding messages. |
| `SERVICE_UNAVAILABLE` | 503 | yes | A backing service is down and the guard fails closed. Back off and retry. |
| `CREDENTIALS_UNAVAILABLE` | 503 | yes | The server cannot read your stored secret. Retry with backoff and tell the operators if it lasts. |

Retry rules for the panel:

- Retry only the "yes" rows, and network errors and timeouts, with exponential backoff and jitter, and stop after a bounded time (recommended, not part of the contract: 1 s, 2 s, 4 s, up to 60 s). Honour `Retry-After` when present.
- A POST retry keeps the same `Idempotency-Key` and the same body, with a fresh timestamp and signature.
- Recommended (not part of the contract): set client timeouts, a connect timeout of a few seconds and a total timeout of about 10 s (the mock panel uses 10 s and at most 4 attempts, retrying only `429` and `503`).
- A retry never turns into a send: the answer to "may I send" is always a final `ALLOW`.

The remaining `ErrorCode` values belong to the operator dashboard API and are never returned on panel routes: `UNAUTHENTICATED`, `SESSION_EXPIRED`, `INVALID_CREDENTIALS`, `MFA_INVALID_CODE`, `MFA_REQUIRED`, `PASSWORD_CHANGE_REQUIRED`, `CSRF_INVALID`, `PERMISSION_DENIED`, `REVIEW_ESCALATED`, `MFA_ALREADY_ENROLLED`, `MFA_NOT_ENROLLED`, `MFA_REQUIRED_FOR_ROLE`, `LAST_ADMIN_PROTECTED`, `SELF_ACTION_FORBIDDEN`, `USERNAME_TAKEN`, `USER_INACTIVE`, `REVIEW_ALREADY_DECIDED`, `REVIEW_NOT_OPEN`, `REVIEW_LOCKED`, `REVIEW_ALREADY_ESCALATED`, `REVIEW_STALE`, `MESSAGE_CANCELLED`, `MESSAGE_NOT_IN_REVIEW`, `SELF_APPROVAL_REFUSED`, `RULE_ID_TAKEN`, `RULE_ID_MISMATCH`, `RULE_VERSION_FROZEN`, `RULE_VERSION_NOT_OWNED`, `RULE_INVALID_TRANSITION`, `RULE_TESTS_FAILED`, `COMPOSITE_REFERENCE_INACTIVE`, `LLM_RULE_LIMIT`, `RULESET_SELECTION_CHANGED`, `RULESET_COMPILE_FAILED`, `RULESET_TESTS_FAILED`, `LIST_ENTRY_EXISTS`, `LIST_ENTRY_INVALID_TRANSITION`, `LIST_ENTRY_NOT_OWNED`, `LIST_SELECTION_CHANGED`, `LIST_COMPILE_FAILED`, `POLICY_NO_CHANGE`, `POLICY_VERSION_FROZEN`, `POLICY_DRAFT_NOT_OWNED`, `POLICY_INVALID_TRANSITION`, `POLICY_DRAFT_STALE`, `LIST_KIND_NOT_AVAILABLE`, `PASSWORD_POLICY_VIOLATION`, `NOTE_REQUIRED`, `SETTING_UNKNOWN`, `SETTING_READ_ONLY`, `TOO_MANY_STREAMS`, `RULES_EVAL_BUSY`, `NOT_IMPLEMENTED`, `PROVIDER_CONFIG_STALE`, `PROVIDER_KEYRING_UNAVAILABLE`, `PROPOSAL_NOT_OPEN`, `ASSISTANT_TURN_BUSY`, `ASSISTANT_DISABLED`. They are documented in [`dashboard-api.yaml`](dashboard-api.yaml).

### Health and readiness

`GET /api/v1/health` is liveness and `GET /api/v1/ready` is readiness (`200` only when the database, Redis and the queue are ok, otherwise `503`; maintenance mode also answers `503`). Neither needs a signature. Use them for monitoring, never as permission to send.

## Rate limits

A token bucket per client. Ingest (`POST /api/v1/messages`) allows the client's `rate_limit` requests per minute (default 600). Poll and cancel share a read bucket ten times as large. Every authenticated response carries:

| Header | Meaning |
|---|---|
| `X-RateLimit-Limit` | The bucket size of the scope. |
| `X-RateLimit-Remaining` | Requests left now. |
| `X-RateLimit-Reset` | Seconds until the bucket is full again. |

A `429 RATE_LIMITED` adds `Retry-After` (seconds). Spread submissions, do not retry in a loop, and ask the operators for a higher limit before a large campaign. If the rate limiter itself is unavailable, submissions fail closed with `503 SERVICE_UNAVAILABLE`.

## Go-live checklist

Complete every item against the staging client before the production client is enabled. The operators run the procedure in the [panel integration runbook](../runbooks/panel-integration.md).

- [ ] Staging credentials received on the agreed channel (inbound key, inbound secret, outbound key, outbound secret), stored in the panel's secret store, not in source control or tickets.
- [ ] Server clocks are NTP-synchronised; skew is well under 300 s.
- [ ] The signature test passes: your implementation reproduces the signatures of the [worked example](#worked-example), the poll and cancel examples and the callback example in this guide byte for byte.
- [ ] Your callback endpoint is reachable at a public `https` address with a valid certificate, and its URL is on the client's allowlist (the operators confirm).
- [ ] A submitted test message returns `202`, and the same request replayed with the same `Idempotency-Key` returns the same `202` with `Idempotent-Replayed: true`.
- [ ] A callback is verified, deduplicated on `event_id`, ordered by `sequence`, and answered `2xx`; a tampered body, an old timestamp and a wrong key are each refused.
- [ ] Poll returns the same decision as the callback.
- [ ] Cancel of a pending message returns `200` and the message is not sent.
- [ ] Fail-closed test: with the guard stopped or unreachable, nothing is sent; `BLOCK`, `MANUAL_REVIEW`, `503 MAINTENANCE_MODE` and a missing callback each send nothing.
- [ ] Only a final `ALLOW` sends, and exactly once per `guard_id`.
- [ ] Your alerting fires on repeated `5xx`, `429` and on callbacks that stop arriving.
- [ ] Both teams know how credentials are rotated: the operators issue a new inbound pair with a grace window (24 h unless agreed otherwise), and the panel switches inside it. A new outbound pair comes with a switch instant (UTC): the panel installs it next to the old pair before that instant, accepts a callback under either pair during the overlap, and removes the old pair after it ([Outbound credential rotation](panel-callback.md#outbound-credential-rotation)).
