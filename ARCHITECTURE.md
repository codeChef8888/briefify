# Briefify Architecture

## 1. End-to-End Sequence Diagram

```
                  ┌────────────────────────┐
                  │ Webhook Event Trigger  │ (FastAPI / Salesforce)
                  └───────────┬────────────┘
                              │
                              ▼
        ┌───────────────────────────────────────────┐
        │ Node 1: fetch_usage_data (Python Node)    │ $0 LLM Cost (MCP / BQ)
        │ Executes Parameterized BQ/MCP Query       │
        └─────────────────────┬─────────────────────┘
                              │ Event(output=UsageTelemetry.model_dump())
                              ▼
        ┌───────────────────────────────────────────┐
        │ Node 2: strategist_agent (Agent Node)     │ 1 Gemini Flash Call
        │ Generates Structured Brief                │ (single_turn mode)
        └─────────────────────┬─────────────────────┘
                              │ Event(output=SalesBrief.model_dump())
                              ▼
        ┌───────────────────────────────────────────┐
        │ Node 3: publish_sales_brief (Python Node) │ $0 LLM Cost
        │ Pushes Brief to CRM / Salesforce Note     │
        └───────────────────────────────────────────┘
```

## 2. Architecture Overview

### Webhook and Ingestion Layer

The ingestion boundary is implemented by FastAPI endpoints:
- `POST /webhook/crm-event` accepts CRM webhook payloads.
- `GET /jobs/{job_id}` exposes asynchronous job status.
- `GET /health` provides service liveness.

Ingestion is guarded and validated in two phases:
- A middleware enforces `MAX_WEBHOOK_PAYLOAD_BYTES` and returns `413` for oversized requests.
- `CRMEventPayload` (Pydantic) enforces strict schema constraints (allowed status literals, account/event ID patterns, size bounds, and forbidden extra fields).

The webhook handler is intentionally non-blocking for AI/data workloads:
- It performs idempotency checks using `event_id`.
- It short-circuits non-Qualified events with an `ignored` response.
- It returns `202 Accepted` and enqueues orchestration work in FastAPI `BackgroundTasks`.

### Agent and Orchestration Layer (Google ADK >= 2.6.3)

The orchestration core uses Google ADK Workflow + Runner:
- A static directed workflow graph is defined as:
  - `START -> query_account_usage -> strategist_agent -> publish_brief_node`
- `InMemorySessionService` holds runtime session state for workflow execution.
- The runner sends an `AccountTrigger` JSON payload as ADK content into Node 1.

Runtime behavior:
- ADK events are streamed asynchronously.
- Terminal output states are normalized (`published`, `refused`, `error`).
- Schema validation is enforced at strategist output and again before publish completion.
- Retry logic is applied for schema-related failures (`WORKFLOW_MAX_SCHEMA_RETRIES`) and transient execution conditions.

This layer is where model calls are controlled and minimized:
- Node 1 and Node 3 are non-LLM Python nodes.
- Node 2 (StrategistAgent) is the primary LLM synthesis step.

### Tool and Context Protocol

MCP has been deliberately dropped from the active runtime path to reduce tool-call overhead.

Current production path:
- The workflow directly invokes `telemetry_node.query_account_usage`.
- That node uses the BigQuery Python client SDK directly.
- No MCP tool broker hop is required between ADK and data retrieval.

Implications:
- Fewer moving parts in orchestration.
- Lower tool-call complexity and latency.
- Direct control over retries, timeout, partition pruning, and dry-run guards inside one node.

### Data and Storage Layer

#### BigQuery telemetry access

`telemetry_node.py` performs parameterized SQL reads from:
- `{GCP_PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`

Data reliability and cost controls in Node 1 include:
- Query parameterization (`company_name`, optional `account_id`, lookback window).
- Optional partition pruning with computed `lookback_start_date`.
- Optional non-prod dry-run byte guard (`BQ_ENABLE_DRY_RUN_GUARD`).
- Bounded query timeout and exponential-backoff retries for transient Google API errors.
- Optional contiguous month validation for telemetry quality.

#### Persistent state and artifacts

- Job metadata, idempotency reservations, and status transitions are stored in Redis when available; otherwise in-memory fallback is used.
- Final briefs are written to `output/briefs` as Markdown.
- Execution metrics, token usage metadata, retry data, and estimated cost are appended to `output/logs/execution_ledger.jsonl`.

## 3. Component Interactions and Serialization Formats

### External Trigger -> FastAPI

- Protocol: HTTP
- Content type: `application/json`
- Payload contract: `CRMEventPayload`
- Response: JSON envelope (`accepted`, `duplicate`, `ignored`, or error)

### FastAPI -> Background Worker / Repository

- Protocol: In-process Python call
- Serialization: Python dicts; Redis persistence uses JSON strings
- Semantics:
  - Atomic event reservation for idempotency
  - Status transitions: `queued -> processing -> completed|failed`

### ADK Runner -> Workflow Nodes

- Protocol: ADK event stream
- Input serialization: JSON payload embedded in ADK content parts
- Output serialization: `Event(output=<dict>)`
- Contract:
  - Node 1 returns telemetry payload plus engineered feature vectors
  - Node 2 returns structured `SalesBriefSchema`
  - Node 3 returns publish result envelope

### telemetry_node -> BigQuery

- Protocol: Google Cloud BigQuery Client SDK
- Query mode: parameterized SQL (`QueryJobConfig` + `ScalarQueryParameter`)
- Result materialization: `RowIterator` -> `list[dict]`
- Date normalization: `snapshot_month` coerced to string for JSON-safe handoff

### Publisher / Ledger -> File System

- Protocol: local file I/O
- Formats:
  - Brief artifacts: Markdown (`.md`)
  - Execution logs: JSON Lines (`.jsonl`)

## 4. Current Workflow Summary

Briefify currently follows this direct path:
1. External webhook event arrives at FastAPI.
2. FastAPI validates and enqueues background orchestration.
3. ADK workflow starts and executes Node 1 telemetry retrieval directly against BigQuery.
4. StrategistAgent synthesizes telemetry into schema-constrained business brief JSON.
5. Publisher node writes Markdown output and returns artifact metadata.
6. Repository state is updated and the client polls job completion via `/jobs/{job_id}`.

ision to avoid MCP in runtime and rely on `telemetry_n