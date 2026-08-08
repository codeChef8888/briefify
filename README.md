# Briefify: Agentic AI Telemetry & Strategic Briefing Engine

Briefify is an event-driven multi-agent system that turns raw B2B software telemetry into executive sales briefs when an account reaches "Qualified" status in a CRM.

## Tech Stack
* **Data Layer:** Google BigQuery Sandbox (Parameterized SQL)
* **Tooling:** FastMCP (Model Context Protocol)
* **Reasoning:** Google Gemini 3.5 Flash (`google-genai`)
* **Orchestration:** Google ADK / Python Agentic Pipeline
* **Integration:** FastAPI (Webhook Listener) & Local File System (Artifact Publisher)

## Quickstart Guide

### 1. Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY="your-api-key"

2. Google Cloud Authentication

```bash

gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_GCP_PROJECT_ID

3. Generate Data & Seed BigQuery

```bash

python data/generate_telemetry.py
# Upload account_telemetry.csv to BigQuery dataset 'crm_telemetry', table 'account_usage'

4. Run Webhook Server

```bash

PYTHONPATH=src uvicorn briefify.api.main:app --reload --port 8000

5. Trigger CRM Event

```bash

curl -X POST "[http://127.0.0.1:8000/webhook/crm-event](http://127.0.0.1:8000/webhook/crm-event)" \
     -H "Content-Type: application/json" \
     -d '{"event_type":"account.status_changed","company_name":"Acme Corp","status":"Qualified"}'

Finally:
     Check output/briefs/acme_corp_brief.md for the generated briefing.