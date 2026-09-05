"""Redis-backed store for node telemetry snapshots.
Designed for sub-millisecond state queries (< 2ms p99) by the Decision Engine.
Externalizes state to enable horizontal scaling of the Orchestration Gateway.
"""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional
import redis

from contracts.models import NodeTelemetrySnapshot


class RedisTelemetryStore:
    """Fast, Redis-backed store representing current cluster telemetry state."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0", staleness_threshold_ms: float = 3000.0) -> None:
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._staleness_threshold_ms = staleness_threshold_ms
        self._hash_key = "telemetry:snapshots"

    @property
    def staleness_threshold_ms(self) -> float:
        return self._staleness_threshold_ms

    @staleness_threshold_ms.setter
    def staleness_threshold_ms(self, value_ms: float) -> None:
        self._staleness_threshold_ms = value_ms

    def record_snapshot(self, snapshot: NodeTelemetrySnapshot) -> None:
        """Ingest or update a node's telemetry snapshot in Redis."""
        self._redis.hset(self._hash_key, snapshot.node_id, snapshot.model_dump_json())

    def get_snapshot(self, node_id: str) -> Optional[NodeTelemetrySnapshot]:
        """Retrieve latest snapshot for a specific node from Redis."""
        data = self._redis.hget(self._hash_key, node_id)
        if data:
            return NodeTelemetrySnapshot.model_validate_json(data)
        return None

    def get_all_snapshots(self) -> List[NodeTelemetrySnapshot]:
        """Retrieve all active node snapshots from Redis."""
        data_dict = self._redis.hgetall(self._hash_key)
        return [NodeTelemetrySnapshot.model_validate_json(v) for v in data_dict.values()]

    def update_heartbeat_age(self) -> None:
        """Helper to advance heartbeat age for active snapshots based on real time."""
        now = time.time()
        snapshots = self.get_all_snapshots()
        pipeline = self._redis.pipeline()
        for snap in snapshots:
            elapsed_ms = (now - snap.timestamp) * 1000.0
            updated_snap = snap.model_copy(update={"last_heartbeat_age_ms": max(0.0, elapsed_ms)})
            pipeline.hset(self._hash_key, updated_snap.node_id, updated_snap.model_dump_json())
        pipeline.execute()

    def clear(self) -> None:
        """Clear all stored snapshots from Redis."""
        self._redis.delete(self._hash_key)
