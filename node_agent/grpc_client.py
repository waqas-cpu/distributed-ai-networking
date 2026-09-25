"""gRPC Client for Node Agent Telemetry Service.
Streams node heartbeats and health metrics to the Orchestration Gateway.
"""

import threading
import time
import grpc
import json
import uuid
import hashlib
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from common.logger import get_logger
from common.tls import get_client_credentials
from common.config import PqcConfig
from contracts.proto import orchestrator_pb2, orchestrator_pb2_grpc
from node_agent.node import SimulatedNode

logger = get_logger("node_agent.grpc_client")

class TelemetryStreamer:
    def __init__(self, node: SimulatedNode, control_plane_target: str = "localhost:50050", use_tls: bool = True):
        self.node = node
        self.target = control_plane_target
        self.use_tls = use_tls
        self._stop_event = threading.Event()
        self._thread = None
        self._metadata = ()
        
        # Phase 4/5: Replay and Signing Identity
        self._sequence_number = 0
        self._previous_hash = b""
        self._signing_key = self.node.signing_key
        self._public_key_pem = self.node.public_key_pem
        
        # Phase 8: PQC setup
        self.pqc_config = PqcConfig.load()
        self.dual_required = self.pqc_config.get("PQC_MESSAGE_SIGNATURE_POLICY") == "dual_required"

    def _sign_telemetry(self, snapshot) -> orchestrator_pb2.SignedTelemetryEnvelope:
        self._sequence_number += 1
        nonce = uuid.uuid4().hex
        now = time.time()
        expires_at = now + 10.0 # 10s TTL
        
        payload_dict = {
            "node_class": snapshot.node_class.value,
            "timestamp": snapshot.timestamp,
            "rtt_ms": snapshot.rtt_ms,
            "bandwidth_available_mbps": snapshot.bandwidth_available_mbps,
            "cpu_util_pct": snapshot.cpu_util_pct,
            "gpu_util_pct": snapshot.gpu_util_pct,
            "queue_depth": snapshot.queue_depth,
            "cost_per_1k_inferences_usd": snapshot.cost_per_1k_inferences_usd,
            "health": snapshot.health.value,
            "data_residency_zones": snapshot.data_residency_zones,
        }
        
        # Canonical JSON encoding
        payload_json = json.dumps(payload_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')
        
        # Calculate new hash chain
        h = hashlib.sha256()
        h.update(b"DISTRIBUTED_AI_TELEMETRY_V1")
        h.update(self._previous_hash)
        h.update(payload_json)
        h.update(str(self._sequence_number).encode('utf-8'))
        h.update(nonce.encode('utf-8'))
        current_hash = h.digest()
        self._previous_hash = current_hash
        
        signature = self._signing_key.sign(payload_json)
        
        env = orchestrator_pb2.SignedTelemetryEnvelope(
            node_id=self.node.node_id,
            schema_version="1.0",
            timestamp=now,
            expires_at=expires_at,
            sequence_number=self._sequence_number,
            nonce=nonce,
            payload_json=payload_json,
            previous_message_hash=current_hash,
            signature_algorithm="Ed25519",
            key_id=f"node-{self.node.node_id}-key-1",
            signature=signature,
            pq_signature_algorithm="",
            pq_signature=b""
        )
        
        if self.dual_required and self.node.pq_signer:
            env.pq_signature_algorithm = self.pqc_config.get("PQC_SIGNATURE", "ML-DSA-65")
            env.pq_signature = self.node.pq_signer.sign(payload_json, self.node.pq_privkey)
            
        return env

    def _telemetry_generator(self):
        while not self._stop_event.is_set():
            snapshot = self.node.emit_snapshot()
            yield self._sign_telemetry(snapshot)
            self._stop_event.wait(1.0) # Stream every 1 second

    def _stream_loop(self):
        while not self._stop_event.is_set():
            try:
                if self.use_tls:
                    creds = get_client_credentials(spiffe_id=f"spiffe://distributed-ai.local/node/{self.node.node_id}")
                    channel = grpc.secure_channel(self.target, creds)
                else:
                    channel = grpc.insecure_channel(self.target)
                    
                registry_stub = orchestrator_pb2_grpc.NodeRegistryStub(channel)
                logger.info(f"Registering node {self.node.node_id} with Control Plane at {self.target}...")
                
                req = orchestrator_pb2.NodeRegistrationRequest(
                    node_id=self.node.node_id,
                    node_class=self.node.node_class.value,
                    supported_models=["vision-classifier-v3"],
                    data_residency_zones=self.node.data_residency_zones,
                    hardware_specs_json="{}",
                    public_signing_key=self._public_key_pem
                )
                
                resp = registry_stub.RegisterNode(req, metadata=self._metadata)
                if resp.status != "success":
                    logger.error(f"Node registration rejected: {resp.message}")
                    self._stop_event.set()
                    return
                
                logger.info(f"Registration successful. Beginning signed telemetry stream.")
                
                telemetry_stub = orchestrator_pb2_grpc.TelemetryStub(channel)
                # This will block as long as the stream is active
                response = telemetry_stub.StreamTelemetry(self._telemetry_generator(), metadata=self._metadata)
                logger.info(f"Stream ended by server: {response.status}")
                
            except grpc.RpcError as e:
                logger.warning(f"gRPC connection disconnected: {e}. Retrying in 2s...")
                self._stop_event.wait(2.0)
            except Exception as e:
                logger.error(f"Unexpected error in telemetry stream: {e}")
                self._stop_event.wait(5.0)

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._stream_loop, daemon=True)
            self._thread.start()
            logger.info("Telemetry streamer started.")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            logger.info("Telemetry streamer stopped.")
