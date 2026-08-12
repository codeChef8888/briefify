from pydantic import BaseModel, Field
from typing import List, Dict, Any


class CalculatedMetrics(BaseModel):
    seat_saturation_pct: float = Field(..., description="Active users vs allocated seats percentage")
    seat_utilization_pct: float = Field(..., description="Latest active users / latest allocated seats * 100")
    mau_6m_momentum_pct: float = Field(..., description="6-month active user growth percentage")
    mau_change_12m_pct: float = Field(..., description="Percentage change in active users over the 12-month window")
    api_12m_velocity_pct: float = Field(..., description="12-month API call volume growth percentage")
    recent_6m_tickets: int = Field(..., description="Critical support tickets in last 6 months")
    support_escalation_ratio: float = Field(..., description="Ratio of recent vs prior 6m tickets")
    ticket_trend: str = Field(..., description="SPIKING, STABLE, or DECREASING based on ticket escalation ratio")

class MLFeatureVector(BaseModel):
    heuristic_signal: str = Field(..., description="STRONG_EXPANSION_CANDIDATE, HIGH_CHURN_RISK, or STABLE_BASELINE")
    saturation_index_S_t: str
    mau_delta_U_6m: str
    api_growth_A_12m: str

class TelemetryFeatureOutput(BaseModel):
    calculated_metrics: CalculatedMetrics
    ml_feature_vector: MLFeatureVector
    
def compute_telemetry_features(records: List[Dict[str, Any]]) -> TelemetryFeatureOutput:
    """Computes quantitative momentum vectors and operational stability metrics 
    from historical monthly telemetry snapshots (sorted newest first).
    """
    if not records or len(records) < 2:
        raise ValueError("Insufficient historical data for feature engineering (minimum 2 months required).")

    latest = records[0]
    six_months_ago = records[min(5, len(records) - 1)]
    twelve_months_ago = records[-1]

    # 1. Current Seat Saturation Trajectory Index (S_t)
    allocated_seats = max(latest.get("allocated_seats", 1), 1)
    active_users_latest = latest.get("active_users", 0)
    seat_saturation_pct = round((active_users_latest / allocated_seats) * 100, 2)
    seat_utilization_pct = round((active_users_latest / allocated_seats) * 100, 2)

    # 2. 6-Month Active User Momentum Delta (ΔU_6m)
    mau_latest = active_users_latest
    mau_6m = six_months_ago.get("active_users", 0)
    mau_momentum_pct = round(((mau_latest - mau_6m) / max(mau_6m, 1)) * 100, 2)

    # 2b. 12-Month Active User Growth (ΔU_12m)
    mau_12m = twelve_months_ago.get("active_users", 0)
    mau_growth_12m_pct = round(((mau_latest - mau_12m) / max(mau_12m, 1)) * 100, 2)

    # 3. 12-Month API Volume Growth Velocity (ΔA_12m)
    api_latest = latest.get("api_call_volume", 0)
    api_12m = twelve_months_ago.get("api_call_volume", 0)
    api_velocity_pct = round(((api_latest - api_12m) / max(api_12m, 1)) * 100, 2)

    # 4. Support Escalation Ratio (E_s)
    recent_6m_tickets = sum(r.get("critical_support_tickets", 0) for r in records[:6])
    prior_6m_tickets = sum(r.get("critical_support_tickets", 0) for r in records[6:12])
    escalation_ratio = round(recent_6m_tickets / max(prior_6m_tickets, 1), 2)

    # 4b. Ticket Trend
    if escalation_ratio >= 2.0:
        ticket_trend = "SPIKING"
    elif escalation_ratio <= 0.5:
        ticket_trend = "DECREASING"
    else:
        ticket_trend = "STABLE"

    # 5. Deterministic Feature Heuristic Vector
    if seat_saturation_pct >= 90.0 and mau_momentum_pct >= 0 and recent_6m_tickets <= 2:
        heuristic_label = "STRONG_EXPANSION_CANDIDATE"
    elif mau_momentum_pct <= -25.0 or escalation_ratio >= 3.0:
        heuristic_label = "HIGH_CHURN_RISK"
    else:
        heuristic_label = "STABLE_BASELINE"

    return TelemetryFeatureOutput(
        calculated_metrics=CalculatedMetrics(
            seat_saturation_pct=seat_saturation_pct,
            seat_utilization_pct=seat_utilization_pct,
            mau_6m_momentum_pct=mau_momentum_pct,
            mau_change_12m_pct=mau_growth_12m_pct,
            api_12m_velocity_pct=api_velocity_pct,
            recent_6m_tickets=recent_6m_tickets,
            support_escalation_ratio=escalation_ratio,
            ticket_trend=ticket_trend,
        ),
        ml_feature_vector=MLFeatureVector(
            heuristic_signal=heuristic_label,
            saturation_index_S_t=f"{seat_saturation_pct}%",
            mau_delta_U_6m=f"{mau_momentum_pct}%",
            api_growth_A_12m=f"{api_velocity_pct}%",
        )
    )