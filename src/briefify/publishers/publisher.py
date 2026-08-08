import os
import json
from pathlib import Path
from abc import ABC, abstractmethod
from briefify.schemas.brief_schema import SalesBriefSchema

class BasePublisher(ABC):
    @abstractmethod
    def publish(self, account_id: str, brief: SalesBriefSchema) -> str:
        pass

# class LocalCMSPublisher(BasePublisher):
#     """Publishes Markdown artifacts locally and updates a mock CMS registry."""
#     def __init__(self, output_dir: str = "output/briefs"):
#         self.output_dir = Path(output_dir)
#         self.output_dir.mkdir(parents=True, exist_ok=True)

#     def publish(self, account_id: str, brief: SalesBriefSchema) -> str:
#         file_path = self.output_dir / f"{brief.company_name.lower().replace(' ', '_')}_brief.md"
        
#         markdown_content = f"""# 📊 Executive Strategic Brief: {brief.company_name}
# **Contract Tier:** {brief.contract_tier} | **Health Score:** {brief.overall_health_score}/100
# **Primary Signal:** {brief.primary_signal}

# ---

# ## 1. Executive Summary
# {brief.executive_summary}

# ## 2. Telemetry Metrics
# - **Seat Utilization:** {brief.metrics_summary.seat_utilization_pct}%
# - **API Call Volume:** {brief.metrics_summary.api_volume_trend}
# - **Critical Support Tickets:** {brief.metrics_summary.critical_tickets_count}

# ## 3. Actionable Talking Points
# """ + "\n".join([f"- {point}" for point in brief.actionable_talking_points])

#         with open(file_path, "w", encoding="utf-8") as f:
#             f.write(markdown_content)
            
#         return str(file_path.absolute())


class LocalCMSPublisher:
    """Publishes rich Markdown artifacts locally and updates mock CMS registry."""
    def __init__(self, output_dir: str = "output/briefs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def publish(self, account_id: str, brief: SalesBriefSchema) -> str:
        file_path = self.output_dir / f"{brief.company_name.lower().replace(' ', '_')}_brief.md"
        
        # Build formatted bullet list for talking points
        talking_points_formatted = "\n\n".join(
            [f"{point}" for point in brief.actionable_talking_points]
        )

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
{talking_points_formatted}
"""

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
            
        return str(file_path.absolute())
    
    
class SalesforceNotePublisher(BasePublisher):
    """Simulates publishing a ContentNote directly to a Salesforce Account record via REST API."""
    def publish(self, account_id: str, brief: SalesBriefSchema) -> str:
        # Construct standard Salesforce REST ContentNote Payload
        sf_payload = {
            "Title": f"AI Strategic Brief - {brief.company_name}",
            "Content": brief.executive_summary,
            "ParentId": account_id
        }
        # Returns simulated Salesforce ContentNote ID
        return f"SF_ContentNote_ID_mock_{account_id}_success"