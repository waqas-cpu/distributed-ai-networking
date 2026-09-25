"""gRPC Server for Node Agent Execution Service.
Listens for inference dispatch requests from the Scheduler.
"""

import json
import time
import grpc
from concurrent import futures
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from common.logger import get_logger
from common.tls import get_server_credentials
from common.identity import extract_spiffe_id
from common.authorization import authorize_scheduler
from common.state import SimulatedEtcdProvider
from common.crypto import decrypt_envelope, encrypt_envelope, get_master_kek, CryptoConfig, OQS_AVAILABLE
from common.config import PqcConfig
from contracts.models import ExecutionRequest, NodeClass
from contracts.proto import orchestrator_pb2, orchestrator_pb2_grpc
from node_agent.node import SimulatedNode
from node_agent.worker import InferenceWorker

logger = get_logger("node_agent.grpc_server")

def _authenticate_scheduler(context: grpc.ServicerContext) -> str:
    """Extract and validate the SPIFFE ID from gRPC metadata, requiring scheduler identity."""
    spiffe_id = extract_spiffe_id(context)
    if not authorize_scheduler(spiffe_id):
        logger.warning(f"Unauthenticated ExecutionRequest rejected. SPIFFE ID: {spiffe_id}")
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid or missing SPIFFE identity")
    return spiffe_id

class ExecutionServiceServicer(orchestrator_pb2_grpc.ExecutionServicer):
    def __init__(self, worker: InferenceWorker):
        self.worker = worker
        self.etcd = SimulatedEtcdProvider()

    def ExecuteTask(self, request: orchestrator_pb2.SignedTaskEnvelope, context: grpc.ServicerContext) -> orchestrator_pb2.SignedResultEnvelope:
        _authenticate_scheduler(context)
        
        metadata = dict(context.invocation_metadata())
        trace_id = metadata.get("x-trace-id", "unknown-trace")
        
        # 1. Verify Signature & Algorithmic Agility (Phase 8)
        try:
            CryptoConfig.validate_signature_algorithm(request.signature_algorithm)
            if request.schema_version not in ["1.0", "1.1"]:
                logger.warning(f"Unexpected schema version from scheduler: {request.schema_version}")

            pubkey_pem = self.etcd.get(f"/distributed-ai/scheduler/{request.key_id}/identity")
            if not pubkey_pem:
                raise ValueError("Scheduler public key not found")
            
            public_key = serialization.load_pem_public_key(pubkey_pem.encode('utf-8'))
            canonical_bytes = request.encrypted_payload + request.encrypted_dek
            public_key.verify(request.signature, canonical_bytes)
            
            pqc_config = PqcConfig.load()
            dual_required = pqc_config.get("PQC_MESSAGE_SIGNATURE_POLICY") == "dual_required"
            if dual_required:
                if not request.pq_signature:
                    raise SecurityError("Task envelope missing required PQ signature under dual_required policy.")
                CryptoConfig.validate_signature_algorithm(request.pq_signature_algorithm)
                # In a real system, verify PQ signature with scheduler's PQ public key
                
        except Exception as e:
            logger.warning(f"Signature verification failed for task {request.task_id}: {e}")
            context.abort(grpc.StatusCode.PERMISSION_DENIED, "Invalid signature")
            
        # 2. Verify Expiry & Lease
        if time.time() > request.expires_at:
            logger.warning(f"Task {request.task_id} expired")
            context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Task expired")
            
        if not self.etcd.is_lease_valid(request.leader_lease_id):
            logger.warning(f"Task {request.task_id} rejected due to stale leader lease")
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Stale leader lease")

        logger.info(
            f"Received SignedTaskEnvelope for task {request.task_id}",
            extra={"task_id": request.task_id, "trace_id": trace_id}
        )
        
        # 3. Decrypt payload
        kek = get_master_kek()
        try:
            payload = decrypt_envelope(request.encrypted_payload, request.encrypted_dek, kek)
        except Exception as e:
            logger.error(f"Failed to decrypt task payload: {e}")
            context.abort(grpc.StatusCode.INTERNAL, "Failed to decrypt payload")
        
        exec_req = ExecutionRequest(
            task_id=request.task_id,
            node_id=request.node_id,
            model_id=payload["model_id"],
            model_digest=payload.get("model_digest"),
            payload_ref=payload["payload_ref"],
            idempotency_key=payload.get("idempotency_key", ""),
            timeout_ms=payload["timeout_ms"],
        )
        
        # 4. Execute
        from common.errors import ArtifactVerificationError
        try:
            result = self.worker.execute(exec_req)
            result_payload = {
                "status": result.status.value,
                "execution_time_ms": result.execution_time_ms,
                "output_json": json.dumps(result.output) if result.output else "",
                "error": result.error or "",
                "cached": result.cached,
                "idempotency_key": result.idempotency_key,
                "node_class": result.node_class.value,
                "model_digest": result.model_digest or "",
            }
        except ArtifactVerificationError as ave:
            logger.warning(f"Supply chain verification rejected task {exec_req.task_id}: {ave}")
            result_payload = {
                "status": "rejected",
                "execution_time_ms": 0.0,
                "output_json": "",
                "error": str(ave),
                "cached": False,
                "idempotency_key": exec_req.idempotency_key,
                "node_class": self.worker.node.node_class.value,
                "model_digest": exec_req.model_digest or "",
            }
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            result_payload = {
                "status": "failed",
                "execution_time_ms": 0.0,
                "output_json": "",
                "error": str(e),
                "cached": False,
                "idempotency_key": exec_req.idempotency_key,
                "node_class": self.worker.node.node_class.value,
                "model_digest": exec_req.model_digest or "",
            }
            
        # 5. Encrypt result and Sign
        encrypted_result, wrapped_dek = encrypt_envelope(result_payload, kek)
        
        resp = orchestrator_pb2.SignedResultEnvelope(
            task_id=request.task_id,
            node_id=request.node_id,
            issue_time=time.time(),
            encrypted_result=encrypted_result,
            encrypted_dek=wrapped_dek,
            signature_algorithm="Ed25519",
            key_id=self.worker.node.node_id,
            schema_version="1.1",
            signature=b"" # placeholder
        )
        
        canonical_bytes = resp.encrypted_result + resp.encrypted_dek
        resp.signature = self.worker.node.signing_key.sign(canonical_bytes)
        
        if dual_required and self.worker.node.pq_signer:
            resp.pq_signature_algorithm = pqc_config.get("PQC_SIGNATURE", "ML-DSA-65")
            resp.pq_signature = self.worker.node.pq_signer.sign(canonical_bytes, self.worker.node.pq_privkey)
            
        return resp

def serve(worker: InferenceWorker, port: int = 50051, use_tls: bool = True):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    orchestrator_pb2_grpc.add_ExecutionServicer_to_server(ExecutionServiceServicer(worker), server)
    
    address = f"[::]:{port}"
    if use_tls:
        creds = get_server_credentials(spiffe_id=f"spiffe://distributed-ai.local/node/{worker.node.node_id}")
        server.add_secure_port(address, creds)
        logger.info(f"Starting Secure gRPC ExecutionService on {address}")
    else:
        server.add_insecure_port(address)
        logger.info(f"Starting Insecure gRPC ExecutionService on {address}")
        
    server.start()
    return server
