from pathlib import Path
from google.adk import Event
from briefify.schemas.brief_schema import SalesBriefSchema

async def publish_brief_node(node_input: dict) -> Event:
    """Node 3: Writes the validated SalesBrief to disk and updates CRM.
    
    Cost: $0 LLM Tokens.
    """
    brief = SalesBriefSchema.model_validate(node_input)
    
    output_dir = Path("output/briefs")
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{brief.company_name.lower().replace(' ', '_')}_brief.md"
    
    markdown_content = f"""# 📊 Executive Strategic Brief: {brief.company_name}
**Contract Tier:** {brief.contract_tier} | **Analysis Date:** {brief.analysis_date} | **Health Score:** {brief.overall_health_score}/100

---

## 1. Executive Summary
{brief.executive_summary}

## 2. Telemetry Breakdown & Key Metrics
- **Seat Utilization:** {brief.metrics_summary.seat_utilization_analysis}
- **API Call Volume Trend:** {brief.metrics_summary.api_volume_trend_analysis}
- **Support & Operational Health:** {brief.metrics_summary.support_operational_health}

## 3. Strategic Signal & Risk Assessment
{brief.primary_signal}

**Evidence:**
{brief.strategic_signal_evidence}

## 4. Actionable Next Steps for Sales Call
{chr(10).join(brief.actionable_talking_points)}
"""
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
        
    return Event(output={
        "status": "published",
        "company_name": brief.company_name,
        "artifact_location": str(file_path.absolute()),
        "brief_data": brief.model_dump()
    })