"""Seed Historical Telemetry Baseline Events for Valid Supabase Users."""

import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from src.db.supabase import get_supabase, init_supabase


def generate_normal_telemetry_session(user_id: str, days_ago: int, session_index: int) -> list[dict[str, Any]]:
    """Generate realistic human typing flight times and clean posture logs for a historical session."""
    events: list[dict[str, Any]] = []
    base_time = datetime.now(UTC) - timedelta(days=days_ago, minutes=session_index * 15)
    session_id = f"sess-hist-{days_ago}d-{session_index}"
    device_id = "device_web_001"

    # Generate 8-15 normal human keystrokes (flight time 105ms - 175ms)
    num_keystrokes = random.randint(8, 15)
    for i in range(num_keystrokes):
        flight_time = random.randint(105, 175)  # Natural human flight time
        evt_time = base_time + timedelta(seconds=i * 2)
        events.append({
            "user_id": user_id,
            "session_id": session_id,
            "device_id": device_id,
            "event_type": "KEYSTROKE",
            "event_value": str(flight_time),
            "app_version": "1.0.0",
            "created_at": evt_time.isoformat(),
        })

    return events


def seed_telemetry_baseline():
    """Seed 90-day normal telemetry baseline events into Supabase telemetry_events for real users."""
    init_supabase()
    client = get_supabase()

    # 1. Clean up legacy mock string 'usr-123' if present
    try:
        client.table("telemetry_events").delete().eq("user_id", "usr-123").execute()
        print("Cleaned up legacy 'usr-123' rows from telemetry_events.")
    except Exception:
        pass

    # 2. Fetch real user UUIDs from public.users table
    try:
        raw_users = client.table("users").select("id").limit(5).execute().data
        user_ids = [u["id"] for u in raw_users] if raw_users else ["619ebd02-82fc-4a13-81f6-ff575c20278d"]
    except Exception:
        user_ids = ["619ebd02-82fc-4a13-81f6-ff575c20278d"]

    print(f"Seeding 90-day telemetry baseline events for {len(user_ids)} real Supabase users...")
    all_events: list[dict[str, Any]] = []

    for user_id in user_ids:
        # Generate clean historical sessions across past 90 days
        for days_ago in range(1, 90, 4):
            session_events = generate_normal_telemetry_session(user_id, days_ago, random.randint(1, 3))
            all_events.extend(session_events)

    print(f"Generated {len(all_events)} logical telemetry baseline events across past 90 days.")

    # Batch insert into public.telemetry_events
    batch_size = 100
    success_count = 0
    for i in range(0, len(all_events), batch_size):
        batch = all_events[i : i + batch_size]
        try:
            client.table("telemetry_events").insert(batch).execute()
            success_count += len(batch)
        except Exception as err:
            print(f"Notice: Table insertion attempt: {err}")
            break

    if success_count > 0:
        print(f"✅ Successfully seeded {success_count} historical telemetry events for real users into Supabase public.telemetry_events.")


if __name__ == "__main__":
    seed_telemetry_baseline()
