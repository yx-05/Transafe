# TranSafe — Frontend Design Document

**Version**: 1.0.0  
**Date**: 2026-07-26  
**Status**: Draft  

---

## 1. Overview & Technology Stack

The TranSafe project consists of two distinct Web Applications built in a single monorepo (or separate Vite projects) to demonstrate the end-to-end fraud prevention flow. 

**Technology Stack:**
* **Framework**: Vite + React
* **Styling**: Vanilla CSS (No Tailwind, utilizing CSS Variables for theming, CSS Modules or standard external stylesheets).
* **State Management**: React Context / Hooks.
* **Real-time Communication**: Native `WebSocket` API and `navigator.mediaDevices.getUserMedia()` for WebRTC audio streams.

---

## 2. App 1: The User Web App (Victim Simulation)

### 2.1 Design Philosophy & Layout
The User App simulates a modern, mobile-first banking application. It is constrained to a mobile aspect ratio (e.g., 390x844 max width/height centered on desktop screens) to provide a realistic feel.

* **Layout Type**: Mobile-first with a Bottom Navigation Bar.
* **Aesthetics**: Premium, clean, utilizing smooth micro-animations (e.g., slide-ups, fade-ins), glassmorphism for modals, and dynamic hover/active states. 

### 2.2 Core Components & Navigation

**Bottom Navigation Tabs:**
1. **Home (Dashboard)**: Account balance card, a quick action button labeled `"Send Money"`, and a `"Recent Activity"` list.
2. **Transfer (Transaction)**: Dedicated page to perform transfers, link contexts, and view real-time multi-agent safety checks.
3. **Scan/Upload**: Dedicated tab for submitting phishing screenshots (WhatsApp/SMS) with a `"Choose File"` button and an `"Analyze Image"` button.
4. **Settings/Profile**: System debug configurations (e.g. `"Reset Sandbox Account"`, `"Simulate Scam Call"` button).

---

### 2.3 Detailed Transaction Page (`/transfer`)

The Transaction Page contains three sequential panels: **The Transfer Form**, **The Live Security Scanner**, and **The System Verdict Panel**.

#### 2.3.1 Panel A: The Transfer Form
An interactive input form for setting up transaction details.

* **Recipient Bank Selection**: 
  - **Label**: `Beneficiary Bank`
  - **Type**: Dropdown list (`<select>`)
  - **Options**: `"Maybank"`, `"CIMB Bank"`, `"Public Bank"`, `"RHB Bank"`, `"Hong Leong Bank"`, `"Bank Islam"`
* **Recipient Name**: 
  - **Label**: `Recipient Name`
  - **Type**: Text Input (`<input type="text">`)
  - **Placeholder**: `"e.g., JOHN DOE"`
* **Recipient Account Number**: 
  - **Label**: `Account Number`
  - **Type**: Text Input (`<input type="text">` with digits and hyphens validation)
  - **Placeholder**: `"e.g., 1641-2345-6789"`
  - **Backend Check**: Evaluated by the **Financial Worker** (against historical frequency) and **Research Worker** (against the pgvector blacklist and fraud memories).
* **Transfer Amount**: 
  - **Label**: `Amount (MYR)`
  - **Type**: Decimal Input (`<input type="number" step="0.01">`)
  - **Placeholder**: `"0.00"`
  - **Backend Check**: Evaluated by the **Financial Worker** to calculate divergence from the 90-day transaction average.
* **Payment Reference / Description**: 
  - **Label**: `Description / Reference`
  - **Type**: Text Input (`<input type="text">`)
  - **Placeholder**: `"e.g., Monthly Rent / Crypto Buy"`
* **Case Linkage Selector (Fraud Context Correlation)**:
  - **Label**: `Link Transaction to Recent Activity (Optional)`
  - **Type**: Radio Button Group / Conditional Dropdown
  - **Option 1**: `(Recommended)` `"Automatically check for recent active calls or phishing checks (Past 2 Hours)"`
  - **Option 2**: `"Select a specific context manually"` 
    - When selected, displays a dropdown populated via `GET /api/v1/cases/recent?user_id=...` containing:
      - `"Phone Call (Case: case-123 | Unknown Caller | 10 mins ago)"`
      - `"Phishing Screenshot (Case: case-456 | WhatsApp Text | 1 hour ago)"`
  - **Option 3**: `"No prior call/phishing activity relates to this transaction"`
  - **Backend Check**: Maps to `associated_case_id` in the API payload, allowing the **Financial Worker** to verify if the recipient account matches any bank details captured during simulated calls or extracted from screenshots.
* **Form Action Buttons**:
  - **Authorize Button**: 
    - **Text**: `"Authorize Transfer"`
    - **Styling**: Large, primary colored button, transitions to loading state upon click.
  - **Cancel Button**:
    - **Text**: `"Cancel & Go Back"`
    - **Styling**: Outlined, light secondary button.

#### 2.3.2 Panel B: The Live Security Scanner (WebSocket Statuses)
Visible immediately after clicking `"Authorize Transfer"`. The form is disabled, and this overlay/section displays the live execution of the multi-agent pipeline:

* **Header**: `"SecureTransfer Active Scan"`
* **Progress Spinner**: Centered CSS-based rotating loader.
* **Status Stream Output**: Displays real-time message streams fetched from `ws://localhost:8000/ws/session/{session_id}`:
  - `"Orchestrator: Routing transaction trigger to analysis workers..."`
  - `"Financial Worker: Reviewing 90-day transaction deviations..."`
  - `"Telemetry Worker: Inspecting behavioral biometrics..."`
  - `"Research Worker: Querying national scam databases..."`
  - `"Risk Scorer: Integrating worker confidence parameters..."`
  - `"Explainable AI: Formatting human-readable verdict..."`

#### 2.3.3 Panel C: Multi-Agent System Verdict (The Outcome)
Renders once the WebSocket receives type `"result"`.

* **Risk Level Gauge**:
  - **Label**: `Risk Assessment Score`
  - **UI**: Visual circular dial or progress bar showcasing `risk_score` (0-100).
  - **Risk Tier Badge**:
    - `LOW` (Score < 30): Green pill badge reading `"LOW RISK — APPROVED"`
    - `MEDIUM` (Score 30-70): Orange pill badge reading `"MEDIUM RISK — REVIEW TRIGGERED"`
    - `HIGH` (Score > 70): Red pill badge reading `"HIGH RISK — ACTION DISPATCHED"`
* **Explainable AI Explanation Card**:
  - **Label**: `Verdict Explanation`
  - **Text**: Displays `xai_report.verdict_summary` (English) and `xai_report.verdict_summary_ms` (Malay translation) to explain exactly why the score was computed.
* **Active Protection Action Banner**:
  - **Label**: `Current Action Status`
  - **Dynamic Banner Texts**:
    - If `action_taken` is `"FREEZE_30_MIN"`: 
      - **Text**: `"🚨 Protection Triggered: Your banking account has been temporarily frozen for a 30-minute cooling-off period to prevent potential scam loss under BNM guidelines."`
    - If `action_taken` is `"BLOCK_TRANSACTION"`:
      - **Text**: `"🚫 Transaction Blocked: The transaction was intercepted. The recipient account matches a known fraudulent account in the NSRC database."`
    - If `action_taken` is `"ALERT_ADMIN"`:
      - **Text**: `"⚠️ Held for Verification: The transaction is pending review by our security operations team. You will be contacted shortly."`
    - If `action_taken` is `"ALLOW"`:
      - **Text**: `"✅ Safe to Proceed: Transaction verified and processed successfully."`
* **Verdict Action Buttons**:
  - **Close Panel Button**: 
    - **Text**: `"Dismiss & Return to Home"`
    - **Styling**: Primary theme button.
  - **Report Hotline Button**: 
    - **Text**: `"Call NSRC Hotline (997)"`
    - **Styling**: Outlined red alert button, visible only on Medium/High risk verdicts.

---

### 2.4 User App Routing (React Router)
* `/`: Main Banking Dashboard (Home).
### 2.4 User App Active Call Screen (`/call-active`)

This interface simulates a live call session and provides real-time risk highlighting (Safety Copilot) and Auto-Talk delegation monitoring.

#### 2.4.1 Active Incoming Call HUD
Visible when an incoming call starts ringing:
* **Caller Caller-ID Text**: `"Unknown Caller (+6016-123-4567)"`
* **Network Status Text**: `"Secure Line Connection: WebRTC Call Session"`
* **Pre-Call Threat Alert Banner**:
  - Displays if the caller's number pattern matches a blacklisted prefix: `"⚠️ Warning: This caller ID mimics CIMB/Maybank support prefixes. Exercise extreme caution."`
* **Interactive Control Buttons**:
  - **Decline Button**:
    - **Text**: `"🔴 Decline"`
    - **Styling**: Rounded red button.
  - **Listen Mode Button**:
    - **Text**: `"🎧 Listen & Monitor"`
    - **Action**: Opens the **Real-Time Safety Copilot** panel where the user speaks, but the AI listens to transcribe and highlight scam phrases.
  - **Auto-Talk Button**:
    - **Text**: `"🤖 Let AI Answer"`
    - **Action**: Delegates call control to the **Phone Worker Dialogue Controller**. Mutes the user's mic and plays AI-synthesized responses to the scammer.

#### 2.4.2 Mode A Panel: Safety Copilot (Listen Mode)
Active when the user manually answers the call while the AI monitors in the background.

* **Live Suspicion Meter**:
  - **Label**: `Call Suspicion Level`
  - **UI**: Horizontal bar shifting from Green ➔ Yellow ➔ Red based on `suspicion_score` (0-100).
* **Live Transcript Feed Container**:
  - A scrollable dialogue container mapping recognized speech segments from the WebSocket highlight stream (`{"type": "highlight"}`):
    - Caller lines shown in gray speech bubbles; User lines in dark blue speech bubbles.
* **Real-time Phrase Risk Highlights**:
  - Suspicious phrases identified by the backend model are bolded and highlighted in light red text with hoverable danger tags:
    - **Example**: `Caller: Your account is flagged for `**`money laundering` [Accusation]**`. You must transfer `**`RM 5,000 to our safe account immediately` [Fund Transfer]**` or face arrest.`
* **Threat Alert Cards**:
  - Dynamically slides in alert panels when a high-risk span matches:
    - `"🚨 Urgent Action Flag: Caller is requesting an immediate bank transfer."`
    - `"🚨 Accusation Flag: Caller is using threats of legal arrest to pressure you."`

#### 2.4.3 Mode B Panel: AI Interception Screen (Auto-Talk Mode)
Active when the user delegates the call to the AI Assistant.

* **Takeover Button**:
  - **Text**: `"🎙️ Take Over Call"`
  - **Styling**: Blue primary button (unmutes user mic and terminates the AI voice agent loop).
* **Autopilot Dialogue Log**:
  - Displays the live chat log between the scammer and the AI Assistant:
    - AI lines marked with a robot icon: `"🤖 AI: I am unauthorized to confirm personal account details over this line. Can you provide your organization and employee ID?"`
    - Scammer responses in gray, rendering **real-time phrase risk highlighting** (same bold/underlined red styling with hoverable danger tags as Listen Mode) as the backend models push highlight events: `"Caller: I don't need to give you my ID, this is a `**`PDRM officer` [Authority Impersonation]**`! Answer my questions!"`
* **Verification Question Checklist**:
  - Shows the progress of the AI checking off the pre-defined verification anchors:
    - `[AQ-1] Organization & Employee ID`: Shows `❌ EVADED` (scammer refused ID)
    - `[AQ-2] Request Call-Back Direct Line`: Shows `❌ FAILED` (insisted user must not hang up)
    - `[AQ-3] Inquiry on Fund Transfer Intent`: Shows `⚠️ FLAG TRIGGERED` (admitted transfer is needed)
    - `[AQ-4] Urgency & Consulting Check`: Shows `❌ FAILED` (threatened caller with legal action if they hang up)

---

### 2.5 User App Routing (React Router)
* `/`: Main Banking Dashboard (Home).
* `/transfer`: Dedicated Transaction & Multi-Agent Feedback Page.
* `/scan`: Phishing screenshot upload page.
* `/call-active`: Real-Time call monitoring and highlight simulation screen.

---

## 3. App 2: The Admin Dashboard (Fraud Operations)

### 3.1 Design Philosophy & Layout
The Admin Dashboard is designed for desktop. It focuses on high-density information display, real-time alerts, and comprehensive analytical views.

* **Layout Type**: Split-Pane View.
* **Aesthetics**: Dark mode preferred (or high-contrast professional light mode), utilizing a sleek, data-heavy design with clear typography, color-coded risk tiers (Red = High, Orange = Medium, Green = Low), and smooth transitions between case views.

### 3.2 Core Components

**Left Pane: Real-Time Case Feed**
* A vertically scrolling list of incoming fraud cases, updated in real-time via WebSocket (`/ws/session/{id}`).
* **Case Cards**: Displays Case ID, User ID, Trigger Type (e.g., `CALL`, `TRANSACTION`, `PHISHING`), Timestamp, and a color-coded Risk Score (0-100).
* **Sorting/Filtering**: Quick toggles to filter by "High Risk", "Pending Action", or "Resolved".

**Right Pane: Case Details & XAI Report (The "Inspector")**
When a case is selected from the left pane, this area populates with deep insights.
* **Header**: Case summary and immediate recommended action.
* **XAI (Explainable AI) Breakdown**:
  * **Risk Score Visualization**: A gauge or progress bar.
  * **Worker Findings Accordions**: Expandable sections for each AI worker involved in the case (Telemetry, Research, Financial, Phone, Phishing).
  * **Evidence List**: Bulleted array of raw evidence (e.g., "Matched Macau Scam blacklist", "High typing speed deviation").
* **Live Transcript/Screenshot Viewer**: 
  * If a `CALL` case: Displays a real-time scrolling transcript of the conversation with the Phone Worker.
  * If a `PHISHING` case: Displays the uploaded screenshot alongside the OCR extracted text.
* **Action Bar (Bottom/Top)**: Manual override buttons for the fraud officer (e.g., `Freeze Account`, `Flag for Review`, `Dismiss`).

### 3.3 Admin App Routing
* `/admin`: The main split-pane dashboard.
* `/admin/settings`: System configuration and rule toggles.
* `/admin/case/:id`: Direct link to a specific case context.

---

## 4. App 3: Scammer Call Simulator Web App (`/scammer`)

### 4.1 Design Philosophy & Layout
A simple, functional desktop web interface representing the scammer's calling software (Phone A). This page acts as the remote audio source for demonstrating live WebRTC call interception.

* **Layout Type**: Single-page dashboard containing a dialer panel and script scenario injection control.
* **Aesthetics**: Functional control deck design (grey borders, monospace feedback panels).

### 4.2 Core Components & Placing

#### 4.2.1 Target Connection Panel
Used to target the user sandbox instance:
* **Target User Input**:
  - **Label**: `Target User Session / ID`
  - **Type**: Text Input (`<input type="text">`)
  - **Placeholder**: `"Enter active banking session ID"`
* **Caller Masking Number**:
  - **Label**: `Spoofed Caller Number`
  - **Type**: Text Input (`<input type="text">`)
  - **Placeholder**: `"e.g., +6016-123-4567"`
* **Dialer Action Buttons**:
  - **Call Button**:
    - **Text**: `"📞 Dial Target"`
    - **Styling**: Green primary button, starts the WebRTC outbound connection to target.
  - **Hangup Button**:
    - **Text**: `"🔴 Disconnect Call"`
    - **Styling**: Red alert button.

#### 4.2.2 Scammer Scenario & Dialogue Injector
Allows the simulator operator to play pre-set scam dialogs (scanned by Whisper STT on the backend) to evaluate how effectively the AI highlights risk.

* **Live Mic Controls**:
  - **Mute Button**:
    - **Text**: `"🎤 Mute Microphone"` / `"🎙️ Unmute Microphone"` (Toggles local browser microphone capture streamed over WebRTC).
* **Scam Script Dialog Injector**:
  - **Label**: `Play Scam Script Template`
  - **Type**: Tabs/Accordion Group.
  - **Tab 1**: `"Macau Police Accusation Scam"`
  - **Tab 2**: `"EPF Fund Account Scam"`
  - **Tab 3**: `"LHDN Tax Audit Warning"`
* **Script Sentence Trigger Buttons**:
  - Within each scenario tab, renders a list of text rows representing parts of a scam call. Clicking the sound icon (`"🔊 Speak"`) next to each triggers the browser TTS to speak the line into the WebRTC stream to Phone B:
    - Row 1: `"Hello, this is Inspector Tan from PDRM Police HQ."` ➔ `[🔊 Speak Line]`
    - Row 2: `"We detected money laundering under your name. Your bank accounts will be seized."` ➔ `[🔊 Speak Line]`
    - Row 3: `"You must immediately move RM 10,000 to our safe audit account: Maybank 7653-1234-5678."` ➔ `[🔊 Speak Line]`
    - Row 4: `"Do not hang up this call or speak to anyone, otherwise we will dispatch officers to arrest you."` ➔ `[🔊 Speak Line]`

### 4.3 Scammer App Routing
* `/scammer`: The dialer interface and script player.

---

## 5. Shared UI/UX Guidelines (Vanilla CSS)


* **CSS Variables (`:root`)**: Define a strict design token system in `index.css` (primary colors, surface colors, text colors, border radiuses, shadows, and z-indexes).
* **Typography**: Modern sans-serif (e.g., Inter, Roboto, or Outfit) for clean readability.
* **Animations**: 
  * Use `transition: all 0.2s ease-in-out` for interactive elements.
  * Define `@keyframes` for the incoming call pulse, slide-in toasts, and modal popups to ensure the application feels highly dynamic and premium. 
* **Modularity**: Use CSS Modules (`Component.module.css`) to prevent global style leakage and maintain strict component-level styling. 
