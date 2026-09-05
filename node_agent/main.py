"""Entrypoint for the Standalone Node Agent Microservice.
Starts the Execution Server and Telemetry Client.
"""

import argparse
import time
import logging

from common.logger import get_logger, setup_logging
from contracts.models import NodeClass
from node_agent.node import SimulatedNode
from node_agent.worker import InferenceWorker
from node_agent.grpc_server import serve
from node_agent.grpc_client import TelemetryStreamer

logger = get_logger("node_agent.main")

def main():
    parser = argparse.ArgumentParser(description="Standalone Node Agent")
    parser.add_argument("--node-id", required=True, help="Unique node identifier")
    parser.add_argument("--node-class", required=True, choices=["edge", "cloud"], help="Node class")
    parser.add_argument("--port", type=int, default=50051, help="gRPC port for Execution Service")
    parser.add_argument("--control-plane", default="localhost:50050", help="Control Plane gRPC address")
    parser.add_argument("--zones", default="eu-only", help="Comma-separated data residency zones")
    parser.add_argument("--cost", type=float, default=1.0, help="Cost per 1k inferences")
    parser.add_argument("--insecure", action="store_true", help="Disable mTLS for local dev")
    
    args = parser.parse_args()
    setup_logging()

    node_class_enum = NodeClass.EDGE if args.node_class == "edge" else NodeClass.CLOUD
    zones = [z.strip() for z in args.zones.split(",")]

    node = SimulatedNode(
        node_id=args.node_id,
        node_class=node_class_enum,
        base_rtt_ms=10.0 if node_class_enum == NodeClass.EDGE else 45.0,
        bandwidth_mbps=100.0,
        cost_per_1k_usd=args.cost,
        data_residency_zones=zones,
        cpu_util_pct=15.0,
        gpu_util_pct=5.0,
        queue_depth=0,
    )

    worker = InferenceWorker(node)
    
    use_tls = not args.insecure
    import os
    auth_token = os.environ.get("CLUSTER_AUTH_TOKEN", "default-insecure-token-123")

    # Start Telemetry Client (Heartbeat to Gateway)
    streamer = TelemetryStreamer(node, auth_token=auth_token, control_plane_target=args.control_plane, use_tls=use_tls)
    streamer.start()

    # Start Execution Server (Listen for Scheduler tasks)
    server = serve(worker, port=args.port, use_tls=use_tls)

    try:
        logger.info(f"Node Agent {args.node_id} running...")
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        logger.info("Shutting down Node Agent...")
        streamer.stop()
        server.stop(0)

if __name__ == "__main__":
    main()
