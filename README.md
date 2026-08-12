# Briefify: Agentic AI Telemetry and Strategic Briefing Engine

Briefify is an event-driven AI pipeline that converts CRM account events into executive sales briefs.
The runtime flow is:
FastAPI webhook -> Google ADK workflow graph -> BigQuery telemetry retrieval -> Gemini strategist synthesis -> markdown brief publishing.

For a full design walkthrough, see ARCHITECTURE.md.

## Repository Layout (Why Files Exist Outside src)

This repository follows a standard Python src-layout:
- `src/briefify`: importable application package code.
- root-level files (`pyproject.toml`, `README.md`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `requirements.txt`): project metadata, docs, and runtime/deployment tooling.
- `scripts/generate_telemetry.py`: canonical telemetry dataset generator.


## 1. Overview

Core stack:
- Python (project runtime requires >= 3.11)
- Google ADK (`google-adk>=2.6.3`) for graph-based orchestration
- FastAPI for webhook ingestion and async job status APIs
- Google BigQuery for telemetry analytics queries
- Gemini (`google-genai`) for structured brief generation
- FastMCP available in the repository for MCP tooling support (not required in the active runtime path)
- Streamlit UI (`app.py`) for end-to-end demo interaction

## 2. Prerequisites

Before running Briefify, ensure you have:
- Python 3.11+ installed (the repository metadata enforces `requires-python >= 3.11`)
- `uv` installed for dependency and environment management
- Google Cloud SDK installed (`gcloud` CLI)
- BigQuery dataset/table prepared with telemetry rows
- Gemini API key

Google Cloud authentication requirements:
- Use Application Default Credentials (ADC)
- Set `GOOGLE_APPLICATION_CREDENTIALS` to a service-account key path, or run ADC login locally

Example ADC setup:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_GCP_PROJECT_ID
```

Service-account alternative:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/absolute/path/to/service-account.json"
```

BigQuery minimum setup:
- Project: your GCP project ID
- Dataset: dataset containing account telemetry
- Table: table containing at least these columns:
  `account_id, company_name, snapshot_month, active_users, allocated_seats, api_call_volume, advanced_features_enabled, critical_support_tickets, contract_tier`

## 3. Installation (uv-first)

Create and activate virtual environment:

```bash
python -m venv venv
source venv/bin/activate
```

Install uv if needed:

```bash
pip install -U uv
```

Install project dependencies with uv:

```bash
uv pip install -e .
```

Install dev dependencies (optional):

```bash
uv pip install -e ".[dev]"
```

Notes:
- `requirements.txt` is kept for compatibility, but `pyproject.toml` is the source of truth.

## 4. Configuration

Create a `.env` file in the repository root.

Required variables:
- `GCP_PROJECT_ID`
- `DATASET_ID`
- `TABLE_ID`
- `GEMINI_API_KEY`

Common runtime variables:
- `REDIS_URL` (optional; if unset/unavailable, in-memory fallback is used)
- `JOB_TTL_SECONDS`
- `IDEMPOTENCY_TTL_SECONDS`
- `MAX_WEBHOOK_PAYLOAD_BYTES`
- `WORKFLOW_MAX_SCHEMA_RETRIES`
- `WORKFLOW_SCHEMA_RETRY_DELAY_SEC`
- `BQ_MAX_RETRIES`
- `BQ_QUERY_TIMEOUT_SEC`
- `TELEMETRY_LOOKBACK_MONTHS`
- `TELEMETRY_REQUIRE_CONTIGUOUS_MONTHS`
- `TELEMETRY_ENABLE_PARTITION_PRUNING`
- `BQ_ENABLE_DRY_RUN_GUARD`
- `BQ_DRY_RUN_MAX_BYTES`

`.env.example`:

```dotenv
# Required
GCP_PROJECT_ID=your-gcp-project
DATASET_ID=crm_telemetry
TABLE_ID=account_usage
GEMINI_API_KEY=your-gemini-api-key

# Optional GCP auth (if not using gcloud ADC login)
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/service-account.json

# API and repository controls
MAX_WEBHOOK_PAYLOAD_BYTES=16384
REDIS_URL=redis://127.0.0.1:6379/0
JOB_TTL_SECONDS=86400
IDEMPOTENCY_TTL_SECONDS=86400

# ADK orchestration controls
WORKFLOW_RATE_DELAY_SEC=0
WORKFLOW_MAX_SCHEMA_RETRIES=2
WORKFLOW_SCHEMA_RETRY_DELAY_SEC=0.5

# BigQuery controls
BQ_MAX_RETRIES=2
BQ_RETRY_BASE_DELAY_SEC=0.5
BQ_QUERY_TIMEOUT_SEC=15
TELEMETRY_LOOKBACK_MONTHS=12
TELEMETRY_REQUIRE_CONTIGUOUS_MONTHS=1
TELEMETRY_ENABLE_PARTITION_PRUNING=1
BQ_ENABLE_DRY_RUN_GUARD=0
BQ_DRY_RUN_MAX_BYTES=1000000000
```

## 5. Step-by-Step Running Guide

### Step A: Verify minimum runtime requirements

```bash
python --version
uv --version
gcloud --version
```

### Step B: Install libraries and packages

```bash
source venv/bin/activate
uv pip install -e .
```

### Step C: Verify Google credentials and BigQuery access

Check active ADC identity:

```bash
gcloud auth application-default print-access-token >/dev/null && echo "ADC OK"
```

Optional quick BigQuery import check:

```bash
python -c "from google.cloud import bigquery; print('BigQuery SDK OK')"
```

### Step D: Minimum requirements to make the app work

At minimum, you need:
1. Valid `.env` with `GCP_PROJECT_ID`, `DATASET_ID`, `TABLE_ID`, `GEMINI_API_KEY`
2. BigQuery table populated with telemetry rows
3. Python environment with dependencies installed
4. FastAPI server running

### Step E: Run FastAPI backend

```bash
PYTHONPATH=src uvicorn briefify.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## 6. Demo Trigger Command (End-to-End)

Use curl:

```bash
curl -X POST "http://127.0.0.1:8000/webhook/crm-event" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "account.status_changed",
    "company_name": "Acme Corp",
    "status": "Qualified",
    "account_id": "ACC-1001",
    "event_id": "evt_demo_20260812_0001"
  }'
```

Then poll job status:

```bash
curl "http://127.0.0.1:8000/jobs/job_xxxxxxxx"
```

Python trigger alternative:

```python
import requests
import time
import uuid

payload = {
    "event_type": "account.status_changed",
    "company_name": "Acme Corp",
    "status": "Qualified",
    "account_id": "ACC-1001",
    "event_id": f"evt_{int(time.time())}_{uuid.uuid4().hex[:6]}",
}

res = requests.post("http://127.0.0.1:8000/webhook/crm-event", json=payload, timeout=10)
print(res.status_code, res.json())
```

## 7. Start Streamlit UI (app.py)

Run Streamlit:

```bash
source venv/bin/activate
streamlit run app.py
```

In the UI:
1. Set FastAPI Base URL (default `http://127.0.0.1:8000`)
2. Select target account and CRM status
3. Click "Dispatch CRM Webhook"
4. Watch live node execution status and generated brief output

## Outputs

- Generated briefs: `output/briefs`
- Execution/cost ledger: `output/logs/execution_ledger.jsonl`

## Optional: Local Redis and Containers

If you want Redis-backed job/idempotency state locally:

```bash
docker compose up -d redis
```

Set `REDIS_URL` accordingly in `.env`.