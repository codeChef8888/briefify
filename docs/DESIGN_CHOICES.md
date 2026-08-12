# DESIGN_CHOICES

This architecture intentionally separates deterministic computation from generative reasoning. Python computes facts, the model explains those facts, and schema gates prevent invalid outputs from propagating.

## 1. Framework and Orchestration (Google ADK >= 2.6.3)

Selected Google ADK's code-first, graph-based workflow model because it gives us explicit control over execution topology, runtime state, and node boundaries. Instead of generic prompt-chaining frameworks that often hide control flow in dynamic prompt logic, ADK lets us encode the pipeline as a directed workflow graph: data retrieval node -> strategist agent -> publishing node.

This design gives three production advantages:
- Native async execution: The runner streams events through the graph without blocking API ingestion, which fits webhook-driven workloads.
- Event-driven streaming: Intermediate node outputs and terminal states are captured as events, enabling structured supervision and diagnostics.
- Structured task delegation: Python nodes handle deterministic data/IO tasks, while the LLM node is isolated to reasoning/synthesis only.

In practice, ADK became the orchestration substrate while FastAPI remained the transport surface. That separation reduced coupling and made it easier to evolve each layer independently.

Technology evolution worth highlighting:
- Phase 1 (raw SDK): direct `google-genai` calls are fast for single-turn generation but require custom orchestration boilerplate.
- Phase 2 (early ADK): improved runner/session primitives, but hierarchical delegation is less ideal for strict linear data pipelines.
- Phase 3 (ADK 2.x): graph-based workflow routing gave deterministic sequencing (`START -> telemetry -> strategist -> publisher`) while retaining async execution and event metadata.

## 2. Node Flow and Feature Engineering Protocol Used

The workflow is intentionally split into specialized nodes:
- Node 1 (`telemetry_node.query_account_usage`): Validates trigger payload, executes parameterized BigQuery SQL, enforces query guards/timeouts/retries, checks month continuity, and computes engineered features.
- Node 2 (`strategist_agent`): Uses Gemini with strict `output_schema` binding (`SalesBriefSchema`) and instruction grounding tied to precomputed features.
- Node 3 (`publish_brief_node`): Revalidates output, detects refusal patterns, writes a canonical markdown artifact, and returns terminal status metadata.

Feature-engineering protocol:
- Precompute quantitative signals (seat saturation, Monthly Active User momentum, API growth, ticket escalation, heuristic label) before the LLM step.
- The LLM is instructed to consume these features directly, not recompute them. This reduces hallucination risk and improves consistency across runs.

Deterministic vs generative handoff (math offloading):
- Arithmetic and heuristic labeling are offloaded to Python in Node 1.
- Gemini receives already-validated metrics and converts them into executive narrative.
- This reduces arithmetic hallucinations, shrinks prompt complexity, and improves token efficiency.

Production-grade AI controls:
- Contract-first schema validation: Pydantic validation is applied at payload intake and final brief output.
- Hallucination containment: The model output is constrained by a typed schema plus explicit grounded instructions.
- Retry policy: Schema-related failures trigger bounded retries with backoff; transient BigQuery failures use exponential retry.
- Error envelopes: Failures are normalized with stage, code, and retryability metadata to support deterministic client handling.
- Idempotent ingestion: Duplicate webhook events are reserved by `event_id` to prevent duplicate execution.
- Ledger logging: Each run logs latency, token usage, estimated cost, pipeline stage, retry counts, and status into append-only JSONL for auditability and postmortems.

Execution safety details:
- Resilient worker loops: non-fatal pipeline failures are returned as structured `Event(output=build_error(...))` responses rather than crashing worker threads.
- Double-validation boundary: output is schema-validated at generation and validated again before publishing artifacts.
- Self-healing retries: schema validation failures trigger orchestrator-level retries up to `MAX_SCHEMA_RETRIES`.

The net effect is that the AI workflow behaves like a reliable distributed service rather than an opaque prompt call.

## 3. Data Store and Analytics (Google BigQuery)

BigQuery was chosen because the problem domain is time-series telemetry analytics, not OLTP record mutation.

Why BigQuery over a traditional SQL/NoSQL app database:
- Columnar performance: Account telemetry queries scan analytical columns efficiently over monthly windows.
- Elastic analytics scale: It is designed for large historical datasets and aggregate-heavy workloads common in enterprise account intelligence.
- Parameterized analytical SQL: Strong support for safe, expressive query templates with query job controls.
- Operational fit: Query timeout control, labels, dry-run byte estimation, and partition pruning map well to cost/performance governance requirements.

For this assessment, direct BigQuery access from the telemetry node also reduced architecture hops and avoided extra tool-call overhead.

## 4. Interface and Entry Point (FastAPI Webhook)

FastAPI is a strong fit for webhook-first AI systems:
- ASGI performance profile supports high-concurrency ingestion.
- Native Pydantic integration provides strict request contracts and clean error behavior.
- First-class async/await model integrates naturally with ADK async orchestration behind background tasks.
- Auto-generated OpenAPI docs improve inspectability and integration testing.

Edge-defense controls:
- Payload-size middleware enforces a hard request body limit (16 KB default) to bound parse/memory risk.
- Redis-backed idempotency (`SET NX` semantics in repository reserve flow) drops duplicate events safely before expensive orchestration starts.

The ingestion pattern is deliberate: accept quickly (`202`), persist job state, execute asynchronously, and expose polling endpoints for eventual completion. This keeps the external interface predictable while allowing complex downstream AI execution.

## 5. Architectural Trade-offs and Engineering Decisions

Given the implementation window, prioritizing reliability and clarity over maximal infrastructure depth.

Trade-offs made:
- Session persistence: ADK uses in-memory session service today for simplicity and speed of delivery. This is sufficient for single-service runtime but not ideal for cross-instance continuity.
- Repository fallback: Redis is primary for job/idempotency state, with in-memory fallback to preserve local/dev operability.
- Strict schema contracts: Intentionally made schema constraints tight to suppress malformed LLM output, accepting occasional retry overhead.
- Async throughput vs complexity: FastAPI background tasks are lightweight and fast to implement; a distributed queue would improve horizontal scaling but add operational burden.
- MCP removal in runtime: Removed the MCP hop in the active path to save tool-call overhead and latency. This improved determinism and reduced moving parts, at the cost of less protocol abstraction between orchestration and analytics.

From an enterprise engineering perspective, these choices optimize for deterministic behavior, observability, and risk control under tight delivery constraints, while leaving a clear path for future hardening (durable session backends, queue-based workers, and deeper SLO instrumentation).
