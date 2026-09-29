# Frontend Redesign: Modern Interactive BI Cost Dashboard + Agent Chat

## Use Case & Core Philosophy
A BI platform lead opens the dashboard on Monday morning to answer:
1. **What changed?** (Computed in code directly from Firestore, rendered instantaneously on the left dashboard in <5s).
2. **Why and what to do?** (Agent on the right explains root causes, cites deterministic remediations, and shows A2UI cards & visual metaphors).

## Architecture & Data Flow
- **FastAPI Direct Data Endpoints** (`GET /api/summary`, `/api/timeseries`, `/api/drivers`, `/api/fx`):
  Query Firestore `bi_costs` directly using the GCP Project ID. All math (deltas, %, growth, sparklines) is calculated deterministically in Python. Zero LLM hallucinations for metrics.
- **Agent Chat Proxy** (`POST /chat`):
  Communicates over A2A protocol to Agent Platform Agent Runtime, returning text & rich A2UI card envelopes.
- **Frontend Layer**:
  Single-page zero-build HTML/CSS/JS with Chart.js (CDN). Dark navy palette (`#0B1426` / `#162238`), teal (`#14b8a6`), amber (`#f59e0b`), red (`#ef4444`), green (`#10b981`).

## Layout & Components
- **Desktop (65% Dashboard / 35% Chat)** | **Mobile (Stacked, Collapsible Bottom Chat)**
- **Header**: Title, Week selector (defaults to latest), USD/EUR currency toggle, Alert threshold settings popover (stored in localStorage).
- **Insights Strip (3 Cards)**:
  1. 🔴 Top Cost Driver (Team/Tool/Dashboard, Cost Δ, Remediation label)
  2. 🟢 Red-Herring Detector (Highest query surge with flat spend -> "efficient growth, no action")
  3. ⚠️ Alert Count (Groups exceeding threshold) with "Ask agent why →" CTAs.
- **KPI Summary Row**: Total Spend, Spend Δ vs Prior Week, Total GB Scanned, Total Query Count — each with micro sparkline canvas.
- **Interactive Charts (Chart.js)**:
  1. *Tool Trend Line Chart*: 8-week spend per tool with selected week vertical band highlight.
  2. *Team Stacked Bar Chart*: Weekly team spend breakdown.
  3. *Cost Efficiency Quadrant Scatter*: X = Query Δ%, Y = GB Scanned Δ%, bubble size = Cost Δ. Quadrants: Top-Left (Full scans), Top-Right (Expensive live), Bottom-Right (Efficient growth), Bottom-Left (Declining).
  4. *Top-5 Drivers Table*: Sortable, with deterministic fix badges.
- **Cross-Component Interactivity**:
  Clicking any chart point, bar, or table row prefills and focuses the chat input with targeted questions. Currency/week toggles re-render all visual components smoothly.
