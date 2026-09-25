import pytest
from contracts.models import TaskRequest, NodeTelemetrySnapshot, AssuranceLevel, NodeClass, HealthStatus
from decision_engine.filter import ConstraintFilter
import time

def test_high_assurance_task_routes_to_high_assurance_node():
    filter_engine = ConstraintFilter()
    
    # Task demanding HIGH_ASSURANCE
    task = TaskRequest(
        model_id="secure-model",
        payload_ref="s3://data",
        idempotency_key="key1",
        required_assurance_level=AssuranceLevel.HIGH_ASSURANCE
    )
    
    # Candidate node with HIGH_ASSURANCE
    node = NodeTelemetrySnapshot(
        node_id="high-assurance-node",
        node_class=NodeClass.CLOUD,
        timestamp=time.time(),
        rtt_ms=10.0,
        bandwidth_available_mbps=100.0,
        cpu_util_pct=50.0,
        gpu_util_pct=50.0,
        queue_depth=5,
        cost_per_1k_inferences_usd=1.0,
        health=HealthStatus.HEALTHY,
        last_heartbeat_age_ms=100.0,
        assurance_level=AssuranceLevel.HIGH_ASSURANCE
    )
    
    passed, rejected = filter_engine.filter_candidates(task, [node])
    assert len(passed) == 1
    assert passed[0].node_id == "high-assurance-node"
    assert len(rejected) == 0

def test_high_assurance_task_rejects_standard_node():
    filter_engine = ConstraintFilter()
    
    # Task demanding HIGH_ASSURANCE
    task = TaskRequest(
        model_id="secure-model",
        payload_ref="s3://data",
        idempotency_key="key2",
        required_assurance_level=AssuranceLevel.HIGH_ASSURANCE
    )
    
    # Candidate node with STANDARD assurance
    node = NodeTelemetrySnapshot(
        node_id="standard-node",
        node_class=NodeClass.CLOUD,
        timestamp=time.time(),
        rtt_ms=10.0,
        bandwidth_available_mbps=100.0,
        cpu_util_pct=50.0,
        gpu_util_pct=50.0,
        queue_depth=5,
        cost_per_1k_inferences_usd=1.0,
        health=HealthStatus.HEALTHY,
        last_heartbeat_age_ms=100.0,
        assurance_level=AssuranceLevel.STANDARD
    )
    
    passed, rejected = filter_engine.filter_candidates(task, [node])
    assert len(passed) == 0
    assert "standard-node" in rejected
    assert "insufficient_assurance_level" in rejected["standard-node"]

def test_standard_task_routes_to_any_node():
    filter_engine = ConstraintFilter()
    
    # Task demanding STANDARD
    task = TaskRequest(
        model_id="standard-model",
        payload_ref="s3://data",
        idempotency_key="key3",
        required_assurance_level=AssuranceLevel.STANDARD
    )
    
    node1 = NodeTelemetrySnapshot(
        node_id="standard-node",
        node_class=NodeClass.CLOUD,
        timestamp=time.time(),
        rtt_ms=10.0,
        bandwidth_available_mbps=100.0,
        cpu_util_pct=50.0,
        gpu_util_pct=50.0,
        queue_depth=5,
        cost_per_1k_inferences_usd=1.0,
        health=HealthStatus.HEALTHY,
        last_heartbeat_age_ms=100.0,
        assurance_level=AssuranceLevel.STANDARD
    )
    
    node2 = NodeTelemetrySnapshot(
        node_id="high-assurance-node",
        node_class=NodeClass.CLOUD,
        timestamp=time.time(),
        rtt_ms=10.0,
        bandwidth_available_mbps=100.0,
        cpu_util_pct=50.0,
        gpu_util_pct=50.0,
        queue_depth=5,
        cost_per_1k_inferences_usd=1.0,
        health=HealthStatus.HEALTHY,
        last_heartbeat_age_ms=100.0,
        assurance_level=AssuranceLevel.HIGH_ASSURANCE
    )
    
    passed, rejected = filter_engine.filter_candidates(task, [node1, node2])
    assert len(passed) == 2
    assert len(rejected) == 0
