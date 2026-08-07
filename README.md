# 🛡️ TranSafe

TranSafe is a next-generation, AI-powered fraud protection platform designed for retail banking. Built on a **Multi-Agent System (MAS)** using LangGraph, TranSafe goes beyond static rule-based fraud engines by autonomously analyzing financial transactions, passive behavioral telemetry, live phone calls, and phishing material to protect users in real-time.

## ✨ Key Features

* **🧠 Multi-Agent Orchestration**: A decentralized intelligence model where specialized agents (Financial, Telemetry, Research, Phone, Phishing) operate in parallel to assess risk, preventing monolithic LLM bloat and reducing latency.
* **📞 Live Call Interception (Auto-Talk)**: Integrates real-time audio streaming via WebSockets and Whisper STT. When a user receives a suspicious call, TranSafe can actively listen to detect coercion markers or autonomously converse with the scammer to verify their identity.
* **🏃‍♂️ Passive Behavioral Telemetry**: Detects device takeover (DTO) or physical coercion (e.g., dictation, screen sharing) by passively analyzing typing cadences and app navigation behavior using a lightweight Llama 3 8B model.
* **🌐 Adaptive Fraud Memory (RAG)**: Integrates Supabase `pgvector` to cross-reference extracted entities (phone numbers, URLs, bank accounts) against an ever-growing internal knowledge base of past fraud playbooks and public web reports via Tavily.
* **⚖️ Explainable AI (XAI)**: Generates human-readable, bilingual narratives detailing *why* an action (e.g., a 30-minute cooling-off freeze) was taken, acting as a transparent committee chair for all agent findings.

## 🏗️ Architecture

TranSafe's core is an event-driven directed state machine built with **LangGraph**:

1. **Trigger Initiation**: Mobile app events (`TRANSACTION`, `CALL`, `TELEMETRY`, `PHISHING`) hit the FastAPI backend.
2. **Orchestration**: The Orchestrator agent dynamically delegates the context to the relevant parallel Worker Agents.
3. **Execution**: Agents independently gather data from Supabase, evaluate using the Groq API (Llama 3 70B/8B), and append their findings to a shared `GraphState`.
4. **Enforcement**: A Risk Scorer aggregates the weighted findings, determining a final tier (LOW, MEDIUM, HIGH) which triggers the Action Dispatcher to approve, challenge, or freeze the activity.

## 🛠️ Technology Stack

* **Frameworks**: FastAPI (Python), LangGraph
* **Inference Core**: Groq API (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`)
* **Database & Memory**: Supabase (PostgreSQL, `pgvector`, REST CRUD)
* **Services**: 
  * Whisper (Speech-to-Text)
  * Edge-TTS (Text-to-Speech)
  * Groq Vision (OCR)
  * Tavily API (External Web Search)

## 📖 Documentation Directory

For deep dives into the system design, agent flows, and database schemas, explore the `/doc` folder:
- [01_product_requirements.md](doc/01_product_requirements.md)
- [02_architecture.md](doc/02_architecture.md)
- [03_agent_flow.md](doc/03_agent_flow.md)
- [04_api_design.md](doc/04_api_design.md)
- [05_database_schema.md](doc/05_database_schema.md)
- [07_backend_implementation.md](doc/07_backend_implementation.md)
- [08_detailed_design.md](doc/08_detailed_design.md)

---
chat log with CodeBuddy.ai:
doc/history_202607261708.md