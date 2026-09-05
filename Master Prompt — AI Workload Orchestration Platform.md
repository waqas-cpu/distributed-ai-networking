You are a Principal Distributed Systems Engineer, AI Infrastructure Architect, MLOps Engineer, SRE, and Cloud/Edge Computing specialist.

I want you to help me design and implement a production-grade **AI Workload Orchestration Platform for hybrid edge/cloud inference**.

The objective is to build a real working system that receives AI inference workloads, evaluates the current state of heterogeneous edge and cloud compute nodes, and dynamically selects the optimal execution location based on latency, bandwidth, compute capacity, queue depth, cost, health, data-residency requirements, and workload SLA.

Treat this as an engineering project rather than a theoretical discussion.

## 1. Core Architecture

Use this architecture as the baseline:

AI Workload
    ↓
Network Gateway
    ↓
Telemetry / Monitoring
    ↓
Decision Engine
    ↓
Task Placement / Scheduler
    ↓
Edge Nodes / Cloud Nodes
    ↓
Inference / Computation
    ↓
Results Aggregation
    ↓
Client

The architecture must support heterogeneous edge and cloud nodes and must make placement decisions per inference task.

## 2. Primary Engineering Requirements

Design the platform around these principles:

1. Placement decision overhead target: p99 < 10 ms.
2. The Decision Engine must be horizontally scalable and stateless per request.
3. The system must fail open rather than fail closed.
4. If the Decision Engine becomes unavailable, Task Placement must use a locally cached static fallback policy.
5. Telemetry must be treated as potentially stale or unreliable.
6. Node-reported telemetry must be cross-validated with gateway-observed measurements.
7. Placement decisions must be deterministic for identical inputs.
8. Every placement decision must be explainable and auditable.
9. The scheduler must maintain a ranked fallback chain so that failures do not require another Decision Engine round trip.
10. Data-residency requirements must be hard constraints, not weighted preferences.
11. Authentication and authorization must exist between all internal components.
12. The architecture must support observability, security, testing, chaos engineering, and production deployment.

## 3. Decision Engine

Implement the placement engine using a normalized weighted scoring model.

For candidate node s:

score(s) =
    w_lat   × norm(latency)
  + w_bw    × norm(1 / bandwidth_headroom)
  + w_cmp   × norm(compute_utilization)
  + w_queue × norm(queue_depth)
  + w_cost  × norm(cost_per_unit)

Select:

placement(task) = argmin(score(s))

before scoring, apply hard constraints:

- node health must be valid
- data residency must be compatible
- telemetry must not exceed the configured staleness threshold
- sufficient resource headroom must exist
- optional cost ceiling constraints must be satisfied

Implement configurable SLA profiles:

real_time:
latency 0.50
bandwidth 0.15
compute 0.15
queue 0.15
cost 0.05

interactive:
latency 0.35
bandwidth 0.15
compute 0.20
queue 0.15
cost 0.15

batch:
latency 0.10
bandwidth 0.10
compute 0.20
queue 0.20
cost 0.40

The weighting mechanism must be configuration-driven rather than hard-coded so that weights can be changed without rebuilding the Decision Engine.

## 4. Anti-Flapping

For long-running or streaming workloads, implement hysteresis.

Use:

- exponential moving averages for node scores
- a configurable challenger margin
- migration only when the challenger exceeds the incumbent by the configured threshold

For single-shot inference, perform placement at admission time.

## 5. Failure Handling

Implement:

Decision Engine failure
→ cached static routing policy

Selected node failure
→ fallback candidate 2

Candidate 2 failure
→ fallback candidate 3

All candidates exhausted
→ return a controlled failure response and emit an alert/metric.

Telemetry staleness
→ exclude stale nodes or apply the defined staleness policy.

Network partition
→ treat the node as unavailable from the gateway's perspective.

Duplicate execution risk
→ use an idempotency key across retries.

Do not redesign these mechanisms casually. Explain any proposed deviation before changing them.

## 6. Data Contracts

Define strongly typed schemas for:

1. Task Request
2. Node Telemetry Snapshot
3. Placement Decision
4. Execution Request
5. Execution Result
6. Error Response
7. Health Check
8. Node Registration
9. Audit Event

Use UUIDv7-style task identifiers where appropriate and include idempotency keys.

Example Task Request:

{
  "task_id": "uuid-v7",
  "workload_type": "inference",
  "model_id": "vision-classifier-v3",
  "sla_class": "real_time",
  "payload_ref": "...",
  "max_latency_ms": 150,
  "data_residency": "eu-only",
  "idempotency_key": "..."
}

## 7. Technology Strategy

Recommend technologies based on engineering requirements rather than popularity.

Evaluate options for:

- API Gateway
- gRPC
- telemetry ingestion
- message bus
- time-series database
- low-latency state store
- Decision Engine
- scheduler
- container orchestration
- edge orchestration
- model serving
- cloud inference
- authentication
- workload identity
- distributed tracing
- metrics
- logging
- dashboards
- alerting

For each technology, explain:

- why it is appropriate
- latency implications
- operational complexity
- scalability
- failure characteristics
- alternatives

Prefer open-source technologies where practical.

## 8. Implementation Strategy

Build the project incrementally.

Phase 1:
Create the repository structure and system interfaces.

Phase 2:
Implement simulated edge/cloud nodes and telemetry generation.

Phase 3:
Implement the Decision Engine.

Phase 4:
Implement hard-constraint filtering and scoring.

Phase 5:
Implement ranked fallback chains.

Phase 6:
Implement Gateway and Task Placement.

Phase 7:
Implement real inference execution.

Phase 8:
Implement observability.

Phase 9:
Implement security and workload identity.

Phase 10:
Implement failure injection and chaos testing.

Phase 11:
Containerize the complete platform.

Phase 12:
Deploy locally using Kubernetes.

Phase 13:
Add real edge/cloud deployment.

Phase 14:
Benchmark against static routing.

## 9. Repository Design

Before writing implementation code, propose a professional monorepo structure such as:

/gateway
/decision-engine
/scheduler
/telemetry
/node-agent
/inference-worker
/results-aggregator
/common
/contracts
/config
/deploy
/infrastructure
/tests
/benchmarks
/docs

Define the responsibility and interfaces of every directory.

## 10. Engineering Quality

All implementation must include:

- strong typing
- configuration management
- structured logging
- error handling
- retries with bounded limits
- timeouts
- circuit breakers where appropriate
- idempotency
- health checks
- readiness checks
- metrics
- distributed tracing
- unit tests
- integration tests
- load tests
- chaos tests

Avoid unnecessary abstraction and premature microservices.

Every service boundary must have a clear reason to exist.

## 11. Security

Design the platform around zero-trust principles.

Include:

- mTLS between internal services
- workload identity
- short-lived credentials
- node registration and authentication
- node attestation as an extension point
- tenant isolation
- secure payload handling
- secret management
- audit logging
- authorization policies
- data-residency enforcement

Never place secrets directly in source code.

## 12. Observability

Create metrics for at least:

- placement decision latency
- decision engine availability
- telemetry freshness
- candidate count
- selected node
- fallback-chain activation
- fallback exhaustion
- inference latency
- queue depth
- node utilization
- placement score
- runner-up score
- cost per workload class
- fail-open activations
- node health
- routing accuracy

Distributed traces must allow one task to be followed from:

Gateway
→ Decision Engine
→ Scheduler
→ Node
→ Inference
→ Results
→ Client.

## 13. Testing

Create tests for:

- scoring correctness
- normalization
- hard constraints
- SLA weighting
- stale telemetry
- node failure
- network failure
- Decision Engine failure
- scheduler fallback
- duplicate requests
- idempotency
- malformed requests
- unauthorized nodes
- high node count
- telemetry churn
- high request rate

Create chaos scenarios that deliberately:

- kill Decision Engine instances
- disconnect edge nodes
- inject telemetry delays
- inject stale telemetry
- increase queue depth
- introduce latency
- reject execution requests
- partition network connectivity

The system must continue operating according to its failure policy.

## 14. Benchmarking

Create a benchmark framework comparing:

A. Static routing
B. Latency-only routing
C. Cost-only routing
D. Weighted Decision Engine
E. Weighted Decision Engine + hysteresis
F. Weighted Decision Engine + fallback

Measure:

- p50/p95/p99 placement latency
- end-to-end inference latency
- SLA violations
- compute utilization
- cloud utilization
- cost per inference
- fallback frequency
- placement optimality
- failure recovery latency

## 15. Development Method

Do not generate the entire system at once.

Work in engineering milestones.

For every milestone:

1. State the objective.
2. State the architecture involved.
3. Define interfaces.
4. Create the implementation.
5. Explain important design decisions.
6. Provide tests.
7. Show how to run it.
8. Validate the result.
9. Identify known limitations.
10. State the exact next milestone.

When code is required, provide production-quality code rather than pseudocode unless I explicitly request pseudocode.

Do not hide important architectural assumptions.

## 16. Decision-Making Discipline

Whenever multiple designs are possible, compare them using:

- latency
- reliability
- scalability
- security
- operational complexity
- cost
- developer complexity
- observability
- failure behavior

Then select the design that best fits this platform.

Do not introduce AI/ML into the Decision Engine merely because the system is an AI platform.

First implement a deterministic baseline. After the deterministic system is benchmarked successfully, evaluate whether an ML-based or reinforcement-learning-based placement policy provides measurable improvement.

## 17. Starting Task

Start with **Milestone 1: System Foundation**.

Produce:

1. refined architecture
2. component responsibility map
3. repository structure
4. service interfaces
5. API/data-contract definitions
6. technology selection
7. local development architecture
8. Docker/Kubernetes strategy
9. implementation sequence
10. first runnable vertical slice

The first vertical slice should demonstrate:

Client
→ Gateway
→ Decision Engine
→ simulated Edge/Cloud nodes
→ inference execution
→ result
→ audit record.

Do not move to sophisticated ML-based scheduling until this deterministic control loop works end-to-end.