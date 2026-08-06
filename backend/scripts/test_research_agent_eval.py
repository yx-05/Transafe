import os
import json
from dotenv import load_dotenv

load_dotenv('.env')

from src.agents.workers.research import _run_query_mode
from src.agents.prompts import build_research_prompt

def run_agent_evaluations():
    test_cases = [
        {
            "id": "TC-01",
            "name": "Clean Transfer (Standard Transfer Account)",
            "recipient_name": "Standard Transfer Account",
            "recipient_account": "9879-2345-2354-1746",
            "amount": 150.00,
            "description": "Standard Transfer",
            "expected_max_score": 10,
        },
        {
            "id": "TC-02",
            "name": "Blacklisted Ponzi Scam (JJPTR)",
            "recipient_name": "JJ Poor to Rich (JJPTR)",
            "recipient_account": "1122-3344-5566-7788",
            "amount": 15000.00,
            "description": "JJPTR Forex Investment Deposit",
            "expected_min_score": 85,
        },
        {
            "id": "TC-03",
            "name": "Blacklisted Gold Scam (Genneva Malaysia)",
            "recipient_name": "Genneva Malaysia Sdn Bhd",
            "recipient_account": "9988-7766-5544-3322",
            "amount": 20000.00,
            "description": "Gold Investment Deposit",
            "expected_min_score": 85,
        },
        {
            "id": "TC-04",
            "name": "Legitimate Personal Transfer (Siti Aminah)",
            "recipient_name": "Siti Aminah Binti Ahmad",
            "recipient_account": "1001-2002-3003-4004",
            "amount": 250.00,
            "description": "Dinner Reimbursement",
            "expected_max_score": 10,
        },
        {
            "id": "TC-05",
            "name": "Legitimate Utility Payment (Tenaga Nasional)",
            "recipient_name": "Tenaga Nasional Berhad (TNB)",
            "recipient_account": "5005-6006-7007-8008",
            "amount": 320.50,
            "description": "Electricity Bill Payment",
            "expected_max_score": 10,
        },
        {
            "id": "TC-06",
            "name": "Generic Recipient Name with Scam Description (JJPTR Forex Deposit)",
            "recipient_name": "Standard Transfer Account",
            "recipient_account": "9879-2345-2354-1746",
            "amount": 5000.00,
            "description": "JJPTR Forex Deposit",
            "expected_min_score": 85,
        },
    ]

    print("==========================================================================")
    print("      TRANSAFE RESEARCH AGENT AUTOMATED EVALUATION SUITE")
    print("==========================================================================")

    passed_count = 0
    total_count = len(test_cases)

    for tc in test_cases:
        print(f"\n--- Running Test [{tc['id']}]: {tc['name']} ---")
        state = {
            "trigger_type": "TRANSACTION",
            "trigger_payload": {
                "user_id": "619ebd02-82fc-4a13-81f6-ff575c20278d",
                "session_id": f"sess-{tc['id'].lower()}",
                "transaction": {
                    "transaction_id": f"tx-{tc['id'].lower()}",
                    "sender_account": "6373-5093-3430-8430",
                    "recipient_account": tc["recipient_account"],
                    "recipient_name": tc["recipient_name"],
                    "amount": tc["amount"],
                    "currency": "MYR",
                    "description": tc["description"],
                    "initiated_at": "2026-08-02T00:40:00Z",
                },
            },
        }

        finding = _run_query_mode(state)

        score = finding.score
        confidence = finding.confidence
        evidence = finding.evidence

        print(f"📊 Resulting Score      : {score} / 100")
        print(f"🎯 Resulting Confidence : {confidence}")
        print("📄 Evidence Items Output:")
        for idx, item in enumerate(evidence, 1):
            print(f"   {idx}. {item}")

        # Evaluate against expectations
        is_pass = False
        if "expected_max_score" in tc:
            is_pass = score <= tc["expected_max_score"]
            eval_msg = f"Score ({score}) <= Expected Max ({tc['expected_max_score']})"
        elif "expected_min_score" in tc:
            is_pass = score >= tc["expected_min_score"]
            eval_msg = f"Score ({score}) >= Expected Min ({tc['expected_min_score']})"

        if is_pass:
            print(f"✅ EVALUATION: PASSED ({eval_msg})")
            passed_count += 1
        else:
            print(f"❌ EVALUATION: FAILED ({eval_msg})")

    print("\n==========================================================================")
    print(f"EVALUATION SUMMARY: {passed_count} / {total_count} PASSED ({passed_count/total_count * 100:.1f}%)")
    print("==========================================================================")

if __name__ == "__main__":
    run_agent_evaluations()
