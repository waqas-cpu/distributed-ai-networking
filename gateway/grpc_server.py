"""gRPC Server for Control Plane Telemetry Service.
Receives heartbeats and metrics from Node Agents and stores them in Redis.
"""

import os
import json
import logging
from concurrent import futures
import grpc
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

from common.logger import get_logger
from common.tls import get_server_credentials
from common.identity import extract_spiffe_id
from common.authorization import authorize_node
from common.state import SimulatedEtcdProvider
from contracts.models import HealthStatus, NodeClass, NodeTelemetrySnapshot
from contracts.proto import orchestrator_pb2, orchestrator_pb2_grpc
from telemetry.redis_store import RedisTelemetryStore
from telemetry.replay_state import ReplayProtectionState
from scheduler.dispatcher import TaskScheduler

logger = get_logger("gateway.grpc_server")

def _authenticate_node(context: grpc.ServicerContext) -> str:
    """Extract and validate the SPIFFE ID from gRPC metadata, requiring a node identity."""
    spiffe_id = extract_spiffe_id(context)
    if not spiffe_id or not spiffe_id.startswith("spiffe://distributed-ai.local/node/"):
        logger.warning(f"Unauthenticated gRPC request rejected. SPIFFE ID: {spiffe_id}")
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid or missing SPIFFE identity")
    return spiffe_id

class NodeRegistryServicer(orchestrator_pb2_grpc.NodeRegistryServicer):
    def __init__(self, scheduler: TaskScheduler):
        self.scheduler = scheduler
        self.etcd = SimulatedEtcdProvider()

    def RegisterNode(self, request: orchestrator_pb2.NodeRegistrationRequest, context: grpc.ServicerContext):
        spiffe_id = extract_spiffe_id(context)
        if not authorize_node(spiffe_id, request.node_id):
            logger.warning(f"Node {request.node_id} failed registration: SPIFFE ID mismatch ({spiffe_id}).")
            return orchestrator_pb2.NodeRegistrationResponse(
                status="rejected",
                message="Invalid authentication identity."
            )
            
        # Store the public signing key in the authoritative state
        if request.public_signing_key:
            self.etcd.put(f"/distributed-ai/members/{request.node_id}/identity", request.public_signing_key)
        else:
            logger.warning(f"Node {request.node_id} did not provide a public signing key.")
            return orchestrator_pb2.NodeRegistrationResponse(
                status="rejected",
                message="Missing public signing key."
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
        self.etcd = SimulatedEtcdProvider()
        self.replay_state = ReplayProtectionState()

    def StreamTelemetry(self, request_iterator, context: grpc.ServicerContext):
        _authenticate_node(context)
        
        node_id = None
        try:
            for env in request_iterator:
                node_id = env.node_id
                
                # Fetch public key from authoritative state
                pubkey_pem = self.etcd.get(f"/distributed-ai/members/{node_id}/identity")
                if not pubkey_pem:
                    logger.warning(f"No public signing key found for node {node_id}")
                    continue
                    
                # Load public key
                public_key = serialization.load_pem_public_key(pubkey_pem.encode('utf-8'))
                
                # Validate replay state
                if not self.replay_state.validate_and_record(
                    node_id, env.sequence_number, env.nonce, env.timestamp, env.expires_at
                ):
                    logger.warning(f"Replay protection rejected telemetry from {node_id}")
                    continue
                    
                # Verify signature
                try:
                    # canonical JSON was signed
                    public_key.verify(env.signature, env.payload_json)
                except InvalidSignature:
                    logger.warning(f"Invalid signature on telemetry from {node_id}")
                    continue
                
                # Parse payload
                payload = json.loads(env.payload_json.decode('utf-8'))
                
                snapshot = NodeTelemetrySnapshot(
                    node_id=node_id,
                    node_class=NodeClass(payload.get("node_class", "edge")),
                    timestamp=payload.get("timestamp", env.timestamp),
                    rtt_ms=payload.get("rtt_ms", 0.0),
                    bandwidth_available_mbps=payload.get("bandwidth_available_mbps", 0.0),
                    cpu_util_pct=payload.get("cpu_util_pct", 0.0),
                    gpu_util_pct=payload.get("gpu_util_pct", 0.0),
                    queue_depth=payload.get("queue_depth", 0),
                    cost_per_1k_inferences_usd=payload.get("cost_per_1k_inferences_usd", 0.0),
                    health=HealthStatus(payload.get("health", "healthy")),
                    last_heartbeat_age_ms=0.0,
                    data_residency_zones=payload.get("data_residency_zones", []),
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
        creds = get_server_credentials(spiffe_id="spiffe://distributed-ai.local/gateway/master")
        server.add_secure_port(address, creds)
        logger.info(f"Starting Secure gRPC Control Plane on {address}")
    else:
        server.add_insecure_port(address)
        logger.info(f"Starting Insecure gRPC Control Plane on {address}")
        
    server.start()
    return server
