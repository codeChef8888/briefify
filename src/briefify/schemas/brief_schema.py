from pydantic import BaseModel, Field
from typing import List, Literal

class AccountTrigger(BaseModel):
    account_id: str = Field(description="Unique CRM Account Identifier")
    company_name: str = Field(description="Target Account Company Name")

class DetailedTelemetryMetrics(BaseModel):
    seat_utilization_analysis: str = Field(
        description=(
            "Comprehensive 6-month seat utilization breakdown. Must cite exact active user counts vs "
            "allocated seats, calculate recent average %, peak %, and analyze capacity strain."
        )
    )
    api_volume_trend_analysis: str = Field(
        description=(
            "Detailed 12-month API transaction volume trajectory. Must cite specific starting and ending "
            "monthly call counts, calculate YoY percentage delta, and assess platform integration depth."
        )
    )
    support_operational_health: str = Field(
        description=(
            "In-depth analysis of critical support ticket volumes over 6-month and 12-month periods, "
            "identifying stability trends, operational friction, or escalation spikes."
        )
    )

class SalesBriefSchema(BaseModel):
    company_name: str = Field(description="Exact target company name")
    contract_tier: str = Field(description="Current subscription contract tier (e.g., Starter, Growth, Enterprise)")
    analysis_date: str = Field(description="Date of analysis formatted as 'Month DD, YYYY'")
    overall_health_score: int = Field(ge=1,le=100,description="Calculated health score between 1 (severe churn risk) and 100 (flawless growth)")
    primary_signal: Literal[
            "🟢 UPSELL OPPORTUNITY", 
            "🔴 CHURN / ENGAGEMENT RISK", 
            "🟡 UNTAPPED CAPACITY"
        ] = Field(description="Categorical health signal derived from historical telemetry heuristics")
    executive_summary: str = Field(
        description=(
            "A rich, multi-sentence executive summary (4-5 sentences) synthesizing account health, "
            "capacity constraints, feature enablement state, operational friction, and overall strategic position."
        )
    )
    metrics_summary: DetailedTelemetryMetrics = Field(
        description="Quantitative metrics and multi-month historical trends."
    )
    strategic_signal_evidence: str = Field(
        description=(
            "A thorough, multi-sentence diagnostic narrative detailing the exact evidence behind the primary signal. "
            "Highlight specific multi-month trends, product adoption depth, or capacity bottlenecks."
        )
    )
    actionable_talking_points: List[str] = Field(
        min_length=3,
        max_length=3,
        description=(
            "Exactly 3 highly strategic, multi-sentence proposals for the sales call. Each talking point MUST "
            "start with a bold title (e.g., '**1. Present the Capacity Bottleneck Insight:** ...') and include "
            "grounded data evidence followed by a concrete pitch or mutual plan."
        )
    )