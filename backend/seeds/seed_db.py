"""Database Seeding Script for TranSafe Demo Data.

Generates realistic mock users, bank accounts, transactions, and fraud memory embeddings.
"""

import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from faker import Faker

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

try:
    fake = Faker("ms_MY")
except AttributeError:
    fake = Faker("en_US")

DEMO_SCAMMER_PHONES = [
    "0161234567",  # Macau scam
    "0197654321",  # Investment scam
    "0123456789",  # Phishing SMS
]

DEMO_SCAMMER_ACCOUNTS = [
    "7653-1234-5678-9012",  # Known fraud account
    "8888-0000-1111-2222",  # Investment scam mule
]

DEMO_PHISHING_URLS = [
    "http://maybank2u-verify.xyz",
    "https://cimb-secure-login.net",
]

DEMO_FRAUD_MEMORIES = [
    {
        "fraud_type": "macau_scam",
        "content": (
            "Fraud Type: Macau Scam / Impersonation. "
            "Summary: Victim received call from someone claiming to be a Royal Malaysia "
            "Police officer, stating victim's identity was used in drug trafficking. "
            "Caller instructed victim to transfer RM 12,000 to a 'safe account'. "
            "Caller ID spoofed to appear as official PDRM number. "
            "Resolution: Funds unrecoverable. Case reported to PDRM."
        ),
        "metadata": {
            "phone_numbers": ["0161234567", "0197654321"],
            "bank_accounts": ["7653-1234-5678-9012"],
            "urls": [],
            "amount_lost_myr": 12000.00,
            "risk_tier": "HIGH",
            "source": "user_report",
            "language": "en",
        },
    },
    {
        "fraud_type": "phishing",
        "content": (
            "Fraud Type: Phishing SMS. "
            "Summary: Victim received SMS with link to fake Maybank2u login page. "
            "URL: http://maybank2u-verify.xyz — page harvested banking credentials. "
            "Victim's account drained of RM 4,500 within 30 minutes."
        ),
        "metadata": {
            "phone_numbers": ["0123456789"],
            "bank_accounts": [],
            "urls": ["http://maybank2u-verify.xyz"],
            "amount_lost_myr": 4500.00,
            "risk_tier": "HIGH",
            "source": "system_detected",
            "language": "en",
        },
    },
    {
        "fraud_type": "investment_scam",
        "content": (
            "Fraud Type: Investment Scam. "
            "Summary: Victim was recruited into a 'crypto trading group' via WhatsApp. "
            "Promised 30% monthly returns. Victim deposited RM 25,000 in three tranches. "
            "After withdrawal request, contact went silent. Platform disappeared."
        ),
        "metadata": {
            "phone_numbers": ["0197654321"],
            "bank_accounts": ["8888-0000-1111-2222"],
            "urls": [],
            "amount_lost_myr": 25000.00,
            "risk_tier": "HIGH",
            "source": "user_report",
            "language": "en",
        },
    },
]


def generate_account_number() -> str:
    """Generate a fake Malaysian bank account number format XXXX-XXXX-XXXX-XXXX."""
    return f"{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"


def generate_mock_data() -> dict[str, Any]:
    """Generate mock users, accounts, and transactions without DB connection."""
    users: list[dict[str, Any]] = []
    accounts: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []

    # 1. Generate 10 Users
    for i in range(10):
        user_id = str(uuid4())
        user_record = {
            "id": user_id,
            "display_name": fake.name(),
            "risk_profile": random.choice(
                ["normal"] * 8 + ["elevated", "high"]
            ),
            "created_at": datetime.now(UTC).isoformat(),
        }
        users.append(user_record)

        # 2. Generate 1-2 accounts per user
        num_accounts = random.randint(1, 2)
        user_accounts = []
        for _ in range(num_accounts):
            acc_num = generate_account_number()
            acc_record = {
                "id": str(uuid4()),
                "account_number": acc_num,
                "user_id": user_id,
                "account_type": random.choice(["SAVINGS", "CURRENT"]),
                "balance_myr": round(random.uniform(500.0, 50000.0), 2),
                "status": "active",
                "created_at": datetime.now(UTC).isoformat(),
            }
            accounts.append(acc_record)
            user_accounts.append(acc_num)

        # 3. Generate 90-day transactions history for each account
        for acc_num in user_accounts:
            num_txs = random.randint(5, 20)
            known_recipients = [generate_account_number() for _ in range(3)]

            # High risk transaction demo scenario for first user
            if i == 0:
                known_recipients.append(DEMO_SCAMMER_ACCOUNTS[0])

            for _ in range(num_txs):
                days_ago = random.randint(0, 90)
                tx_time = datetime.now(UTC) - timedelta(
                    days=days_ago, minutes=random.randint(0, 1440)
                )

                is_anomalous = random.random() < 0.1
                recipient = (
                    DEMO_SCAMMER_ACCOUNTS[0]
                    if (i == 0 and is_anomalous)
                    else random.choice(known_recipients)
                )
                amount = (
                    round(random.uniform(5000.0, 15000.0), 2)
                    if is_anomalous
                    else round(random.uniform(10.0, 500.0), 2)
                )

                tx_record = {
                    "id": str(uuid4()),
                    "transaction_id": f"TX-{random.randint(100000, 999999)}",
                    "session_id": str(uuid4()),
                    "sender_account": acc_num,
                    "recipient_account": recipient,
                    "recipient_name": fake.name(),
                    "amount_myr": amount,
                    "currency": "MYR",
                    "description": random.choice(
                        [
                            "Transfer to friend",
                            "Online Purchase",
                            "Bill Payment",
                            "Urgent Transfer",
                            "Investment",
                        ]
                    ),
                    "status": "completed",
                    "initiated_at": tx_time.isoformat(),
                    "created_at": tx_time.isoformat(),
                }
                transactions.append(tx_record)

    return {
        "users": users,
        "accounts": accounts,
        "transactions": transactions,
        "fraud_memories": DEMO_FRAUD_MEMORIES,
    }


def seed_db() -> None:
    """Execute database seeding against Supabase and Groq pgvector."""
    from src.db import supabase as db_supabase
    from src.db.vector_store import add_fraud_memory, init_vector_store

    db_supabase.init_supabase()
    init_vector_store()

    client = db_supabase.supabase_client
    if not client:
        print(
            "Supabase client not initialized. Ensure SUPABASE_URL and SUPABASE_SERVICE_KEY are set."
        )
        data = generate_mock_data()
        print(
            f"Generated mock data in dry-run mode: {len(data['users'])} users, "
            f"{len(data['accounts'])} accounts, {len(data['transactions'])} transactions."
        )
        return

    print("Seeding database...")
    mock_data = generate_mock_data()

    # Insert Users
    print(f"Inserting {len(mock_data['users'])} users...")
    client.table("users").upsert(mock_data["users"]).execute()

    # Insert Accounts
    print(f"Inserting {len(mock_data['accounts'])} accounts...")
    client.table("accounts").upsert(mock_data["accounts"]).execute()

    # Insert Transactions
    print(f"Inserting {len(mock_data['transactions'])} transactions...")
    client.table("transactions").upsert(
        mock_data["transactions"]
    ).execute()

    # Insert Fraud Memories
    print(f"Inserting {len(mock_data['fraud_memories'])} fraud memories...")
    for entry in mock_data["fraud_memories"]:
        try:
            add_fraud_memory(
                case_id=None,
                fraud_type=entry["fraud_type"],
                content=entry["content"],
                metadata=entry["metadata"],
            )
        except Exception as e:
            print(f"Warning: Failed to add vector memory: {e}")

    print("Seeding completed successfully.")


if __name__ == "__main__":
    seed_db()
