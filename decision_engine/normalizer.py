"""Min-Max normalization across candidate node pools per decision cycle.
Ensures scale-invariant multi-criteria scoring without historical bias.
"""

from __future__ import annotations

from typing import Dict, List
from contracts.models import NodeTelemetrySnapshot


class CandidateNormalizer:
    """Computes min-max normalized feature vectors for a candidate set."""

    @staticmethod
    def _normalize_metric(values: Dict[str, float]) -> Dict[str, float]:
        """Min-max normalize a map of node_id -> raw value.
        If all values are equal (min == max), normalized value is 0.0.
        """
        if not values:
            return {}
        raw_vals = list(values.values())
        min_v = min(raw_vals)
        max_v = max(raw_vals)
        spread = max_v - min_v

        if spread <= 1e-9:
            return {node_id: 0.0 for node_id in values}

        return {node_id: (val - min_v) / spread for node_id, val in values.items()}

    def normalize_candidates(
        self,
        candidates: List[NodeTelemetrySnapshot],
    ) -> Dict[str, Dict[str, float]]:
        """Extract and normalize all 5 decision dimensions across candidate set.
        Returns:
            Dict[node_id, Dict[metric_name, normalized_value]]
        """
        if not candidates:
            return {}

        raw_lat = {c.node_id: c.rtt_ms for c in candidates}
        raw_inv_bw = {c.node_id: 1.0 / max(c.bandwidth_available_mbps, 0.001) for c in candidates}
        raw_cmp = {c.node_id: c.compute_utilization for c in candidates}
        raw_queue = {c.node_id: float(c.queue_depth) for c in candidates}
        raw_cost = {c.node_id: c.cost_per_1k_inferences_usd for c in candidates}

        norm_lat = self._normalize_metric(raw_lat)
        norm_inv_bw = self._normalize_metric(raw_inv_bw)
        norm_cmp = self._normalize_metric(raw_cmp)
        norm_queue = self._normalize_metric(raw_queue)
        norm_cost = self._normalize_metric(raw_cost)

        normalized_pool: Dict[str, Dict[str, float]] = {}
        for c in candidates:
            nid = c.node_id
            normalized_pool[nid] = {
                "latency": norm_lat[nid],
                "bandwidth": norm_inv_bw[nid],
                "compute": norm_cmp[nid],
                "queue": norm_queue[nid],
                "cost": norm_cost[nid],
            }

        return normalized_pool
