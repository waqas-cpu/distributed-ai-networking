"""Unit tests for the Decision Engine scoring, constraints, and SLA weighting."""

import time
import pytest
from contracts.models import HealthStatus, NodeClass, NodeTelemetrySnapshot, SLAClass, TaskRequest
from contracts.sla_profiles import SLAWeights
from decision_engine.engine import DecisionEngine
from decision_engine.filter import ConstraintFilter
from decision_engine.normalizer import CandidateNormalizer


@pytest.fixture
def sample_candidates():
    return [
        NodeTelemetrySnapshot(
            node_id="edge-fast",
            node_class=NodeClass.EDGE,
            rtt_ms=10.0,
            bandwidth_available_mbps=50.0,
            cpu_util_pct=30.0,
            gpu_util_pct=25.0,
            queue_depth=1,
            cost_per_1k_inferences_usd=0.010,
            last_heartbeat_age_ms=100.0,
            data_residency_zones=["eu-only"],
        ),
        NodeTelemetrySnapshot(
            node_id="edge-cheap",
            node_class=NodeClass.EDGE,
            rtt_ms=25.0,
            bandwidth_available_mbps=50.0,
            cpu_util_pct=25.0,
            gpu_util_pct=25.0,
            queue_depth=1,
            cost_per_1k_inferences_usd=0.001,
            last_heartbeat_age_ms=100.0,
            data_residency_zones=["eu-only"],
        ),
        NodeTelemetrySnapshot(
            node_id="cloud-heavy",
            node_class=NodeClass.CLOUD,
            rtt_ms=80.0,
            bandwidth_available_mbps=500.0,
            cpu_util_pct=15.0,
            gpu_util_pct=10.0,
            queue_depth=0,
            cost_per_1k_inferences_usd=0.030,
            last_heartbeat_age_ms=50.0,
            data_residency_zones=["us-only", "global"],
        ),
    ]


def test_hard_constraint_filtering(sample_candidates):
    filter_eng = ConstraintFilter(staleness_threshold_ms=3000.0)

    # 1. Data residency constraint: eu-only
    task_eu = TaskRequest(
        model_id="vision-v3",
        data_residency="eu-only",
        payload_ref="ref",
        idempotency_key="key-1",
    )
    surviving, rejected = filter_eng.filter_candidates(task_eu, sample_candidates)
    surviving_ids = [n.node_id for n in surviving]

    # cloud-heavy has ['us-only', 'global']. If 'global' is present, it's allowed.
    # Let's test a node with strict 'us-only' and no global
    node_strict_us = NodeTelemetrySnapshot(
        node_id="cloud-us-strict",
        node_class=NodeClass.CLOUD,
        rtt_ms=90.0,
        bandwidth_available_mbps=100.0,
        cpu_util_pct=10.0,
        gpu_util_pct=10.0,
        queue_depth=0,
        cost_per_1k_inferences_usd=0.02,
        last_heartbeat_age_ms=10.0,
        data_residency_zones=["us-only"],
    )
    surviving, rejected = filter_eng.filter_candidates(task_eu, [node_strict_us])
    assert len(surviving) == 0
    assert "data_residency_mismatch" in rejected["cloud-us-strict"]


def test_staleness_rejection():
    filter_eng = ConstraintFilter(staleness_threshold_ms=2000.0)
    stale_node = NodeTelemetrySnapshot(
        node_id="edge-stale",
        node_class=NodeClass.EDGE,
        rtt_ms=10.0,
        bandwidth_available_mbps=50.0,
        cpu_util_pct=10.0,
        gpu_util_pct=10.0,
        queue_depth=0,
        cost_per_1k_inferences_usd=0.005,
        last_heartbeat_age_ms=5500.0,  # Stale!
        data_residency_zones=["global"],
    )
    task = TaskRequest(model_id="v3", payload_ref="ref", idempotency_key="k1")
    surviving, rejected = filter_eng.filter_candidates(task, [stale_node])
    assert len(surviving) == 0
    assert "stale_telemetry" in rejected["edge-stale"]


def test_normalization_handles_identical_values():
    normalizer = CandidateNormalizer()
    candidates = [
        NodeTelemetrySnapshot(
            node_id="n1",
            node_class=NodeClass.EDGE,
            rtt_ms=20.0,
            bandwidth_available_mbps=100.0,
            cpu_util_pct=50.0,
            gpu_util_pct=50.0,
            queue_depth=2,
            cost_per_1k_inferences_usd=0.01,
            last_heartbeat_age_ms=10.0,
        ),
        NodeTelemetrySnapshot(
            node_id="n2",
            node_class=NodeClass.EDGE,
            rtt_ms=20.0,  # Identical
            bandwidth_available_mbps=100.0,  # Identical
            cpu_util_pct=50.0,
            gpu_util_pct=50.0,
            queue_depth=2,
            cost_per_1k_inferences_usd=0.01,
            last_heartbeat_age_ms=10.0,
        ),
    ]
    pool = normalizer.normalize_candidates(candidates)
    assert pool["n1"]["latency"] == 0.0
    assert pool["n2"]["latency"] == 0.0


def test_sla_profile_selection(sample_candidates):
    engine = DecisionEngine()

    # Real time task (w_lat=0.50) -> should strongly favor 'edge-fast' (10ms RTT)
    rt_task = TaskRequest(
        model_id="vision-v3",
        sla_class=SLAClass.REAL_TIME,
        payload_ref="ref",
        idempotency_key="key-rt",
    )
    rt_decision = engine.evaluate_placement(rt_task, sample_candidates)
    assert rt_decision.chosen_node == "edge-fast"
    assert rt_decision.decision_latency_ms < 10.0  # p99 < 10ms target!

    # Batch task (w_cost=0.40, w_lat=0.10) -> should favor 'edge-cheap' ($0.002 vs $0.010/$0.030)
    batch_task = TaskRequest(
        model_id="vision-v3",
        sla_class=SLAClass.BATCH,
        payload_ref="ref",
        idempotency_key="key-batch",
    )
    batch_decision = engine.evaluate_placement(batch_task, sample_candidates)
    assert batch_decision.chosen_node == "edge-cheap"


def test_deterministic_decision(sample_candidates):
    engine = DecisionEngine()
    task = TaskRequest(
        model_id="vision-v3",
        sla_class=SLAClass.INTERACTIVE,
        payload_ref="ref",
        idempotency_key="key-det",
    )
    d1 = engine.evaluate_placement(task, sample_candidates)
    d2 = engine.evaluate_placement(task, sample_candidates)
    assert d1.chosen_node == d2.chosen_node
    assert d1.chosen_score == d2.chosen_score
    assert d1.fallback_chain == d2.fallback_chain
