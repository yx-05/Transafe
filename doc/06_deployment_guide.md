# TranSafe — Deployment & Configuration Guide

**Version**: 1.0.0
**Date**: 2026-07-26
**Status**: Approved for Hackathon Implementation

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Project Setup](#2-project-setup)
3. [Environment Variables Configuration](#3-environment-variables-configuration)
4. [Supabase Setup](#4-supabase-setup)
5. [Groq API Setup](#5-groq-api-setup)
6. [Tavily Search API Setup](#6-tavily-search-api-setup)
7. [Dependency Installation](#7-dependency-installation)
8. [Seed Demo Data](#8-seed-demo-data)
9. [Running the Server](#9-running-the-server)
10. [Hackathon Demo Checklist](#10-hackathon-demo-checklist)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

Ensure the following are installed on your machine before starting:

| Tool | Minimum Version | Install |
|------|----------------|---------|
| Python | 3.13+ | [python.org](https://www.python.org/downloads/) |
| uv | 0.5+ | `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Git | Any | Pre-installed on most systems |

**Cloud accounts required** (all free tier):

| Service | Purpose | Sign Up |
|---------|---------|---------|
| Supabase | PostgreSQL database | [supabase.com](https://supabase.com) |
| Groq | LLM inference API | [console.groq.com](https://console.groq.com) |

---

## 2. Project Setup

### Clone and Navigate

```powershell
# The repo is already cloned at d:\Github\transafe
cd d:\Github\transafe\agents
```

### Initialise uv Virtual Environment

```powershell
uv venv
.venv\Scripts\activate    # Windows PowerShell
# OR
source .venv/bin/activate  # macOS/Linux
```

### Verify Python Version

```powershell
python --version
# Expected: Python 3.13.x
```

---

## 3. Environment Variables Configuration

Create a `.env` file in the `backend/` directory. **Never commit this file to git.**

```powershell
# backend/.env
New-Item -Path ".env" -ItemType File
```

Copy and fill in the following template:

```dotenv
# ── API Authentication ─────────────────────────────────────────
API_KEY=transafe-hackathon-key-2026
ADMIN_API_KEY=transafe-admin-key-2026

# ── Supabase ───────────────────────────────────────────────────
SUPABASE_URL=https://<your-project-id>.supabase.co
SUPABASE_ANON_KEY=<your-supabase-anon-key>
SUPABASE_SERVICE_KEY=<your-supabase-service-role-key>

# ── Groq API ───────────────────────────────────────────────────
GROQ_API_KEY=gsk_<your-groq-api-key>
GROQ_MODEL_PRIMARY=llama-3.3-70b-versatile
GROQ_MODEL_FAST=llama-3.1-8b-instant

# ── Tavily API ─────────────────────────────────────────────────
TAVILY_API_KEY=tvly-<your-tavily-api-key>

# ── LangSmith Tracking ─────────────────────────────────────────
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=lsv2_<your-langsmith-api-key>
LANGCHAIN_PROJECT=transafe-backend

# ── Server ─────────────────────────────────────────────────────
HOST=0.0.0.0
PORT=8000
DEBUG=true

# ── Risk Thresholds ────────────────────────────────────────────
RISK_THRESHOLD_LOW=40
RISK_THRESHOLD_HIGH=70
COOLING_OFF_SECONDS=1800
```

### Verify `.gitignore`

Ensure the following is present in `backend/.gitignore`:

```gitignore
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
```

---

## 4. Supabase Setup

### Step 1: Create a New Supabase Project

1. Go to [supabase.com](https://supabase.com) → **New Project**
2. Name: `transafe-hackathon`
3. Region: Southeast Asia (Singapore) — closest for demo latency
4. Note down: **Project URL**, **anon/public key**, **service_role key**

### Step 2: Run Initialisation SQL

1. In Supabase dashboard → **SQL Editor** → **New Query**
2. Paste the full SQL from `05_database_schema.md` Section 7
3. Click **Run**

Verify tables were created:
```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema IN ('public', 'telemetry')
ORDER BY table_schema, table_name;
```

Expected output:
```
table_schema | table_name
-------------+-------------------
public       | accounts
public       | admin_alerts
public       | fraud_cases
public       | transactions
public       | users
telemetry    | telemetry_events
```

### Step 3: Get API Keys

In Supabase dashboard → **Project Settings** → **API**:

- Copy **URL** → `SUPABASE_URL` in `.env`
- Copy **anon public** key → `SUPABASE_ANON_KEY`
- Copy **service_role** key → `SUPABASE_SERVICE_KEY`

> **Note**: The `service_role` key bypasses Row Level Security — keep it secret and use it only server-side.

---

## 5. Groq API Setup

### Step 1: Get API Key

1. Go to [console.groq.com](https://console.groq.com)
2. Sign up / Log in
3. **API Keys** → **Create API Key**
4. Copy the key → `GROQ_API_KEY` in `.env`

### Step 2: Verify Available Models

The following models are used in TranSafe:

| Model | Usage | Free Tier Rate |
|-------|-------|---------------|
| `llama-3.3-70b-versatile` | Orchestrator, Research, Financial, Phone, Phishing Workers, XAI | 6,000 req/day |
| `llama-3.1-8b-instant` | Telemetry Worker (lightweight) | 14,400 req/day |

### Step 3: Test Groq Connection

```python
# Quick test — run from backend/ directory
python -c "
from groq import Groq
import os
from dotenv import load_dotenv
load_dotenv()
client = Groq(api_key=os.getenv('GROQ_API_KEY'))
r = client.chat.completions.create(
    model='llama-3.1-8b-instant',
    messages=[{'role': 'user', 'content': 'Say: Groq connected OK'}]
)
print(r.choices[0].message.content)
"
```

Expected: `Groq connected OK`

---

## 6. Tavily Search API Setup

Tavily is used by the Research Worker to search the web for public scam reports when local fraud memory similarity is low.

### Step 1: Get API Key

1. Go to [tavily.com](https://tavily.com)
2. Sign up for a free account (includes 1,000 free searches per month)
3. Copy your API key → `TAVILY_API_KEY` in `.env`

---

## 7. Dependency Installation

### Update `pyproject.toml`

Add the following dependencies to `backend/pyproject.toml`:

```toml
[project]
name = "agents"
version = "0.1.0"
description = "TranSafe — Multi-Agent Banking Fraud Prevention Backend"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    # Web framework
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "python-dotenv>=1.0.0",

    # Multi-agent orchestration
    "langgraph>=0.2.0",
    "langchain-groq>=0.2.0",
    "langchain-core>=0.3.0",

    # Groq LLM
    "groq>=0.12.0",

    # Supabase
    "supabase>=2.9.0",

    # Web search
    "tavily-python>=0.5.0",

    # Neural TTS
    "edge-tts>=6.1.13",

    # Data validation
    "pydantic>=2.9.0",

    # HTTP client (for health checks)
    "httpx>=0.27.0",
]

[dependency-groups]
dev = [
    "mypy>=2.3.0",
    "pytest>=9.1.1",
    "pytest-asyncio>=0.24.0",
    "ruff>=0.16.0",
    "faker>=30.0.0",    # for seed scripts
]
```

### Install Dependencies

```powershell
# Install all dependencies (including dev)
uv sync --all-extras

# Verify installation
uv pip list | Select-String "fastapi|langgraph|groq|supabase|tavily|edge-tts"
```

Expected output (versions may vary):
```
edge-tts          6.1.x
fastapi           0.115.x
groq              0.12.x
langgraph         0.2.x
supabase          2.9.x
tavily-python     0.5.x
```

---

## 8. Seed Demo Data

### Seed Supabase (Mock Banking Data)

```powershell
python seeds/seed_supabase.py
```

This creates:
- 10 mock users with pseudonymous names
- 15 mock accounts (1-2 per user)
- 200+ mock transactions (90-day history per user, varied patterns)
- 5 pre-built fraud case scenarios for demo

Verify:
```powershell
python -c "
from supabase import create_client
import os; from dotenv import load_dotenv; load_dotenv()
sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY'))
print('Users:', sb.table('users').select('id', count='exact').execute().count)
print('Accounts:', sb.table('accounts').select('id', count='exact').execute().count)
print('Transactions:', sb.table('transactions').select('id', count='exact').execute().count)
"
```

Expected:
```
Users: 10
Accounts: 15
Transactions: 215
```

---

## 9. Running the Server

### Start the FastAPI Server

```powershell
cd d:\Github\transafe\agents

# Development mode (auto-reload on file change)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# OR using uv
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Verify Server Health

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health" -Method GET
```

Expected:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "services": {
    "supabase": "connected",
    "groq": "connected"
  }
}
```

### Access Auto-Generated API Docs

Open in browser:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 10. Hackathon Demo Checklist

Use this checklist before every demo session to ensure all systems are operational.

### Pre-Demo Checks

#### Environment
- [ ] `.env` file exists in `backend/` with all required variables filled
- [ ] `.venv` is activated: `(.venv)` visible in terminal prompt

#### Services
- [ ] **Groq API**: Run test command in Section 5 Step 3 → returns "Groq connected OK"
- [ ] **Supabase**: Run verification in Section 8 → shows correct counts

#### Server
- [ ] Server starts without errors: `uvicorn main:app --reload`
- [ ] Health check passes: `GET /health` returns `"status": "healthy"`
- [ ] All core services shown as "connected" in health response

### Demo Flow Tests

#### Demo 1: HIGH Risk Transaction (Core Demo)
```powershell
# Step 1: Initiate transaction trigger
$body = @{
    user_id = "demo-user-1-uuid"
    session_id = "demo-session-001"
    transaction = @{
        transaction_id = "txn-demo-001"
        sender_account = "1234-5678-9012-3456"
        recipient_account = "7653-1234-5678-9012"  # scammer account
        recipient_name = "Investment Returns Ltd"
        amount = 9800.00
        currency = "MYR"
        description = "Investment payment"
        initiated_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    }
} | ConvertTo-Json -Depth 3

$response = Invoke-RestMethod `
    -Uri "http://localhost:8000/api/v1/trigger/transaction" `
    -Method POST `
    -Headers @{"X-API-Key" = "transafe-hackathon-key-2026"; "Content-Type" = "application/json"} `
    -Body $body

# Note the session_id for WebSocket connection
$response.data.session_id
```

- [ ] Receives `202 Accepted` with `session_id`
- [ ] Connect WebSocket to `/ws/session/{session_id}` → see status messages from each Worker
- [ ] Final `result` message shows `risk_tier: "HIGH"`, `risk_score` ≥ 70
- [ ] `action_taken: "FREEZE_30_MIN"` in response
- [ ] Check Supabase `transactions` table → status = `frozen`
- [ ] Check Supabase `admin_alerts` table → new alert created

#### Demo 2: Known Scammer Call
```powershell
$body = @{
    user_id = "demo-user-1-uuid"
    session_id = "demo-session-002"
    call = @{
        caller_number = "+60161234567"  # blacklisted number
        caller_name = "Unknown"
        call_direction = "INCOMING"
        received_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
        is_during_banking_session = $true
    }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod `
    -Uri "http://localhost:8000/api/v1/trigger/call" `
    -Method POST `
    -Headers @{"X-API-Key" = "transafe-hackathon-key-2026"; "Content-Type" = "application/json"} `
    -Body $body
```

- [ ] Risk tier = HIGH
- [ ] XAI report mentions "found in fraud database" and "Macau scam"
- [ ] Response time < 15 seconds

#### Demo 3: Phishing SMS Analysis
```powershell
$body = @{
    user_id = "demo-user-2-uuid"
    session_id = "demo-session-003"
    material = @{
        content_type = "TEXT"
        content = "URGENT: Your Maybank account has been compromised. Click http://maybank2u-verify.xyz to verify now or your account will be suspended."
        source = "SMS"
    }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod `
    -Uri "http://localhost:8000/api/v1/trigger/phishing" `
    -Method POST `
    -Headers @{"X-API-Key" = "transafe-hackathon-key-2026"; "Content-Type" = "application/json"} `
    -Body $body
```

- [ ] Risk tier = HIGH or MEDIUM
- [ ] XAI report identifies: urgency language, fake domain, OTP request

#### Demo 4: Admin Dashboard
```powershell
# List fraud cases
Invoke-RestMethod `
    -Uri "http://localhost:8000/admin/v1/cases?risk_tier=HIGH&page_size=5" `
    -Method GET `
    -Headers @{"X-Admin-Key" = "transafe-admin-key-2026"}
```

- [ ] Returns paginated list of HIGH risk cases
- [ ] Analytics endpoint works: `GET /admin/v1/analytics/summary`
- [ ] Account freeze works: `POST /admin/v1/accounts/{account}/freeze`

#### Demo 5: Fraud Report → Memory Update
```powershell
$body = @{
    user_id = "demo-user-3-uuid"
    report = @{
        description = "Someone called claiming to be Maybank officer and asked me to transfer to safe account"
        phone_numbers = @("0189999888")
        bank_accounts = @("5555-6666-7777-8888")
        fraud_type = "IMPERSONATION_SCAM"
        amount_lost_myr = 0
        incident_date = "2026-07-26"
    }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod `
    -Uri "http://localhost:8000/api/v1/trigger/report" `
    -Method POST `
    -Headers @{"X-API-Key" = "transafe-hackathon-key-2026"; "Content-Type" = "application/json"} `
    -Body $body
```

- [ ] Returns `case_id` synchronously
- [ ] Verify Supabase public.fraud_memory row count increased by 1
- [ ] Subsequent call trigger with `0189999888` now returns higher risk score

---

## 11. Troubleshooting

### Issue: `GROQ_API_KEY` rate limit exceeded

**Symptom**: Workers return errors, response contains `"error": "rate_limit_exceeded"`

**Fix**:
1. Check current usage at [console.groq.com](https://console.groq.com)
2. Switch Telemetry Worker to `llama-3.1-8b-instant` (already configured)
3. If daily limit hit, wait until midnight UTC for reset

---

### Issue: Supabase connection refused

**Symptom**: Health check shows `"supabase": "disconnected"`

**Fix**:
1. Verify `SUPABASE_URL` is correct (format: `https://xxxxx.supabase.co`)
2. Verify `SUPABASE_SERVICE_KEY` is the **service_role** key, not the anon key
3. Check Supabase dashboard → Project Settings → API to confirm keys

---

### Issue: WebSocket connection rejected with code 4001

**Symptom**: Client cannot connect to WebSocket

**Fix**: Ensure `api_key` query parameter matches `API_KEY` in `.env`:
```
ws://localhost:8000/ws/session/{id}?api_key=transafe-hackathon-key-2026
```

---

### Issue: LangGraph graph takes > 15 seconds

**Symptom**: Pipeline times out or feels slow during demo

**Fix**:
1. Reduce `match_count` in pgvector queries from 5 to 3
2. Shorten Worker system prompts (reduce token count)
3. Switch all Workers to `llama-3.1-8b-instant` temporarily
4. Ensure Workers are running in parallel (check LangGraph `Send` implementation)

---

### Issue: `uvicorn` port already in use

**Symptom**: `ERROR: [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8000)`

**Fix**:
```powershell
# Find and kill the process using port 8000
netstat -ano | findstr :8000
taskkill /PID <pid> /F

# OR use a different port
uvicorn main:app --port 8001 --reload
```

---

### Environment Variable Quick Reference

```powershell
# Print all loaded env vars (PowerShell)
Get-Content .env | Where-Object { $_ -notmatch "^#" -and $_ -ne "" }
```

| Variable | Where to Get |
|----------|-------------|
| `API_KEY` | Set yourself (any string) |
| `ADMIN_API_KEY` | Set yourself (any string) |
| `SUPABASE_URL` | Supabase → Project Settings → API → Project URL |
| `SUPABASE_ANON_KEY` | Supabase → Project Settings → API → anon public |
| `SUPABASE_SERVICE_KEY` | Supabase → Project Settings → API → service_role |
| `GROQ_API_KEY` | console.groq.com → API Keys |
| `GROQ_MODEL_PRIMARY` | Use: `llama-3.3-70b-versatile` |
| `GROQ_MODEL_FAST` | Use: `llama-3.1-8b-instant` |
| `TAVILY_API_KEY` | Get from: tavily.com |
| `LANGCHAIN_TRACING_V2` | Enable tracing: `true` |
| `LANGCHAIN_ENDPOINT` | LangSmith endpoint: `https://api.smith.langchain.com` |
| `LANGCHAIN_API_KEY` | Get from: smith.langchain.com |
| `LANGCHAIN_PROJECT` | Set target project name: `transafe-backend` |
| `HOST` | Use: `0.0.0.0` |
| `PORT` | Use: `8000` |
