from pathlib import Path
from google.adk import Event
from briefify.schemas.brief_schema import SalesBriefSchema
from briefify.schemas.error_contract import build_error


def _detect_refusal(node_input: dict) -> str | None:
    """Best-effort refusal detection for model safety/policy blocks."""
    if not isinstance(node_input, dict):
        return None

    direct_refusal = node_input.get("refusal") or node_input.get("refusal_reason")
    if isinstance(direct_refusal, str) and direct_refusal.strip():
        return direct_refusal.strip()

    text_blobs = [
        str(node_input.get("message", "")),
        str(node_input.get("error", "")),
        str(node_input.get("text", "")),
    ]
    combined = " ".join(text_blobs).lower()
    refusal_markers = ("refus", "safety", "policy", "blocked", "content restriction")
    if any(marker in combined for marker in refusal_markers):
        return "Strategist model refused to generate a brief due to safety/policy constraints"

    return None


def _build_brief_markdown(brief: SalesBriefSchema) -> str:
    """Build canonical markdown used by both storage and frontend rendering."""
    talking_points = [
        point if point.lstrip().startswith(("- ", "* ")) else f"- {point}"
        for point in brief.actionable_talking_points
    ]

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
{chr(10).join(talking_points)}
"""

async def publish_brief_node(node_input: dict) -> Event:
    """Node 3: Writes the validated SalesBrief to disk and updates CRM.
    
    Cost: $0 LLM Tokens.
    """
    refusal_reason = _detect_refusal(node_input)
    if refusal_reason:
        return Event(output=build_error(
            code="MODEL_REFUSAL",
            message=refusal_reason,
            stage="publisher_node",
            retryable=False,
            status="refused",
        ))

    try:
        brief = SalesBriefSchema.model_validate(node_input)
    except Exception as exc:
        return Event(output=build_error(
            code="PUBLISHER_VALIDATION_FAILED",
            message=f"Publisher validation failed: {str(exc)}",
            stage="publisher_node",
            retryable=False,
        ))

    output_dir = Path("output/briefs")
    file_path = output_dir / f"{brief.company_name.lower().replace(' ', '_')}_brief.md"
    markdown_content = _build_brief_markdown(brief)

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
    except OSError as exc:
        return Event(output=build_error(
            code="PUBLISHER_FILE_WRITE_FAILED",
            message=f"Publisher file write failed: {str(exc)}",
            stage="publisher_node",
            retryable=True,
        ))

    return Event(output={
        "status": "published",
        "company_name": brief.company_name,
        "artifact_location": str(file_path.absolute()),
        "brief": markdown_content,
        "brief_data": brief.model_dump()
    })