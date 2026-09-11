# TranSafe v2 — Demo Video Recording Plan

> **Status:** grounded in a live, verified run of the system (2026-09-11/12), not in
> the design docs. Where `06_demo_runbook.md` disagrees with this file, this file
> wins — that document was written before implementation and still says "CodeBuddy"
> and `src.api.main:app`.

---

## 0. The short version

**Three decisions carry the whole plan. Make them before you touch a recorder.**

1. **Pre-warm before you hit record.** The discovery sweep takes **~4 minutes**. It is
   unusable as live footage. Run it once, then record starting from VALIDATION.
2. **Use REPLAY for the visual story, LIVE for the numeric proof.** REPLAY lights up
   the whole nervous system in **18 seconds**. The live eval/adaptation loop produces
   the numbers. Each is bad at what the other is good at.
3. **Record the MCP act on a second take.** It needs WorkBuddy in another window, and
   it is the only act where something outside your app can fail on camera.

Everything else below is detail.

---

## 1. What you are actually recording

The story, in one line: *a scam wave hits, the system discovers the campaign on its own,
compiles a defence, and gets measurably better at catching it.*

The numbers that carry it — all **measured**, not projected:

| Metric | Before | After | Where it comes from |
|---|---|---|---|
| Detection rate (all variants) | 66.7% | **96.7%** | `▶ RUN ADAPTATION`, Evaluation screen |
| **Red-team detection** | 20% | **90%** | same |
| False positive rate | 0% | **0%** | same — lead with this, it's the honest one |
| Core artifact | v6 | **v8** | header counter `Core` |
| New rule discovered | — | **R-3** | Registry diff, `+2 −0` |

**Lead with the false-positive number.** Anyone can make a detector fire more often.
"Red-team detection 20% → 90% with **zero** new false positives" is the claim that
survives a judge's follow-up question.

---

## 2. Real timings — plan around these, not around estimates

These are stopwatch numbers from a live run. The **bold** one will ruin your video if
you don't plan for it.

| Action | Duration | On camera? |
|---|---|---|
| `CHECK READINESS` | ~8 s | ✅ Yes — it's a good credibility beat |
| `PREPARE DEMO` (reset + discovery sweep) | **~236 s (4 min)** | ❌ **Never** |
| `VALIDATION` → `✅ Approve` | ~1 s click, publish lands within seconds | ✅ Yes |
| `▶ RUN EVAL` | ~20 s | ✅ Yes |
| `▶ RUN ADAPTATION` | ~30 s | ✅ Yes |
| `RESET` | ~25–40 s | ❌ Only before recording |
| REPLAY replay of the 5-act sequence | **18.1 s** at `speed=1` | ✅ Yes |
| WorkBuddy `ask_transafe` round trip | ~8 s | ✅ Yes, separate take |

**Total recordable content: ~4–5 minutes.**

---

## 3. The pre-warm decision

`PREPARE DEMO` is the button that produces an approvable campaign. You cannot skip it —
**REPLAY's `campaign_proposed` is broadcast but *not persisted*** (a replay is a
rehearsal; it never writes to `ns_events`), so a replay campaign has nothing to approve.

So you have exactly two options:

| Option | How | Best for |
|---|---|---|
| **A. Pre-warm (recommended)** | Run `PREPARE DEMO`, wait 4 min, then start recording at VALIDATION | A tight, scripted video. Nothing to cut around. |
| **B. Record and speed-ramp** | Record the wait, cut it to ~5 s at 16×, caption "discovery sweep — 4 min, accelerated" | If you want to prove the wait is real |

**Do A.** Option B looks like a cut, and a judge who suspects a cut distrusts the
numbers that follow. If you want to show the wait is genuine, show the
`discovery_sweep_started` → `discovery_sweep_completed` event pair on the Overview feed
instead — same proof, no dead air.

---

## 4. Pre-flight — T minus 60 minutes

Run this top to bottom. Do not skip step 6.

```bash
# 1. Backend (no --reload: a mid-run restart drops in-flight background tasks
#    and looks exactly like the pipeline failing)
cd backend
unset proxies && export NO_PROXY='*'
uv run uvicorn main:app --host 127.0.0.1 --port 8000

# 2. Enterprise console
cd frontend/enterprise
npm run dev -- --port 5174 --strictPort

# 3. (optional, Act 1 only) v1 consumer app — the "victim" screen
cd frontend/transafe
npm run dev -- --port 5173

# 4. Log the backend to a file, not the terminal, so a noisy socket can't
#    flood your recording window:
#    ... >> /tmp/transafe-backend.log 2>&1 &
```

**5. Confirm readiness before anything else:**

```bash
curl -s localhost:8000/enterprise/preflight
```

You want `ok: true | Ready` and all six checks green — in particular:

```
[pass] core_artifact  phone_agent_core v6 published
[pass] llm            deepseek-chat (served as deepseek-flash) answered, no reasoning tokens
```

If `llm` says **warn** (thinking mode) or **fail** (empty content), stop. Every
downstream number depends on that check.

**6. Reset to the clean opening position, then pre-warm.** In the console:

1. Click `PREP`. Confirm `CHECK READINESS` is all green — this is your on-camera beat later.
2. Click `PREPARE DEMO`. Wait ~4 minutes.
3. You are ready when the panel reads **"Candidate campaign ready — open VALIDATION to review it."**

Verify the starting state in the header before recording:

```
Cases 127 · Open 127 · ⚠ Unrecognised 6 · Campaigns 3 · Core v6 · Exposure RM 0
```

`Campaigns 3` includes SCAM-027 `PENDING_VALIDATION`. That is your Act 1.

> **If it says "Timed out" but the counters changed** — you're on an older build. The
> timeout bug was fixed; pull the latest `transafe-enterprise` branch.

---

## 5. Recording setup

**Screen layout.** Record the console full-window. Do **not** try a 2-up split for the
main takes — at 1080p the console's small labels (chart axes, evidence rows) become
unreadable, and legibility of the numbers is the entire point.

- **Browser:** Chrome, one tab, `http://localhost:5174`, F11 full-screen.
- **Hide:** bookmarks bar (`⌘⇧B`), any extensions with toolbar icons, other tabs.
- **Notifications:** macOS Focus / Do Not Disturb **on**. A Slack banner over the
  adaptation chart is a wasted take.
- **Resolution:** record at 1920×1080 minimum, 2560×1440 if your machine is happy.
- **Zoom:** browser at 100%. If your display is smaller than 1080p tall, zoom *out* to
  90% rather than scrolling — the whole header (counters + Core version) needs to be in
  frame, because that's where v6 → v8 lands.
- **Cursor:** enabled. The viewer needs to see what you clicked.

**Recorder.** QuickTime is fine for a single screen and simplest to start. OBS if you
want the WorkBuddy window as a second scene and hotkey switching. Either way: **30 fps,
record at high bitrate** — you can always compress later, but you cannot recover text
legibility from a low-bitrate capture.

**Audio.** Record narration live if you're comfortable; otherwise record silent and dub,
which makes it trivial to re-take a fluffed line without re-doing the clicks. For a
competition video I'd **dub** — the clicking is the hard part to redo, the talking isn't.

**One thing to check before every take:** the header badge must read **`LIVE`** with a
**green dot**. If the dot is dark the WebSocket is down and nothing will stream.

---

## 6. The shot list

Five takes. Each is independently re-recordable, which is the point.

### Take 1 — Discovery already happened (20 s) · *no clicks*

Open on the header and the Overview feed.

> "Four minutes ago I pressed one button. This is what the system did on its own: six
> previously unconnected cases clustered into a campaign candidate it had never seen
> before. Nobody wrote a rule for it. It found it."

Point at `⚠ Unrecognised 6` → `Campaigns 3`. Let the event feed sit on screen.

**Don't** click `RUN SCENARIO` here. In LIVE mode it only stops a replay — it does
nothing visible, and clicking a dead button on camera reads as a broken app.

---

### Take 2 — Human validation (45 s) · *1 click*

`VALIDATION` → click **SCAM-027 PENDING_VALIDATION**.

Let the evidence panel land. This is the strongest credibility beat in the whole video,
so slow down here:

> "Left column is **computed** — six cases, six distinct victims, strongest link 1.00,
> six-day span. Read the note at the bottom: *'No language model was involved in
> producing it.'* The right column is the LLM's hypothesis. We keep them visually
> separate so you can see which is which."

Then click **`✅ Approve`**.

> "That's the only human decision in the loop."

The three buttons grey out. Hold for a beat.

---

### Take 3 — The defence compiles (40 s) · *no clicks*

`REGISTRY`.

> "Five pack artifacts — one per downstream worker. And here's the interesting one:
> the generaliser found a rule that spans **all three** campaigns, so the *core* skill
> moved from v6 to v7. Not a per-campaign rule. A core rule."

Point at the diff — `+2 −0`, and the new **R-3**:

> "R-3 escalates when the caller tells the victim to keep the conversation secret from
> their family. That indicator came from *this* campaign. It is now general policy."

**Caption at edit time:** `phone_agent_core v6 → v7 · +2 rules · 0 regressions`

---

### Take 4 — The proof (75 s) · *2 clicks*

`EVALUATION`.

Optional but I recommend it: click **`▶ RUN EVAL`** first (~20 s).

> "Scored against the red-team corpus: 66.7%. A new campaign pack did **not** move the
> needle — and I want you to see that, because it's the honest picture."

Then click **`▶ RUN ADAPTATION`** (~30 s).

> "Now the adaptation loop: it scores the corpus, generalises one structural rule from
> what it *missed*, and re-scores."

The cards update. Hold on the numbers.

> "Red-team detection, 20% to 90%. Detection overall 66.7 to 96.7. And false positives:
> zero, before and after. It got dramatically better at catching attacks without
> getting any more trigger-happy."

**Caption:** `Core v6 → v8 · red-team 20% → 90% · FP 0% → 0%`

This is the take to spend your time on. If you only nail one, nail this one.

---

### Take 5 — The boundary (45 s) · *separate take, second window*

Bring WorkBuddy forward **in the same frame** as the console's `MCP LOG` screen.

**Do the WorkBuddy `ask_transafe` call BEFORE you open MCP LOG.** The redaction summary
reads `redaction lens unavailable — assuming least privilege` until at least one MCP call
exists. Showing that message on camera looks like a broken screen.

> "A third-party agent — Tencent WorkBuddy — calls TranSafe over MCP. It never touches
> the database. The Liaison Agent retrieves, redacts by role, and answers with citations.
> TranSafe doesn't control what WorkBuddy does with the answer. It exposes intelligence.
> That's the boundary."

Point at the `mcp_call` row landing in MCP LOG.

**Cut here if the round trip misbehaves.** This is the act most likely to fail, and it
is the least load-bearing. The video stands without it.

---

## 7. Timing budget

| Segment | Runtime |
|---|---|
| Cold open (Take 1) | 0:20 |
| Validation + approve (Take 2) | 0:45 |
| Registry diff (Take 3) | 0:40 |
| **The proof** (Take 4) | 1:15 |
| MCP boundary (Take 5) | 0:45 |
| Intro / outro / titles | 0:30 |
| **Total** | **~4:15** |

Budget **90 minutes** of wall clock for the whole session: 60 min pre-flight (mostly the
4-minute warm-up plus verification), then ~30 min of takes. Do not plan to record and
finish in the same half hour.

---

## 8. Risks, and what to do when they bite

| Risk | How it looks | Do this |
|---|---|---|
| **4-min warm-up** | Dead air if you record it | Pre-warm (§3, Option A) |
| **LLM latency spike** | `▶ RUN EVAL` sits on "RUNNING…" | Rehearse it once. If a take exceeds ~40 s, abort the take and re-run — don't wait it out on camera |
| **Supabase DNS flake** | Every screen empties; console errors | `curl -s localhost:8000/enterprise/preflight`. If supabase fails, wait 60 s and retry. This was transient before; it recovers |
| **WebSocket drops** | Green dot turns dark, feed stops | Reload the page. The console reconnects and replays a 25-event backlog |
| **`⚠ FIXTURE` badge appears** | Red badge, screens show fabricated data | **Stop the take.** The backend died and the console is rendering placeholders. Restart the backend, reload, reset, re-warm |
| **Stale eval chart** | Old bars still on screen after a reset | Fixed — reload if you see it |
| **screens show `Cases —`** | Counters all dashes | Usually just not loaded yet. Wait 5 s. If it persists, the proxy is down; restart the console |
| **Approved the wrong campaign** | Demo state advanced | Click `RESET`, then `PREPARE DEMO` again (4 min). Budget for one of these |

**Before every take, glance at two things:** the `LIVE` badge with a green dot, and the
absence of a `FIXTURE` badge. Those two checks catch most of the above.

---

## 9. Post-production

- **Captions carry the numbers.** Overlay them (`20% → 90%`, `FP 0% → 0%`) the moment
  they land. Judges rewatch; make the claim readable without the audio.
- **Zoom into the evidence panel** in Take 2 during the "no language model" line. It's
  small text and it's the most quotable thing on screen.
- **Speed-ramp any unavoidable wait** to ~16× with a visible "accelerated" caption.
  Never cut silently — an unexplained jump beside a benchmark number is a trust problem.
- **Do not add music over the narration.** It buys nothing and costs clarity.
- **Keep one uncut continuous take** of Take 4 as a separately exported file. If a judge
  asks whether the benchmark is real, that single clip answers it.

---

## 10. Rehearsal

**Do one full dry run 24 hours before.** It is not optional, because the two things most
likely to go wrong — the 4-minute warm-up and the WorkBuddy round trip — are the two you
cannot fix by re-clicking quickly.

Then:

1. Dry run end to end, recording enabled. Keep the file even though you'll re-record.
2. Watch it back **at 1× with the sound off**. If the numbers aren't legible, your
   resolution or zoom is wrong, and no amount of editing fixes it.
3. Fix the setup, then record takes 1–5 in order.
4. Name files for the take, not the date: `take4-eval-proof-g3.mp4`. You will do
   Take 4 more than once.

**Reset between full attempts.** After Take 4 the state is Core v8 with eval runs
present — re-running `PREPARE DEMO` resets it cleanly.

---

## Appendix — reference

**Ports:** backend `8000` · console `5174` · consumer app `5173`

**Commands**
```bash
# backend
cd backend && uv run uvicorn main:app --host 127.0.0.1 --port 8000
# console
cd frontend/enterprise && npm run dev -- --port 5174 --strictPort
# readiness
curl -s localhost:8000/enterprise/preflight
# reset (same as the RESET button)
curl -X POST localhost:8000/enterprise/demo/reset -H 'Content-Type: application/json' -d '{}'
# replay the 5-act sequence, slowed for narration (console button uses speed 1 = 18 s)
curl -X POST localhost:8000/enterprise/demo/scenario \
  -H 'Content-Type: application/json' -d '{"mode":"replay","speed":0.5}'
```

**Clean opening state:** Core v6 · Campaigns 2 (SCAM-019, SCAM-024) · 127 cases ·
Unrecognised 0 · no eval run

**Warmed state (record from here):** Core v6 · Campaigns 3 · Unrecognised 6 ·
SCAM-027 `PENDING_VALIDATION`

**The five acts in REPLAY** (25 events, 18.1 s at `speed=1`): `I_sensing` →
discovery → compiler → `IV_compile` → `V_proof`. The recorded `mcp_call` names caller
`workbuddy`, so the replay is current with the WorkBuddy switch.

**Keys:** `M` toggles LIVE/REPLAY · `R` resets. **Don't press either while recording** —
`R` wipes the campaign you just warmed up.
