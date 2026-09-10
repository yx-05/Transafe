# TranSafe — Product Requirements Document (PRD)

**Version**: 1.0.0
**Date**: 2026-07-26
**Status**: Approved for Hackathon Implementation

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Target Users](#2-target-users)
3. [Problem Statement](#3-problem-statement)
4. [User Stories](#4-user-stories)
5. [Functional Requirements](#5-functional-requirements)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [Acceptance Criteria](#7-acceptance-criteria)
8. [Out of Scope](#8-out-of-scope)

---

## 1. Product Overview

**TranSafe** is a multi-agent AI backend system designed to prevent online banking scams in real time. It is embedded in a web or mobile banking application and continuously monitors user behaviour, transactions, calls, and submitted phishing materials. When suspicious activity is detected, TranSafe dynamically orchestrates a team of specialised AI agents to assess the risk and trigger appropriate protective responses — from silent approval to cooling-off transaction freezes.

The system learns continuously from confirmed fraud cases, building an adaptive fraud memory that keeps it current with evolving scam tactics.

### Key Value Propositions

| Value | Description |
|-------|-------------|
| Real-time Protection | Risk assessment within 15 seconds of trigger |
| Explainable AI | Every risk verdict is accompanied by a human-readable explanation |
| Adaptive Learning | Fraud memory updated after every confirmed scam case |
| Proportional Response | Three-tier risk response avoids over-blocking legitimate transactions |
| Admin Visibility | Dashboard APIs for fraud case management and account controls |

---

## 2. Target Users

### Primary User: Bank Customer (Mobile App User)

- **Profile**: Individual using a mobile banking app for daily transactions
- **Goal**: Complete legitimate transactions safely without friction
- **Pain Points**: Receives scam calls while transacting; encounters phishing links; is coerced into transfers by social engineers
- **Technical Literacy**: Non-technical; interacts only through the mobile app UI

### Secondary User: Bank Administrator (Admin Dashboard)

- **Profile**: Bank fraud analyst or operations staff
- **Goal**: Monitor fraud cases, review flagged transactions, manage frozen accounts, and track scam trends
- **Pain Points**: High volume of alerts with no prioritisation; lack of explainability for AI decisions
- **Technical Literacy**: Moderate; uses a web dashboard

---

## 3. Problem Statement

Online banking fraud in Malaysia and the broader region is growing rapidly, with scammers employing increasingly sophisticated social engineering tactics (Macau scams, love scams, investment scams). Existing rule-based fraud systems fail to:

1. Detect novel scam patterns not seen before
2. Consider multi-signal context (simultaneous call + transaction = high coercion risk)
3. Provide explainable verdicts that users and regulators can understand
4. Learn and adapt without manual rule updates

TranSafe addresses all four gaps through a multi-agent LLM architecture with adaptive vector memory.

---

## 4. User Stories

### 4.1 Bank Customer — Telemetry Tracking

> **As a** bank customer opening the mobile app,
> **I want** the system to silently track my device and behavioural signals in the background,
> **So that** a baseline of normal behaviour is established to detect anomalies during high-risk moments.

**Trigger**: App opens
**Actors**: Mobile App, Telemetry Worker
**Notes**: No user-visible action required; runs in background

---

### 4.2 Bank Customer — Transaction Risk Interception

> **As a** bank customer about to perform a funds transfer,
> **I want** the system to assess the risk of this transaction before it executes,
> **So that** I am warned or protected if the transaction appears to be scam-induced.

**Trigger**: User initiates a transaction (transfer/payment)
**Actors**: Mobile App, Orchestrator, Financial Worker, Telemetry Worker, Research Worker
**Outcomes**:
- Low risk → transaction proceeds silently
- Medium risk → user sees a contextual warning and must complete biometric authentication
- High risk → transaction is paused for 30 minutes, user and admin are notified

---

### 4.3 Bank Customer — Call Interception

> **As a** bank customer receiving or participating in a suspicious call,
> **I want** the system to identify whether the caller is a known scammer and monitor the conversation in real time,
> **So that** I am alerted before or during my engagement with a potential fraudster.

**Trigger**: User initiates or receives a browser-based WebRTC call session inside the Web App (`app.com/call`) — browser captures audio via `navigator.mediaDevices.getUserMedia()` and streams audio chunks to backend via WebSocket (`/ws/call/{id}/audio`).

**Actors**: Web App / Mobile App, Orchestrator, Phone Worker, Research Worker
**Outcomes**:
- Caller number blacklisted → immediate pre-call risk banner with scam type context
- Caller unknown but suspicious speech pattern detected mid-call → Safety Copilot overlay pushed to user's screen in real time
- Caller appears legitimate → no disruption
- LISTEN mode: user speaks; AI highlights danger phrases live
- AUTO_TALK mode: AI takes over the call; user observes transcript

---

### 4.4 Bank Customer — Phishing Material Analysis

> **As a** bank customer who has received a suspicious message, link, or screenshot,
> **I want** to submit it to TranSafe for analysis,
> **So that** I can verify whether it is a phishing attempt before acting on it.

**Trigger**: User manually submits material via app — three supported types:
- **Text**: Raw SMS / WhatsApp / email message body
- **URL**: A suspicious link
- **Image**: Screenshot of the suspicious message (JPG/PNG, base64-encoded) — text is extracted server-side via Groq Vision API (llama-3.2-11b-vision-preview)

**Actors**: Mobile App, Orchestrator, Phishing Analyst Worker (Stage 1 — extract entities), Research Worker (Stage 2 — blacklist check + Tavily web search)
**Outcomes**:
- Confirmed phishing → high-confidence alert with explanation
- Likely phishing → advisory warning
- Clean → confirmation that material appears safe

---

### 4.5 Bank Customer — Report Fraud

> **As a** bank customer who has been scammed or suspects a scam attempt,
> **I want** to report the incident (phone number, account number, description),
> **So that** the fraud intelligence database is updated to protect other users.

**Trigger**: User submits a fraud report through the app
**Actors**: Mobile App, Research Worker, Supabase pgvector (Fraud Memory)
**Outcomes**:
- Report ingested, summarised by LLM, embedded, and written to `public.fraud_memory`
- Reported phone numbers and accounts added to scammer blacklist (searchable via pgvector)
- Confirmation returned to user

---

### 4.6 Bank Administrator — Fraud Case Management

> **As a** bank administrator,
> **I want** to view a list of fraud cases with risk scores, worker findings, and AI explanations,
> **So that** I can prioritise my investigation and take action.

**Trigger**: Admin accesses the dashboard
**Actors**: Admin Dashboard, Admin REST API, Supabase
**Outcomes**:
- Paginated list of fraud cases with filters (date, risk level, status)
- Case detail view with full Explainable AI report
- One-click account freeze/unfreeze

---

### 4.7 Bank Administrator — Analytics

> **As a** bank administrator,
> **I want** to see trend charts (cases over time, risk distribution, scam type breakdown),
> **So that** I can identify emerging fraud patterns and report to management.

**Trigger**: Admin views analytics section of dashboard
**Actors**: Admin Dashboard, Admin REST API, Supabase
**Outcomes**:
- Daily/weekly/monthly case count
- Risk level distribution (low/medium/high)
- Top scammer phone numbers and accounts
- Worker activation frequency

---

## 5. Functional Requirements

### 5.1 Trigger Handling

| ID | Requirement |
|----|-------------|
| FR-T01 | System SHALL accept telemetry events from the web/mobile app when it opens, including optional `session_metrics`, `behavioral_biometrics`, and `browser_network_fingerprint` blocks for web deployments |
| FR-T02 | System SHALL accept transaction initiation events with amount, recipient, and session context |
| FR-T03 | System SHALL accept call interception events with caller number via Web App WebRTC audio streams (`/ws/call/{call_session_id}/audio` WebSocket) |
| FR-T04 | System SHALL accept phishing material submissions in three formats: plain text, URL string, and base64-encoded image (JPG/PNG); for IMAGE submissions, the backend SHALL extract text using the Groq Vision API (llama-3.2-11b-vision-preview) before analysis |
| FR-T05 | System SHALL accept fraud reports with phone number, account number, and description |

### 5.2 Orchestration & Agent Behaviour

| ID | Requirement |
|----|-------------|
| FR-O01 | Orchestrator SHALL route each trigger to the correct Worker subset (see routing table in `03_agent_flow.md`) |
| FR-O02 | Orchestrator SHALL aggregate Worker outputs and pass them to the Risk Scorer |
| FR-O03 | Each Worker SHALL produce a structured finding with confidence score and evidence |
| FR-O04 | Risk Scorer SHALL produce a final risk score (0–100) and risk tier (low/medium/high) |
| FR-O05 | Explainable AI Node SHALL produce a human-readable explanation of the verdict in both English and Malay |

### 5.3 Risk Response

| ID | Requirement |
|----|-------------|
| FR-R01 | Low risk (0–39): System SHALL approve transaction and return result via WebSocket |
| FR-R02 | Medium risk (40–69): System SHALL return warning payload and request biometric challenge from app |
| FR-R03 | High risk (70–100): System SHALL mark transaction as frozen in Supabase for 30 minutes, notify user via WebSocket, and create an admin alert |
| FR-R04 | All responses SHALL include an Explainable AI report |
| FR-R05 | After issuing a biometric challenge (FR-R02), the mobile app SHALL POST the biometric result back to the backend via `POST /api/v1/biometric/result`; backend SHALL update the transaction status in Supabase (`approved` on PASSED, `blocked` on FAILED or DECLINED) and return the final decision via WebSocket |

### 5.4 Adaptive Fraud Memory

| ID | Requirement |
|----|-------------|
| FR-M01 | System SHALL maintain a persistent fraud intelligence knowledge base using Supabase pgvector (`public.fraud_memory` table) |
| FR-M02 | System SHALL generate 768-dimensional embeddings using Groq `nomic-embed-text-v1.5` for all fraud case narratives stored in the knowledge base |
| FR-M03 | On fraud report submission, system SHALL use LLM to summarise the case, extract entities, and write an embedding to `public.fraud_memory` via the `add_fraud_memory` helper |
| FR-M04 | Workers SHALL query `public.fraud_memory` via the `search_fraud_memory` RPC (cosine similarity, threshold ≥ 0.75) before making their assessment |

### 5.5 Admin Dashboard APIs

| ID | Requirement |
|----|-------------|
| FR-A01 | System SHALL provide a REST endpoint to list fraud cases with pagination and filters |
| FR-A02 | System SHALL provide a REST endpoint to retrieve full case detail including XAI report |
| FR-A03 | System SHALL provide a REST endpoint to freeze an account |
| FR-A04 | System SHALL provide a REST endpoint to unfreeze an account |
| FR-A05 | System SHALL provide a REST endpoint for analytics data (case trends, risk distribution) |

---

## 6. Non-Functional Requirements

### 6.1 Performance

| ID | Requirement |
|----|-------------|
| NFR-P01 | End-to-end risk assessment SHALL complete within **15 seconds** under normal Groq API load |
| NFR-P02 | WebSocket intermediate status updates SHALL be pushed every 2–3 seconds during processing |
| NFR-P03 | Admin REST endpoints SHALL respond within **500ms** for database queries |

### 6.2 Reliability

| ID | Requirement |
|----|-------------|
| NFR-R01 | If a Worker fails, the Orchestrator SHALL continue with remaining Workers and flag the failure in the XAI report |
| NFR-R02 | If Groq API is unavailable, the system SHALL fall back to a rule-based risk score and return an error explanation |

### 6.3 Security

| ID | Requirement |
|----|-------------|
| NFR-S01 | All API endpoints SHALL require an API key in the `X-API-Key` header (Hackathon-tier auth) |
| NFR-S02 | Supabase connection credentials SHALL be stored in environment variables, never hardcoded |
| NFR-S03 | User telemetry data SHALL NOT include personally identifiable information beyond a pseudonymous `user_id` |

### 6.4 Groq API Cost Control

| ID | Requirement |
|----|-------------|
| NFR-G01 | System SHALL use `llama-3.3-70b-versatile` as the default model (free tier) |
| NFR-G02 | Worker prompts SHALL be concise and structured to minimise token usage |
| NFR-G03 | Telemetry analysis (app-open trigger) SHALL use a lightweight model (`llama-3.1-8b-instant`) to reduce latency and cost |

### 6.5 Observability

| ID | Requirement |
|----|-------------|
| NFR-O01 | All LangGraph state transitions SHALL be logged with timestamps |
| NFR-O02 | Each Worker's raw LLM response SHALL be stored in the fraud case record for auditability |

---

## 7. Acceptance Criteria

### AC-01: Transaction Risk Flow (End-to-End)
- [ ] Given a mock transaction event is submitted via the API
- [ ] When the risk score is in the HIGH tier (70–100)
- [ ] Then the transaction record in Supabase is marked `frozen`
- [ ] And a WebSocket message is received by the client with the XAI explanation
- [ ] And an admin alert record is created in Supabase

### AC-02: Phishing Material Analysis
- [ ] Given a known phishing URL is submitted to the phishing analysis endpoint
- [ ] When the Phishing Analyst Worker and Research Worker complete their analysis
- [ ] Then the response contains a risk tier of MEDIUM or HIGH
- [ ] And the XAI report identifies the phishing indicators found

### AC-03: Call Interception with Known Scammer
- [ ] Given a phone number in the Supabase pgvector blacklist is submitted as an incoming call
- [ ] When the Phone Worker and Research Worker complete their analysis
- [ ] Then the risk tier is HIGH
- [ ] And the response includes the known fraud case associated with that number

### AC-04: Fraud Report → Memory Update
- [ ] Given a user submits a fraud report with a new phone number and description
- [ ] When the report is processed
- [ ] Then a new document is written to Supabase pgvector
- [ ] And the phone number appears in subsequent Research Worker RAG queries

### AC-05: Admin Account Freeze
- [ ] Given an admin submits a freeze request for a user account
- [ ] When the request is processed
- [ ] Then the account status in Supabase is updated to `frozen`
- [ ] And subsequent transaction requests for that account return a FROZEN error

### AC-06: Explainable AI Output
- [ ] Given any trigger that produces a risk assessment
- [ ] Then the response JSON contains an `explanation` field
- [ ] And the explanation includes: which Workers were activated, what each Worker found, and the final risk rationale

### AC-07: Adaptive Memory — Groq Embedding
- [ ] Given a fraud report is submitted
- [ ] When the LLM summarises the case
- [ ] Then the summary is embedded and stored in Supabase pgvector
- [ ] And a subsequent semantic search for similar fraud patterns returns this case

### AC-08: Biometric Challenge → Result Flow
- [ ] Given a MEDIUM risk transaction triggers a biometric challenge
- [ ] When the mobile app completes biometric authentication and POSTs the result to `/api/v1/biometric/result`
- [ ] Then if result is `PASSED`, transaction status in Supabase is updated to `approved` and a WebSocket `result` message confirms the transaction proceeds
- [ ] And if result is `FAILED` or `DECLINED`, transaction status is updated to `blocked` and a WebSocket `result` message informs the user the transaction was blocked

---

## 8. Out of Scope

The following items are explicitly **not** in scope for this Hackathon:

| Item | Reason |
|------|--------|
| Mobile app frontend | Backend-only system; app/web frontend is assumed to exist |
| Admin dashboard UI | Backend APIs only; UI assumed to be built separately |
| Real bank system integration | Mock data (Supabase + Faker) used throughout |
| SMS/email notifications | Notifications represented as database records only |
| Biometric hardware integration | Direct access to device fingerprint sensor / FaceID hardware is app-side only; backend receives and acts on the result |
| PSTN/VoIP native OS call interception | Out of scope — TranSafe standardizes 100% on browser-native WebRTC calls |
| Multi-tenant / multi-bank support | Single-tenant Hackathon build |
| GDPR / PDPA compliance | Architecture is designed with privacy in mind but formal compliance is out of scope |
| Production-grade authentication (OAuth2/JWT) | Simple API key auth used for Hackathon |
