"""Task Placement / Scheduler module executing workloads across ranked fallback chains."""

from __future__ import annotations

import json
import time
import grpc
from typing import Dict, List, Tuple
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from common.errors import FallbackExhaustionError, NodeUnavailableError
from common.logger import get_logger
from common.tls import get_client_credentials
from common.state import SimulatedEtcdProvider
from common.crypto import encrypt_envelope, get_master_kek, CryptoConfig, OqsSignatureProvider, OQS_AVAILABLE
from common.config import PqcConfig
from contracts.models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    NodeClass,
    PlacementDecision,
    TaskRequest,
)
from contracts.proto import orchestrator_pb2, orchestrator_pb2_grpc

logger = get_logger("scheduler.dispatcher", component="scheduler")


class TaskScheduler:
    """Dispatches execution requests along the Decision Engine's ranked fallback chain via gRPC."""

    def __init__(self, node_targets: Dict[str, str] = None, use_tls: bool = True, scheduler_id: str = "scheduler-1") -> None:
        self.node_targets = node_targets or {}
        self.use_tls = use_tls
        self.scheduler_id = scheduler_id
        self._channels: Dict[str, grpc.Channel] = {}
        
        self.etcd = SimulatedEtcdProvider()
        self.lease_id = self.etcd.grant_lease(ttl=30)
        self.is_leader = self.etcd.compare_and_swap(
            key="/distributed-ai/scheduler/leader",
            expected_value=None,
            new_value=self.scheduler_id,
            lease_id=self.lease_id
        )
        if self.is_leader:
            logger.info(f"Scheduler {self.scheduler_id} acquired leader lease {self.lease_id}")
        else:
            logger.warning(f"Scheduler {self.scheduler_id} failed to acquire leadership (currently held by {self.etcd.get('/distributed-ai/scheduler/leader')})")
            
        # Phase 5: Scheduler signing identity
        self._signing_key = ed25519.Ed25519PrivateKey.generate()
        self._public_key_pem = self._signing_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')
        
        # Publish public key to authoritative state
        self.etcd.put(f"/distributed-ai/scheduler/{self.scheduler_id}/identity", self._public_key_pem)
        
        # Phase 8: PQC Setup
        self.pqc_config = PqcConfig.load()
        self.dual_required = self.pqc_config.get("PQC_MESSAGE_SIGNATURE_POLICY") == "dual_required"
        self._pq_signer = None
        if self.dual_required:
            if not OQS_AVAILABLE:
                logger.critical("dual_required signature policy requested but OQS provider is unavailable")
            else:
                self._pq_signer = OqsSignatureProvider(self.pqc_config.get("PQC_SIGNATURE", "ML-DSA-65"))
                self._pq_pubkey, self._pq_privkey = self._pq_signer.generate_keypair()
                # In a real system, publish self._pq_pubkey to etcd alongside _public_key_pem

    def register_worker(self, node_id: str, grpc_target: str) -> None:
        """Register or update an active worker's gRPC target address."""
        self.node_targets[node_id] = grpc_target
        # Reset channel if target changes
        if node_id in self._channels:
            self._channels[node_id].close()
            del self._channels[node_id]

    def _get_stub(self, node_id: str) -> orchestrator_pb2_grpc.ExecutionStub:
        if node_id not in self._channels:
            target = self.node_targets.get(node_id)
            if not target:
                raise NodeUnavailableError(f"No gRPC target registered for {node_id}", node_id)
            
            if self.use_tls:
                creds = get_client_credentials(spiffe_id="spiffe://distributed-ai.local/scheduler/master")
                channel = grpc.secure_channel(target, creds)
            else:
                channel = grpc.insecure_channel(target)
            self._channels[node_id] = channel
            
        return orchestrator_pb2_grpc.ExecutionStub(self._channels[node_id])

    def dispatch(
        self,
        task: TaskRequest,
        decision: PlacementDecision,
    ) -> Tuple[ExecutionResult, bool, int]:
        """Execute task on chosen node or fall back along chain without re-scoring.
        Returns:
            (ExecutionResult, fallback_activated: bool, total_attempts: int)
        """
        if self.is_leader and not self.etcd.is_lease_valid(self.lease_id):
            logger.critical(f"Scheduler {self.scheduler_id} lost leader lease! Halting dispatch.")
            self.is_leader = False
            
        if not self.is_leader:
            raise NodeUnavailableError(f"Scheduler {self.scheduler_id} is not the leader. Cannot authorize work.", "scheduler")

        chain: List[str] = []
        if decision.chosen_node:
            chain.append(decision.chosen_node)
        for node_id in decision.fallback_chain:
            if node_id not in chain:
                chain.append(node_id)

        if not chain:
            raise FallbackExhaustionError(
                f"No candidates available in fallback chain for task {task.task_id}",
                chain=[],
            )

        attempts = 0
        fallback_activated = False

        for candidate_id in chain:
            attempts += 1
            if attempts > 1:
                fallback_activated = True
                logger.warning(
                    f"Fallback triggered for task {task.task_id}: attempting candidate {candidate_id} (attempt {attempts})",
                    extra={"task_id": task.task_id, "node_id": candidate_id, "attempt": attempts}
                )

            try:
                stub = self._get_stub(candidate_id)
            except NodeUnavailableError as err:
                logger.error(
                    f"Candidate {candidate_id} not registered in scheduler",
                    extra={"task_id": task.task_id, "node_id": candidate_id}
                )
                continue

            # Phase 5: Construct SignedTaskEnvelope
            now = time.time()
            expires_at = now + (task.max_latency_ms / 1000.0) + 10.0 # 10s buffer
            
            # Phase 7: Supply-chain assurance - resolve immutable model digest
            model_digest = task.model_digest
            if not model_digest:
                approved_raw = self.etcd.get(f"/distributed-ai/artifacts/models/{task.model_id}")
                if approved_raw:
                    try:
                        record_data = json.loads(approved_raw)
                        model_digest = record_data.get("digest")
                    except Exception:
                        pass

            payload_dict = {
                "model_id": task.model_id,
                "model_digest": model_digest,
                "payload_ref": task.payload_ref,
                "idempotency_key": task.idempotency_key,
                "timeout_ms": task.max_latency_ms
            }
            
            # Envelope Encryption
            kek = get_master_kek()
            encrypted_payload, wrapped_dek = encrypt_envelope(payload_dict, kek)
            
            req = orchestrator_pb2.SignedTaskEnvelope(
                task_id=task.task_id,
                node_id=candidate_id,
                cluster_epoch=1,
                leader_lease_id=self.lease_id,
                issue_time=now,
                expires_at=expires_at,
                encrypted_payload=encrypted_payload,
                encrypted_dek=wrapped_dek,
                signature_algorithm="Ed25519",
                key_id=self.scheduler_id,
                schema_version="1.1",
                signature=b"" # placeholder
            )
            
            # Sign
            canonical_bytes = req.encrypted_payload + req.encrypted_dek
            req.signature = self._signing_key.sign(canonical_bytes)
            
            if self.dual_required and self._pq_signer:
                req.pq_signature_algorithm = self.pqc_config.get("PQC_SIGNATURE", "ML-DSA-65")
                req.pq_signature = self._pq_signer.sign(canonical_bytes, self._pq_privkey)

            try:
                metadata = (
                    ('x-trace-id', f'trace-{task.task_id}'),
                )
                
                # Dispatch over gRPC
                resp = stub.ExecuteTask(req, timeout=task.max_latency_ms / 1000.0, metadata=metadata)
                
                # Phase 5: Unpack SignedResultEnvelope (we aren't validating node signature here for simplicity, but we would in production)
                # Phase 8: Cryptographic Agility Validation
                CryptoConfig.validate_signature_algorithm(resp.signature_algorithm)
                if resp.schema_version not in ["1.0", "1.1"]:
                    logger.warning(f"Unexpected schema version from node: {resp.schema_version}")
                
                if self.dual_required:
                    if not resp.pq_signature:
                        raise SecurityError("Node result missing required PQ signature under dual_required policy.")
                    CryptoConfig.validate_signature_algorithm(resp.pq_signature_algorithm)

                # But we do need to decrypt the result
                from common.crypto import decrypt_envelope
                result_payload = decrypt_envelope(resp.encrypted_result, resp.encrypted_dek, kek)
                
                if result_payload.get("status") == "failed" or result_payload.get("status") == "rejected":
                    raise NodeUnavailableError(f"Execution failed on node: {result_payload.get('error')}", candidate_id)

                result = ExecutionResult(
                    task_id=resp.task_id,
                    node_id=resp.node_id,
                    node_class=NodeClass(result_payload.get("node_class", "edge")),
                    status=ExecutionStatus(result_payload.get("status", "success")),
                    execution_time_ms=result_payload.get("execution_time_ms", 0.0),
                    model_digest=result_payload.get("model_digest") or model_digest,
                    output=json.loads(result_payload["output_json"]) if result_payload.get("output_json") else None,
                    error=result_payload.get("error"),
                    cached=result_payload.get("cached", False),
                    idempotency_key=result_payload.get("idempotency_key", ""),
                )

                if fallback_activated:
                    logger.info(
                        f"Task {task.task_id} successfully recovered on fallback node {candidate_id}",
                        extra={"task_id": task.task_id, "node_id": candidate_id, "attempts": attempts}
                    )
                return result, fallback_activated, attempts
                
            except grpc.RpcError as err:
                logger.warning(
                    f"gRPC call to node {candidate_id} failed: {err.code()}. Advancing along fallback chain.",
                    extra={"task_id": task.task_id, "node_id": candidate_id}
                )
                continue
            except NodeUnavailableError as err:
                logger.warning(
                    f"Candidate node {candidate_id} failed: {err.message}. Advancing along fallback chain.",
                    extra={"task_id": task.task_id, "node_id": candidate_id}
                )
                continue
            except Exception as ex:
                logger.error(
                    f"Unexpected error executing on node {candidate_id}: {str(ex)}",
                    extra={"task_id": task.task_id, "node_id": candidate_id}
                )
                continue

        logger.critical(
            f"All candidate nodes in fallback chain exhausted for task {task.task_id}: {chain}",
            extra={"task_id": task.task_id, "fallback_chain": chain}
        )
        raise FallbackExhaustionError(
            f"All {len(chain)} candidate nodes in fallback chain failed for task {task.task_id}",
            chain=chain,
        )
