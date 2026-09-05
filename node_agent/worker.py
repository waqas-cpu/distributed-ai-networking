"""Inference worker executing AI workloads on edge and cloud compute nodes."""

from __future__ import annotations

import time
from typing import Dict, Optional
from common.errors import NodeUnavailableError
from common.logger import get_logger
from contracts.models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    NodeClass,
)
from node_agent.node import SimulatedNode

logger = get_logger("node_agent.worker", component="inference_worker")


class InferenceWorker:
    """Simulates AI inference execution (e.g. vision-classifier-v3) on compute nodes."""

    def __init__(self, node: SimulatedNode) -> None:
        self.node = node
        self._processed_idempotency_keys: Dict[str, ExecutionResult] = {}

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute inference workload with idempotency tracking and failure simulation."""
        # 1. Check idempotency cache to prevent duplicate billing / execution
        if request.idempotency_key in self._processed_idempotency_keys:
            cached_result = self._processed_idempotency_keys[request.idempotency_key]
            logger.info(
                f"Returning cached execution result for idempotency key {request.idempotency_key}",
                extra={"task_id": request.task_id, "node_id": self.node.node_id}
            )
            return cached_result.model_copy(update={"cached": True})

        # 2. Check node health and failure flags
        if self.node.is_offline or self.node.fail_execution:
            msg = f"Node {self.node.node_id} is offline or failed execution check"
            logger.error(msg, extra={"task_id": request.task_id, "node_id": self.node.node_id})
            raise NodeUnavailableError(msg, node_id=self.node.node_id)

        start_time = time.perf_counter()

        # 3. Simulate realistic inference computation
        # Edge nodes simulate quantized lightweight inference (e.g. 15ms base)
        # Cloud nodes simulate high-throughput GPU inference (e.g. 8ms base)
        base_exec_ms = 12.0 if self.node.node_class == NodeClass.EDGE else 6.0
        simulated_delay_s = base_exec_ms / 1000.0
        time.sleep(simulated_delay_s)

        exec_duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Output payload simulation for vision classifier
        output_payload = {
            "model": request.model_id,
            "prediction": "classified_defect_none",
            "confidence": 0.984,
            "latency_breakdown": {
                "compute_ms": round(exec_duration_ms, 2),
                "queue_ms": round(self.node.queue_depth * 2.5, 2),
            },
            "node_metadata": {
                "node_id": self.node.node_id,
                "node_class": self.node.node_class.value,
                "residency": self.node.data_residency_zones,
            },
        }

        result = ExecutionResult(
            task_id=request.task_id,
            node_id=self.node.node_id,
            node_class=self.node.node_class,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=round(exec_duration_ms, 2),
            output=output_payload,
            error=None,
            cached=False,
            idempotency_key=request.idempotency_key,
        )

        # Cache result under idempotency key
        self._processed_idempotency_keys[request.idempotency_key] = result
        return result
