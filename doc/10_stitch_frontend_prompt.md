# Google Stitch Code Generation Prompt: TranSafe Frontend Implementation

Feed this prompt to the Google Stitch code generation assistant to build the frontend application for the TranSafe project.

---

## System Context & Tech Stack

You are building the frontend codebase for **TranSafe**, a multi-agent real-time fraud prevention platform. The workspace must contain three independent web interfaces built using **Vite + React + React Router** and styled with **Vanilla CSS** (do NOT use Tailwind).

### Styling Guidelines (Vanilla CSS)
All styles must be managed via CSS Variables defined in a global `src/index.css` file. Choose a premium, dark-themed cyber-security aesthetic:
- `--primary`: `#0066FF` (Safe banking blue)
- `--bg-dark`: `#0B0F19` (Deep canvas)
- `--surface`: `#161D30` (Glassmorphic cards)
- `--text-main`: `#F3F4F6` (White-grey)
- `--risk-high`: `#EF4444` (Alert red)
- `--risk-med`: `#F59E0B` (Warning amber)
- `--risk-low`: `#10B981` (Safe green)
- **Glassmorphic Effect**: Use `backdrop-filter: blur(12px); background: rgba(22, 29, 48, 0.75); border: 1px solid rgba(255, 255, 255, 0.08);` for cards and modals.
- **Interactions**: Subtle `transition: all 0.2s ease-in-out` on all hover and focus states.

### Routing Table
Configure `react-router-dom` to support these views:
- `/` - User App Home Dashboard (Mobile banking simulation)
- `/transfer` - User App Dedicated Transaction Page with Multi-Agent scan results
- `/scan` - User App Phishing Screenshot Upload page
- `/call-active` - User App Active Call simulation screen (with highlights & transcript overlay)
- `/admin` - Admin Dashboard (Split-pane desktop view)
- `/admin/case/:id` - Admin Inspector View for a specific fraud case
- `/scammer` - Scammer Call Simulator Panel (Desktop dialer & script injector)

---

## Page-by-Page Specifications

### 1. User Web App (Victim Simulator)
*Constraints*: Constrain the main viewport wrapper of this app to a mobile viewport container (`max-width: 410px; height: 844px; border-radius: 40px; margin: 2rem auto; box-shadow: 0 20px 50px rgba(0,0,0,0.5); position: relative; overflow: hidden;`) centered on a desktop screen to simulate a phone frame.

#### 1.1 Home Dashboard (`/`)
- **Balance Card**: Renders account holder details: `"SAVINGS ACCOUNT"`, `"RM 24,530.80"`, and a primary action button labeled `"Send Money"` (navigates to `/transfer`).
- **Activity Section**: Text header `"Recent Activity"`. List of 3-4 mock transactions containing beneficiary name, time, and amount (e.g. `"Ali Bin Ahmad", "Today, 2:15 PM", "-RM 150.00"`).
- **Navigation Bar**: Bottom-docked menu bar with 4 tabs: `"Home"`, `"Transfer"`, `"Scan"`, and `"Settings"`.

#### 1.2 Phishing Screenshot Upload (`/scan`)
- **Upload Box**: Standard drag-and-drop box with label `"Upload suspicious chat or message screenshot"` and a button labeled `"Choose File"`.
- **Button**: A primary button labeled `"Analyze Image"` which triggers a mock uploading progress spinner and navigates back to Home with a success toast.

#### 1.3 Transaction Page (`/transfer`)
Renders a wizard containing three sequential panels:
- **Panel A: The Transfer Form**:
  - `Beneficiary Bank` Dropdown: Options include `Maybank`, `CIMB Bank`, `Public Bank`, `RHB Bank`.
  - `Recipient Name` Text Input: (Placeholder: `"e.g., JOHN DOE"`).
  - `Account Number` Text Input: Hyphenated account string validation.
  - `Amount (MYR)` Numeric Input: (Placeholder: `"0.00"`).
  - `Description / Reference` Text Input: (Placeholder: `"e.g., Investment Payment"`).
  - `Link Transaction to Recent Activity` Radio Options: 
    - Option 1: `"Check for recent active calls / phishing checks automatically"`
    - Option 2: `"Link a specific context manually"` (Displays a dropdown containing recent mock call and screenshot cases).
    - Option 3: `"No prior activity relates to this transfer"`.
  - Action buttons: `"Authorize Transfer"` (triggers scanner) and `"Cancel & Go Back"`.
- **Panel B: Live Security Scanner Overlay**:
  - Activated upon submission. Form gets disabled. Displays a circular progress indicator with header `"SecureTransfer Active Scan"`.
  - Displays a log terminal scrolling through WebSocket status updates:
    - `"Orchestrator: Routing transaction trigger..."`
    - `"Financial Worker: Reviewing 90-day transaction deviations..."`
    - `"Telemetry Worker: Inspecting behavioral biometrics..."`
    - `"Research Worker: Querying national scam databases..."`
    - `"Risk Scorer: Integrating parameters..."`
    - `"Explainable AI: Formatting human-readable verdict..."`
- **Panel C: Multi-Agent System Verdict**:
  - **Risk Score Gauge**: Renders score (0-100) inside a visual dial.
  - **Risk Tier Badge**:
    - `LOW`: Green badge (`"LOW RISK — APPROVED"`)
    - `MEDIUM`: Orange badge (`"MEDIUM RISK — REVIEW TRIGGERED"`)
    - `HIGH`: Red badge (`"HIGH RISK — ACTION DISPATCHED"`)
  - **Verdict Summary**: Renders bilingual XAI output (English & Malay).
  - **System Action Banner**: Dynamic message depending on action taken:
    - `FREEZE_30_MIN`: `"🚨 Protection Triggered: Your banking account has been temporarily frozen for a 30-minute cooling-off period under Bank Negara Malaysia guidelines."`
    - `BLOCK_TRANSACTION`: `"🚫 Transaction Blocked: Recipient account matches a known fraudulent account in the NSRC database."`
  - **Action Buttons**: `"Dismiss & Return to Home"` and `"Call NSRC Hotline (997)"` (visible only on Medium/High risk).

#### 1.4 Active Call Screen (`/call-active`)
Acts as a full-screen overlay mimicking an incoming call:
- **Ringing HUD**: Shows caller ID `"Unknown Caller (+6016-123-4567)"` with pulsing green `"Decline"` and red `"Accept"` icons.
- **Listen Mode Panel**:
  - **Suspicion Indicator**: A progress bar shifting Green ➔ Orange ➔ Red as the suspicion score increases.
  - **Live Transcript Bubble Log**: Renders scrolling conversation bubbles. Risky phrases must be styled in bold red underlined text with a hovering tag (e.g., `"...transfer `**`RM 5,000 to our safe account immediately` [Fund Transfer]**` or face arrest."`).
- **Auto-Talk Interception Mode Panel**:
  - Displays dialogue log with a robot icon for AI statements (e.g. `🤖 AI: Can you provide your employee ID?`).
  - Renders the scammer's text, maintaining the same real-time bold red underlined highlights.
  - **Anchor Checklist Card**: Visual checklist with status icons (`Pending`, `Answered`, `Evaded`, `Failed`) for `[AQ-1] Organization ID`, `[AQ-2] Call-Back Direct Line`, `[AQ-3] Transfer Intent Inquiry`, `[AQ-4] Urgency & Consult Check`.
  - Button: `"🎙️ Take Over Call"` (terminates AI loop).

---

### 2. Admin Dashboard (desktop View)
Exposes a premium split-pane operation dashboard at `/admin`:

- **Left Pane (Live Case Feed)**:
  - Scrollable grid listing case cards in real-time.
  - Card fields: Case ID, Trigger type (`CALL`, `TRANSACTION`, `PHISHING`), Timestamp, and a badge color-coded to the Risk Score (0-100).
- **Right Pane (Case Inspector)**:
  - Opens when a card on the left pane is clicked.
  - Renders:
    - Case header and recommended action.
    - Explanations accordion: Individual cards for `Financial Worker`, `Telemetry Worker`, and `Research Worker` showing their scores and evidence lists.
    - Media panel: If call, renders full scrollable text transcript; if phishing screenshot, renders the uploaded image and extracted OCR text.
    - Actions panel: Button bar containing: `"Freeze User Account"`, `"Flag Case for Review"`, and `"Dismiss Alert"`.

---

### 3. Scammer Call Simulator (`/scammer`)
Simulates the scammer's dialing computer (desktop format):

- **Target Connection Deck**:
  - Input field: Target session ID.
  - Input field: Spoofed number (Default: `+6016-123-4567`).
  - Action buttons: `"📞 Dial Target"` (starts call simulation) and `"🔴 Disconnect Call"`.
- **Dialogue Script Injector**:
  - Microphone toggle button: `"🎤 Mute Microphone"` / `"🎙️ Unmute Microphone"`.
  - Script Selectors: Tabs for `"Macau Police Accusation Scam"`, `"EPF Fund Account Scam"`, `"LHDN Tax Audit Warning"`.
  - Sentence injection list: Buttons next to dialogue lines (e.g. `"You must move RM 10,000 to Maybank 7653-1234-5678"`) that play the text via TTS or inject it directly as speech into the active WebRTC connection to Phone B.

---

## State Synchronization & Mock WebSocket Server

Provide a React Context (`SimulationContext`) that binds all three apps together:
1. **Real-time WebSockets**:
   - Establish actual connection to `ws://localhost:8000/ws/session/{session_id}` and `ws://localhost:8000/ws/call/{id}/events`.
2. **Offline Simulation Mode (Critical for Demos)**:
   - If the backend is not running, the application must detect connection failure and fallback to a fully local **Simulation Runner** loop.
   - When dialing from `/scammer`, it should automatically trigger the Ringing Modal in the User App.
   - When speech lines are clicked on `/scammer`, the local loop must append the line to `/call-active`'s live transcript, calculate mock suspicion scores, generate text highlights, and check off corresponding anchor checklist items.
   - When `"Authorize Transfer"` is clicked, it should run a 5-second mock timer, appending status logs before outputting a pre-set high-risk verdict to show off the system capabilities offline.
