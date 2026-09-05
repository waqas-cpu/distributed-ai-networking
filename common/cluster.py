"""Cluster initialization and bootstrap helper for simulated edge/cloud environments."""

from __future__ import annotations

from typing import Dict, Tuple
from contracts.models import HealthStatus, NodeClass
from decision_engine.engine import DecisionEngine
from gateway.app import create_gateway_app
from node_agent.node import SimulatedNode
from node_agent.worker import InferenceWorker
from results_aggregator.aggregator import ResultsAggregator
from scheduler.dispatcher import TaskScheduler
from telemetry.store import TelemetryStore
from fastapi import FastAPI


def create_simulated_cluster() -> Tuple[
    TelemetryStore,
    DecisionEngine,
    TaskScheduler,
    ResultsAggregator,
    Dict[str, SimulatedNode],
    FastAPI,
]:
    """Instantiate and wire up a full simulated hybrid edge/cloud platform cluster."""
    # 1. Initialize core state and components
    telemetry_store = TelemetryStore(staleness_threshold_ms=3000.0)
    decision_engine = DecisionEngine()
    aggregator = ResultsAggregator()

    # 2. Define heterogeneous nodes
    nodes: Dict[str, SimulatedNode] = {
        "edge-frankfurt-1": SimulatedNode(
            node_id="edge-frankfurt-1",
            node_class=NodeClass.EDGE,
            base_rtt_ms=14.2,
            bandwidth_mbps=120.0,
            cost_per_1k_usd=0.003,
            data_residency_zones=["eu-only", "eu-central-1"],
            cpu_util_pct=42.0,
            gpu_util_pct=38.0,
            queue_depth=2,
            health=HealthStatus.HEALTHY,
        ),
        "edge-london-1": SimulatedNode(
            node_id="edge-london-1",
            node_class=NodeClass.EDGE,
            base_rtt_ms=18.5,
            bandwidth_mbps=90.0,
            cost_per_1k_usd=0.004,
            data_residency_zones=["uk-only", "eu-west-2"],
            cpu_util_pct=60.0,
            gpu_util_pct=52.0,
            queue_depth=5,
            health=HealthStatus.HEALTHY,
        ),
        "cloud-aws-eu-central": SimulatedNode(
            node_id="cloud-aws-eu-central",
            node_class=NodeClass.CLOUD,
            base_rtt_ms=45.0,
            bandwidth_mbps=1000.0,
            cost_per_1k_usd=0.024,
            data_residency_zones=["eu-only", "eu-central-1"],
            cpu_util_pct=25.0,
            gpu_util_pct=18.0,
            queue_depth=1,
            health=HealthStatus.HEALTHY,
        ),
        "cloud-aws-us-east": SimulatedNode(
            node_id="cloud-aws-us-east",
            node_class=NodeClass.CLOUD,
            base_rtt_ms=115.0,
            bandwidth_mbps=2500.0,
            cost_per_1k_usd=0.018,
            data_residency_zones=["us-only", "us-east-1"],
            cpu_util_pct=15.0,
            gpu_util_pct=10.0,
            queue_depth=0,
            health=HealthStatus.HEALTHY,
        ),
    }

    # 3. Create workers, start gRPC servers, and register snapshots
    node_targets: Dict[str, str] = {}
    
    # Optional: we can store the server objects if we need to shut them down later,
    # but for testing they can just run in the background.
    grpc_servers = []
    
    # We will use TLS for local testing if certs are present, otherwise insecure
    import os
    use_tls = os.path.exists("certs/ca.crt")
    
    base_port = 50051
    for i, (node_id, node) in enumerate(nodes.items()):
        worker = InferenceWorker(node)
        
        # Start a local gRPC Execution server for this worker
        port = base_port + i
        from node_agent.grpc_server import serve
        server = serve(worker, port=port, use_tls=use_tls)
        grpc_servers.append(server)
        
        target = f"localhost:{port}"
        node_targets[node_id] = target
        
        telemetry_store.record_snapshot(node.emit_snapshot())

    scheduler = TaskScheduler(node_targets=node_targets, use_tls=use_tls)

    # 4. Create Gateway app
    gateway_app = create_gateway_app(
        telemetry_store=telemetry_store,
        decision_engine=decision_engine,
        scheduler=scheduler,
        aggregator=aggregator,
    )

    # We return grpc_servers so they can be cleanly shut down by the test runner if needed
    return telemetry_store, decision_engine, scheduler, aggregator, nodes, gateway_app, grpc_servers
