"""Telemetry validation and gateway cross-checking logic.
Prevents blind trust of node-reported metrics and quarantines stale or dishonest nodes.
"""

from __future__ import annotations

from typing import Tuple
from contracts.models import NodeTelemetrySnapshot, HealthStatus
from common.logger import get_logger

logger = get_logger("telemetry.validator", component="telemetry")


class TelemetryValidator:
    """Validates node snapshots against staleness thresholds and gateway cross-measurements."""

    def __init__(self, max_allowed_divergence_pct: float = 50.0) -> None:
        # Max allowed percentage difference between node-reported RTT and gateway-observed RTT
        self.max_allowed_divergence_pct = max_allowed_divergence_pct

    def is_stale(self, snapshot: NodeTelemetrySnapshot, threshold_ms: float) -> bool:
        """Evaluate if the snapshot has exceeded the freshness deadline."""
        return snapshot.last_heartbeat_age_ms > threshold_ms

    def cross_validate_rtt(self, snapshot: NodeTelemetrySnapshot) -> Tuple[bool, str]:
        """Cross-checks node-reported RTT against gateway-observed RTT.
        Returns (is_valid, reason).
        """
        if snapshot.gateway_observed_rtt_ms is None:
            # No independent gateway measurement available yet
            return True, "no_gateway_measurement"

        observed = snapshot.gateway_observed_rtt_ms
        reported = snapshot.rtt_ms

        if reported <= 0.0:
            return False, "invalid_reported_rtt_zero_or_negative"

        # Calculate divergence
        divergence = abs(observed - reported) / max(reported, 1.0) * 100.0

        if divergence > self.max_allowed_divergence_pct:
            logger.warning(
                f"Node {snapshot.node_id} telemetry divergence alert: reported RTT {reported}ms, "
                f"gateway observed {observed}ms ({divergence:.1f}% divergence)",
                extra={"node_id": snapshot.node_id, "divergence_pct": divergence}
            )
            return False, f"divergence_exceeded_{divergence:.1f}_pct"

        return True, "validated"
