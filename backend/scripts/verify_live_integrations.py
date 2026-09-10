"""Live Integration Verification Script for TranSafe.

Tests real network API connections and data persistence for:
1. LangSmith Tracing
2. Supabase PostgreSQL Data Storage
3. DeepSeek LLM API
4. Tavily Search API
"""

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

# Ensure backend root is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

def verify_deepseek():
    print("\n--- 1. Testing Live DeepSeek API ---")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("[FAIL] DEEPSEEK_API_KEY not found in environment.")
        return False

    from openai import OpenAI
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    print("Calling DeepSeek model `deepseek-chat`...")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Respond with 'DEEPSEEK_LIVE_OK'"}],
        max_tokens=20,
    )
    reply = response.choices[0].message.content or ""
    print(f"[SUCCESS] DeepSeek API Response: '{reply.strip()}'")
    return True


def verify_tavily():
    print("\n--- 2. Testing Live Tavily API ---")
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        print("[FAIL] TAVILY_API_KEY not found in environment.")
        return False

    from tavily import TavilyClient
    client = TavilyClient(api_key=api_key)
    print("Searching Tavily API for Malaysian scam query...")
    results = client.search(query="semak.my scam phone check malaysia", max_results=2)
    hits = results.get("results", [])
    print(f"[SUCCESS] Tavily API returned {len(hits)} live results:")
    for hit in hits:
        print(f"  - Title: {hit.get('title')} | URL: {hit.get('url')}")
    return True


def verify_supabase():
    print("\n--- 3. Testing Live Supabase Database Data Storage ---")
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("[FAIL] SUPABASE_URL or SUPABASE_SERVICE_KEY not set.")
        return False

    from supabase import create_client
    client = create_client(url, key)

    test_user_id = str(uuid4())
    test_session_id = str(uuid4())
    print(f"Inserting live test record into Supabase `public.users` (id: {test_user_id})...")

    # 1. Insert User
    user_res = client.table("users").insert({
        "id": test_user_id,
        "display_name": "Live Verification User",
        "risk_profile": "normal",
    }).execute()
    print("  Inserted User:", user_res.data)

    # 2. Insert Fraud Case
    case_data = {
        "user_id": test_user_id,
        "session_id": test_session_id,
        "trigger_type": "TRANSACTION",
        "risk_score": 88,
        "risk_tier": "HIGH",
        "status": "frozen",
        "action_taken": "FREEZE_30_MIN",
        "xai_report": {"verdict_summary": "Live database storage verification test"},
    }
    case_res = client.table("fraud_cases").insert(case_data).execute()
    created_case_id = case_res.data[0]["id"]
    print(f"  Inserted Fraud Case (id: {created_case_id}):", case_res.data[0]["status"])

    # 3. Query back from Supabase
    fetch_res = client.table("fraud_cases").select("*").eq("id", created_case_id).execute()
    fetched = fetch_res.data[0]
    print(f"[SUCCESS] Verified live data storage in Supabase! Stored case_id: {fetched['id']}, Risk Score: {fetched['risk_score']}")
    return True


async def verify_langsmith():
    print("\n--- 4. Testing Live LangSmith Tracing ---")
    api_key = os.getenv("LANGCHAIN_API_KEY")
    endpoint = os.getenv("LANGCHAIN_ENDPOINT")
    project = os.getenv("LANGCHAIN_PROJECT", "Transafe")
    tracing_v2 = os.getenv("LANGCHAIN_TRACING_V2")

    print(f"  Config: TRACING_V2={tracing_v2}, PROJECT={project}, ENDPOINT={endpoint}")

    if not api_key:
        print("[FAIL] LANGCHAIN_API_KEY not set.")
        return False

    from langsmith import Client
    try:
        ls_client = Client(api_key=api_key, api_url=endpoint)
        now = datetime.now(UTC)
        run_id = str(uuid4())
        print(f"  Creating live test run on LangSmith project '{project}' (run_id: {run_id})...")
        
        ls_client.create_run(
            name="live_agentic_tracing_verification",
            run_type="chain",
            inputs={"user_request": "Verify TranSafe multi-agent graph tracing"},
            outputs={"status": "Graph execution traced successfully", "agents_active": ["telemetry", "financial", "research"]},
            project_name=project,
            start_time=now,
            end_time=now,
        )
        print(f"[SUCCESS] Successfully pushed live trace run to LangSmith under project '{project}'!")
        return True
    except Exception as e:
        print(f"[FAIL] LangSmith tracing error: {e}")
        return False


async def main():
    print("=" * 65)
    print("      TRANSAFE LIVE INTEGRATIONS VERIFICATION PASS")
    print("=" * 65)

    d_ok = verify_deepseek()
    t_ok = verify_tavily()
    s_ok = verify_supabase()
    l_ok = await verify_langsmith()

    print("\n" + "=" * 65)
    print("SUMMARY RESULTS:")
    print(f"  DeepSeek API:  {'[OK] PASSED' if d_ok else '[FAIL] FAILED'}")
    print(f"  Tavily API:    {'[OK] PASSED' if t_ok else '[FAIL] FAILED'}")
    print(f"  Supabase DB:   {'[OK] PASSED' if s_ok else '[FAIL] FAILED'}")
    print(f"  LangSmith:     {'[OK] PASSED' if l_ok else '[FAIL] FAILED'}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
