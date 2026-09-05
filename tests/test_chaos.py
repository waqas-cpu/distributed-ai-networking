import pytest
import httpx
import time
from common.cluster import create_simulated_cluster
from contracts.models import NodeTelemetrySnapshot, NodeClass, HealthStatus

@pytest.fixture
def cluster_env():
    telemetry_store, decision_engine, scheduler, aggregator, nodes, app, grpc_servers = create_simulated_cluster()
    
    yield {
        "telemetry_store": telemetry_store,
        "decision_engine": decision_engine,
        "scheduler": scheduler,
        "aggregator": aggregator,
        "nodes": nodes,
        "app": app,
    }
    
    for srv in grpc_servers:
        srv.stop(0)

@pytest.mark.anyio
async def test_chaos_de_crash_fail_open(cluster_env):
    """Scenario C: Decision Engine crashes, Gateway must fail open."""
    app = cluster_env["app"]
    app.state.decision_engine_enabled = False # Simulate crash
    
    payload = {
        "workload_type": "inference",
        "model_id": "vision-classifier-v3",
        "sla_class": "real_time",
        "payload_ref": "s3://test/data",
        "idempotency_key": "chaos-de-crash-1",
    }
    
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/tasks/infer", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        
        # Should have routed using static fallback
        audit_resp = await client.get(f"/v1/audit/events?task_id={data['task_id']}")
        events = audit_resp.json()
        assert len(events) == 1
        assert events[0]["decision"]["used_fallback_policy"] is True

@pytest.mark.anyio
async def test_chaos_telemetry_staleness(cluster_env):
    """Scenario B: Edge node stops heartbeating, must be excluded from placement."""
    app = cluster_env["app"]
    telemetry = cluster_env["telemetry_store"]
    
    # Inject a very old snapshot for edge-frankfurt-1
    old_snapshot = NodeTelemetrySnapshot(
        node_id="edge-frankfurt-1",
        node_class=NodeClass.EDGE,
        timestamp=time.time() - 100.0, # 100 seconds ago (stale!)
        rtt_ms=10.0,
        bandwidth_available_mbps=100.0,
        cpu_util_pct=10,
        gpu_util_pct=10,
        queue_depth=0,
        cost_per_1k_inferences_usd=0.001,
        health=HealthStatus.HEALTHY,
        last_heartbeat_age_ms=100000.0,
        data_residency_zones=["eu-only"]
    )
    telemetry.record_snapshot(old_snapshot)
    
    payload = {
        "workload_type": "inference",
        "model_id": "vision-classifier-v3",
        "sla_class": "real_time",
        "payload_ref": "s3://test/data",
        "idempotency_key": "chaos-stale-1",
    }
    
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/tasks/infer", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        # Should NOT route to edge-frankfurt-1 because it's stale, should pick the next best edge
        assert data["execution_metadata"]["executed_node"] != "edge-frankfurt-1"

@pytest.mark.anyio
async def test_chaos_network_partition_fallback(cluster_env):
    """Scenario A: Network partition (execution timeout), must fallback instantly."""
    app = cluster_env["app"]
    nodes = cluster_env["nodes"]
    
    # Simulate network partition by forcing the first edge node to timeout
    nodes["edge-frankfurt-1"].fail_execution = True
    
    payload = {
        "workload_type": "inference",
        "model_id": "vision-classifier-v3",
        "sla_class": "real_time",
        "payload_ref": "s3://test/data",
        "idempotency_key": "chaos-net-partition-1",
    }
    
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/tasks/infer", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        
        # Should have failed on candidate 1 and succeeded on candidate 2
        assert data["status"] == "success"
        assert data["execution_metadata"]["fallback_activated"] is True
        assert data["execution_metadata"]["attempts"] > 1
        assert data["execution_metadata"]["executed_node"] != "edge-frankfurt-1"
