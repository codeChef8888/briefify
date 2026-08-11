# Briefify: Agentic AI Telemetry & Strategic Briefing Engine

Briefify is an event-driven multi-agent system that turns B2B software telemetry into executive sales briefs when an account reaches `Qualified` status in a CRM.

## Tech Stack
- **Data Layer:** Google BigQuery Sandbox (parameterized SQL)
- **Tooling:** FastMCP (Model Context Protocol)
- **Reasoning:** Google Gemini Flash (`google-genai`)
- **Orchestration:** Google ADK workflow graph
- **Integration:** FastAPI webhook API + Streamlit dashboard + file publisher

## Repository Layout
- `src/briefify`: Core application package (API, nodes, agents, schemas, telemetry, MCP tools)
- `app.py`: Streamlit dashboard UI
- `scripts`: Utility and manual-run scripts
- `tests`: Automated test suite root
- `output/briefs`: Generated brief markdown artifacts
- `output/logs`: Execution ledger artifacts

## Quickstart

### 1. Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY="your-api-key"
```

### 2. Google Cloud Authentication
```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_GCP_PROJECT_ID
```

### 3. Generate Telemetry Data
```bash
python scripts/generate_telemetry.py
```
Upload `account_telemetry.csv` to BigQuery dataset `crm_telemetry`, table `account_usage`.

### 4. Run FastAPI Backend
```bash
PYTHONPATH=src uvicorn briefify.api.main:app --reload --port 8000
```

### 5. Run Streamlit Dashboard
```bash
streamlit run app.py
```

### 6. Trigger CRM Event (Optional via cURL)
```bash
curl -X POST "http://127.0.0.1:8000/webhook/crm-event" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"account.status_changed","company_name":"Acme Corp","status":"Qualified","account_id":"ACC-1001"}'
```

Generated briefs are written to `output/briefs`.