# Phishing Detection Playbook

Operational playbook for TranSafe's **Phishing Worker** — the deep-analysis
engine that scores SMS, email, URLs, and live-call transcripts for scam risk.

This file is loaded dynamically at runtime and is the **single source of truth**
for BOTH detection paths:

1. **Rule engine** (`_rule_based_phishing_analysis` in
   `src/agents/workers/phishing.py`) — reads the *Heavy money-demand keywords*
   and *Light social-engineering / urgency keywords* columns to compute the
   deterministic baseline score.
2. **LLM system prompt** (`PHISHING_SYSTEM_PROMPT`) — reads the *LLM guidance*
   column to recognise archetypes the keyword rules cannot express.

To add a new scam archetype, add a row to the table below — no code changes
required. Keep each keyword on the relevant column:

- **Heavy** = concrete financial demand (transfer, OTP, card details, fees).
- **Light** = social-engineering / urgency / coercion signal that corroborates
  a heavy hit (friend, urgent, don't hang up, arrest, prize...).

---

## 1. Detection Archetypes

| ID | Archetype | Typical script phrases | Heavy money-demand keywords | Light social-engineering / urgency keywords | LLM guidance |
|---|---|---|---|---|---|
| **P-1** | Friend / Relative Emergency | "your friend from Thailand", "I'm in trouble", "I lost my phone", "emergency" | transfer, send money, wire, remit | friend, relative, sister, brother, urgent, right now, asap, immediately, don't tell anyone, keep it a secret | Impersonating a friend or relative in distress and pressing for an urgent money transfer (emergency bail, hospital bills, customs release). |
| **P-2** | Investment Opportunity | "guaranteed profit", "special opportunity", "double your money", "limited time" | deposit, top up, topup, transfer, activation fee | investment, invest, guaranteed profit, double your money, urgent, right now, asap, immediately, limited time | Promising guaranteed or unusually high returns and pressing for an immediate "investment" payment or account activation fee. |
| **P-3** | Bank Impersonation | "card was swiped", "account frozen", "unauthorized transaction", "safe account" | bank account, safe account, akaun selamat, otp, card number, card password, card pin, transfer, withdraw, wire | don't hang up, do not hang up, must not disconnect, urgent, right now, asap, immediately | Pretending to be a bank or bank officer and demanding funds be moved to a "safe account", or harvesting card / OTP details. |
| **P-4** | Government / Authority | PDRM, LHDN, court, "arrest warrant", "case file", "money laundering" | bail, court fee | arrest, jail, don't hang up, do not hang up, must not disconnect, urgent, right now, asap, immediately | Impersonating police, tax, or court and threatening arrest or jail unless a fine, bail, or court fee is paid immediately; forbidding you from hanging up. |
| **P-5** | Prize / Lottery | "you have won", "redeem your prize", "claim your reward", "processing fee" | | redeem, prize, won, pay, payment, money, cash, you have won, claim your prize, urgent, right now, asap, immediately | Claiming a prize or lottery winnings that require an upfront tax, processing, or "claim fee" to release. |
| **P-6** | Parcel / Customs | "package held", "customs fee", "delivery blocked", "shipping charge" | customs fee, deposit, transfer, remit, top up | package held, parcel held, urgent, right now, asap, immediately | Claiming a parcel is held by customs or courier and demanding a delivery or customs fee before release. |

---

## 2. Amount Corroboration

A concrete amount (e.g. "$100,000", "RM5,000", "a thousand dollars",
"two million ringgit") corroborates any heavy money-demand signal above and
raises the rule-engine contribution from mention-only (15) to corroborated (35).

## 3. Scoring Notes (rule engine)

- Base score 10/100. Each heavy keyword adds 35 when corroborated by a light
  signal or a concrete amount, otherwise 15. Each light keyword adds 10.
- Impersonation keywords (bank / government names, "urgent", "suspension")
  add 15 each. Suspicious URL TLDs / unencrypted http add 35.
- Maximum score is 100. Tiers: >= 70 HIGH, >= 40 MEDIUM, else LOW.
