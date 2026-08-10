from typing import List, Dict, Any

def compute_telemetry_features(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Computes quantitative momentum vectors and operational stability metrics 
    from historical monthly telemetry snapshots (sorted newest first).
    """
    if not records or len(records) < 2:
        return {"error": "Insufficient historical data for feature engineering."}

    latest = records[0]
    six_months_ago = records[min(5, len(records) - 1)]
    twelve_months_ago = records[-1]

    # 1. Current Seat Saturation Trajectory Index (S_t)
    allocated_seats = max(latest.get("allocated_seats", 1), 1)
    seat_saturation_pct = round((latest.get("active_users", 0) / allocated_seats) * 100, 2)

    # 2. 6-Month Active User Momentum Delta (ΔU_6m)
    mau_latest = latest.get("active_users", 0)
    mau_6m = six_months_ago.get("active_users", 0)
    mau_momentum_pct = round(((mau_latest - mau_6m) / max(mau_6m, 1)) * 100, 2)

    # 3. 12-Month API Volume Growth Velocity (ΔA_12m)
    api_latest = latest.get("api_call_volume", 0)
    api_12m = twelve_months_ago.get("api_call_volume", 0)
    api_velocity_pct = round(((api_latest - api_12m) / max(api_12m, 1)) * 100, 2)

    # 4. Support Escalation Ratio (E_s)
    recent_6m_tickets = sum(r.get("critical_support_tickets", 0) for r in records[:6])
    prior_6m_tickets = sum(r.get("critical_support_tickets", 0) for r in records[6:12])
    escalation_ratio = round(recent_6m_tickets / max(prior_6m_tickets, 1), 2)

    # 5. Deterministic Feature Heuristic Vector
    if seat_saturation_pct >= 90.0 and mau_momentum_pct >= 0 and recent_6m_tickets <= 2:
        heuristic_label = "STRONG_EXPANSION_CANDIDATE"
    elif mau_momentum_pct <= -25.0 or escalation_ratio >= 3.0:
        heuristic_label = "HIGH_CHURN_RISK"
    else:
        heuristic_label = "STABLE_BASELINE"

    return {
        "calculated_metrics": {
            "seat_saturation_pct": seat_saturation_pct,
            "mau_6m_momentum_pct": mau_momentum_pct,
            "api_12m_velocity_pct": api_velocity_pct,
            "recent_6m_tickets": recent_6m_tickets,
            "support_escalation_ratio": escalation_ratio,
        },
        "ml_feature_vector": {
            "heuristic_signal": heuristic_label,
            "saturation_index_S_t": f"{seat_saturation_pct}%",
            "mau_delta_ΔU_6m": f"{mau_momentum_pct}%",
            "api_growth_ΔA_12m": f"{api_velocity_pct}%",
        }
    }