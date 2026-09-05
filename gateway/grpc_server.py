"""gRPC Server for Control Plane Telemetry Service.
Receives heartbeats and metrics from Node Agents and stores them in Redis.
"""

import os
import json
import logging
from concurrent import futures
import grpc

from common.logger import get_logger
from common.tls import get_server_credentials
from contracts.models import HealthStatus, NodeClass, NodeTelemetrySnapshot
from contracts.proto import orchestrator_pb2, orchestrator_pb2_grpc
from telemetry.redis_store import RedisTelemetryStore
from scheduler.dispatcher import TaskScheduler

logger = get_logger("gateway.grpc_server")

# The expected token for nodes to join the cluster
EXPECTED_AUTH_TOKEN = os.environ.get("CLUSTER_AUTH_TOKEN", "default-insecure-token-123")

def _authenticate(context: grpc.ServicerContext) -> bool:
    """Extract and validate the auth token from gRPC metadata."""
    metadata = dict(context.invocation_metadata())
    token = metadata.get("authorization", "")
    if token == f"Bearer {EXPECTED_AUTH_TOKEN}":
        return True
    
    logger.warning("Unauthenticated gRPC request rejected.")
    context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid or missing auth token")
    return False

class NodeRegistryServicer(orchestrator_pb2_grpc.NodeRegistryServicer):
    def __init__(self, scheduler: TaskScheduler):
        self.scheduler = scheduler

    def RegisterNode(self, request: orchestrator_pb2.NodeRegistrationRequest, context: grpc.ServicerContext):
        if request.auth_token != EXPECTED_AUTH_TOKEN:
            logger.warning(f"Node {request.node_id} failed registration: Invalid auth_token in payload.")
            return orchestrator_pb2.NodeRegistrationResponse(
                status="rejected",
                message="Invalid authentication token."
            )
            
        logger.info(f"Node {request.node_id} successfully authenticated and registered.")
        
        # Register the node's execution target
        # Assumes node is reachable at node_id:50051 in the docker network
        grpc_target = f"{request.node_id}:50051"
        self.scheduler.register_worker(request.node_id, grpc_target)
        
        return orchestrator_pb2.NodeRegistrationResponse(
            status="success",
            message="Node registered successfully."
        )

class TelemetryServiceServicer(orchestrator_pb2_grpc.TelemetryServicer):
    def __init__(self, store: RedisTelemetryStore):
        self.store = store

    def StreamTelemetry(self, request_iterator, context: grpc.ServicerContext):
        _authenticate(context)
        
        node_id = None
        try:
            for snapshot_req in request_iterator:
                node_id = snapshot_req.node_id
                
                snapshot = NodeTelemetrySnapshot(
                    node_id=node_id,
                    node_class=NodeClass(snapshot_req.node_class),
                    timestamp=snapshot_req.timestamp,
                    rtt_ms=snapshot_req.rtt_ms,
                    bandwidth_available_mbps=snapshot_req.bandwidth_available_mbps,
                    cpu_util_pct=snapshot_req.cpu_util_pct,
                    gpu_util_pct=snapshot_req.gpu_util_pct,
                    queue_depth=snapshot_req.queue_depth,
                    cost_per_1k_inferences_usd=snapshot_req.cost_per_1k_inferences_usd,
                    health=HealthStatus(snapshot_req.health),
                    last_heartbeat_age_ms=0.0,
                    data_residency_zones=list(snapshot_req.data_residency_zones),
                )
                
                self.store.record_snapshot(snapshot)

            return orchestrator_pb2.TelemetryAck(status="success")
        except grpc.RpcError as e:
            logger.warning(f"Telemetry stream disconnected for {node_id}: {e}")
            return orchestrator_pb2.TelemetryAck(status="disconnected")
        except Exception as e:
            logger.error(f"Error processing telemetry from {node_id}: {e}")
            return orchestrator_pb2.TelemetryAck(status="error")

def serve_control_plane(store: RedisTelemetryStore, scheduler: TaskScheduler, port: int = 50050, use_tls: bool = True):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    orchestrator_pb2_grpc.add_NodeRegistryServicer_to_server(NodeRegistryServicer(scheduler), server)
    orchestrator_pb2_grpc.add_TelemetryServicer_to_server(TelemetryServiceServicer(store), server)
    
    address = f"[::]:{port}"
    if use_tls:
        creds = get_server_credentials()
        server.add_secure_port(address, creds)
        logger.info(f"Starting Secure gRPC Control Plane on {address}")
    else:
        server.add_insecure_port(address)
        logger.info(f"Starting Insecure gRPC Control Plane on {address}")
        
    server.start()
    return server
