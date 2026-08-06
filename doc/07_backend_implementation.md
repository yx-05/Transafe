# TranSafe — Backend Technical Implementation Document

**Version**: 1.0.0  
**Date**: 2026-07-26  
**Status**: Approved for Hackathon Implementation  

---

## 1. Directory Structure

The complete backend codebase is laid out as follows:

```
backend/
├── main.py                 ← FastAPI entry point & WebSocket handlers
├── pyproject.toml          ← Project dependencies
├── .env                    ← Environment credentials (gitignored)
├── src/
│   ├── api/
│   │   ├── triggers.py     ← Trigger endpoints (/api/v1/trigger/*)
│   │   ├── websocket.py    ← Core session WebSocket (/ws/session/*)
│   │   └── websocket_call.py ← WebRTC call WebSockets (/ws/call/*)
│   ├── agents/
│   │   ├── graph.py        ← LangGraph builder & node registry
│   │   ├── state.py        ← GraphState dictionary definition
│   │   ├── orchestrator.py ← Router node logic
│   │   └── workers/
│   │       ├── telemetry.py
│   │       ├── research.py
│   │       ├── financial.py
│   │       ├── phone.py
│   │       └── phishing.py
│   ├── db/
│   │   ├── supabase.py     ← Supabase client & relational queries
│   │   └── vector_store.py ← pgvector client, embeddings & search
│   └── models/
│       └── schemas.py      ← Pydantic models for request/response validation
```

---

## 2. Core Backend Modules

### 2.1 Entry Point (`main.py`)

Initializes the FastAPI application, mounts CORS middlewares, compiles the LangGraph state machine, and defines health checks.

```python
import os
from fastapi import FastAPI, Depends, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from src.api import triggers, websocket, websocket_call
from src.agents.graph import compile_graph
from src.db.supabase import init_supabase
from src.db.vector_store import init_vector_store

load_dotenv()

app = FastAPI(
    title="TranSafe API",
    version="1.0.0",
    description="Multi-Agent Banking Fraud Prevention Backend"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Key Middleware
async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("API_KEY"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )
    return x_api_key

# Include routers
app.include_router(triggers.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(websocket.router)
app.include_router(websocket_call.router)

@app.on_event("startup")
async def startup_event():
    # Initialize DB connections
    init_supabase()
    init_vector_store()
    # Pre-compile the LangGraph graph
    app.state.compiled_graph = compile_graph()

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "services": {
            "supabase": "connected",
            "groq": "connected"
        }
    }
```

### 2.2 Database Clients & Helpers

#### Supabase Connection Manager (`src/db/supabase.py`)

Handles structured CRUD operations for transactions, fraud cases, accounts, and transcripts.

```python
import os
from supabase import create_client, Client

supabase_client: Client = None

def init_supabase():
    global supabase_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    supabase_client = create_client(url, key)

async def insert_fraud_case(case_data: dict) -> str:
    response = supabase_client.table("fraud_cases").insert(case_data).execute()
    return response.data[0]["id"]

async def insert_call_transcript(case_id: str, speaker: str, utterance: str, risk_score: int):
    row = {
        "case_id": case_id,
        "speaker": speaker,
        "utterance": utterance,
        "risk_score": risk_score
    }
    supabase_client.table("call_transcripts").insert(row).execute()

async def fetch_case_context(case_id: str) -> dict:
    # Query transcripts, phishing text, and entities for a case
    transcripts = supabase_client.table("call_transcripts").select("*").eq("case_id", case_id).execute()
    phishing = supabase_client.table("phishing_submissions").select("*").eq("case_id", case_id).execute()
    entities = supabase_client.table("case_entities").select("*").eq("case_id", case_id).execute()
    
    return {
        "transcripts": transcripts.data,
        "phishing": phishing.data,
        "entities": entities.data
    }
```

#### pgvector Store Helper (`src/db/vector_store.py`)

Generates 768-dimensional text embeddings using Groq and performs cosine similarity queries on the `public.fraud_memory` table.

```python
import os
from groq import Groq
from supabase import create_client, Client

groq_client: Groq = None
supabase_client: Client = None

def init_vector_store():
    global groq_client, supabase_client
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    supabase_client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))

def embed_text(text: str) -> list[float]:
    response = groq_client.embeddings.create(
        model="nomic-embed-text-v1.5",
        input=text
    )
    return response.data[0].embedding

def search_fraud_memory(query: str, threshold: float = 0.75, top_k: int = 5) -> list[dict]:
    query_embedding = embed_text(query)
    response = supabase_client.rpc(
        "search_fraud_memory",
        {
            "query_embedding": query_embedding,
            "match_threshold": threshold,
            "match_count": top_k
        }
    ).execute()
    return response.data

def add_fraud_memory(case_id: str, fraud_type: str, content: str, metadata: dict):
    embedding = embed_text(content)
    row = {
        "case_id": case_id,
        "fraud_type": fraud_type,
        "content": content,
        "embedding": embedding,
        **metadata
    }
    supabase_client.table("fraud_memory").insert(row).execute()
```

---

## 3. WebRTC Audio & Event WebSocket Skeletons

### 3.1 WebRTC Audio Handler (`src/api/websocket_call.py`)

Manages the incoming call audio stream (transcribing chunks with Groq Whisper) and streams simulated TTS responses back to the caller using `edge-tts`.

```python
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.agents.workers.phone import transcribe_audio_chunk, synthesize_text_to_audio, phone_worker_pre_check
from src.db.supabase import insert_call_transcript

router = APIRouter()

class CallConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, call_session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[call_session_id] = websocket

    def disconnect(self, call_session_id: str):
        if call_session_id in self.active_connections:
            del self.active_connections[call_session_id]

    async def send_event(self, call_session_id: str, message: dict):
        if call_session_id in self.active_connections:
            await self.active_connections[call_session_id].send_json(message)

manager = CallConnectionManager()

@router.websocket("/ws/call/{call_session_id}/audio")
async def ws_call_audio(websocket: WebSocket, call_session_id: str):
    await manager.connect(call_session_id, websocket)
    audio_buffer = bytearray()
    
    try:
        while True:
            # Receive binary chunk from WebRTC recorder (~1s interval)
            data = await websocket.receive_bytes()
            audio_buffer.extend(data)
            
            # Trigger STT when buffer hits ~32KB (approx 2s of audio)
            if len(audio_buffer) >= 32000:
                chunk_to_process = bytes(audio_buffer)
                audio_buffer.clear()
                
                # Async transcription
                transcript = await transcribe_audio_chunk(chunk_to_process)
                if transcript.strip():
                    await manager.send_event(call_session_id, {
                        "type": "transcript",
                        "call_session_id": call_session_id,
                        "speaker": "CALLER",
                        "text": transcript
                    })
                    
                    # Highlight analysis
                    # ... run highlighter worker pass ...
                    
    except WebSocketDisconnect:
        manager.disconnect(call_session_id)
```

---

## 4. LangGraph Compiled Machine (`src/agents/graph.py`)

Compiles the worker nodes, routers, and edge triggers into a compiled LangGraph graph singleton.

```python
from langgraph.graph import StateGraph, END
from src.agents.state import GraphState
from src.agents.orchestrator import orchestrator_node
from src.agents.workers.telemetry import telemetry_worker_node
from src.agents.workers.research import research_worker_node
from src.agents.workers.financial import financial_worker_node
from src.agents.workers.phone import phone_worker_node
from src.agents.workers.phishing import phishing_worker_node
from src.agents.graph_nodes import risk_scorer_node, xai_node, action_dispatcher_node

def route_workers(state: GraphState):
    """Conditional router based on Orchestrator's worker selection."""
    return state["workers_to_activate"]

def compile_graph():
    # Build state graph
    workflow = StateGraph(GraphState)
    
    # Define Nodes
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("telemetry", telemetry_worker_node)
    workflow.add_node("research", research_worker_node)
    workflow.add_node("financial", financial_worker_node)
    workflow.add_node("phone", phone_worker_node)
    workflow.add_node("phishing", phishing_worker_node)
    workflow.add_node("scorer", risk_scorer_node)
    workflow.add_node("xai", xai_node)
    workflow.add_node("dispatcher", action_dispatcher_node)
    
    # Set entry point
    workflow.set_entry_point("orchestrator")
    
    # Conditional Edges (Fan-Out routing to activated workers)
    workflow.add_conditional_edges(
        "orchestrator",
        route_workers,
        {
            "telemetry": "telemetry",
            "research": "research",
            "financial": "financial",
            "phone": "phone",
            "phishing": "phishing"
        }
    )
    
    # Joins (routing back to scorer after worker execution completion)
    workflow.add_edge("telemetry", "scorer")
    workflow.add_edge("research", "scorer")
    workflow.add_edge("financial", "scorer")
    workflow.add_edge("phone", "scorer")
    workflow.add_edge("phishing", "scorer")
    
    # Linear evaluation
    workflow.add_edge("scorer", "xai")
    workflow.add_edge("xai", "dispatcher")
    workflow.add_edge("dispatcher", END)
    
    return workflow.compile()
```

---

## 8. Enterprise Resiliency & Fraud Engine Updates (August 2026)

### 8.1 Central Groq LLM Multi-Key Rotation Pool (`src/agents/llm.py`)
To prevent system outages caused by Groq API 429 rate limit errors (100,000 TPD limit on `llama-3.3-70b-versatile`), a centralized key-rotation manager was introduced:
* **Dynamic Key Discovery**: Automatically loads `GROQ_API_KEY`, `GROQ_API_KEY_1`, `GROQ_API_KEY_2`, `GROQ_API_KEY_3`, and environment key lists.
* **Tier 1 Multi-Key Rotation**: Tries primary model (`llama-3.3-70b-versatile`) across all available API keys sequentially.
* **Tier 2 Model Fallback**: Automatically switches to `llama-3.1-8b-instant` (500,000 TPD limit) if all keys hit rate limits.
* **Robust JSON Extraction**: `extract_json_object()` parses embedded JSON payloads from smaller model responses that contain conversational preambles or markdown fences.

### 8.2 Multi-Tiered Tavily Fraud Intelligence Search (`src/services/tavily.py`)
* **Tier 1 (Regulatory Alert Lists)**: Targets `bnm.gov.my` (Bank Negara) and `sc.com.my` (Securities Commission).
* **Tier 2 (Enforcement & Community Forums)**: Targets `rmp.gov.my` (PDRM CCID) and `forum.lowyat.net`.
* **Tier 3 (Unconstrained Broad Search)**: Automatically triggers if domain-restricted searches return low entity relevance, ensuring explicit scam articles (e.g., `Bestino Group`, `JJPTR`, `Genneva`) are retrieved.
* **Slot Allocation**: Guarantees Slot #1 is occupied by an official BNM/SC regulatory alert notice whenever available.

### 8.3 Historical Baseline Isolation & Pending Transaction Filtering (`src/db/supabase.py` & `financial.py`)
* Excludes the current pending transaction ID (`current_tx_id`) and status `'pending'` / `'frozen_pending'` from `fetch_user_transaction_history()` queries.
* Prevents newly initiated transactions from polluting customer 90-day baselines or false-flagging first-time recipients as known recipients.

### 8.4 Non-Empty Evidence Safety Net across All Workers
* All 5 worker agents (`Telemetry`, `Financial`, `Research`, `Phishing`, `Phone`) enforce a mandatory default evidence string when `score == 0` or evidence is empty, ensuring UI explanation cards never render blank.
