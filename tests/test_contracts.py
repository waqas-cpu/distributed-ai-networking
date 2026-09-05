"""Unit tests for strongly typed data contracts and SLA profiles."""

import pytest
from pydantic import ValidationError
from contracts.models import (
    NodeClass,
    NodeTelemetrySnapshot,
    SLAClass,
    TaskRequest,
    generate_uuidv7,
)
from contracts.sla_profiles import SLAWeights, DEFAULT_SLA_PROFILES, get_sla_weights


def test_uuidv7_format():
    uid = generate_uuidv7()
    parts = uid.split("-")
    assert len(parts) == 5
    assert len(parts[0]) == 8
    assert len(parts[1]) == 4
    assert len(parts[2]) == 4
    assert parts[2].startswith("7")  # UUIDv7 version nibble
    assert len(parts[3]) == 4
    assert len(parts[4]) == 12


def test_task_request_validation():
    req = TaskRequest(
        model_id="vision-classifier-v3",
        sla_class=SLAClass.REAL_TIME,
        payload_ref="s3://inference-bucket/sample.jpg",
        data_residency="eu-only",
        idempotency_key="client-req-001",
    )
    assert req.task_id is not None
    assert req.max_latency_ms == 150.0
    assert req.data_residency == "eu-only"

    # Validation failure on empty idempotency key
    with pytest.raises(ValidationError):
        TaskRequest(
            model_id="vision-classifier-v3",
            payload_ref="s3://test",
            idempotency_key="",
        )


def test_node_telemetry_snapshot():
    snap = NodeTelemetrySnapshot(
        node_id="edge-frankfurt-1",
        node_class=NodeClass.EDGE,
        rtt_ms=12.5,
        bandwidth_available_mbps=100.0,
        cpu_util_pct=50.0,
        gpu_util_pct=75.0,
        queue_depth=3,
        cost_per_1k_inferences_usd=0.005,
        last_heartbeat_age_ms=250.0,
        data_residency_zones=["eu-only"],
    )
    assert snap.compute_utilization == 75.0
    assert snap.health.value == "healthy"


def test_sla_weights_sum_validation():
    # Valid sum to 1.0
    valid = SLAWeights(w_lat=0.4, w_bw=0.15, w_cmp=0.2, w_queue=0.1, w_cost=0.15)
    assert valid is not None

    # Invalid sum raises ValidationError
    with pytest.raises(ValidationError):
        SLAWeights(w_lat=0.5, w_bw=0.5, w_cmp=0.5, w_queue=0.1, w_cost=0.1)


def test_default_sla_profiles():
    rt = get_sla_weights(SLAClass.REAL_TIME)
    assert rt.w_lat == 0.50
    assert rt.w_cost == 0.05

    batch = get_sla_weights(SLAClass.BATCH)
    assert batch.w_cost == 0.40
    assert batch.w_lat == 0.10
