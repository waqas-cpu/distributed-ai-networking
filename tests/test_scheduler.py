"""Unit tests for the Task Scheduler fallback chains and idempotency."""

import pytest
from common.errors import FallbackExhaustionError
from contracts.models import (
    ExecutionStatus,
    NodeClass,
    PlacementDecision,
    SLAClass,
    TaskRequest,
)
from node_agent.node import SimulatedNode
from node_agent.worker import InferenceWorker
from scheduler.dispatcher import TaskScheduler


@pytest.fixture
def setup_scheduler():
    n1 = SimulatedNode("node-1", NodeClass.EDGE, 10.0, 100.0, 0.005, ["eu-only"])
    n2 = SimulatedNode("node-2", NodeClass.EDGE, 20.0, 80.0, 0.004, ["eu-only"])
    n3 = SimulatedNode("node-3", NodeClass.CLOUD, 50.0, 500.0, 0.02, ["global"])

    w1 = InferenceWorker(n1)
    w2 = InferenceWorker(n2)
    w3 = InferenceWorker(n3)

    from node_agent.grpc_server import serve
    import os
    use_tls = os.path.exists("certs/ca.crt")
    
    s1 = serve(w1, port=50061, use_tls=use_tls)
    s2 = serve(w2, port=50062, use_tls=use_tls)
    s3 = serve(w3, port=50063, use_tls=use_tls)

    scheduler = TaskScheduler(
        node_targets={
            "node-1": "localhost:50061",
            "node-2": "localhost:50062",
            "node-3": "localhost:50063",
        },
        use_tls=use_tls
    )
    
    yield scheduler, n1, n2, n3
    
    s1.stop(0)
    s2.stop(0)
    s3.stop(0)


def test_primary_node_execution(setup_scheduler):
    scheduler, n1, n2, n3 = setup_scheduler
    task = TaskRequest(model_id="v3", payload_ref="ref", idempotency_key="key-sched-1")
    decision = PlacementDecision(
        task_id=task.task_id,
        chosen_node="node-1",
        chosen_score=0.25,
        runner_up_node="node-2",
        runner_up_score=0.35,
        weights_used={},
        decision_latency_ms=1.2,
        fallback_chain=["node-1", "node-2", "node-3"],
    )

    result, fallback_activated, attempts = scheduler.dispatch(task, decision)
    assert result.status == ExecutionStatus.SUCCESS
    assert result.node_id == "node-1"
    assert fallback_activated is False
    assert attempts == 1


def test_fallback_chain_activation_on_failure(setup_scheduler):
    scheduler, n1, n2, n3 = setup_scheduler
    # Incur failure on node-1
    n1.fail_execution = True

    task = TaskRequest(model_id="v3", payload_ref="ref", idempotency_key="key-sched-fallback")
    decision = PlacementDecision(
        task_id=task.task_id,
        chosen_node="node-1",
        chosen_score=0.25,
        runner_up_node="node-2",
        runner_up_score=0.35,
        weights_used={},
        decision_latency_ms=1.5,
        fallback_chain=["node-1", "node-2", "node-3"],
    )

    result, fallback_activated, attempts = scheduler.dispatch(task, decision)
    # Successfully recovered on node-2!
    assert result.status == ExecutionStatus.SUCCESS
    assert result.node_id == "node-2"
    assert fallback_activated is True
    assert attempts == 2


def test_fallback_exhaustion(setup_scheduler):
    scheduler, n1, n2, n3 = setup_scheduler
    # Fail all nodes
    n1.fail_execution = True
    n2.fail_execution = True
    n3.fail_execution = True

    task = TaskRequest(model_id="v3", payload_ref="ref", idempotency_key="key-sched-exhaust")
    decision = PlacementDecision(
        task_id=task.task_id,
        chosen_node="node-1",
        chosen_score=0.25,
        runner_up_node="node-2",
        runner_up_score=0.35,
        weights_used={},
        decision_latency_ms=1.1,
        fallback_chain=["node-1", "node-2", "node-3"],
    )

    with pytest.raises(FallbackExhaustionError):
        scheduler.dispatch(task, decision)


def test_idempotency_caching(setup_scheduler):
    scheduler, n1, n2, n3 = setup_scheduler
    task = TaskRequest(model_id="v3", payload_ref="ref", idempotency_key="idemp-repeat-key")
    decision = PlacementDecision(
        task_id=task.task_id,
        chosen_node="node-1",
        chosen_score=0.2,
        weights_used={},
        decision_latency_ms=1.0,
        fallback_chain=["node-1"],
    )

    r1, _, _ = scheduler.dispatch(task, decision)
    assert r1.cached is False

    r2, _, _ = scheduler.dispatch(task, decision)
    assert r2.cached is True
    assert r2.output == r1.output
