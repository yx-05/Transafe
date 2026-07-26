# Phone Agent Anchor Question Schedule

These questions are scheduled by the Dialogue Controller during a call. The AI assistant must ask these questions at natural transitions in the conversation.

---

### Question Schedule

| ID | Goal | Question Template | Scam Indicator (Triggers Suspicion Increase) |
|---|---|---|---|
| **AQ-1** | Verify organisation & agent ID | *"May I know the full name of your department/organisation and your employee ID registration number, please?"* | Caller cannot provide ID, gives general/vague answers (e.g. "We are the security department"), or gets defensive/angry. |
| **AQ-2** | Call-back verification check | *"I'd feel much safer if I call your official office number directly to reach you. What is your department extension number?"* | Caller refuses to let you hang up, claims the line is secure and must not be disconnected, or claims "immediate arrest" if you hang up. |
| **AQ-3** | Financial transfer probe | *"Will this procedure involve transferring my funds to another account or verifying my card passwords?"* | Caller confirms money needs to be moved to a "secure" or "safe" account, or deflects the question. |
| **AQ-4** | Urgent action challenge | *"I need to consult my family or visit a local branch first before making this decision. Is it okay if I do that tomorrow?"* | Caller pressures for immediate execution, states that waiting will result in arrest, account freeze, or penalty, or says you are prohibited from telling family members. |
