"""Low-latency thread-safe in-memory store for node telemetry snapshots.
Designed for sub-millisecond state queries (< 2ms p99) by the Decision Engine.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional
from contracts.models import NodeTelemetrySnapshot, HealthStatus


class TelemetryStore:
    """Fast, thread-safe in-memory store representing current cluster telemetry state."""

    def __init__(self, staleness_threshold_ms: float = 3000.0) -> None:
        self._lock = threading.RLock()
        self._snapshots: Dict[str, NodeTelemetrySnapshot] = {}
        self._staleness_threshold_ms = staleness_threshold_ms

    @property
    def staleness_threshold_ms(self) -> float:
        return self._staleness_threshold_ms

    @staleness_threshold_ms.setter
    def staleness_threshold_ms(self, value_ms: float) -> None:
        with self._lock:
            self._staleness_threshold_ms = value_ms

    def record_snapshot(self, snapshot: NodeTelemetrySnapshot) -> None:
        """Ingest or update a node's telemetry snapshot."""
        with self._lock:
            self._snapshots[snapshot.node_id] = snapshot

    def get_snapshot(self, node_id: str) -> Optional[NodeTelemetrySnapshot]:
        """Retrieve latest snapshot for a specific node."""
        with self._lock:
            return self._snapshots.get(node_id)

    def get_all_snapshots(self) -> List[NodeTelemetrySnapshot]:
        """Retrieve all active node snapshots."""
        with self._lock:
            return list(self._snapshots.values())

    def update_heartbeat_age(self) -> None:
        """Helper to advance heartbeat age for active snapshots based on real time."""
        with self._lock:
            now = time.time()
            for node_id, snap in self._snapshots.items():
                elapsed_ms = (now - snap.timestamp) * 1000.0
                # Preserve updated heartbeat age
                self._snapshots[node_id] = snap.model_copy(update={"last_heartbeat_age_ms": max(0.0, elapsed_ms)})

    def clear(self) -> None:
        """Clear all stored snapshots."""
        with self._lock:
            self._snapshots.clear()
