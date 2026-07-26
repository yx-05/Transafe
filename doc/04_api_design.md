# TranSafe — API Design Document

**Version**: 1.0.0
**Date**: 2026-07-26
**Status**: Approved for Hackathon Implementation

---

## Table of Contents

1. [API Overview](#1-api-overview)
2. [Authentication](#2-authentication)
3. [Common Conventions](#3-common-conventions)
4. [User App REST Endpoints — Triggers](#4-user-app-rest-endpoints--triggers)
   - 4.1 POST /api/v1/trigger/telemetry
   - 4.2 POST /api/v1/trigger/transaction
   - 4.3 POST /api/v1/trigger/call
   - 4.4 POST /api/v1/trigger/phishing
   - 4.5 POST /api/v1/trigger/report
   - 4.6 POST /api/v1/biometric/result ← biometric challenge callback
   - 4.7 POST /api/v1/call/{session_id}/takeover ← mid-call Listen→AUTO_TALK switch
5. [WebSocket Protocol — Pipeline Stream](#5-websocket-protocol)
6. [Phone Session WebSocket Protocol](#5b-phone-session-websocket-protocol)
7. [Admin REST Endpoints](#6-admin-rest-endpoints)
8. [Error Codes Reference](#7-error-codes-reference)
9. [Rate Limiting](#8-rate-limiting)

---

## 1. API Overview

| Group | Base Path | Protocol | Auth |
|-------|-----------|----------|------|
| User App Triggers | `/api/v1/trigger/` | REST (POST) | `X-API-Key` |
| Biometric Callback | `/api/v1/biometric/` | REST (POST) | `X-API-Key` |
| WebSocket Stream | `/ws/session/{session_id}` | WebSocket | `X-API-Key` (query param) |
| Phone Session — Events | `/ws/call/{call_session_id}/events` | WebSocket | `X-API-Key` (query param) |
| Phone Session — Audio | `/ws/call/{call_session_id}/audio` | WebSocket (binary, Opus/WebM) | `X-API-Key` (query param) |
| Admin Operations | `/admin/v1/` | REST | `X-Admin-Key` |
| Health Check | `/health` | REST (GET) | None |

**Base URL (local dev)**: `http://localhost:8000`

---

## 2. Authentication

### User App Endpoints

All `/api/v1/` and `/ws/` endpoints require:

```http
X-API-Key: <API_KEY env var value>
```

### Admin Endpoints

All `/admin/v1/` endpoints require:

```http
X-Admin-Key: <ADMIN_API_KEY env var value>
```

### WebSocket Authentication

Pass the API key as a query parameter (WebSocket headers are not universally supported):

```
ws://localhost:8000/ws/session/{session_id}?api_key=<API_KEY>
```

---

## 3. Common Conventions

### Request Headers

```http
Content-Type: application/json
X-API-Key: <key>
```

### Response Envelope

All REST responses follow this envelope:

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "timestamp": "2026-07-26T10:00:00Z"
}
```

On error:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "amount must be greater than 0",
    "details": { ... }
  },
  "timestamp": "2026-07-26T10:00:00Z"
}
```

### Pagination (Admin list endpoints)

```json
{
  "success": true,
  "data": {
    "items": [...],
    "total": 142,
    "page": 1,
    "page_size": 20,
    "has_next": true
  }
}
```

---

## 4. User App REST Endpoints — Triggers

All trigger endpoints follow the same **async pattern**:
1. Request is accepted immediately with `202 Accepted` and a `session_id`
2. The LangGraph pipeline runs asynchronously
3. Results are streamed via WebSocket using the returned `session_id`

---

### 4.1 POST /api/v1/trigger/telemetry

Trigger telemetry analysis when the app/page loads or when a transaction page is about to be submitted. For Web App deployments, this endpoint is enriched with three additional payload blocks (`session_metrics`, `behavioral_biometrics`, `browser_network_fingerprint`) that replace native mobile signals.

**Request**:
```json
{
  "user_id": "uuid-...",
  "session_id": "uuid-...",
  "device_id": "device-fingerprint-hash",
  "app_version": "2.3.1",
  "events": [
    {
      "event_type": "APP_OPEN",
      "event_value": null,
      "timestamp": "2026-07-26T10:00:00Z"
    },
    {
      "event_type": "SCREEN_VIEW",
      "event_value": "transfer",
      "timestamp": "2026-07-26T10:00:01Z"
    }
  ],
  "session_metrics": {
    "time_on_page_seconds": 38,
    "tab_switch_count": 3,
    "page_focused": true
  },
  "behavioral_biometrics": {
    "is_account_number_pasted": true,
    "avg_keystroke_flight_time_ms": 340,
    "backspace_count": 4,
    "mouse_cursor_erratic_score": 72,
    "device_tremor_detected": true
  },
  "browser_network_fingerprint": {
    "browser_fingerprint_hash": "a8f9c102b44e",
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
    "screen_resolution": "1440x900",
    "network_type": "4g",
    "browser_timezone": "Asia/Kuala_Lumpur"
  }
}
```

> All three blocks (`session_metrics`, `behavioral_biometrics`, `browser_network_fingerprint`) are **optional** — omit them for native app deployments. When present, the Telemetry Worker uses them as high-signal coercion indicators.

**Event types** (`event_type` enum):
| Value | Platform | Description |
|-------|----------|-------------|
| `APP_OPEN` | Native + Web | App/page launched (`visibilitychange` on web) |
| `APP_BACKGROUND` | Native + Web | App sent to background / tab hidden |
| `SCREEN_VIEW` | Native + Web | User navigated to screen/route (value = screen name) |
| `INPUT_FOCUS` | Native + Web | User tapped / clicked an input field |
| `COPY_PASTE` | Native + Web | Paste action detected (value = field name) |
| `SCREENSHOT` | Native only | Screenshot taken within app |
| `SCREEN_SHARE_DETECTED` | Native only | OS reports screen sharing active |
| `DEVICE_ORIENTATION_CHANGE` | Native + Web | Portrait/landscape switch (`DeviceOrientationEvent` on web) |

**`session_metrics` fields**:
| Field | Type | Description |
|-------|------|-------------|
| `time_on_page_seconds` | integer | Time elapsed on the current transaction page — very short or very long times are anomalous |
| `tab_switch_count` | integer | Number of times user switched browser tabs during this session — high count suggests following external instructions |
| `page_focused` | boolean | Whether the transaction page currently has browser focus |

**`behavioral_biometrics` fields**:
| Field | Type | Description |
|-------|------|-------------|
| `is_account_number_pasted` | boolean | Recipient account number was pasted rather than typed — strong scam coercion signal |
| `avg_keystroke_flight_time_ms` | float | Average time between keystrokes in ms — abnormally high values suggest hesitation or external dictation |
| `backspace_count` | integer | Number of backspace/delete keypresses during form fill — reflects uncertainty |
| `mouse_cursor_erratic_score` | integer (0–100) | Computed score for erratic mouse movement patterns; >60 is anomalous |
| `device_tremor_detected` | boolean | Derived from pointer jitter or `DeviceMotionEvent` — elevated tremor may indicate user distress |

**`browser_network_fingerprint` fields**:
| Field | Type | Description |
|-------|------|-------------|
| `browser_fingerprint_hash` | string | Canvas/font fingerprint hash — detects device anomaly or headless browser |
| `user_agent` | string | Full browser user agent string |
| `screen_resolution` | string | Screen resolution (e.g. `"1440x900"`) |
| `network_type` | string | Connection type from `navigator.connection.effectiveType`: `"4g"`, `"3g"`, `"2g"`, `"wifi"`, `"unknown"` |
| `browser_timezone` | string | IANA timezone from `Intl.DateTimeFormat` — cross-check against `user_id` home country |

**Response** `202 Accepted`:
```json
{
  "success": true,
  "data": {
    "session_id": "uuid-...",
    "message": "Telemetry analysis initiated. Connect to WebSocket for results."
  }
}
```

---

### 4.2 POST /api/v1/trigger/transaction

Trigger risk assessment before a transaction is executed.

**Request**:
```json
{
  "user_id": "uuid-...",
  "session_id": "uuid-...",
  "associated_case_id": "uuid-...", // optional, linked prior case ID (e.g. active call or phishing check)
  "transaction": {
    "transaction_id": "uuid-...",
    "sender_account": "1234-5678-9012-3456",
    "recipient_account": "9876-5432-1098-7654",
    "recipient_name": "JOHN DOE",
    "amount": 9800.00,
    "currency": "MYR",
    "description": "Investment payment",
    "initiated_at": "2026-07-26T02:14:00Z"
  }
}
```

**Response** `202 Accepted`:
```json
{
  "success": true,
  "data": {
    "session_id": "uuid-...",
    "transaction_id": "uuid-...",
    "message": "Risk assessment initiated. Connect to WebSocket for results.",
    "estimated_seconds": 10
  }
}
```

---

### 4.3 POST /api/v1/trigger/call

Trigger risk assessment for a browser-based WebRTC call and start a Phone Worker session (Listen Mode or Auto-Talk Mode). Both parties connect via browser-native WebRTC, and audio is tapped via WebSocket (`/ws/call/{call_session_id}/audio`) for real-time STT + scam analysis.

**Request**:
```json
{
  "user_id": "uuid-...",
  "session_id": "uuid-...",
  "associated_case_id": "uuid-...", // optional, links call to a prior phishing check
  "call": {
    "caller_number": "+60161234567",
    "caller_name": "Unknown",
    "call_direction": "INCOMING",
    "received_at": "2026-07-26T10:00:00Z",
    "is_during_banking_session": true,
    "call_mode": "LISTEN",
    "call_channel": "WEBRTC"
  }
}
```

**`call_channel` values**:
| Value | Platform | Description |
|-------|----------|-------------|
| `WEBRTC` | Web App | Call is conducted inside the browser using WebRTC (PeerJS / LiveKit OSS). Backend receives audio via `/ws/call/{call_session_id}/audio` WebSocket. |

**`call_mode` values**:
| Value | Description |
|-------|-------------|
| `LISTEN` | Phone Worker monitors the call and streams real-time highlight events to the user's browser/app. User speaks to the caller themselves. |
| `AUTO_TALK` | Phone Worker autonomously conducts the call via STT → LLM → TTS pipeline. AI speaks to the caller; user observes the transcript in real time. |
| `NONE` | No phone session started — only a pre-call number risk check is performed (default if omitted). |

**Response** `202 Accepted`:
```json
{
  "success": true,
  "data": {
    "session_id": "uuid-...",
    "call_session_id": "uuid-...",
    "call_mode": "LISTEN",
    "call_channel": "WEBRTC",
    "pre_check": {
      "blacklisted": true,
      "blacklist_cases": 2,
      "initial_risk": "HIGH",
      "warning": "This number has been reported 2 times for impersonation scams."
    },
    "message": "Phone session started in LISTEN mode (WebRTC). Stream audio to /ws/call/{call_session_id}/audio and connect to events at /ws/call/{call_session_id}/events",
    "ws_audio_url": "/ws/call/uuid-.../audio",
    "ws_events_url": "/ws/call/uuid-.../events"
  }
}
```

> **Note**: The `pre_check` response is returned **synchronously** before audio processing begins, allowing the browser to immediately display a risk warning banner.

#### WebRTC Audio Flow (Web App)

```
Browser (User Page)                      Backend
      │                                     │
      │  POST /api/v1/trigger/call          │
      │ ─────────────────────────────────► │  Returns call_session_id + ws_audio_url
      │                                     │
      │  WebRTC P2P audio established       │
      │  (Browser A ↔ Browser B via PeerJS) │
      │                                     │
      │  MediaRecorder chunks (Opus/WebM)   │
      │ ─── ws/call/{id}/audio ──────────► │  Groq Whisper STT → Phone Worker
      │                                     │  (real-time scam detection)
      │  WebSocket events (highlights)      │
      │ ◄─── ws/call/{id}/events ────────── │  Safety Copilot alerts pushed to browser
```

> **Implementation note**: The User-side browser records its local microphone stream using `MediaRecorder` and sends binary chunks (Opus/WebM, ~1 s intervals) to the backend audio WebSocket. The backend does NOT need direct P2P access — the server-side tap is achieved through the browser's own microphone capture, which includes the local speaker output when `echoCancellation: false` is set.

---

### 4.4 POST /api/v1/trigger/phishing

Submit suspicious content for phishing analysis.

**Request**:
```json
{
  "user_id": "uuid-...",
  "session_id": "uuid-...",
  "associated_case_id": "uuid-...", // optional, links analysis to an active call or case
  "material": {
    "content_type": "TEXT",
    "content": "URGENT: Your Maybank account has been compromised. Click http://maybank2u-verify.xyz to verify. Call 0161234567 immediately.",
    "source": "SMS"
  }
}
```

**`content_type` enum**:
| Value | `content` field | Backend processing |
|-------|----------------|-------------------|
| `TEXT` | Raw SMS / email / chat message text | Direct LLM analysis |
| `URL` | Single URL string | URL metadata analysis + LLM assessment |
| `IMAGE` | Base64-encoded screenshot (JPG/PNG) | OCR via Groq Vision → extracted text → LLM analysis |

> **IMAGE upload**: Encode the screenshot as base64 (`btoa()` on web, `Base64.encodeToString()` on Android/iOS) and pass the raw base64 string in `content`. Do not include a `data:image/...;base64,` prefix. Max image size: **4 MB** before base64 encoding.

**`source` enum**: `SMS`, `WHATSAPP`, `EMAIL`, `WEBSITE`, `OTHER`

**Response** `202 Accepted`:
```json
{
  "success": true,
  "data": {
    "session_id": "uuid-...",
    "message": "Phishing analysis initiated.",
    "estimated_seconds": 12
  }
}
```

---

### 4.5 POST /api/v1/trigger/report

Submit a fraud report.

**Request**:
```json
{
  "user_id": "uuid-...",
  "associated_case_id": "uuid-...", // optional, links report to a specific active case/phishing session
  "report": {
    "description": "I received a call from 0161234567 claiming to be from Bank Negara. They said my account was used for money laundering and I must transfer RM 5,000 to 'safe account' 7653-1234-5678-9012 or face arrest.",
    "phone_numbers": ["0161234567", "0197654321"],
    "bank_accounts": ["7653-1234-5678-9012"],
    "fraud_type": "IMPERSONATION_SCAM",
    "amount_lost_myr": 5000.00,
    "incident_date": "2026-07-25"
  }
}
```

**`fraud_type` enum**:
| Value | Description |
|-------|-------------|
| `MACAU_SCAM` | Caller impersonates police/government |
| `IMPERSONATION_SCAM` | Caller impersonates bank/utility |
| `INVESTMENT_SCAM` | Fake high-return investment |
| `LOVE_SCAM` | Romantic relationship fraud |
| `PHISHING` | Fake website/message |
| `PARCEL_SCAM` | Fake customs/delivery |
| `OTHER` | Other types |

**Response** `200 OK` (synchronous — no WebSocket needed):
```json
{
  "success": true,
  "data": {
    "case_id": "uuid-...",
    "message": "Thank you for your report. Your information helps protect other users.",
    "entities_recorded": {
      "phone_numbers": ["0161234567", "0197654321"],
      "bank_accounts": ["7653-1234-5678-9012"]
    }
  }
}
```

---

### 4.8 GET /api/v1/cases/recent

Fetch recent active call sessions or phishing submissions for a user within the past 2 hours. Used by the mobile app to prompt the user for confirmation: *"We detected an active call or phishing check in the last 2 hours. Is this transaction/report related to that incident?"* If the user selects "Yes", the transaction is initiated with the corresponding `associated_case_id`. If the user selects "No", the transaction executes with no link (or the user can choose another case from history).

**Parameters**:
* `user_id` (Query, UUID, Required)

**Request**:
```http
GET /api/v1/cases/recent?user_id=uuid-...
X-API-Key: <key>
```

**Response**:
```json
{
  "success": true,
  "data": {
    "has_recent_activity": true,
    "recent_cases": [
      {
        "case_id": "uuid-1234-5678",
        "trigger_type": "CALL",
        "caller_number": "+60161234567",
        "risk_tier": "HIGH",
        "created_at": "2026-07-26T18:30:00Z"
      }
    ]
  },
  "error": null,
  "timestamp": "2026-07-26T18:32:00Z"
}
```

---

### 4.7 POST /api/v1/call/{session_id}/takeover

Switch an active LISTEN mode call session to AUTO_TALK mode mid-call. Called when the user taps the "Let AI Answer" button in the app.

**Path Parameter**: `session_id` — the active call session ID returned by `POST /api/v1/trigger/call`

**Request**: No body required.

**Response** `200 OK`:
```json
{
  "success": true,
  "data": {
    "session_id": "uuid-...",
    "call_mode": "AUTO_TALK",
    "message": "TranSafe is now speaking on your behalf.",
    "ws_events_url": "/ws/call/uuid-.../events"
  }
}
```

**Error responses**:
| HTTP | Error Code | Condition |
|------|------------|-----------|
| 404 | `NOT_FOUND` | `session_id` does not exist or has already ended |
| 409 | `ALREADY_AUTO_TALK` | Session is already in AUTO_TALK mode |
| 422 | `CALL_ENDED` | Call session has ended — takeover not possible |

> **Note**: After takeover, the Phone Worker initialises its `dialogue_history` from the existing call transcript so it is aware of what has already been said. The call remains connected — no interruption to the audio stream.

---

### 4.6 POST /api/v1/biometric/result

Report the outcome of a biometric authentication challenge back to the backend. This endpoint is called by the mobile app after the device-side biometric verification (FaceID / fingerprint) completes.

**When to call**: Only after the backend has returned a MEDIUM risk response containing `"action": "BIOMETRIC_CHALLENGE"` for a transaction.

**Request**:
```json
{
  "user_id": "uuid-...",
  "session_id": "uuid-...",
  "transaction_id": "uuid-...",
  "biometric_result": "PASSED",
  "method": "FACE_ID",
  "attempted_at": "2026-07-26T10:01:45Z"
}
```

**`biometric_result` enum**:
| Value | Description |
|-------|-------------|
| `PASSED` | User successfully authenticated — proceed with transaction |
| `FAILED` | Authentication failed (e.g. face not recognised, fingerprint mismatch) |
| `DECLINED` | User cancelled the biometric prompt — treat as refusal |
| `UNAVAILABLE` | Device biometric not available; app fell back to PIN/pattern |

**`method` enum**: `FACE_ID`, `FINGERPRINT`, `PIN_FALLBACK`, `PATTERN_FALLBACK`

**Response** `200 OK`:
```json
{
  "success": true,
  "data": {
    "session_id": "uuid-...",
    "transaction_id": "uuid-...",
    "transaction_status": "approved",
    "message": "Biometric authentication passed. Transaction approved.",
    "message_ms": "Pengesahan biometrik berjaya. Transaksi diluluskan."
  }
}
```

**`transaction_status` values**:
| Value | Condition |
|-------|-----------|
| `approved` | `biometric_result` is `PASSED` |
| `blocked` | `biometric_result` is `FAILED` or `DECLINED` |
| `manual_review` | `biometric_result` is `UNAVAILABLE` — transaction held for admin review |

> **Backend actions on receipt**:
> 1. Update `transactions` record in Supabase: set `status` = `approved` / `blocked` / `manual_review`
> 2. Record the biometric attempt in `biometric_audit_log` table (method, result, timestamp, user_id, transaction_id)
> 3. Push a final `result` WebSocket message to the session so the app receives the decision
> 4. If `FAILED` and this is the **3rd consecutive failure** for this user, escalate risk tier to HIGH and trigger an admin alert

**Error — Session not found** `404`:
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "NOT_FOUND",
    "message": "No pending biometric challenge found for this session_id.",
    "details": {}
  }
}
```

**Error — Challenge already resolved** `409`:
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "CHALLENGE_ALREADY_RESOLVED",
    "message": "Biometric challenge for this transaction has already been processed.",
    "details": { "resolved_at": "2026-07-26T10:01:50Z", "transaction_status": "approved" }
  }
}
```

---

## 5. WebSocket Protocol

### Connection

```
WS ws://localhost:8000/ws/session/{session_id}?api_key=<API_KEY>
```

The `session_id` must match the one returned by the triggering REST endpoint.

### Message Direction

- **Server → Client**: Status updates and final result
- **Client → Server**: Heartbeat ping only (optional)

### Message Types (Server → Client)

All messages are JSON with a `type` field.

---

#### Type: `status`

Sent during pipeline execution to show progress.

```json
{
  "type": "status",
  "session_id": "uuid-...",
  "message": "Financial Worker: analysing 90-day transaction history...",
  "worker": "financial",
  "timestamp": "2026-07-26T10:00:03Z"
}
```

**Sequence of status messages** for a TRANSACTION trigger:
```
1. "Orchestrator: routing TRANSACTION trigger to [financial, telemetry, research]"
2. "Financial Worker: querying transaction history..."
3. "Telemetry Worker: analysing session behaviour..."
4. "Research Worker: checking recipient account against fraud database..."
5. "Research Worker: found 3 matching fraud cases"
6. "Risk Scorer: calculating final risk score..."
7. "Explainable AI: generating verdict explanation..."
8. "Action Dispatcher: executing HIGH risk response — freezing transaction"
```

---

#### Type: `result`

Final message — sent once the LangGraph pipeline completes.

```json
{
  "type": "result",
  "session_id": "uuid-...",
  "trigger_type": "TRANSACTION",
  "xai_report": {
    "session_id": "uuid-...",
    "trigger_type": "TRANSACTION",
    "risk_score": 82,
    "risk_tier": "HIGH",
    "verdict_summary": "This transaction shows multiple signs of a scam: the transfer amount is unusually large, the recipient has never received money from you before, and their account appears in our fraud database.",
    "verdict_summary_ms": "Transaksi ini menunjukkan beberapa tanda penipuan: jumlah pemindahan luar biasa besar, penerima tidak pernah menerima wang daripada anda sebelum ini, dan akaun mereka terdapat dalam pangkalan data penipuan kami.",
    "workers_activated": ["financial", "telemetry", "research"],
    "worker_findings": [
      {
        "worker": "financial",
        "score": 88,
        "confidence": 0.93,
        "evidence": [
          "Transfer amount RM 9,800 is 47x higher than 90-day average (RM 208)",
          "First-time recipient account",
          "Initiated at 02:14 AM — outside normal activity window"
        ]
      },
      {
        "worker": "telemetry",
        "score": 15,
        "confidence": 0.82,
        "evidence": [
          "Known device fingerprint",
          "Normal typing cadence"
        ]
      },
      {
        "worker": "research",
        "score": 95,
        "confidence": 0.97,
        "evidence": [
          "Recipient account found in fraud database — 3 prior cases",
          "Associated with Macau scam category"
        ]
      }
    ],
    "action_taken": "FREEZE_30_MIN",
    "unfreeze_at": "2026-07-26T10:30:00Z",
    "recommendation": "Do not proceed with this transfer. If someone called you and instructed this transfer, hang up immediately and call your bank's official number to verify.",
    "case_id": "uuid-..."
  },
  "timestamp": "2026-07-26T10:00:15Z"
}
```

---

#### Type: `error`

Sent if the pipeline encounters a fatal error.

```json
{
  "type": "error",
  "session_id": "uuid-...",
  "error_code": "GROQ_API_UNAVAILABLE",
  "message": "AI analysis service temporarily unavailable. Rule-based assessment applied.",
  "fallback_risk_tier": "MEDIUM",
  "timestamp": "2026-07-26T10:00:05Z"
}
```

---

#### Type: `ping` / `pong`

Client may send `{"type": "ping"}` to keep the connection alive. Server responds with `{"type": "pong"}`.

---

### WebSocket Connection Lifecycle

```
Client connects → Server validates API key
    ├─ Invalid key → Server closes with code 4001 (Unauthorized)
    └─ Valid key →
        ├─ Session not found → Server closes with code 4004 (Not Found)
        └─ Session active →
            ├─ Server streams status messages as pipeline runs
            ├─ Server sends result message when complete
            └─ Server closes connection with code 1000 (Normal Closure)
```

---

## 5b. Phone Session WebSocket Protocol

Phone Worker uses **two dedicated WebSocket connections** per call session, separate from the main pipeline WebSocket.

---

### 5b.1 Audio Stream — WS /ws/call/{call_session_id}/audio

**Direction**: Bidirectional
**Purpose**:
- **Client → Server**: Mobile app streams raw call audio (both Listen and Auto-Talk modes)
- **Server → Client** (Auto-Talk only): Backend sends TTS audio chunks to be played to the caller

**Connection**:
```
WS ws://localhost:8000/ws/call/{call_session_id}/audio?api_key=<API_KEY>
```

**Client → Server** (binary frames):
```
Frame format: binary
Content: PCM audio chunks (16kHz, 16-bit mono)
Chunk size: 1024 bytes (approximately 32ms per chunk)
```

**Server → Client** (Auto-Talk mode, binary frames):
```
Frame format: binary
Content: MP3 or WAV audio (TTS output to be played to caller)
Prepended with 4-byte little-endian uint32 indicating chunk length
```

**Control messages** (JSON text frames, Client → Server):
```json
{ "type": "call_start", "call_session_id": "uuid-...", "call_mode": "AUTO_TALK" }
{ "type": "call_end",   "call_session_id": "uuid-..." }
{ "type": "pause_tts"  }   // user pressed "take over" in AUTO_TALK mode
{ "type": "resume_tts" }   // user hands back to AI
```

---

### 5b.2 Events Stream — WS /ws/call/{call_session_id}/events

**Direction**: Server → Client only
**Purpose**: Push real-time highlight events, suspicion score updates, and final call analysis to the mobile app

**Connection**:
```
WS ws://localhost:8000/ws/call/{call_session_id}/events?api_key=<API_KEY>
```

---

#### Event: `pre_check_result`
Sent immediately when call session is created (before call is answered).
```json
{
  "type": "pre_check_result",
  "call_session_id": "uuid-...",
  "caller_number": "+60161234567",
  "blacklisted": true,
  "blacklist_case_count": 2,
  "spoofed_prefix": false,
  "initial_risk": "HIGH",
  "warning_text": "This number has been reported 2 times for impersonation scams.",
  "warning_text_ms": "Nombor ini telah dilaporkan 2 kali untuk penipuan penyamaran.",
  "timestamp": "2026-07-26T10:00:00Z"
}
```

---

#### Event: `transcript`
New utterance transcribed from audio stream.
```json
{
  "type": "transcript",
  "call_session_id": "uuid-...",
  "utterance_id": "utt-007",
  "speaker": "CALLER",
  "text": "Your account has been flagged for money laundering...",
  "timestamp": "2026-07-26T10:02:15Z"
}
```
`speaker` values: `"CALLER"` | `"AI"` (Auto-Talk mode) | `"USER"` (Listen mode if user speech captured)

---

#### Event: `highlight`
Real-time risk annotation for a transcribed utterance.
```json
{
  "type": "highlight",
  "call_session_id": "uuid-...",
  "utterance_id": "utt-007",
  "speaker": "CALLER",
  "text": "Your account has been flagged for money laundering. Transfer RM 5,000 to a safe account immediately or face arrest.",
  "spans": [
    {
      "start": 0,
      "end": 50,
      "text": "Your account has been flagged for money laundering",
      "risk_level": "HIGH",
      "tag": "false_accusation",
      "tag_label": "False accusation"
    },
    {
      "start": 52,
      "end": 99,
      "text": "Transfer RM 5,000 to a safe account immediately",
      "risk_level": "HIGH",
      "tag": "fund_transfer_request",
      "tag_label": "Fund transfer request"
    },
    {
      "start": 103,
      "end": 118,
      "text": "or face arrest",
      "risk_level": "HIGH",
      "tag": "coercion_threat",
      "tag_label": "Coercion / threat"
    }
  ],
  "utterance_risk_score": 97,
  "cumulative_suspicion_score": 78,
  "timestamp": "2026-07-26T10:02:16Z"
}
```

**`risk_level` values**: `"LOW"` | `"MEDIUM"` | `"HIGH"`

**`tag` values** (scam indicator categories):
| Tag | Label |
|-----|-------|
| `false_accusation` | False accusation |
| `fund_transfer_request` | Fund transfer request |
| `coercion_threat` | Coercion / threat |
| `urgency_pressure` | Urgency pressure |
| `otp_request` | OTP / credential request |
| `impersonation` | Impersonating authority |
| `safe_account` | "Safe account" mention |
| `investment_return` | Guaranteed investment return |
| `personal_info_request` | Personal info request |

---

#### Event: `suspicion_update`
Cumulative suspicion score update after each utterance analysis.
```json
{
  "type": "suspicion_update",
  "call_session_id": "uuid-...",
  "suspicion_score": 78,
  "risk_tier": "HIGH",
  "trigger_escalation": true,
  "escalation_reason": "Score exceeded 80 — Phishing Analyst dispatched for deep analysis",
  "timestamp": "2026-07-26T10:02:17Z"
}
```

---

#### Event: `ai_response` (Auto-Talk mode only)
What the AI said to the caller (shown on user's app screen).
```json
{
  "type": "ai_response",
  "call_session_id": "uuid-...",
  "utterance_id": "utt-008",
  "text": "I see. Could you please provide me your employee ID so I can verify your identity?",
  "anchor_question_asked": "AQ-1",
  "reasoning_summary": "Caller claimed to be from Bank Negara — AQ-1 triggered",
  "timestamp": "2026-07-26T10:02:20Z"
}
```

---

#### Event: `anchor_result` (Auto-Talk mode only)
Result of an anchor question attempt.
```json
{
  "type": "anchor_result",
  "call_session_id": "uuid-...",
  "anchor_id": "AQ-1",
  "question": "Could you provide your employee ID?",
  "caller_response": "Err... I don't have my ID with me right now.",
  "result": "FAILED",
  "scam_signal": "Could not provide employee ID — consistent with impersonator",
  "timestamp": "2026-07-26T10:02:35Z"
}
```
`result` values: `"PASSED"` | `"FAILED"` | `"EVASIVE"` | `"PENDING"`

---

#### Event: `call_result`
Final call analysis — sent when the call ends or is terminated.
```json
{
  "type": "call_result",
  "call_session_id": "uuid-...",
  "case_id": "uuid-...",
  "call_mode": "AUTO_TALK",
  "call_duration_seconds": 252,
  "final_risk_score": 91,
  "final_risk_tier": "HIGH",
  "verdict_summary": "This call exhibits all hallmarks of a Macau impersonation scam. The caller failed all 4 verification checks and repeatedly pressed for an immediate fund transfer.",
  "verdict_summary_ms": "Panggilan ini menunjukkan semua ciri-ciri penipuan penyamaran Macau. Pemanggil gagal semua 4 pemeriksaan pengesahan.",
  "action_taken": "FREEZE_30_MIN",
  "anchor_questions_summary": {
    "AQ-1": "FAILED",
    "AQ-2": "FAILED",
    "AQ-3": "CONFIRMED",
    "AQ-4": "FAILED"
  },
  "transcript_length_utterances": 18,
  "high_risk_utterances": 7,
  "timestamp": "2026-07-26T10:06:12Z"
}
```

---

### Phone Session WebSocket Lifecycle

```
App detects incoming call
    │
    ▼
POST /api/v1/trigger/call (with call_mode)
    │
    ├─→ pre_check_result event pushed immediately (before call answered)
    │
    ▼
App connects to /ws/call/{id}/events   (receive highlight events)
App connects to /ws/call/{id}/audio    (stream audio + receive TTS)
    │
    ▼
User answers call → audio streaming begins
    │
    ├─→ transcript events
    ├─→ highlight events (real-time)
    ├─→ suspicion_update events
    └─→ ai_response + anchor_result events (AUTO_TALK only)
    │
    ▼
Call ends (client sends call_end control message)
    │
    ▼
call_result event pushed
Both WebSocket connections closed (code 1000)
```



Base path: `/admin/v1/`
Auth header: `X-Admin-Key: <ADMIN_API_KEY>`

---

### 6.1 GET /admin/v1/cases

List fraud cases with optional filters.

**Query Parameters**:
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number |
| `page_size` | int | 20 | Results per page (max 100) |
| `risk_tier` | string | all | Filter: `LOW`, `MEDIUM`, `HIGH` |
| `status` | string | all | Filter: `approved`, `pending_biometric`, `frozen`, `reported` |
| `date_from` | ISO date | 30 days ago | Start date |
| `date_to` | ISO date | today | End date |
| `trigger_type` | string | all | Filter: `TRANSACTION`, `CALL`, `PHISHING`, `REPORT` |

**Response** `200 OK`:
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "case_id": "uuid-...",
        "user_id": "uuid-...",
        "trigger_type": "TRANSACTION",
        "risk_score": 82,
        "risk_tier": "HIGH",
        "status": "frozen",
        "action_taken": "FREEZE_30_MIN",
        "created_at": "2026-07-26T10:00:00Z",
        "verdict_summary": "Multiple fraud indicators detected..."
      }
    ],
    "total": 142,
    "page": 1,
    "page_size": 20,
    "has_next": true
  }
}
```

---

### 6.2 GET /admin/v1/cases/{case_id}

Retrieve full case detail including complete XAI report.

**Response** `200 OK`:
```json
{
  "success": true,
  "data": {
    "case_id": "uuid-...",
    "user_id": "uuid-...",
    "trigger_type": "TRANSACTION",
    "risk_score": 82,
    "risk_tier": "HIGH",
    "status": "frozen",
    "action_taken": "FREEZE_30_MIN",
    "unfreeze_at": "2026-07-26T10:30:00Z",
    "xai_report": { ... },
    "created_at": "2026-07-26T10:00:00Z",
    "updated_at": "2026-07-26T10:00:15Z"
  }
}
```

---

### 6.3 POST /admin/v1/accounts/{account_number}/freeze

Freeze an account (admin-initiated, different from auto-freeze).

**Request**:
```json
{
  "reason": "Confirmed fraud case #uuid-...",
  "case_id": "uuid-...",
  "admin_note": "Victim confirmed scam. Freezing pending investigation."
}
```

**Response** `200 OK`:
```json
{
  "success": true,
  "data": {
    "account_number": "1234-5678-9012-3456",
    "status": "frozen",
    "frozen_at": "2026-07-26T10:05:00Z",
    "frozen_by": "admin",
    "reason": "Confirmed fraud case #uuid-..."
  }
}
```

---

### 6.4 POST /admin/v1/accounts/{account_number}/unfreeze

Unfreeze an account.

**Request**:
```json
{
  "reason": "Transaction verified as legitimate by account holder.",
  "case_id": "uuid-...",
  "admin_note": "Customer called branch. Transfer confirmed voluntary."
}
```

**Response** `200 OK`:
```json
{
  "success": true,
  "data": {
    "account_number": "1234-5678-9012-3456",
    "status": "active",
    "unfrozen_at": "2026-07-26T10:10:00Z",
    "unfrozen_by": "admin"
  }
}
```

---

### 6.5 GET /admin/v1/analytics/summary

Dashboard summary statistics.

**Query Parameters**: `date_from`, `date_to` (ISO date strings)

**Response** `200 OK`:
```json
{
  "success": true,
  "data": {
    "period": {
      "from": "2026-07-01",
      "to": "2026-07-26"
    },
    "total_cases": 142,
    "by_risk_tier": {
      "LOW": 89,
      "MEDIUM": 35,
      "HIGH": 18
    },
    "by_trigger_type": {
      "TRANSACTION": 67,
      "CALL": 42,
      "PHISHING": 28,
      "REPORT": 5
    },
    "by_fraud_type": {
      "MACAU_SCAM": 31,
      "INVESTMENT_SCAM": 24,
      "IMPERSONATION_SCAM": 19,
      "PHISHING": 28,
      "OTHER": 40
    },
    "accounts_frozen": 12,
    "total_amount_protected_myr": 287500.00,
    "avg_risk_score": 52.3,
    "worker_activation_counts": {
      "financial": 67,
      "telemetry": 72,
      "research": 142,
      "phone": 42,
      "phishing": 28
    }
  }
}
```

---

### 6.6 GET /admin/v1/analytics/trend

Daily case count trend for charting.

**Query Parameters**: `date_from`, `date_to`, `group_by` (`day` | `week`)

**Response** `200 OK`:
```json
{
  "success": true,
  "data": {
    "series": [
      { "date": "2026-07-20", "total": 4, "HIGH": 1, "MEDIUM": 2, "LOW": 1 },
      { "date": "2026-07-21", "total": 7, "HIGH": 3, "MEDIUM": 2, "LOW": 2 },
      { "date": "2026-07-22", "total": 3, "HIGH": 0, "MEDIUM": 1, "LOW": 2 }
    ]
  }
}
```

---

### 6.7 GET /admin/v1/alerts

Get unreviewed admin alerts (HIGH risk events requiring human attention).

**Query Parameters**: `status` (`pending` | `reviewed` | `all`), `page`, `page_size`

**Response** `200 OK`:
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "alert_id": "uuid-...",
        "case_id": "uuid-...",
        "alert_type": "HIGH_RISK_FREEZE",
        "status": "pending",
        "risk_score": 82,
        "verdict_summary": "Multiple fraud indicators...",
        "created_at": "2026-07-26T10:00:00Z"
      }
    ],
    "total": 3,
    "page": 1,
    "page_size": 20,
    "has_next": false
  }
}
```

---

### 6.8 PATCH /admin/v1/alerts/{alert_id}

Mark an alert as reviewed.

**Request**:
```json
{
  "status": "reviewed",
  "admin_note": "Confirmed scam. Account frozen indefinitely."
}
```

**Response** `200 OK`:
```json
{
  "success": true,
  "data": {
    "alert_id": "uuid-...",
    "status": "reviewed",
    "reviewed_at": "2026-07-26T10:20:00Z"
  }
}
```

---

### 6.9 GET /health

No authentication required.

**Response** `200 OK`:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "services": {
    "supabase": "connected",
    "supabase_pgvector": "connected",
    "groq": "connected",
    "tavily": "connected"
  },
  "timestamp": "2026-07-26T10:00:00Z"
}
```

---

## 7. Error Codes Reference

| HTTP Status | Error Code | Description |
|-------------|------------|-------------|
| 400 | `VALIDATION_ERROR` | Request body fails schema validation |
| 401 | `UNAUTHORIZED` | Missing or invalid API key |
| 403 | `FORBIDDEN` | Valid key but insufficient permissions (e.g. user key on admin endpoint) |
| 404 | `NOT_FOUND` | Session ID, case ID, or account not found |
| 409 | `ALREADY_FROZEN` | Account is already frozen |
| 409 | `CHALLENGE_ALREADY_RESOLVED` | Biometric challenge for this transaction was already processed |
| 422 | `UNPROCESSABLE_ENTITY` | Valid JSON but business rule violation |
| 429 | `RATE_LIMIT_EXCEEDED` | Too many requests |
| 503 | `SERVICE_UNAVAILABLE` | Groq API or Supabase unreachable |

**WebSocket Close Codes**:
| Code | Meaning |
|------|---------|
| 1000 | Normal closure (pipeline complete) |
| 4001 | Unauthorized (invalid API key) |
| 4004 | Session not found |
| 4008 | Session expired (connected too late) |

---

## 8. Rate Limiting

| Endpoint Group | Limit | Window |
|----------------|-------|--------|
| `/api/v1/trigger/telemetry` | 10 req | per user per minute |
| `/api/v1/trigger/transaction` | 5 req | per user per minute |
| `/api/v1/trigger/call` | 20 req | per user per minute |
| `/api/v1/trigger/phishing` | 10 req | per user per minute |
| `/api/v1/trigger/report` | 5 req | per user per hour |
| `/api/v1/biometric/result` | 10 req | per user per minute |
| `/admin/v1/` | 100 req | per key per minute |

Rate limit headers returned on all requests:
```http
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 4
X-RateLimit-Reset: 1753516860
```
