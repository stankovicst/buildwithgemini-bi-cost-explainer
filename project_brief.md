# My agent: BI Cost Explainer
One-liner: A conversational assistant for a BI platform team that explains why BI spend changed across teams and tools with data-driven root causes and actionable fixes.

Tool coverage:
- Memory: User's team, preferred currency (e.g., USD, EUR), and alert threshold.
- Tools: Firestore query tools to retrieve and compare weekly BI cost records; free exchange-rate API to convert costs to EUR.
- Catalog/UI: Collection of weekly cost records and top dashboard drivers rendered as rich A2UI cards and tables.
- Image gen: Branded cover illustration for the BI Cost Explainer assistant / weekly reports.
- Sandbox: Code execution sandbox for calculating week-over-week percentages, cost variance math, and data-scan ratios.

Recommended for every project: memory, storage, tools, image generation, A2UI
Agent-specific / stretch (pick what fits): code sandbox for calculations, Firestore for structured cost records, external exchange-rate API, Cloud Trace

Domain & Data Details:
- Domain: BI Platform Cost Governance and Optimization (Looker, Looker Studio, Tableau).
- Dataset: Synthetic weekly BI cost records for 8 weeks across 4 teams (Sales, Supply Chain, Finance, Marketing) and 3 tools (Looker, Looker Studio, Tableau).
- Schema: week_start, team, tool, cost_usd, query_count, gb_processed, top_dashboard.
- Planted Story: In the week starting 2026-09-14, Sales' Looker Studio cost triples because one dashboard ("Daily Store Sales Live") runs full table scans — gb_processed spikes dramatically while query_count remains flat. Actionable fix: add a partition filter or switch from live queries to an extract/scheduled refresh.
- Red Herring: Marketing's query_count rises 40% that week, but cost barely moves because queries hit cached or small tables.
- Strict Grounding Rule: Every number, metric, and percentage in a reply must come from a tool lookup or code sandbox computation result, never guesses or hallucinations.
