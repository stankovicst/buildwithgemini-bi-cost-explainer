"""Chart generation tool using matplotlib with brand dark navy / teal / amber styling."""

import io
import uuid
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from google.cloud import storage
from google.genai import types
from google.adk.tools import ToolContext
from app.tools.bi_cost_tools import get_costs

PROJECT_ID = "qwiklabs-gcp-03-6baaeaff7c42"
BUCKET_NAME = "bi-cost-explainer-o7rv0e"
_storage_client = storage.Client(project=PROJECT_ID)

TOOL_COLORS = {
    "Looker": "#2ec4b6",         # Teal
    "Looker Studio": "#f77f00",  # Amber
    "Tableau": "#00b4d8",        # Cyan / Accent
}


async def build_cost_chart(
    team: str | None = None,
    tool_context: ToolContext = None,
) -> str:
    """Renders a line chart of weekly cost per tool over the 8-week period using Firestore data.

    Args:
        team: Optional team filter (Sales, Supply Chain, Finance, Marketing).
        tool_context: ADK ToolContext injected automatically by the runtime.

    Returns:
        The public HTTPS URL of the rendered chart PNG.
    """
    records = get_costs(team=team)
    if not records:
        return "No cost records found to chart."

    # Aggregate weekly cost per tool: {tool: {week: cost}}
    data: dict[str, dict[str, float]] = {}
    weeks_set = set()
    for r in records:
        w = r["week_start"]
        t = r["tool"]
        c = float(r["cost_usd"])
        weeks_set.add(w)
        if t not in data:
            data[t] = {}
        data[t][w] = data[t].get(w, 0.0) + c

    weeks = sorted(list(weeks_set))

    # Matplotlib styling: Dark navy background (#0b132b), teal and amber lines
    bg_color = "#0b132b"
    card_color = "#1c2541"
    text_color = "#e0e1dd"

    fig, ax = plt.subplots(figsize=(10, 5), facecolor=bg_color)
    ax.set_facecolor(card_color)

    for tool_name, week_costs in data.items():
        y_vals = [week_costs.get(w, 0.0) for w in weeks]
        color = TOOL_COLORS.get(tool_name, "#e76f51")
        ax.plot(
            weeks,
            y_vals,
            marker="o",
            linewidth=2.5,
            markersize=6,
            color=color,
            label=tool_name,
        )

    title = f"Weekly BI Cost per Tool ({team} Team)" if team else "Weekly BI Cost per Tool (All Teams)"
    ax.set_title(title, color=text_color, fontsize=14, pad=15, weight="bold")
    ax.set_xlabel("Week Starting", color=text_color, fontsize=11, labelpad=10)
    ax.set_ylabel("Cost (USD)", color=text_color, fontsize=11, labelpad=10)
    ax.tick_params(colors=text_color, which="both")
    ax.grid(True, linestyle="--", alpha=0.25, color="#ffffff")

    plt.xticks(rotation=30, ha="right")

    legend = ax.legend(facecolor=bg_color, edgecolor="#4a5568")
    for text in legend.get_texts():
        text.set_color(text_color)

    for spine in ax.spines.values():
        spine.set_color("#4a5568")

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    png_bytes = buf.getvalue()

    filename = f"chart_{team.lower() if team else 'all'}_{uuid.uuid4().hex[:8]}.png"

    # Save artifact for Playground Artifacts panel
    if tool_context and hasattr(tool_context, "save_artifact"):
        try:
            await tool_context.save_artifact(
                filename=filename,
                artifact=types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
            )
        except Exception as e:
            print(f"Notice: artifact saving skipped: {e}")

    # Upload to Cloud Storage
    bucket = _storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(png_bytes, content_type="image/png")

    return f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
