"""Task Placement / Scheduler module executing workloads across ranked fallback chains."""

from __future__ import annotations

import json
import grpc
from typing import Dict, List, Tuple
from common.errors import FallbackExhaustionError, NodeUnavailableError
from common.logger import get_logger
from common.tls import get_client_credentials
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

    def __init__(self, node_targets: Dict[str, str] = None, use_tls: bool = True) -> None:
        self.node_targets = node_targets or {}
        self.use_tls = use_tls
        self._channels: Dict[str, grpc.Channel] = {}

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
                creds = get_client_credentials()
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

            req = orchestrator_pb2.ExecutionRequest(
                task_id=task.task_id,
                node_id=candidate_id,
                model_id=task.model_id,
                payload_ref=task.payload_ref,
                idempotency_key=task.idempotency_key,
                timeout_ms=task.max_latency_ms,
            )

            try:
                import os
                auth_token = os.environ.get("CLUSTER_AUTH_TOKEN", "default-insecure-token-123")
                metadata = (
                    ('authorization', f'Bearer {auth_token}'),
                    ('x-trace-id', f'trace-{task.task_id}')
                )
                
                # Dispatch over gRPC
                resp = stub.ExecuteTask(req, timeout=task.max_latency_ms / 1000.0, metadata=metadata)
                
                if resp.status == "failed" or resp.status == "rejected":
                    raise NodeUnavailableError(f"Execution failed on node: {resp.error}", candidate_id)

                result = ExecutionResult(
                    task_id=resp.task_id,
                    node_id=resp.node_id,
                    node_class=NodeClass(resp.node_class),
                    status=ExecutionStatus(resp.status),
                    execution_time_ms=resp.execution_time_ms,
                    output=json.loads(resp.output_json) if resp.output_json else None,
                    error=resp.error if resp.error else None,
                    cached=resp.cached,
                    idempotency_key=resp.idempotency_key,
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

