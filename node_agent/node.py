"""Simulated Edge and Cloud compute nodes with telemetry reporting."""

from __future__ import annotations

import time
from typing import Dict, List, Optional
from contracts.models import HealthStatus, NodeClass, NodeTelemetrySnapshot


class SimulatedNode:
    """Represents an edge or cloud node capable of executing inference tasks and reporting telemetry."""

    def __init__(
        self,
        node_id: str,
        node_class: NodeClass,
        base_rtt_ms: float,
        bandwidth_mbps: float,
        cost_per_1k_usd: float,
        data_residency_zones: List[str],
        cpu_util_pct: float = 20.0,
        gpu_util_pct: float = 30.0,
        queue_depth: int = 0,
        health: HealthStatus = HealthStatus.HEALTHY,
    ) -> None:
        self.node_id = node_id
        self.node_class = node_class
        self.base_rtt_ms = base_rtt_ms
        self.bandwidth_mbps = bandwidth_mbps
        self.cost_per_1k_usd = cost_per_1k_usd
        self.data_residency_zones = data_residency_zones
        self.cpu_util_pct = cpu_util_pct
        self.gpu_util_pct = gpu_util_pct
        self.queue_depth = queue_depth
        self.health = health
        self.last_heartbeat_time = time.time()
        self.is_offline = False
        self.fail_execution = False

    def emit_snapshot(self, gateway_observed_rtt_ms: Optional[float] = None) -> NodeTelemetrySnapshot:
        """Produce current telemetry snapshot."""
        now = time.time()
        heartbeat_age_ms = (now - self.last_heartbeat_time) * 1000.0

        return NodeTelemetrySnapshot(
            node_id=self.node_id,
            node_class=self.node_class,
            timestamp=now,
            rtt_ms=self.base_rtt_ms,
            bandwidth_available_mbps=self.bandwidth_mbps,
            cpu_util_pct=self.cpu_util_pct,
            gpu_util_pct=self.gpu_util_pct,
            queue_depth=self.queue_depth,
            cost_per_1k_inferences_usd=self.cost_per_1k_usd,
            health=self.health if not self.is_offline else HealthStatus.UNREACHABLE,
            last_heartbeat_age_ms=heartbeat_age_ms,
            data_residency_zones=self.data_residency_zones,
            gateway_observed_rtt_ms=gateway_observed_rtt_ms,
        )

    def heartbeat(self) -> None:
        """Update last heartbeat timestamp."""
        self.last_heartbeat_time = time.time()
