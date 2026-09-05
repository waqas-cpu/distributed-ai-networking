"""Hard constraint evaluation for AI Workload Placement.
Filters out candidate nodes that fail non-negotiable requirements prior to scoring.
"""

from __future__ import annotations

from typing import Dict, List, Tuple
from contracts.models import HealthStatus, NodeTelemetrySnapshot, TaskRequest, SLAClass
from telemetry.validator import TelemetryValidator

COST_CEILINGS_USD = {
    SLAClass.REAL_TIME: 10.0,
    SLAClass.INTERACTIVE: 2.0,
    SLAClass.BATCH: 0.5,
}


class ConstraintFilter:
    """Pre-scoring hard constraints evaluator."""

    def __init__(
        self,
        staleness_threshold_ms: float = 3000.0,
        max_queue_depth: int = 50,
        max_compute_pct: float = 98.0,
        validator: TelemetryValidator | None = None,
    ) -> None:
        self.staleness_threshold_ms = staleness_threshold_ms
        self.max_queue_depth = max_queue_depth
        self.max_compute_pct = max_compute_pct
        self.validator = validator or TelemetryValidator()

    def filter_candidates(
        self,
        task: TaskRequest,
        candidates: List[NodeTelemetrySnapshot],
    ) -> Tuple[List[NodeTelemetrySnapshot], Dict[str, str]]:
        """Filter candidate pool based on non-negotiable constraints.
        Returns:
            passed: List of compliant candidate snapshots.
            rejected: Dictionary of node_id -> rejection reason.
        """
        passed: List[NodeTelemetrySnapshot] = []
        rejected: Dict[str, str] = {}

        for node in candidates:
            # 1. Health constraint
            if node.health == HealthStatus.UNREACHABLE:
                rejected[node.node_id] = "node_unreachable"
                continue

            # 2. Telemetry staleness constraint
            if self.validator.is_stale(node, self.staleness_threshold_ms):
                rejected[node.node_id] = f"stale_telemetry_age_{node.last_heartbeat_age_ms:.1f}ms"
                continue

            # 3. Gateway cross-validation check
            is_valid, reason = self.validator.cross_validate_rtt(node)
            if not is_valid:
                rejected[node.node_id] = f"gateway_cross_check_failed_{reason}"
                continue

            # 4. Data residency hard constraint
            if task.data_residency and task.data_residency.lower() not in ("none", "any", ""):
                req_residency = task.data_residency.lower()
                node_zones = [z.lower() for z in node.data_residency_zones]
                if req_residency not in node_zones:
                    rejected[node.node_id] = (
                        f"data_residency_mismatch: required '{task.data_residency}', node provides {node.data_residency_zones}"
                    )
                    continue

            # 5. Resource headroom constraints
            if node.queue_depth >= self.max_queue_depth:
                rejected[node.node_id] = f"queue_saturated_{node.queue_depth}>={self.max_queue_depth}"
                continue

            if node.compute_utilization >= self.max_compute_pct:
                rejected[node.node_id] = f"compute_exhausted_{node.compute_utilization:.1f}%>={self.max_compute_pct}%"
                continue

            # 6. Cost Ceiling constraint
            cost_ceiling = COST_CEILINGS_USD.get(task.sla_class, 10.0)
            if node.cost_per_1k_inferences_usd > cost_ceiling:
                rejected[node.node_id] = f"cost_ceiling_exceeded_${node.cost_per_1k_inferences_usd}>${cost_ceiling}"
                continue

            passed.append(node)

        return passed, rejected
