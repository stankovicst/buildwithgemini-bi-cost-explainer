"""Seed script for Firestore bi_costs collection."""

import random
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-03-6baaeaff7c42"
COLLECTION_NAME = "bi_costs"

WEEKS = [
    "2026-08-03",
    "2026-08-10",
    "2026-08-17",
    "2026-08-24",
    "2026-08-31",
    "2026-09-07",
    "2026-09-14",  # Spike & red herring week
    "2026-09-21",
]

TEAMS = ["Sales", "Supply Chain", "Finance", "Marketing"]
TOOLS = ["Looker", "Looker Studio", "Tableau"]

TOP_DASHBOARDS = {
    ("Sales", "Looker"): "Sales Pipeline & Territory Exec",
    ("Sales", "Looker Studio"): "Daily Regional Sales",
    ("Sales", "Tableau"): "Quota Attainment Matrix",
    ("Supply Chain", "Looker"): "Global Freight Tracking",
    ("Supply Chain", "Looker Studio"): "Warehouse Fulfillment Live",
    ("Supply Chain", "Tableau"): "Supplier Reliability Index",
    ("Finance", "Looker"): "Corporate P&L Realtime",
    ("Finance", "Looker Studio"): "Expense Variance Tracker",
    ("Finance", "Tableau"): "Cash Flow & Runway Model",
    ("Marketing", "Looker"): "Customer Acquisition Funnel",
    ("Marketing", "Looker Studio"): "Social Ad Campaign Insights",
    ("Marketing", "Tableau"): "Multi-touch Attribution Deck",
}

# Base weekly stats (cost_usd, query_count, gb_processed)
BASE_STATS = {
    ("Sales", "Looker"): (3100.0, 18500, 62000.0),
    ("Sales", "Looker Studio"): (1200.0, 15000, 45000.0),
    ("Sales", "Tableau"): (1550.0, 6200, 18500.0),
    ("Supply Chain", "Looker"): (1900.0, 9500, 35000.0),
    ("Supply Chain", "Looker Studio"): (750.0, 6000, 12000.0),
    ("Supply Chain", "Tableau"): (2200.0, 7100, 28000.0),
    ("Finance", "Looker"): (2500.0, 8200, 31000.0),
    ("Finance", "Looker Studio"): (620.0, 4100, 9800.0),
    ("Finance", "Tableau"): (1800.0, 5200, 21000.0),
    ("Marketing", "Looker"): (2250.0, 11200, 41000.0),
    ("Marketing", "Looker Studio"): (820.0, 9800, 14000.0),
    ("Marketing", "Tableau"): (1150.0, 5100, 16000.0),
}


def generate_records():
    records = []
    # Deterministic seed for consistency
    rng = random.Random(42)

    for week in WEEKS:
        for team in TEAMS:
            for tool in TOOLS:
                base_cost, base_queries, base_gb = BASE_STATS[(team, tool)]
                top_dashboard = TOP_DASHBOARDS[(team, tool)]

                # Standard subtle jitter (+/- 3%)
                jitter = rng.uniform(-0.03, 0.03)
                cost = round(base_cost * (1 + jitter), 2)
                queries = int(base_queries * (1 + jitter))
                gb = round(base_gb * (1 + jitter), 2)

                # Planted story: In week starting 2026-09-14, Sales' Looker Studio cost triples
                # because "Daily Store Sales Live" does full table scans: gb_processed spikes while queries flat
                if team == "Sales" and tool == "Looker Studio":
                    if week == "2026-09-14":
                        cost = 3600.00  # Exactly 3x baseline $1,200
                        queries = 15050  # Flat (+0.3%)
                        gb = 148500.00  # Spikes 3.3x from 45,000 GB due to unpartitioned full table scans
                        top_dashboard = "Daily Store Sales Live"
                    elif week == "2026-09-21":
                        # Remains high into next week
                        cost = 3580.00
                        queries = 15100
                        gb = 147200.00
                        top_dashboard = "Daily Store Sales Live"

                # Red herring: In week starting 2026-09-14, Marketing's query_count rises 40%,
                # but cost barely moves (queries hit cached/small aggregate tables)
                if team == "Marketing" and tool == "Looker Studio" and week == "2026-09-14":
                    queries = int(base_queries * 1.40)  # +40% query count
                    cost = round(base_cost * 1.015, 2)   # Cost barely moves (+1.5%)
                    gb = round(base_gb * 1.02, 2)        # GB barely moves (+2%)
                    top_dashboard = "Social Ad Campaign Insights"

                doc_id = f"{week}_{team.lower().replace(' ', '_')}_{tool.lower().replace(' ', '_')}"
                record = {
                    "week_start": week,
                    "team": team,
                    "tool": tool,
                    "cost_usd": cost,
                    "query_count": queries,
                    "gb_processed": gb,
                    "top_dashboard": top_dashboard,
                }
                records.append((doc_id, record))

    return records


def main():
    print(f"Connecting to Firestore using project ID: {PROJECT_ID}...")
    db = firestore.Client(project=PROJECT_ID)
    collection = db.collection(COLLECTION_NAME)

    records = generate_records()
    print(f"Generated {len(records)} records (8 weeks x 4 teams x 3 tools). Seeding into '{COLLECTION_NAME}'...")

    batch = db.batch()
    count = 0
    total = len(records)

    for doc_id, data in records:
        doc_ref = collection.document(doc_id)
        batch.set(doc_ref, data)
        count += 1
        if count % 500 == 0:
            batch.commit()
            batch = db.batch()

    batch.commit()
    print(f"Successfully seeded {total} documents into Firestore collection '{COLLECTION_NAME}'!")


if __name__ == "__main__":
    main()
