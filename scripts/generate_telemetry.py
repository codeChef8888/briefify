import csv
import random
from datetime import datetime, timedelta


def generate_telemetry_dataset(filename: str = "account_telemetry.csv") -> None:
    """Generate synthetic account telemetry data for local testing and demos."""
    # Target accounts with deterministic behavioral archetypes.
    archetypes = {
        "Acme Corp": {"tier": "Growth", "base_seats": 100, "profile": "upsell"},
        "Beta Logistics": {"tier": "Enterprise", "base_seats": 500, "profile": "churn_risk"},
        "Gamma Tech": {"tier": "Starter", "base_seats": 50, "profile": "stagnant"},
    }

    # Additional baseline accounts for realistic distribution.
    company_names = [
        "Apex Systems", "BlueSky Media", "CloudScale AI", "DataPulse Inc",
        "Evolve Health", "Frontier Retail", "Global Logistics", "Hyperion Financial",
        "Innovate Labs", "Jupiter Networks", "Kinetix Solutions", "Lumina Tech",
        "Matrix Operations", "Nexus Capital", "Omni Soft", "Pinnacle Group",
        "Quantum Dynamics", "Redline Energy", "Strata Corp", "Titanium Digital",
    ]

    for name in company_names:
        archetypes[name] = {
            "tier": random.choice(["Starter", "Growth", "Enterprise"]),
            "base_seats": random.choice([25, 50, 100, 250, 500]),
            "profile": "standard",
        }

    # Monthly snapshots over 24 months (2024-09 through 2026-08).
    base_date = datetime(2024, 9, 1)
    months = 24

    rows = []
    account_id_counter = 1001

    for company_name, config in archetypes.items():
        account_id = f"ACC-{account_id_counter}"
        account_id_counter += 1
        tier = config["tier"]
        seats = config["base_seats"]
        profile = config["profile"]

        for month_idx in range(months):
            snapshot_date = (base_date + timedelta(days=month_idx * 30.5)).strftime("%Y-%m-01")

            if profile == "upsell":
                mau = int(seats * (0.85 + (month_idx / months) * 0.14))
                api_volume = 150000 + (month_idx * 12000) + random.randint(-2000, 2000)
                adv_features = True
                tickets = 0 if month_idx > 12 else random.choice([0, 1])
            elif profile == "churn_risk":
                decay_factor = max(0.3, 1.0 - (month_idx / months) * 0.5)
                mau = int(seats * 0.75 * decay_factor)
                api_volume = int(300000 * decay_factor) + random.randint(-5000, 5000)
                adv_features = False
                tickets = random.randint(3, 8) if month_idx >= 18 else random.randint(0, 2)
            elif profile == "stagnant":
                mau = int(seats * 0.25) + random.randint(-2, 2)
                api_volume = random.randint(5000, 12000)
                adv_features = False
                tickets = random.choice([0, 0, 1])
            else:
                mau = int(seats * random.uniform(0.4, 0.85))
                api_volume = random.randint(20000, 180000)
                adv_features = random.choice([True, False])
                tickets = random.choice([0, 0, 1, 2])

            rows.append(
                {
                    "account_id": account_id,
                    "company_name": company_name,
                    "snapshot_month": snapshot_date,
                    "active_users": mau,
                    "allocated_seats": seats,
                    "api_call_volume": api_volume,
                    "advanced_features_enabled": str(adv_features).lower(),
                    "critical_support_tickets": tickets,
                    "contract_tier": tier,
                }
            )

    fieldnames = [
        "account_id",
        "company_name",
        "snapshot_month",
        "active_users",
        "allocated_seats",
        "api_call_volume",
        "advanced_features_enabled",
        "critical_support_tickets",
        "contract_tier",
    ]

    with open(filename, mode="w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Successfully generated {len(rows)} telemetry rows in '{filename}'")


if __name__ == "__main__":
    generate_telemetry_dataset()
