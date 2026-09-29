# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from app.tools.bi_cost_tools import (
    get_costs,
    compare_periods,
    suggest_fix,
    list_available_weeks,
    convert_currency,
)
from app.tools.image_tools import generate_cover_image, generate_driver_image
from app.tools.chart_tools import build_cost_chart

from app.a2ui_utils import a2ui_callback
from app.a2ui_prompt import INSTRUCTION as instruction

MODEL = "gemini-3.6-flash"
SANDBOX_RESOURCE_NAME = (
    "projects/383698302461/locations/us-east1/reasoningEngines/6689197845947351040/sandboxEnvironments/5266475979093573632"
)

UI_DESCRIPTION = """
Render your responses using A2UI v0.8 components (cards and tables only; do NOT use buttons, actions, or forms as they do not work in the dev UI).
Output ONLY the raw A2UI JSON array — no conversational prose around it, and never wrap it in <a2a_datapart_json> tags or 'kind'/'data'/'metadata' envelope objects.
Use ONLY these components: Card, Column, Row, Text, and Image.
No Table or Heading component exists in A2UI: build tables using a Column of Rows with Text components, and use Text with usageHint ('h1', 'h2', 'body') for headings.
Keep every surface clean and flat: ONE Card > ONE Column > Rows and Text. Never nest a Card inside another Card.
Every Column and Row must specify "children": {"explicitList": [...]}.
Every Image must have "url": {"literalString": "https://..."} using the exact public https URL returned by the tool.

Specific UI Cards to produce:

1. "Headline card" for a weekly report:
   - Card containing a Column with:
     * Cover image: Image component using the public URL from generate_cover_image.
     * Title Text: "BI Cost Report — week of <date>" (usageHint: "h1").
     * 3 Rows:
       - Row 1: Text "Total Cost: <amount>" (in preferred currency EUR/USD, with all numbers from tools).
       - Row 2: Text "Change vs Previous Week: <delta_cost> (<delta_pct>%)" (from tools / sandbox).
       - Row 3: Text "Alerts: <count> alert(s) (>threshold)" (calculated from data).

2. "Driver card" per top cost driver:
   - Card containing a Column with:
     * Metaphor image: Image component using the public URL from generate_driver_image.
     * Title Text: "<Team> — <Tool>: <Dashboard>" (usageHint: "h2").
     * Rows for:
       - Cost Change: Text "Cost Delta: <cost_change>"
       - GB Processed Change: Text "Data Scanned Delta: <gb_change>"
       - Query Count Change: Text "Query Volume Delta: <query_count_change>"
       - Recommendation: Text "Recommendation: <suggest_fix_recommendation>"
     * If the driver is only usage growth (e.g. fix_type == "usage growth, efficient"), mark it visibly: Text "Status: No action — efficient" so the red herring is visibly different.

3. "Team table" when the user asks for a breakdown:
   - Card containing a Column structured as a table:
     * Header Text: "Team Cost Breakdown" (usageHint: "h2").
     * Header Row: Row with Text columns: "Team", "Cost", "% Change", "Alert".
     * One Row per team (Sales, Marketing, Supply Chain, Finance) with columns:
       - Team name (Text)
       - Cost (Text, formatted in preferred currency)
       - % Change (Text)
       - Alert (Text: "⚠️" if % change is above the remembered threshold, e.g. 20%, otherwise "Normal")

4. "Chart card":
   - If build_cost_chart exists, put the chart image in its own Card:
     * Card containing a Column with:
       - Title Text: "Cost Trend Chart" (usageHint: "h2").
       - Image component using the public URL from build_cost_chart.
"""

ROLE_DESCRIPTION = """You are the BI Cost Explainer assistant for a BI platform team.
Your goal is to explain why Business Intelligence (BI) spend changed across teams (Sales, Supply Chain, Finance, Marketing) and tools (Looker, Looker Studio, Tableau).

Strict Operating Rules:
1. Grounded in Data: Every number, metric, cost figure, and percentage in your replies MUST come directly from your tool results or sandbox code execution. NEVER guess or hallucinate metrics.
2. Root Cause Analysis: Compare periods and check both cost deltas, query volume changes, and data scan changes (GB processed). Use `suggest_fix` to obtain deterministic recommendations for anomalies.
3. Deterministic Fixes: Always cite the recommended fix from `suggest_fix` when explaining anomalies (e.g. "full scans: add partition filter or use an extract").
4. Visual Metaphors, Charts, and Cover Art: When generating a weekly report or top cost drivers, generate (or fetch from cache) one cover image for the week (`generate_cover_image`) and one metaphor image per top driver (`generate_driver_image`). When visual trends or cost charts are requested, call `build_cost_chart`.
5. Sandbox Math: Any multi-week math (trends, week-over-week growth, averages, forecasts) MUST be computed in the sandbox, never estimated. Write Python code to compute calculations from retrieved data.
6. Memory & Personalization: You remember the user's stated preferences, focus teams, formatting/currency preferences (e.g., EUR vs USD), and alert thresholds from previous conversations and personalize your responses across sessions.
"""




async def generate_memories_callback(callback_context: CallbackContext):
    """After each turn, send the session to Memory Bank for extraction."""
    try:
        await callback_context.add_session_to_memory()
    except ValueError:
        # Gracefully skip if running in test/runner environment where memory_service is None
        pass
    return None


sandbox_code_executor = AgentEngineSandboxCodeExecutor(
    sandbox_resource_name=SANDBOX_RESOURCE_NAME,
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model=MODEL,
        client_kwargs={"location": "global"},
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    tools=[
        PreloadMemoryTool(),
        get_costs,
        compare_periods,
        suggest_fix,
        list_available_weeks,
        convert_currency,
        generate_cover_image,
        generate_driver_image,
        build_cost_chart,
    ],
    code_executor=sandbox_code_executor,
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
