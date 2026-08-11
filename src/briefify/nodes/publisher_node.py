from pathlib import Path
from google.adk import Event
from briefify.schemas.brief_schema import SalesBriefSchema


def _build_brief_markdown(brief: SalesBriefSchema) -> str:
    """Build canonical markdown used by both storage and frontend rendering."""
    return f"""# 📊 Executive Strategic Brief: {brief.company_name}
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

async def publish_brief_node(node_input: dict) -> Event:
    """Node 3: Writes the validated SalesBrief to disk and updates CRM.
    
    Cost: $0 LLM Tokens.
    """
    try:
        brief = SalesBriefSchema.model_validate(node_input)
    except Exception as exc:
        return Event(output={
            "status": "error",
            "message": f"Publisher validation failed: {str(exc)}"
        })

    output_dir = Path("output/briefs")
    file_path = output_dir / f"{brief.company_name.lower().replace(' ', '_')}_brief.md"
    markdown_content = _build_brief_markdown(brief)

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
    except OSError as exc:
        return Event(output={
            "status": "error",
            "message": f"Publisher file write failed: {str(exc)}"
        })

    return Event(output={
        "status": "published",
        "company_name": brief.company_name,
        "artifact_location": str(file_path.absolute()),
        "brief": markdown_content,
        "brief_data": brief.model_dump()
    })