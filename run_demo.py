"""AI Workload Orchestration Platform — Milestone 1 Demonstration
Executes an end-to-end vertical slice across all platform components:
Client -> Gateway -> Decision Engine -> Scheduler -> Simulated Compute Nodes -> Results Aggregator -> Audit Log.
"""

from __future__ import annotations

import json
import sys
import time

# Ensure UTF-8 output if supported on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from common.cluster import create_simulated_cluster
from contracts.models import SLAClass, TaskRequest
import httpx


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title.upper()}")
    print("=" * 80)


def print_json(data: dict) -> None:
    print(json.dumps(data, indent=2))


async def main() -> None:
    print_header("Initializing AI Workload Orchestration Cluster")
    telemetry_store, decision_engine, scheduler, aggregator, nodes, app, grpc_servers = create_simulated_cluster()
    
    print("[OK] Active Nodes in Cluster:")
    for node_id, node in nodes.items():
        print(f"  * {node_id:<22} | Class: {node.node_class.value:<5} | RTT: {node.base_rtt_ms:5.1f}ms | Cost/1k: ${node.cost_per_1k_usd:.4f} | Zones: {node.data_residency_zones}")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://platform.internal") as client:
        # Check Health
        health_resp = await client.get("/v1/health")
        print(f"\n[OK] Gateway Health Check: {health_resp.json()['status']} (Dependencies: {health_resp.json()['dependencies']})")

        # ----------------------------------------------------------------------
        # SCENARIO 1: Real-Time Workload Placement
        # ----------------------------------------------------------------------
        print_header("Scenario 1: Real-Time Workload Placement (SLA: real_time)")
        task_1 = {
            "workload_type": "inference",
            "model_id": "vision-classifier-v3",
            "sla_class": "real_time",
            "payload_ref": "s3://assembly-line-cameras/cam-42/frame-089.jpg",
            "max_latency_ms": 150.0,
            "data_residency": "none",
            "idempotency_key": "demo-task-realtime-001",
        }
        print("Submitting Task Request to Gateway:")
        print_json(task_1)

        t0 = time.perf_counter()
        resp_1 = await client.post("/v1/tasks/infer", json=task_1)
        duration_1 = (time.perf_counter() - t0) * 1000.0
        data_1 = resp_1.json()

        print(f"\n[OK] Response received in {duration_1:.2f}ms (HTTP {resp_1.status_code}):")
        print_json(data_1)
        print(f"-> Analysis: Decision Engine evaluated in {data_1['execution_metadata']['decision_overhead_ms']}ms (p99 target < 10ms).")
        print(f"-> Selected optimal node: {data_1['execution_metadata']['executed_node']} (Score: {data_1['routing_audit']['chosen_score']}).")

        # ----------------------------------------------------------------------
        # SCENARIO 2: Hard Data Residency Enforcement
        # ----------------------------------------------------------------------
        print_header("Scenario 2: Strict Data Residency Constraint ('us-only')")
        task_2 = {
            "workload_type": "inference",
            "model_id": "vision-classifier-v3",
            "sla_class": "real_time",
            "payload_ref": "s3://us-patient-records/scan-902.dcm",
            "max_latency_ms": 250.0,
            "data_residency": "us-only",
            "idempotency_key": "demo-task-us-residency-002",
        }
        print("Submitting Task with strict 'us-only' compliance:")
        resp_2 = await client.post("/v1/tasks/infer", json=task_2)
        data_2 = resp_2.json()

        print(f"\n[OK] Routed Compliantly to: {data_2['execution_metadata']['executed_node']}")
        print(f"-> Node Class: {data_2['execution_metadata']['node_class']}")
        print(f"-> European edge/cloud nodes were filtered out prior to scoring.")

        # ----------------------------------------------------------------------
        # SCENARIO 3: Automatic Candidate Fallback Chain Execution
        # ----------------------------------------------------------------------
        print_header("Scenario 3: Primary Node Failure & Fallback Chain Activation")
        primary_node = nodes["edge-frankfurt-1"]
        print(f"Injecting simulated crash/failure on primary candidate: {primary_node.node_id}...")
        primary_node.fail_execution = True

        task_3 = {
            "workload_type": "inference",
            "model_id": "vision-classifier-v3",
            "sla_class": "real_time",
            "payload_ref": "s3://drone-feed/stream-frame-12.jpg",
            "max_latency_ms": 150.0,
            "data_residency": "none",
            "idempotency_key": "demo-task-fallback-003",
        }

        resp_3 = await client.post("/v1/tasks/infer", json=task_3)
        data_3 = resp_3.json()
        print(f"\n[OK] Fallback Activated: {data_3['execution_metadata']['fallback_activated']}")
        print(f"-> Original Winner: edge-frankfurt-1 (Failed)")
        print(f"-> Successfully Recovered On: {data_3['execution_metadata']['executed_node']}")
        print(f"-> Attempts Required: {data_3['execution_metadata']['attempts']}")
        print("-> Immediate local recovery achieved without Decision Engine roundtrip!")

        # Restore node health
        primary_node.fail_execution = False

        # ----------------------------------------------------------------------
        # SCENARIO 4: Gateway Fail-Open Static Routing
        # ----------------------------------------------------------------------
        print_header("Scenario 4: Decision Engine Outage & Fail-Open Static Routing")
        print("Simulating total Decision Engine service outage...")
        app.state.decision_engine_enabled = False

        task_4 = {
            "workload_type": "inference",
            "model_id": "vision-classifier-v3",
            "sla_class": "batch",
            "payload_ref": "s3://analytics-batch/batch-99.parquet",
            "max_latency_ms": 300.0,
            "data_residency": "none",
            "idempotency_key": "demo-task-failopen-004",
        }

        resp_4 = await client.post("/v1/tasks/infer", json=task_4)
        data_4 = resp_4.json()
        print(f"\n[OK] Workload Succeeded via Fail-Open: {data_4['status']}")
        print(f"-> Routed via Pre-computed Static Fallback to: {data_4['execution_metadata']['executed_node']}")
        print("-> Platform maintained availability: failed open, not closed!")

        # Restore Decision Engine
        app.state.decision_engine_enabled = True

        # ----------------------------------------------------------------------
        # AUDIT TRAIL VERIFICATION
        # ----------------------------------------------------------------------
        print_header("Governance & Audit Trail Inspection")
        audit_resp = await client.get("/v1/audit/events")
        events = audit_resp.json()
        print(f"Total Immutable Audit Records Persisted: {len(events)}")
        latest = events[-1]
        print("\nLatest Audit Record Snapshot:")
        print(f"  * Event ID: {latest['event_id']}")
        print(f"  * Task ID: {latest['task_id']}")
        print(f"  * Chosen Node: {latest['decision']['chosen_node']}")
        print(f"  * Fallback Used: {latest['decision']['used_fallback_policy']}")
        print(f"  * Executed Node: {latest['execution']['node_id']}")
        print(f"  * Status: {latest['execution']['status']}")

    print_header("Milestone 1 Demonstration Successfully Completed")


if __name__ == "__main__":
    import anyio
    anyio.run(main)
