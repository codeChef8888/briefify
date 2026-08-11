import streamlit as st
import requests
import time
import uuid
import pandas as pd
import plotly.express as px


def _render_brief_from_data(brief_data: dict) -> str:
    """Build markdown from structured brief payload when direct markdown is absent."""
    metrics = brief_data.get("metrics_summary", {}) if isinstance(brief_data, dict) else {}
    talking_points = brief_data.get("actionable_talking_points", []) if isinstance(brief_data, dict) else []
    tp_text = "\n".join(talking_points) if isinstance(talking_points, list) and talking_points else "No talking points generated."

    return f"""# 📊 Executive Strategic Brief: {brief_data.get('company_name', 'Unknown Account')}
**Contract Tier:** {brief_data.get('contract_tier', 'N/A')} | **Analysis Date:** {brief_data.get('analysis_date', 'N/A')} | **Health Score:** {brief_data.get('overall_health_score', 'N/A')}/100

---

## 1. Executive Summary
{brief_data.get('executive_summary', 'No summary generated.')}

## 2. Telemetry Breakdown & Key Metrics
- **Seat Utilization:** {metrics.get('seat_utilization_analysis', 'N/A')}
- **API Call Volume Trend:** {metrics.get('api_volume_trend_analysis', 'N/A')}
- **Support & Operational Health:** {metrics.get('support_operational_health', 'N/A')}

## 3. Strategic Signal & Risk Assessment
{brief_data.get('primary_signal', 'N/A')}

**Evidence:**
{brief_data.get('strategic_signal_evidence', 'N/A')}

## 4. Actionable Next Steps for Sales Call
{tp_text}
"""

st.set_page_config(page_title="Briefify Agentic Dashboard", layout="wide")

st.title("⚡ Briefify Agentic Sales Briefing Engine")
st.caption("3-Node Architecture | BigQuery → Gemini 3.5 Flash → CRM Publisher")

# Sidebar Configuration
st.sidebar.header("Backend API Settings")
backend_base_url = st.sidebar.text_input("FastAPI Base URL", value="http://127.0.0.1:8000")
# telemetry_csv = st.sidebar.file_uploader("Upload Telemetry CSV", type=["csv"])

# Preset mock target accounts
ACCOUNT_PRESETS = {
    "Acme Corp": {"id": "ACC-1001"},
    "Beta Logistics": {"id": "ACC-1002"},
    "Gamma Tech": {"id": "ACC-1003"},
    "Apex Systems": {"id": "ACC-1004"},
    "BlueSky Media": {"id": "ACC-1005"},
    "CloudScale AI": {"id": "ACC-1006"},
    "DataPulse Inc": {"id": "ACC-1007"},
    "Evolve Health": {"id": "ACC-1008"},
    "Frontier Retail": {"id": "ACC-1009"},
    "Global Logistics": {"id": "ACC-1010"},
    "Hyperion Financial": {"id": "ACC-1011"},
    "Innovate Labs": {"id": "ACC-1012"},
    "Jupiter Networks": {"id": "ACC-1013"},
    "Kinetix Solutions": {"id": "ACC-1014"},
    "Lumina Tech": {"id": "ACC-1015"},
    "Matrix Operations": {"id": "ACC-1016"},
    "Nexus Capital": {"id": "ACC-1017"},
    "Omni Soft": {"id": "ACC-1018"},
    "Pinnacle Group": {"id": "ACC-1019"},
    "Quantum Dynamics": {"id": "ACC-1020"},
    "Redline Energy": {"id": "ACC-1021"},
    "Strata Corp": {"id": "ACC-1022"},
    "Titanium Digital": {"id": "ACC-1023"},
}

col_left, col_right = st.columns([1, 1.2])

# Left Column: Event Trigger & Data Telemetry
with col_left:
    st.subheader("1. Webhook Trigger Controls")
    
    selected_company = st.selectbox("Select Target Account", options=list(ACCOUNT_PRESETS.keys()))
    account_info = ACCOUNT_PRESETS[selected_company]
    
    col_a, col_b = st.columns(2)
    with col_a:
        crm_status = st.selectbox("CRM Status", options=["Qualified", "Prospect", "Negotiation"])
    # with col_b:
    #     event_type = st.text_input("Event Type", value="account.status_changed")

    account_id = st.text_input("Account ID", value=account_info["id"])
    
    trigger_btn = st.button("🚀 Dispatch CRM Webhook", type="primary", use_container_width=True)

    st.divider()
    # st.subheader("2. Historical Telemetry Visualizer")
    
    # if telemetry_csv:
    #     df = pd.read_csv(telemetry_csv)
    #     account_df = df[df["company_name"] == selected_company]
        
    #     if not account_df.empty:
    #         account_df["utilization_pct"] = (account_df["active_users"] / account_df["allocated_seats"]) * 100
            
    #         fig = px.line(
    #             account_df, 
    #             x="snapshot_month", 
    #             y=["utilization_pct", "critical_support_tickets"],
    #             title=f"Telemetry History: {selected_company}",
    #             labels={"value": "Metrics", "snapshot_month": "Month"}
    #         )
    #         st.plotly_chart(fig, use_container_width=True)
    #         st.dataframe(account_df.tail(4), use_container_width=True)
    #     else:
    #         st.warning(f"No records found for '{selected_company}' in uploaded file.")
    # else:
    #     st.info("Upload `account_telemetry.csv` in the sidebar to render account visuals.")

# Right Column: Live Pipeline Trace & Strategic Brief Output
with col_right:
    st.subheader("3. Pipeline Execution Trace & Sales Brief")
    
    if trigger_btn:
        # EXACT CRMEventPayload Match
        payload = {
            "event_type": "account.status_changed",
            "company_name": selected_company,
            "status": crm_status,
            "account_id": account_id,
            "event_id": f"evt_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        }
        
        target_endpoint = f"{backend_base_url.rstrip('/')}/webhook/crm-event"
        
        try:
            # 1. Post to FastAPI
            res = requests.post(
                target_endpoint, 
                json=payload, 
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if res.status_code == 202:
                try:
                    init_data = res.json()
                except ValueError:
                    st.error("Webhook accepted response was not valid JSON.")
                    st.text(res.text)
                    st.stop()
                
                if init_data.get("status") == "ignored":
                    st.warning(f"⚠️ **Pipeline Ignored:** {init_data.get('message')}")
                else:
                    job_id = init_data.get("job_id")
                    if not job_id:
                        st.error("Webhook response missing `job_id`; cannot poll workflow status.")
                        st.json(init_data)
                        st.stop()

                    st.success(f"Webhook Accepted | Job ID: `{job_id}`")
                    
                    # Live Pipeline Visualizer Container
                    trace_box = st.container(border=True)
                    with trace_box:
                        st.markdown("**Node 1: `fetch_usage_data` (Python Node)**")
                        n1 = st.empty()
                        n1.info("⏳ Extracting parameterized usage data from BigQuery...")

                        st.markdown("**Node 2: `strategist_agent` (Gemini Flash Node)**")
                        n2 = st.empty()
                        n2.text("⏸️ Awaiting Node 1 payload...")

                        st.markdown("**Node 3: `publish_sales_brief` (Python Node)**")
                        n3 = st.empty()
                        n3.text("⏸️ Awaiting Node 2 synthesis...")

                    # 2. Poll Async Job Endpoint
                    attempts = 0
                    while attempts < 35:
                        time.sleep(0.8)
                        attempts += 1
                        
                        try:
                            poll_res = requests.get(
                                f"{backend_base_url.rstrip('/')}/jobs/{job_id}",
                                timeout=(3.0, 12.0)
                            )
                        except requests.exceptions.ReadTimeout:
                            # Background job can temporarily delay status checks; keep polling.
                            n1.info("⏳ Waiting for status endpoint response...")
                            continue
                        except requests.exceptions.RequestException as poll_err:
                            st.error(f"Polling request failed: {poll_err}")
                            break

                        if poll_res.status_code == 200:
                            try:
                                job_data = poll_res.json()
                            except ValueError:
                                st.error("Polling response was not valid JSON.")
                                st.text(poll_res.text)
                                break

                            job_status = job_data.get("status")
                            
                            if job_status in {"queued", "processing"}:
                                n1.success("✅ Complete: Direct BigQuery data extraction ($0.00)")
                                n2.info("⏳ Synthesizing brief via Gemini 3.5 Flash...")
                                
                            elif job_status == "completed":
                                n1.success("✅ Complete: Direct BigQuery data extraction ($0.00)")
                                n2.success("✅ Complete: Strategic Brief generated (1 Single-Turn Call)")
                                n3.success("✅ Complete: Written to Salesforce Note / CRM ($0.00)")
                                
                                result = job_data.get("result", {})
                                brief_content = result.get("brief") or result.get("sales_brief")
                                if not brief_content and isinstance(result.get("brief_data"), dict):
                                    brief_content = _render_brief_from_data(result["brief_data"])
                                if not brief_content:
                                    brief_content = "No brief text generated."
                                
                                # Render Executive Briefing
                                st.divider()
                                st.markdown(f"### Generated Sales Brief: {selected_company}")
                                st.markdown(brief_content)

                                artifact_path = result.get("artifact_location")
                                if artifact_path:
                                    st.caption(f"Published artifact: {artifact_path}")
                                
                                st.divider()
                                m1, m2, m3 = st.columns(3)
                                m1.metric("Execution Time", f"{job_data.get('execution_time_sec', 0)}s")
                                m2.metric("LLM API Calls", "1 Turn")
                                m3.metric("Tool Cost Overhead", "$0.00")
                                break
                                
                            elif job_status == "failed":
                                n2.error("❌ Node Execution Failed")
                                st.error(f"Error Details: {job_data.get('error')}")
                                if isinstance(job_data.get("result"), dict) and job_data["result"].get("message"):
                                    st.info(f"Workflow message: {job_data['result']['message']}")
                                break
                            else:
                                n1.info(f"Current pipeline status: {job_status}")
                        else:
                            st.error(f"Polling HTTP Error {poll_res.status_code}: {poll_res.text}")
                            break
                    else:
                        st.warning("Timed out waiting for workflow completion. Please retry polling with the same job ID.")
                            
            elif res.status_code == 422:
                st.error("❌ HTTP 422 Unprocessable Entity")
                st.json(res.json())
            else:
                st.error(f"HTTP Error {res.status_code}: {res.text}")

        except requests.exceptions.RequestException as err:
            st.error(f"Could not connect to FastAPI server at `{backend_base_url}`. Error: {err}")
    else:
        st.info("Select options and click 'Dispatch CRM Webhook' to test execution.")