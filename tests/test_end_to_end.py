"""End-to-end integration tests for the AI Workload Orchestration Platform."""

import pytest
import httpx
from common.cluster import create_simulated_cluster
from contracts.models import SLAClass


@pytest.fixture
def cluster_env():
    """Initializes a full simulated cluster for testing."""
    telemetry_store, decision_engine, scheduler, aggregator, nodes, app, grpc_servers = create_simulated_cluster()
    
    yield {
        "telemetry_store": telemetry_store,
        "decision_engine": decision_engine,
        "scheduler": scheduler,
        "aggregator": aggregator,
        "nodes": nodes,
        "app": app,
    }
    
    # Teardown
    for srv in grpc_servers:
        srv.stop(0)


@pytest.mark.anyio
async def test_gateway_health(cluster_env):
    app = cluster_env["app"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service_name"] == "network-gateway"
        assert int(data["dependencies"]["telemetry_nodes_count"]) >= 4


@pytest.mark.anyio
async def test_end_to_end_inference_real_time(cluster_env):
    app = cluster_env["app"]
    payload = {
        "workload_type": "inference",
        "model_id": "vision-classifier-v3",
        "sla_class": "real_time",
        "payload_ref": "s3://factory-floor-camera-1/sample.jpg",
        "max_latency_ms": 150.0,
        "data_residency": "none",
        "idempotency_key": "e2e-rt-task-001",
    }

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/tasks/infer", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] == "success"
        assert data["prediction"] == "classified_defect_none"
        # Real-time should choose the lowest latency node: edge-frankfurt-1
        assert data["execution_metadata"]["executed_node"] == "edge-frankfurt-1"
        assert data["execution_metadata"]["node_class"] == "edge"
        # Decision engine overhead target: < 10ms
        assert data["execution_metadata"]["decision_overhead_ms"] < 10.0
        assert data["execution_metadata"]["fallback_activated"] is False
        assert data["execution_metadata"]["attempts"] == 1


@pytest.mark.anyio
async def test_end_to_end_data_residency_constraint(cluster_env):
    app = cluster_env["app"]
    # Requesting us-only data residency
    payload = {
        "workload_type": "inference",
        "model_id": "vision-classifier-v3",
        "sla_class": "real_time",
        "payload_ref": "s3://us-customer-data/sample.jpg",
        "max_latency_ms": 200.0,
        "data_residency": "us-only",
        "idempotency_key": "e2e-us-residency-001",
    }

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/tasks/infer", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        # Must be routed to cloud-aws-us-east due to hard residency constraint
        assert data["execution_metadata"]["executed_node"] == "cloud-aws-us-east"
        assert data["execution_metadata"]["node_class"] == "cloud"


@pytest.mark.anyio
async def test_fail_open_when_decision_engine_offline(cluster_env):
    app = cluster_env["app"]
    # Deliberately disable Decision Engine to simulate outage
    app.state.decision_engine_enabled = False

    payload = {
        "workload_type": "inference",
        "model_id": "vision-classifier-v3",
        "sla_class": "interactive",
        "payload_ref": "s3://bucket/test.jpg",
        "idempotency_key": "e2e-fail-open-001",
    }

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/tasks/infer", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        # Verification that system failed open to static policy
        assert data["status"] == "success"
        # Primary candidate from static policy was executed
        assert data["execution_metadata"]["executed_node"] == "edge-frankfurt-1"


@pytest.mark.anyio
async def test_audit_trail_recorded(cluster_env):
    app = cluster_env["app"]
    payload = {
        "workload_type": "inference",
        "model_id": "vision-classifier-v3",
        "sla_class": "batch",
        "payload_ref": "s3://nightly-eval/img.jpg",
        "idempotency_key": "e2e-audit-task-001",
    }

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        infer_resp = await client.post("/v1/tasks/infer", json=payload)
        assert infer_resp.status_code == 200
        task_id = infer_resp.json()["task_id"]

        audit_resp = await client.get(f"/v1/audit/events?task_id={task_id}")
        assert audit_resp.status_code == 200
        events = audit_resp.json()
        assert len(events) == 1
        record = events[0]
        assert record["task_id"] == task_id
        assert "decision" in record
        assert "execution" in record
