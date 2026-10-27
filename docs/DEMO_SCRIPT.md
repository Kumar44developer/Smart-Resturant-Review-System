# Demo Script (≈8 minutes)

A guided walkthrough that shows the platform **and** its honesty guarantees. Run the
app first:

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py seed-demo
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8008
```

Open <http://127.0.0.1:8008/> and sign in as **demo@smart.app / demo12345**.
Keep DevTools → Network open if you like; every figure on screen is a live API call.

---

### 1. Dashboard — "everything is computed" (1 min)
Point at the KPIs (review volume, average rating, sentiment mix, **analysis coverage**)
and the **DEMO MODE** badge.

> Say: "Nothing here is hardcoded. These are aggregates over the stored review rows,
> and the app is transparently telling me it's running the deterministic demo pipeline."

**Proof:** refresh — numbers are stable because they come from data, not randomisation.

### 2. Reviews + mixed sentiment (1.5 min)
Open a review whose text praises food but complains about service. Show that the
analysis keeps **food = positive** and **service = negative** on the *same* review, and
that `latest_analysis` stores measured fields separately from the summary.

> Say: "A naive tool would average this into one 'neutral'. We preserve the nuance,
> because the operational signal is in the breakdown."

### 3. Analytics — no fake trends (1 min)
Show sentiment/rating trends and the aspect leaderboard. Then open a restaurant with a
single month of data and point out `enough_data: false` — **the trend is suppressed,
not invented**.

### 4. Ask (RAG) — citations + honest refusal (2 min)
Ask: *"What do people say about the service?"* → the answer lists **citations**; click
one to show it resolves to a real review **in this restaurant**.

Then ask: *"What was our total revenue last quarter?"* → it **refuses**:
`abstain: true, reason: out_of_scope`.

> Say: "Revenue was never ingested, so the assistant won't guess it. And every claim it
> *does* make is traceable to a specific review."

### 5. Reply Studio — human-in-the-loop (1.5 min)
On a negative review, generate a draft. Show it is labelled **AI-generated**, starts as
a **draft**, and is grounded in the real complaint aspects. Edit it, then approve.

> Say: "Approval records a human decision. There is **no code path that publishes this
> anywhere** — an actual person still sends the reply."

### 6. Operations — traceable advice (1 min)
Run **Detect alerts** and **Compute recommendations**. Open a recommendation and show its
**supporting review ids** and the measured metric behind an alert.

### 7. Evaluation — we measure what we ship (1 min)
`POST /api/v1/evaluation/run?restaurant_id=1` (or the Evaluation page). Show the
sentiment accuracy / macro-F1, aspect micro-F1, and RAG abstention + citation-integrity
scores — and that the run is **persisted** with dataset/model/prompt versions.

> Say: "These numbers describe the pipeline that is actually running. We're not quoting a
> benchmark we never executed."

---

## Closing points
- **Multi-tenant by construction** — the tests prove one restaurant can never read another.
- **Replaceable AI** — swap the demo provider for Groq/OpenAI by setting env vars only.
- **Honest by default** — labelled synthetic data, abstention, evidence links, human approval.

## One-command smoke test (alternative to the UI)
```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q     # 46 passed
```

## End-to-end over real HTTP (with a server already running)
```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8009   # terminal 1
..\.venv\Scripts\python.exe verify_e2e.py                          # 23/23 checks
```
