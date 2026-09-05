"""gRPC Client for Node Agent Telemetry Service.
Streams node heartbeats and health metrics to the Orchestration Gateway.
"""

import threading
import time
import grpc

from common.logger import get_logger
from common.tls import get_client_credentials
from contracts.proto import orchestrator_pb2, orchestrator_pb2_grpc
from node_agent.node import SimulatedNode

logger = get_logger("node_agent.grpc_client")

class TelemetryStreamer:
    def __init__(self, node: SimulatedNode, auth_token: str, control_plane_target: str = "localhost:50050", use_tls: bool = True):
        self.node = node
        self.auth_token = auth_token
        self.target = control_plane_target
        self.use_tls = use_tls
        self._stop_event = threading.Event()
        self._thread = None
        self._metadata = (('authorization', f'Bearer {self.auth_token}'),)

    def _telemetry_generator(self):
        while not self._stop_event.is_set():
            snapshot = self.node.emit_snapshot()
            
            yield orchestrator_pb2.TelemetrySnapshot(
                node_id=snapshot.node_id,
                node_class=snapshot.node_class.value,
                timestamp=snapshot.timestamp,
                rtt_ms=snapshot.rtt_ms,
                bandwidth_available_mbps=snapshot.bandwidth_available_mbps,
                cpu_util_pct=snapshot.cpu_util_pct,
                gpu_util_pct=snapshot.gpu_util_pct,
                queue_depth=snapshot.queue_depth,
                cost_per_1k_inferences_usd=snapshot.cost_per_1k_inferences_usd,
                health=snapshot.health.value,
                data_residency_zones=snapshot.data_residency_zones,
            )
            self._stop_event.wait(1.0) # Stream every 1 second

    def _stream_loop(self):
        while not self._stop_event.is_set():
            try:
                if self.use_tls:
                    creds = get_client_credentials()
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
                    auth_token=self.auth_token
                )
                
                resp = registry_stub.RegisterNode(req, metadata=self._metadata)
                if resp.status != "success":
                    logger.error(f"Node registration rejected: {resp.message}")
                    self._stop_event.set()
                    return
                
                logger.info(f"Registration successful. Beginning telemetry stream.")
                
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
