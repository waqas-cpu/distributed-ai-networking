import asyncio
import httpx
import time
import argparse
from typing import Dict, Any

from common.cluster import create_simulated_cluster
from contracts.models import NodeTelemetrySnapshot, NodeClass, HealthStatus

async def run_scenario(scenario_num: int):
    print(f"==================================================")
    print(f" INITIALIZING TEST CONTROL CLUSTER (SCENARIO {scenario_num})")
    print(f"==================================================")
    
    telemetry_store, decision_engine, scheduler, aggregator, nodes, app, grpc_servers = create_simulated_cluster()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    
    # Base task
    task_payload = {
        "workload_type": "inference",
        "model_id": "vision-classifier-v3",
        "sla_class": "real_time",
        "payload_ref": "s3://test/data",
        "idempotency_key": f"scenario-{scenario_num}-{time.time()}",
    }

    try:
        if scenario_num == 1:
            print("\nSCENARIO 1: Normal routing (All nodes healthy)")
            # No changes needed.
            
        elif scenario_num == 2:
            print("\nSCENARIO 2: Latency degradation (Increase Edge-1 latency)")
            # Edge 1 is normally edge-frankfurt-1
            snap = telemetry_store._store["edge-frankfurt-1"]
            snap.rtt_ms = 500.0 # Massive latency
            telemetry_store.record_snapshot(snap)
            
        elif scenario_num == 3:
            print("\nSCENARIO 3: Queue overload (Increase Edge-2 queue depth)")
            snap = telemetry_store._store["edge-london-1"]
            snap.queue_depth = 100 # Massive queue
            telemetry_store.record_snapshot(snap)
            
        elif scenario_num == 4:
            print("\nSCENARIO 4: Node failure (Mark Edge-1 unreachable via execution timeout)")
            nodes["edge-frankfurt-1"].fail_execution = True
            
        elif scenario_num == 5:
            print("\nSCENARIO 5: Multiple node failures (Fail Edge-1 and Edge-2)")
            nodes["edge-frankfurt-1"].fail_execution = True
            nodes["edge-london-1"].fail_execution = True
            
        elif scenario_num == 6:
            print("\nSCENARIO 6: Decision Engine failure (Stop Decision Engine)")
            app.state.decision_engine_enabled = False
            
        elif scenario_num == 7:
            print("\nSCENARIO 7: Stale telemetry (Age Edge-1 heartbeat beyond threshold)")
            snap = telemetry_store._store["edge-frankfurt-1"]
            snap.last_heartbeat_age_ms = 999999.0 # Very stale
            telemetry_store.record_snapshot(snap)
            
        elif scenario_num == 8:
            print("\nSCENARIO 8: Data residency constraint (Task requires us-only)")
            task_payload["data_residency"] = "us-only"
            
        elif scenario_num == 9:
            print("\nSCENARIO 9: Different SLA classes (Testing real_time, interactive, batch)")
            for sla in ["real_time", "interactive", "batch"]:
                print(f"\n--- Testing SLA: {sla} ---")
                task_payload["sla_class"] = sla
                resp = await client.post("/v1/tasks/infer", json=task_payload)
                data = resp.json()
                print(f"Routed to: {data['execution_metadata']['executed_node']}")
            return

        print("\nSending workload...")
        resp = await client.post("/v1/tasks/infer", json=task_payload)
        data = resp.json()
        
        print("\n--- RESULTS ---")
        if resp.status_code == 200:
            print(f"Status: SUCCESS")
            print(f"Executed on: {data['execution_metadata']['executed_node']} ({data['execution_metadata']['node_class']})")
            print(f"Fallback Activated: {data['execution_metadata']['fallback_activated']}")
            if data['execution_metadata']['fallback_activated']:
                print(f"Attempts: {data['execution_metadata']['attempts']}")
        else:
            print(f"Status: FAILED")
            print(f"Error: {data}")

    finally:
        await client.aclose()
        for srv in grpc_servers:
            srv.stop(0)
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Orchestration Test Controls")
    parser.add_argument("--scenario", type=int, choices=range(1, 10), required=True, help="Scenario number to run (1-9)")
    args = parser.parse_args()
    
    asyncio.run(run_scenario(args.scenario))
