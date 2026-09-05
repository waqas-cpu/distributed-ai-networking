# AI Workload Orchestration Platform
## Architecture & Production Readiness Specification

**Status:** Draft v0.1 — for review
**Domain:** Edge/Cloud hybrid inference orchestration
**Audience:** Platform engineering, SRE, ML infra, security review

---

## 1. Overview

This document specifies a production-grade architecture for routing AI inference/compute workloads across a heterogeneous pool of **edge** and **cloud** nodes. A central **Decision Engine** consumes real-time telemetry (latency, bandwidth, compute headroom, queue depth, cost) and makes a per-task **placement decision**, trading off user-experience SLOs against infrastructure cost.

The diagram you supplied is the *conceptual* control/data flow. This spec turns each box into a concrete component with defined interfaces, failure modes, and the operational scaffolding required to run it in production — not just in a demo.

```
                         AI Workload
                              ↓
                      Network Gateway
                              ↓
                   Telemetry / Monitoring
                              ↓
                   ┌───────────────────┐
                   │  Decision Engine  │
                   │                   │
                   │  Latency          │
                   │  Bandwidth        │
                   │  CPU/GPU          │
                   │  Queue Length     │
                   │  Cost             │
                   └─────────┬─────────┘
                              ↓
                      Task Placement
                   ┌──────────┼──────────┐
                   ↓          ↓          ↓
                Edge 1      Edge 2      Cloud
                   ↓          ↓          ↓
             Inference / Computation
                              ↓
                          Results
```

### 1.1 What's missing from the conceptual diagram (and why this doc exists)

The diagram describes the **happy path**. Production systems fail on the paths it doesn't show:

- What happens when the Decision Engine itself is slow or down?
- What happens when telemetry is stale or a node lies about its own load?
- How do you stop tasks from oscillating between Edge 1 and Edge 2 every cycle?
- Who authenticates the AI Workload caller, and who authenticates the edge nodes back to the gateway?
- What's the cost of a wrong decision, and how do you roll it back mid-flight?

Sections 4–15 answer these.

---

## 2. Goals & Non-Goals

**Goals**
- Sub-decision-cycle (target: <10ms p99) placement overhead — the router must not become the bottleneck.
- Graceful degradation: a failed Decision Engine should fail *open* to a safe static policy, never fail closed (blocking all traffic).
- No single node's self-reported telemetry is trusted blindly — cross-validate against gateway-observed metrics.
- Placement decisions are explainable and auditable (log the winning score and the runner-up).

**Non-Goals (explicitly out of scope for v1)**
- Cross-region WAN optimization / CDN-level routing (assume single region or pre-selected region set).
- Training/fine-tuning workload placement — this spec targets **inference** workloads only.
- Full autoscaling of the underlying node pools (covered only at the interface level in §11).

---

## 3. Component Specifications

### 3.1 AI Workload (Client)
The originating caller — could be a mobile app, an IoT device, or an internal service. It sends a **Task Request** (see §5.1) and never talks directly to Edge/Cloud nodes; all traffic is fronted by the Gateway.

### 3.2 Network Gateway
- Terminates client TLS (mTLS for service-to-service, TLS+API-key/OAuth for external clients).
- Performs request-level auth, rate limiting, and payload validation *before* the request touches the Decision Engine.
- Emits gateway-observed metrics (RTT to client, request size, ingress region) into the Telemetry pipeline — this is the independent signal used to cross-check node self-reports.
- Recommended: Envoy or Kong, fronted by a regional load balancer.

### 3.3 Telemetry / Monitoring
- A streaming pipeline (not a polling one) that continuously ingests: node health pings, resource metrics (CPU/GPU util, memory, queue depth), and network path metrics (latency, jitter, packet loss, available bandwidth).
- Recommended stack: OpenTelemetry Collector → Prometheus (metrics) + a lightweight time-series store optimized for read latency (VictoriaMetrics or Thanos) so the Decision Engine can query "current state" in single-digit milliseconds.
- Telemetry has its own SLA — see §7.2 (stale-data handling) because the Decision Engine is only as good as this feed.

### 3.4 Decision Engine
The scoring/optimization core. Full algorithm in §6. Must be:
- **Stateless per request** (all state — node scores, EMAs — lives in an external low-latency store like Redis) so it can be horizontally scaled and restarted without losing context.
- **Deterministic given the same inputs**, for auditability.

### 3.5 Task Placement (Scheduler)
Takes the Decision Engine's ranked candidate list and *executes* the placement: opens the connection/stream to the chosen node, handles admission-control rejection, and triggers fallback to the next-ranked candidate on failure — without a full re-scoring round trip (see §6.4).

### 3.6 Execution Layer — Edge Nodes & Cloud
- Edge nodes: resource-constrained, variable connectivity, run a lightweight agent that reports health and executes a bounded set of quantized/optimized models.
- Cloud: elastic pool, full model catalog, higher latency floor, higher raw throughput ceiling.
- Both expose the same execution interface (§5.3) so the Decision Engine's choice is transparent to the caller.

### 3.7 Results Aggregation
Normalizes the response envelope regardless of where the task ran (edge vs. cloud should be indistinguishable to the caller), attaches placement metadata for observability, and streams the result back through the Gateway.

---

## 4. Component Responsibility & Interface Matrix

| Component | Protocol | Direction | Payload | Timeout budget |
|---|---|---|---|---|
| Client → Gateway | HTTPS/gRPC + mTLS | inbound | Task Request | client-defined (e.g. 30s) |
| Gateway → Telemetry | async (Kafka/NATS) | fire-and-forget | Gateway metrics event | n/a |
| Node Agents → Telemetry | gRPC streaming | inbound | Health/resource metrics, 1–5s cadence | n/a |
| Decision Engine → Telemetry Store | Redis/gRPC read | query | Current node state snapshot | 5ms |
| Decision Engine → Task Placement | in-process/gRPC | internal | Ranked candidate list | 10ms (p99 target) |
| Task Placement → Edge/Cloud | gRPC + mTLS | outbound | Execution Request | node-class-specific (§7.3) |
| Edge/Cloud → Results Aggregation | gRPC streaming | outbound | Inference result / error | matches execution timeout |

---

## 5. Data Contracts

Concrete schemas prevent the classic integration failure mode: every component agreeing on the diagram but disagreeing on the wire format.

### 5.1 Task Request

```json
{
  "task_id": "uuid-v7",
  "workload_type": "inference",
  "model_id": "vision-classifier-v3",
  "sla_class": "real_time | interactive | batch",
  "payload_ref": "s3://... or inline bytes",
  "max_latency_ms": 150,
  "data_residency": "eu-only | none",
  "idempotency_key": "client-generated"
}
```

### 5.2 Node Telemetry Snapshot

```json
{
  "node_id": "edge-1",
  "node_class": "edge | cloud",
  "timestamp": "2026-09-05T10:00:00Z",
  "rtt_ms": 12.4,
  "bandwidth_available_mbps": 85.0,
  "cpu_util_pct": 62,
  "gpu_util_pct": 40,
  "queue_depth": 3,
  "cost_per_1k_inferences_usd": 0.004,
  "health": "healthy | degraded | unreachable",
  "last_heartbeat_age_ms": 800
}
```

### 5.3 Placement Decision (logged for audit)

```json
{
  "task_id": "uuid-v7",
  "chosen_node": "edge-2",
  "chosen_score": 0.83,
  "runner_up_node": "cloud-1",
  "runner_up_score": 0.71,
  "weights_used": { "latency": 0.4, "bandwidth": 0.15, "compute": 0.2, "queue": 0.1, "cost": 0.15 },
  "decision_latency_ms": 4.2,
  "fallback_chain": ["edge-2", "cloud-1", "cloud-2"]
}
```

---

## 6. Decision Engine Algorithm

### 6.1 Scoring function

For each candidate node `s` and task `t`, compute a normalized composite score. Lower is better (cost-minimization framing):

```
score(s) = w_lat   · norm(latency(s))
         + w_bw    · norm(1 / bandwidth_headroom(s))
         + w_cmp   · norm(compute_utilization(s))
         + w_queue · norm(queue_depth(s))
         + w_cost  · norm(cost_per_unit(s))

placement(t) = argmin_s score(s)   subject to hard constraints (below)
```

Normalization: min-max scale each metric across the *current candidate set* per decision cycle, not against a fixed historical range — this keeps the score meaningful as the fleet's absolute performance shifts over time.

### 6.2 Hard constraints (pre-filter before scoring)

Evaluate before scoring, not as weighted factors — a node that fails these is removed from the candidate set entirely, regardless of how well it scores otherwise:

- `health != unhealthy`
- `data_residency` compatible with task requirement
- `last_heartbeat_age_ms < staleness_threshold` (see §7.2)
- available headroom ≥ task's declared resource footprint

### 6.3 Weight profiles per SLA class

Weights are not global constants — they're configuration per workload class, hot-reloadable without a Decision Engine redeploy:

| SLA class | latency | bandwidth | compute | queue | cost |
|---|---|---|---|---|---|
| `real_time` | 0.50 | 0.15 | 0.15 | 0.15 | 0.05 |
| `interactive` | 0.35 | 0.15 | 0.20 | 0.15 | 0.15 |
| `batch` | 0.10 | 0.10 | 0.20 | 0.20 | 0.40 |

### 6.4 Anti-flapping (hysteresis)

Naively re-scoring every cycle causes tasks to migrate back and forth between two nodes with near-identical scores. Mitigations:

- Maintain an **exponential moving average** of each node's score over the last N cycles (e.g., N=3, α=0.5) instead of the instantaneous value.
- Require a challenger node to beat the incumbent by a **minimum margin** (e.g., 10%) before triggering a migration for a long-running or streaming task.
- For single-shot inference tasks (the common case), this is moot — score once at admission time.

### 6.5 Fallback without re-scoring

Task Placement carries the top-3 ranked candidates from the original decision (`fallback_chain` in §5.3). If the chosen node rejects (admission control) or fails mid-request, Placement retries the next candidate in the chain immediately — no round trip back to the Decision Engine. This is the single biggest latency saver under partial failure.

---

## 7. Reliability & Failure Handling

### 7.1 Decision Engine failure mode: fail open, not closed

If the Decision Engine is unreachable or exceeds its latency budget:
- Task Placement falls back to a **static default policy** (e.g., "nearest healthy edge node by last-known-good telemetry, else cloud").
- This static fallback must be pre-computed and cached locally in Task Placement — it cannot itself depend on a live call to the Decision Engine.

### 7.2 Stale telemetry handling

- Every telemetry snapshot carries `last_heartbeat_age_ms`. Above a configurable threshold (e.g., 3× the expected heartbeat interval), the node is excluded from scoring rather than scored optimistically on old data.
- Node self-reported metrics are periodically cross-checked against Gateway-observed RTT for the same node; persistent large divergence flags the node agent as untrustworthy (possible misconfiguration or compromise) and routes it to a quarantine pool for investigation.

### 7.3 Node/network failure

| Failure | Detection | Mitigation |
|---|---|---|
| Edge node unreachable | Missed heartbeats (N consecutive) | Circuit-break node out of candidate pool for cooldown period T; retry via fallback chain |
| Edge node overloaded (silently) | Queue depth spike + rising p99 latency without heartbeat loss | Weighted score naturally deprioritizes it; add a hard queue-depth ceiling as a constraint |
| Network partition (edge unreachable from gateway, but node itself healthy) | Gateway-side timeout without corresponding node-side error | Treat identically to node failure from the caller's perspective — indistinguishable and should be |
| Decision Engine instance crash | Health check / orchestrator restart | Stateless design (§3.4) means any replica can serve the next request; no session affinity required |
| Telemetry pipeline backlog | Consumer lag metric on the stream | Decision Engine falls back to last-known-good snapshot with an explicit staleness penalty added to that node's score |

### 7.4 Idempotency & retries

Every Task Request carries a client-generated `idempotency_key`. Task Placement retries against fallback nodes using the same key so a node that already started processing (but whose response was lost) doesn't get double-billed or double-executed — Results Aggregation dedupes on this key.

---

## 8. Non-Functional Requirements / SLOs

| Metric | Target | Notes |
|---|---|---|
| Decision Engine scoring latency | p99 < 10ms | Excludes network hop; in-process/co-located with a fast KV store |
| End-to-end added latency vs. direct-to-node call | < 5% overhead | The router must be cheap relative to inference time |
| Decision Engine availability | 99.99% | Achieved via statelessness + N+2 replicas across zones |
| Telemetry freshness | 95% of snapshots < 2s old | Drives the staleness threshold in §7.2 |
| Placement accuracy (post-hoc) | > 95% of placements within 10% of the optimal score computed retrospectively | Tracked via the audit log in §5.3 |
| Cost drift | Actual spend within 10% of `batch`-class projected cost | Alerts if the fleet mix drifts (e.g., cloud overused due to edge capacity shortfall) |

---

## 9. Security & Compliance

- **mTLS everywhere** between Gateway ↔ Decision Engine ↔ Task Placement ↔ Edge/Cloud nodes; no plaintext internal traffic.
- **Workload isolation** on shared edge hardware (gVisor/Kata containers or equivalent) — an edge node may host workloads from multiple tenants.
- **Data residency as a hard constraint** (§6.2), not a scoring preference — a compliance requirement that gets "outweighed" by a good latency score is a compliance failure, not a trade-off.
- **Node attestation**: edge nodes should present a hardware/software attestation on registration so a compromised or spoofed node can't join the candidate pool and receive sensitive payloads.
- **Audit trail**: every placement decision (§5.3) is retained for a defined period to support incident investigation and regulatory requests.
- **Secrets**: node agent credentials rotated via short-lived tokens (SPIFFE/SPIRE or cloud-native workload identity), never long-lived static keys baked into edge images.

---

## 10. Observability Stack

- **Metrics**: Prometheus/VictoriaMetrics for node and pipeline health; Grafana dashboards per SLA class showing score distribution, fallback-chain trigger rate, and cost-per-class over time.
- **Tracing**: OpenTelemetry distributed traces spanning Gateway → Decision Engine → Placement → Execution, so a single task's full journey (including *why* a node was chosen) is reconstructable.
- **Logging**: structured, sampled at 100% for the Placement Decision audit record (§5.3) — this one log line is cheap and is your primary debugging and compliance artifact.
- **Alerting**: page on Decision Engine fail-open activation, sustained fallback-chain exhaustion (all candidates rejected), and telemetry pipeline lag exceeding the staleness threshold.

---

## 11. Scalability & Deployment Topology

- **Decision Engine**: run as a stateless Kubernetes Deployment, horizontally autoscaled on request rate; co-locate replicas with the telemetry read-store to keep the 10ms budget realistic.
- **Edge fleet management**: K3s or KubeEdge for edge node lifecycle, with the node agent as a lightweight DaemonSet-equivalent.
- **Cloud pool**: standard autoscaling group / HPA on GPU utilization, with a minimum warm pool sized to absorb edge-fleet-wide outages without a cold-start latency spike.
- **Multi-region**: out of scope for v1 (§2), but the Decision Engine's stateless design and the region field on telemetry snapshots leave room to extend scoring with a region-aware constraint later.

---

## 12. Testing Strategy

- **Unit**: scoring function correctness (weight profiles, normalization, constraint filtering) — this is pure logic and should have exhaustive test coverage.
- **Load testing**: verify the p99 decision-latency SLO under a realistic candidate-pool size and telemetry churn rate.
- **Chaos testing**: kill Decision Engine replicas, inject telemetry staleness, partition a subset of edge nodes — verify fail-open behavior and fallback-chain execution actually trigger as designed, not just in theory.
- **Shadow mode**: before full cutover, run the Decision Engine in parallel with the existing/static routing, logging what it *would* have chosen without acting on it, to validate scoring quality against real traffic.

---

## 13. CI/CD & Release Process

- Weight-profile changes (§6.3) are configuration, not code — ship through a separate, faster-moving config pipeline with its own review gate, decoupled from Decision Engine binary releases.
- Canary the Decision Engine itself: route a small percentage of traffic through the new version, compare placement-decision distributions against the incumbent before full rollout.
- Edge node agent updates require a staged rollout strategy tolerant of intermittent connectivity — never assume an edge fleet update completes atomically.

---

## 14. Cost Governance

- Track actual spend against the `batch`-class weight profile's cost projection (§8) — the cost dimension is the one most likely to silently drift if edge capacity shrinks and traffic spills to cloud.
- Set a **cost ceiling constraint** (not just a weighted factor) for cost-sensitive SLA classes, so a batch job can't be silently routed to expensive cloud GPU time even if every other metric favors it.
- Expose per-tenant cost attribution if the platform is multi-tenant — required for chargeback and for detecting a single noisy tenant skewing the fleet's routing behavior.

---

## 15. Production Readiness Checklist

| Area | Requirement | Status |
|---|---|---|
| Fail-open default policy implemented and tested | | ☐ |
| Hard constraints (residency, health, staleness) enforced pre-scoring | | ☐ |
| Anti-flapping hysteresis in place for long-running tasks | | ☐ |
| Fallback chain execution without re-scoring round trip | | ☐ |
| mTLS on all internal hops | | ☐ |
| Node attestation on registration | | ☐ |
| Audit log (Placement Decision) retained and queryable | | ☐ |
| Chaos tests covering Decision Engine crash, telemetry staleness, edge partition | | ☐ |
| Shadow-mode validation against existing routing completed | | ☐ |
| Cost ceiling constraints configured per SLA class | | ☐ |
| Dashboards + alerts for fail-open rate and fallback exhaustion | | ☐ |
| Weight-profile config pipeline decoupled from binary release | | ☐ |

---

## 16. Roadmap / Phasing

1. **Phase 1 — Static fallback + telemetry pipeline.** Ship the "safe default" routing and telemetry ingestion first; this is the floor everything else falls back to.
2. **Phase 2 — Decision Engine in shadow mode.** Validate scoring against production traffic without acting on it.
3. **Phase 3 — Canary cutover.** Small traffic percentage live, compare cost/latency outcomes against Phase 1 baseline.
4. **Phase 4 — Full rollout + hysteresis tuning.** Enable long-running-task migration logic once single-shot placement is stable.
5. **Phase 5 — Multi-region / autoscaling integration.** Extend beyond v1 non-goals once the core loop is proven.

---

## 17. Open Questions & Assumptions

- Assumes a single region or a pre-selected fixed region set (§2) — multi-region routing is a known follow-on.
- Assumes edge nodes run a bounded, pre-approved model catalog (quantized variants); full model parity between edge and cloud is not assumed.
- Cost figures in telemetry (§5.2) assume a pricing feed is available per node/class — the source of truth for that feed (billing API vs. static config) needs to be confirmed with finance/infra owners before Phase 3.
- Assumes tenants are known at admission time for cost attribution (§14) — anonymous/unauthenticated workloads are out of scope as currently specified.
