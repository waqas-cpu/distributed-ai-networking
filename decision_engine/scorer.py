"""Multi-criteria weighted scoring engine for candidate nodes."""

from __future__ import annotations

from typing import Dict, List, Tuple
from contracts.sla_profiles import SLAWeights


class WeightedScorer:
    """Calculates normalized composite scores using active SLA weights."""

    @staticmethod
    def calculate_score(metrics: Dict[str, float], weights: SLAWeights) -> float:
        """Compute composite scalar score for a node."""
        score = (
            weights.w_lat * metrics["latency"]
            + weights.w_bw * metrics["bandwidth"]
            + weights.w_cmp * metrics["compute"]
            + weights.w_queue * metrics["queue"]
            + weights.w_cost * metrics["cost"]
        )
        return round(score, 6)

    def rank_candidates(
        self,
        normalized_pool: Dict[str, Dict[str, float]],
        weights: SLAWeights,
    ) -> List[Tuple[str, float]]:
        """Rank all candidates by composite score in ascending order (lower is better).
        Returns list of (node_id, composite_score).
        """
        scores: List[Tuple[str, float]] = []
        for node_id, metrics in normalized_pool.items():
            score = self.calculate_score(metrics, weights)
            scores.append((node_id, score))

        # Sort deterministically: score ascending, then node_id lexicographically for tie-breaking
        scores.sort(key=lambda item: (item[1], item[0]))
        return scores
