# TranSafe — Detailed Design & Unit Testing Specification

**Version**: 1.0.0  
**Date**: 2026-07-26  
**Status**: Approved for Hackathon Implementation  

---

## 1. System Overview & Modular Decoupling Architecture

The TranSafe backend is built around **strict modular decoupling**. Each component operates as an independent module with clean abstractions, allowing individual modules to be built, modified, and **unit-tested in isolation** without requiring running databases, live external APIs, or WebSocket connections.

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           MODULE 6: REST API & WebSockets                       │
│                   (FastAPI, Trigger Routes, WS Streamers, Admin)                │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │ invokes
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    MODULE 5: GRAPH ORCHESTRATION & STATE MACHINE                │
│                   (GraphState, Router, Risk Scorer, XAI, Dispatcher)            │
└──────┬─────────────────────────────────┬─────────────────────────────────┬──────┘
       │ delegates                       │ delegates                       │ delegates
       ▼                                 ▼                                 ▼
┌───────────────────────┐     ┌───────────────────────┐     ┌───────────────────────┐
│   MODULE 4: WORKERS   │     │   MODULE 3: SKILLS    │     │  MODULE 2: SERVICES   │
│  (Telemetry, Research,│     │ (phone_dialogue_guide,│     │ (Groq Vision OCR, STT,│
│  Financial, Phone,    │     │  anchor_questions,    │     │  edge-tts, Tavily)    │
│  Phishing Analyst)    │     │  prompt templates)    │     │                       │
└──────────┬────────────┘     └───────────────────────┘     └───────────────────────┘
           │ queries
           ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    MODULE 1: DATABASE & MEMORY PERSISTENCE                      │
│                (Supabase Relational CRUD, pgvector Vector Store)                │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Module 1: Database & Memory Persistence Layer (`src/db/`)

### 2.1 Component Overview
Handles all interactions with the hosted Supabase PostgreSQL instance:
* `supabase.py`: Relational database operations (`transactions`, `accounts`, `fraud_cases`, `admin_alerts`, `case_entities`, `phishing_submissions`, `call_transcripts`, `telemetry_events`).
* `vector_store.py`: Vector database operations on `public.fraud_memory` using 768-dimensional embeddings generated via Groq (`nomic-embed-text-v1.5`) and PostgreSQL RPC similarity queries.

### 2.2 Interface Specifications & Data Contracts

```python
# Pydantic Row Models for Type Safety
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class FraudCaseRecord(BaseModel):
    id: Optional[str] = None
    session_id: str
    user_id: str
    trigger_type: str
    risk_score: int
    risk_tier: str
    status: str
    action_taken: str
    xai_report: Dict[str, Any]
    transaction_id: Optional[str] = None

class FraudMemoryRecord(BaseModel):
    case_id: str
    fraud_type: str
    content: str
    phone_numbers: List[str] = []
    bank_accounts: List[str] = []
    urls: List[str] = []
    amount_lost_myr: Optional[float] = None
    risk_tier: str = "HIGH"
    source: str = "user_report"

# Core Function Signatures (src/db/supabase.py)
def init_supabase() -> None: ...
async def insert_fraud_case(case_data: dict) -> str: ...
async def insert_call_transcript(case_id: str, speaker: str, utterance: str, risk_score: int) -> str: ...
async def fetch_case_context(case_id: str) -> dict: ...
async def fetch_telemetry_events(user_id: str, session_id: str, limit: int = 100) -> list[dict]: ...
async def fetch_user_transaction_history(sender_account: str, days: int = 90) -> dict: ...

# Core Function Signatures (src/db/vector_store.py)
def init_vector_store() -> None: ...
def embed_text(text: str) -> list[float]: ...
def search_fraud_memory(query: str, threshold: float = 0.75, top_k: int = 5) -> list[dict]: ...
def check_blacklist(phone: Optional[str] = None, url: Optional[str] = None) -> list[dict]: ...
def add_fraud_memory(case_id: str, fraud_type: str, content: str, metadata: dict) -> None: ...
```

### 2.3 Unit Testing Strategy & Test Suite (`tests/unit/test_db.py`)
* **Mock Strategy**: Mock `supabase.create_client` and `groq.Groq` clients so tests do not execute real HTTP network calls.
* **Test Assertions**:
  1. `test_embed_text_returns_768_float_vector`: Verifies vector dimension output.
  2. `test_fetch_case_context_aggregates_subtables`: Verifies dictionary merging of transcripts, phishing OCR, and entities.
  3. `test_search_fraud_memory_filters_by_threshold`: Ensures similarity score filtering works.

```python
import pytest
from unittest.mock import MagicMock, patch
from src.db.vector_store import embed_text, search_fraud_memory

@patch("src.db.vector_store.groq_client")
def test_embed_text(mock_groq):
    # Mock Groq embedding API return
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1] * 768)]
    mock_groq.embeddings.create.return_value = mock_response

    vec = embed_text("test scam message")
    assert len(vec) == 768
    assert vec[0] == 0.1
    mock_groq.embeddings.create.assert_called_once_with(
        model="nomic-embed-text-v1.5", input="test scam message"
    )

@patch("src.db.vector_store.supabase_client")
@patch("src.db.vector_store.embed_text")
def test_search_fraud_memory(mock_embed, mock_supabase):
    mock_embed.return_value = [0.1] * 768
    mock_rpc_response = MagicMock()
    mock_rpc_response.execute.return_value.data = [
        {"case_id": "case-1", "similarity": 0.88, "content": "Macau scam report"}
    ]
    mock_supabase.rpc.return_value = mock_rpc_response

    results = search_fraud_memory("0161234567", threshold=0.75)
    assert len(results) == 1
    assert results[0]["case_id"] == "case-1"
    mock_supabase.rpc.assert_called_once()
```

---

## 3. Module 2: External Integration Services (`src/services/`)

### 3.1 Component Overview
Wraps third-party cloud APIs into isolated async Python utilities:
* `vision.py`: Groq Vision (`llama-3.2-11b-vision-preview`) text extraction from base64 screenshots.
* `stt.py`: Groq Whisper (`whisper-large-v3`) audio chunk transcription.
* `tts.py`: `edge-tts` Microsoft Edge Neural voice synthesis (`en-SG-LunaNeural` / `ms-MY-YasminNeural`).
* `tavily.py`: Tavily Search API client for querying Malaysian scam blacklist portals (`semak.my`, `rmp.gov.my`, `bnm.gov.my`, `lowyat.net`).

### 3.2 Interface Specifications

```python
# Function Signatures
async def extract_text_from_image(base64_image: str) -> str: ...
async def transcribe_audio_chunk(audio_bytes: bytes, language: str = "en") -> str: ...
async def synthesize_text_to_audio(text: str, voice: str = "en-SG-LunaNeural") -> bytes: ...
def tavily_search(entities: list[str]) -> list[dict]: ...
```

### 3.3 Unit Testing Strategy & Test Suite (`tests/unit/test_services.py`)
* **Mock Strategy**: Mock HTTP responses from `tavily-python`, `Groq.chat.completions`, and `edge_tts.Communicate`.

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.vision import extract_text_from_image
from src.services.tavily import tavily_search

@pytest.mark.asyncio
@patch("src.services.vision.groq_client")
async def test_extract_text_from_image(mock_groq):
    mock_choice = MagicMock()
    mock_choice.message.content = "URGENT: Verify account at http://scam.xyz"
    mock_groq.chat.completions.create.return_value.choices = [mock_choice]

    result = await extract_text_from_image("fake_base64_string")
    assert "URGENT: Verify account" in result
    mock_groq.chat.completions.create.assert_called_once()

@patch("src.services.tavily.TavilyClient")
def test_tavily_search(mock_tavily_class):
    mock_instance = MagicMock()
    mock_instance.search.return_value = {
        "results": [{"title": "Scam Report", "url": "https://lowyat.net/topic/1"}]
    }
    mock_tavily_class.return_value = mock_instance

    res = tavily_search(["0161234567"])
    assert len(res) == 1
    assert "lowyat.net" in res[0]["url"]
```

---

## 4. Module 3: Dynamic Skills & Prompt Management (`backend/skills/` & `src/agents/prompts.py`)

### 4.1 Component Overview
Manages conversational instructions and prompt templates independently of application code:
* Reads external skill markdown files (`backend/skills/phone_dialogue_guide.md`, `backend/skills/anchor_questions.md`) dynamically at runtime.
* Formats LLM system and human prompts for all Worker nodes.

### 4.2 Interface Specifications

```python
def load_skill_file(skill_filename: str) -> str: ...
def get_phone_dialogue_guide() -> str: ...
def get_anchor_questions() -> list[dict]: ...
def build_telemetry_prompt(user_id: str, session_id: str, device_id: str, events: list) -> str: ...
def build_financial_prompt(pending_tx: dict, history: dict, case_context: Optional[dict]) -> str: ...
def build_research_prompt(entities: list, internal_hits: list, tavily_hits: list) -> str: ...
def build_phishing_analysis_prompt(source: str, content: str) -> str: ...
```

### 4.3 Unit Testing Strategy & Test Suite (`tests/unit/test_skills.py`)

```python
import os
import pytest
from src.agents.prompts import load_skill_file, get_anchor_questions

def test_load_skill_file_success():
    content = load_skill_file("phone_dialogue_guide.md")
    assert "Safety & Data Privacy Guardrails" in content
    assert "Zero User Information Access" in content

def test_get_anchor_questions_parsing():
    questions = get_anchor_questions()
    assert len(questions) == 4
    assert questions[0]["id"] == "AQ-1"
    assert "employee ID" in questions[0]["question_example"]
```

---

## 5. Module 4: Worker Agents (`src/agents/workers/`)

### 5.1 Component Overview
Contains the business logic and LLM inference tasks for each worker. Each worker is a **pure function** that receives the immutable `GraphState` dictionary and returns a partial update dictionary containing its `WorkerFinding`.

```python
class WorkerFinding(BaseModel):
    worker: str                          # "telemetry" | "research" | "financial" | "phone" | "phishing"
    score: int                           # 0 - 100
    confidence: float                    # 0.0 - 1.0
    evidence: List[str]
```

### 5.2 Worker Function Contracts

```python
def telemetry_worker_node(state: GraphState) -> dict: ...
def research_worker_node(state: GraphState) -> dict: ...
def financial_worker_node(state: GraphState) -> dict: ...
def phone_worker_node(state: GraphState) -> dict: ...
def phishing_worker_node(state: GraphState) -> dict: ...
```

### 5.3 Unit Testing Strategy & Test Suite (`tests/unit/test_workers.py`)
* **Mock Strategy**: Mock external DB client functions and LLM invocations so worker nodes can be tested purely as transformation functions on `GraphState`.

```python
import pytest
from unittest.mock import patch, MagicMock
from src.agents.workers.financial import financial_worker_node

@patch("src.agents.workers.financial.fetch_user_transaction_history")
@patch("src.agents.workers.financial.llm")
def test_financial_worker_case_context_override(mock_llm, mock_history):
    # Setup state with associated_case_context matching recipient account
    state = {
        "trigger_type": "TRANSACTION",
        "trigger_payload": {
            "transaction": {
                "amount": 9800.0,
                "recipient_account": "7653-1234-5678-9012"
            }
        },
        "associated_case_context": {
            "bank_accounts": ["7653-1234-5678-9012"]
        }
    }
    
    mock_history.return_value = {"avg_amount": 200.0, "known_recipients": []}
    
    # Mock LLM JSON output
    mock_llm.invoke.return_value.content = '{"score": 98, "confidence": 0.95, "evidence": ["Recipient account matches active call transcript"]}'

    res = financial_worker_node(state)
    assert res["financial_finding"]["score"] == 98
    assert res["financial_finding"]["worker"] == "financial"
    assert "matches active call" in res["financial_finding"]["evidence"][0]
```

---

## 6. Module 5: Graph Orchestration & State Machine (`src/agents/`)

### 6.1 Component Overview
Defines the overall LangGraph workflow:
* `state.py`: Defines `GraphState` TypedDict.
* `orchestrator.py`: Evaluates `trigger_type`, loads `associated_case_context`, and determines active worker nodes.
* `graph_nodes.py`: `risk_scorer_node`, `xai_node`, and `action_dispatcher_node`.
* `graph.py`: Builds and compiles the `StateGraph` object.

### 6.2 Interface Specifications & Routing Map

```python
TRIGGER_WORKER_MAP = {
    "TELEMETRY":   ["telemetry"],
    "TRANSACTION": ["financial", "telemetry", "research"],
    "CALL":        ["phone", "research"],
    "PHISHING":    ["phishing"],    # Two-stage: Phishing Worker runs first, Research Worker second
    "REPORT":      ["research"],    # Research Worker runs in INGEST mode
}

def orchestrator_node(state: GraphState) -> dict: ...
def risk_scorer_node(state: GraphState) -> dict: ...
def xai_node(state: GraphState) -> dict: ...
def action_dispatcher_node(state: GraphState) -> dict: ...
def compile_graph() -> CompiledStateGraph: ...
```

### 6.2.1 LangSmith Tracing & Observability Integration

Because the backend utilizes LangGraph for state machine orchestration, system-wide agent tracing, latency logging, and performance analysis are enabled out-of-the-box using **LangSmith**. Tracing captures all LLM inputs/outputs, node execution times, state updates, and branching routes automatically.

**Zero-Code Tracing Protocol**:
LangGraph reads standard environment variables at initialization to authenticate and stream execution traces to LangSmith asynchronously. No additional boilerplate or import wrappers are required.

**Required Configuration** (in `backend/.env`):
* `LANGCHAIN_TRACING_V2=true`: Enables tracing globally.
* `LANGCHAIN_ENDPOINT=https://api.smith.langchain.com`: Standard cloud tracing URL.
* `LANGCHAIN_API_KEY=lsv2_...`: Authenticates requests to LangSmith.
* `LANGCHAIN_PROJECT=transafe-backend`: Organizes traces under this project workspace.

### 6.3 Unit Testing Strategy & Test Suite (`tests/unit/test_graph.py`)

```python
import pytest
from unittest.mock import patch, MagicMock
from src.agents.orchestrator import orchestrator_node
from src.agents.graph_nodes import risk_scorer_node, action_dispatcher_node

def test_orchestrator_routing_transaction():
    state = {
        "trigger_type": "TRANSACTION",
        "trigger_payload": {"associated_case_id": None},
        "status_messages": []
    }
    res = orchestrator_node(state)
    assert res["workers_to_activate"] == ["financial", "telemetry", "research"]

def test_risk_scorer_node_weighted_scoring():
    state = {
        "financial_finding": {"score": 90, "confidence": 0.9, "evidence": ["High amount"]},
        "telemetry_finding": {"score": 10, "confidence": 0.8, "evidence": ["Normal device"]},
        "research_finding": None,
        "phone_finding": None,
        "phishing_finding": None,
        "status_messages": []
    }
    res = risk_scorer_node(state)
    assert res["risk_score"] > 40
    assert res["risk_tier"] in ["MEDIUM", "HIGH"]

def test_action_dispatcher_high_risk_freeze():
    state = {
        "risk_tier": "HIGH",
        "status_messages": []
    }
    res = action_dispatcher_node(state)
    assert res["action_taken"] == "FREEZE_30_MIN"
```

---

## 7. Module 6: REST API & WebSockets Layer (`src/api/` & `main.py`)

### 7.1 Component Overview
Exposes external endpoints:
* `triggers.py`: Handles REST POST triggers (`/api/v1/trigger/*`) and `GET /api/v1/cases/recent`.
* `websocket.py`: Main session WebSocket handler (`/ws/session/{session_id}`).
* `websocket_call.py`: WebRTC audio stream & event WebSocket handlers (`/ws/call/{id}/audio` and `/ws/call/{id}/events`).
* `admin.py`: Fraud operations REST endpoints.
* `main.py`: Application lifespan, middleware configuration, CORS, and dependency injection setup.

### 7.2 Interface Specifications

```python
# API Key Verification Dependency
async def verify_api_key(x_api_key: str = Header(...)) -> str: ...

# Endpoint Routers
@router.post("/trigger/transaction", response_model=TriggerResponse, status_code=202)
async def trigger_transaction(payload: TransactionTriggerRequest): ...

@router.get("/cases/recent", response_model=RecentCasesResponse)
async def get_recent_cases(user_id: str): ...

@websocket_router.websocket("/ws/session/{session_id}")
async def ws_session_stream(websocket: WebSocket, session_id: str): ...
```

### 7.3 Unit Testing Strategy & Test Suite (`tests/unit/test_api.py`)
* **Mock Strategy**: Use FastAPI's `TestClient` and mock `app.state.compiled_graph` and database helper functions.

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from main import app

client = TestClient(app)

def test_trigger_endpoint_requires_api_key():
    response = client.post("/api/v1/trigger/transaction", json={})
    assert response.status_code == 401

def test_trigger_transaction_success():
    headers = {"X-API-Key": "transafe-hackathon-key-2026"}
    payload = {
        "user_id": "usr-123",
        "session_id": "sess-456",
        "transaction": {
            "transaction_id": "tx-789",
            "sender_account": "12345678",
            "recipient_account": "87654321",
            "amount": 5000.0,
            "currency": "MYR",
            "description": "Test transfer",
            "initiated_at": "2026-07-26T10:00:00Z"
        }
    }
    
    response = client.post("/api/v1/trigger/transaction", json=payload, headers=headers)
    assert response.status_code == 202
    assert response.json()["success"] is True
    assert "session_id" in response.json()["data"]

@patch("src.api.triggers.fetch_recent_cases_from_db")
def test_get_recent_cases(mock_fetch):
    mock_fetch.return_value = [
        {"case_id": "case-101", "trigger_type": "CALL", "created_at": "2026-07-26T18:30:00Z"}
    ]
    headers = {"X-API-Key": "transafe-hackathon-key-2026"}
    
    response = client.get("/api/v1/cases/recent?user_id=usr-123", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["has_recent_activity"] is True
    assert len(response.json()["data"]["recent_cases"]) == 1
```

---

## 8. Summary of Independent Unit Test Execution

All unit tests are designed to be executed using `pytest` without requiring external server dependencies:

```bash
# Run all module unit tests from backend/ directory
pytest tests/unit/ -v

# Run specific module unit tests in isolation
pytest tests/unit/test_db.py -v
pytest tests/unit/test_services.py -v
pytest tests/unit/test_skills.py -v
pytest tests/unit/test_workers.py -v
pytest tests/unit/test_graph.py -v
pytest tests/unit/test_api.py -v
```
