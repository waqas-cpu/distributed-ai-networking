"""Results Aggregation and Audit Logging module.
Normalizes response envelopes across edge and cloud execution and creates an immutable audit trail.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from common.logger import get_logger
from contracts.models import AuditEvent, ExecutionResult, PlacementDecision

logger = get_logger("results_aggregator", component="results_aggregator")


class ResultsAggregator:
    """Aggregates execution results, normalizes response envelopes, and records audit logs."""

    def __init__(self) -> None:
        self._audit_log: List[AuditEvent] = []

    def aggregate(
        self,
        task_id: str,
        decision: PlacementDecision,
        execution: ExecutionResult,
        fallback_activated: bool = False,
        attempts: int = 1,
        gateway_observed_rtt_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Produce the unified client-facing response envelope and persist audit event."""
        audit_record = AuditEvent(
            task_id=task_id,
            timestamp=time.time(),
            decision=decision,
            execution=execution,
            fallback_activated=fallback_activated,
            attempts=attempts,
            gateway_rtt_observed_ms=gateway_observed_rtt_ms,
        )

        self._audit_log.append(audit_record)

        logger.info(
            f"Audit event recorded for task {task_id}: event_id={audit_record.event_id}, "
            f"chosen={decision.chosen_node}, executed_on={execution.node_id}, attempts={attempts}",
            extra={
                "event_id": audit_record.event_id,
                "task_id": task_id,
                "node_id": execution.node_id,
                "decision_latency_ms": decision.decision_latency_ms,
            }
        )

        # Standard unified response envelope
        return {
            "task_id": task_id,
            "status": execution.status.value,
            "prediction": execution.output.get("prediction") if execution.output else None,
            "confidence": execution.output.get("confidence") if execution.output else None,
            "execution_metadata": {
                "executed_node": execution.node_id,
                "node_class": execution.node_class.value,
                "execution_time_ms": execution.execution_time_ms,
                "decision_overhead_ms": decision.decision_latency_ms,
                "fallback_activated": fallback_activated,
                "attempts": attempts,
                "audit_event_id": audit_record.event_id,
                "cached": execution.cached,
            },
            "routing_audit": {
                "chosen_score": decision.chosen_score,
                "runner_up_node": decision.runner_up_node,
                "runner_up_score": decision.runner_up_score,
                "weights_used": decision.weights_used,
                "fallback_chain": decision.fallback_chain,
            },
        }

    def get_audit_trail(self, task_id: Optional[str] = None) -> List[AuditEvent]:
        """Retrieve recorded audit events, optionally filtered by task_id."""
        if task_id:
            return [e for e in self._audit_log if e.task_id == task_id]
        return list(self._audit_log)
