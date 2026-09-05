"""Stateless Decision Engine for AI Workload Placement.
Evaluates candidate nodes in sub-10ms latency budgets using multi-criteria normalized scoring.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional
from common.errors import ConstraintViolationError
from common.logger import get_logger
from common.config import load_static_routing_policy
from contracts.models import NodeTelemetrySnapshot, PlacementDecision, SLAClass, TaskRequest
from contracts.sla_profiles import SLAWeights, get_sla_weights
from decision_engine.filter import ConstraintFilter
from decision_engine.normalizer import CandidateNormalizer
from decision_engine.scorer import WeightedScorer

logger = get_logger("decision_engine", component="decision_engine")


class DecisionEngine:
    """Core placement decision orchestrator."""

    def __init__(
        self,
        custom_sla_profiles: Dict[SLAClass, SLAWeights] | None = None,
        filter_engine: ConstraintFilter | None = None,
        normalizer: CandidateNormalizer | None = None,
        scorer: WeightedScorer | None = None,
        ema_alpha: float = 0.5,
        challenger_margin: float = 0.10,
    ) -> None:
        self.custom_sla_profiles = custom_sla_profiles or {}
        self.filter_engine = filter_engine or ConstraintFilter()
        self.normalizer = normalizer or CandidateNormalizer()
        self.scorer = scorer or WeightedScorer()
        self.ema_alpha = ema_alpha
        self.challenger_margin = challenger_margin
        self._node_ema_scores: Dict[str, float] = {}
        self._static_policy = load_static_routing_policy()

    def update_sla_profiles(self, profiles: Dict[SLAClass, SLAWeights]) -> None:
        """Hot-reload SLA weight profiles without restarting."""
        self.custom_sla_profiles.update(profiles)
        logger.info("Updated SLA profiles in Decision Engine", extra={"updated_profiles": list(profiles.keys())})

    def get_static_fallback_decision(self, task: TaskRequest, reason: str = "fail_open_triggered") -> PlacementDecision:
        """Construct a deterministic static fallback decision when normal scoring cannot proceed."""
        start_time = time.perf_counter()
        chain = list(self._static_policy.get("default_fallback_chain", []))

        # Check residency override if present
        if task.data_residency and task.data_residency.lower() in self._static_policy.get("residency_overrides", {}):
            chain = list(self._static_policy["residency_overrides"][task.data_residency.lower()])

        chosen = chain[0] if chain else "cloud-default-fallback"
        runner_up = chain[1] if len(chain) > 1 else None
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        weights = get_sla_weights(task.sla_class, self.custom_sla_profiles)

        logger.warning(
            f"Failing open to static policy for task {task.task_id}: chosen={chosen}, reason={reason}",
            extra={"task_id": task.task_id, "node_id": chosen, "reason": reason}
        )

        return PlacementDecision(
            task_id=task.task_id,
            chosen_node=chosen,
            chosen_score=1.0,
            runner_up_node=runner_up,
            runner_up_score=1.0 if runner_up else None,
            weights_used=weights.to_dict(),
            decision_latency_ms=round(elapsed_ms, 3),
            fallback_chain=chain,
            filtered_out_nodes={"system": reason},
            used_fallback_policy=True,
        )

    def evaluate_placement(
        self,
        task: TaskRequest,
        candidates: List[NodeTelemetrySnapshot],
        incumbent_node_id: Optional[str] = None,
    ) -> PlacementDecision:
        """Evaluate candidate nodes and produce a ranked placement decision.
        Target overhead: p99 < 10ms.
        """
        start_time = time.perf_counter()

        # Step 1: Filter candidates by hard constraints
        surviving, rejected = self.filter_engine.filter_candidates(task, candidates)

        if not surviving:
            logger.warning(
                f"No candidates satisfied hard constraints for task {task.task_id}",
                extra={"task_id": task.task_id, "rejected": rejected}
            )
            # Try fail-open static policy if available
            return self.get_static_fallback_decision(task, reason="all_candidates_failed_hard_constraints")

        # Step 2: Retrieve active SLA weights
        weights = get_sla_weights(task.sla_class, self.custom_sla_profiles)

        # Step 3: Min-Max normalize across candidate pool
        normalized_pool = self.normalizer.normalize_candidates(surviving)

        # Step 4: Multi-criteria weighted scoring
        ranked_scores = self.scorer.rank_candidates(normalized_pool, weights)

        # Step 5: Anti-flapping hysteresis for incumbent node (if specified)
        chosen_node = ranked_scores[0][0]
        chosen_score = ranked_scores[0][1]

        if incumbent_node_id and incumbent_node_id != chosen_node:
            incumbent_score = next((score for nid, score in ranked_scores if nid == incumbent_node_id), None)
            if incumbent_score is not None:
                # If challenger does not beat incumbent by challenger_margin, keep incumbent
                # Note: lower is better, so challenger must be lower than incumbent * (1 - margin)
                required_threshold = incumbent_score * (1.0 - self.challenger_margin)
                if chosen_score > required_threshold:
                    # Retain incumbent
                    chosen_node = incumbent_node_id
                    chosen_score = incumbent_score

        # Update EMA score tracking
        for nid, score in ranked_scores:
            if nid in self._node_ema_scores:
                self._node_ema_scores[nid] = (
                    self.ema_alpha * score + (1.0 - self.ema_alpha) * self._node_ema_scores[nid]
                )
            else:
                self._node_ema_scores[nid] = score

        # Step 6: Construct ranked fallback chain (top 3 candidates)
        fallback_chain = [nid for nid, _ in ranked_scores[:3]]

        runner_up_node = ranked_scores[1][0] if len(ranked_scores) > 1 else None
        runner_up_score = ranked_scores[1][1] if len(ranked_scores) > 1 else None

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        decision = PlacementDecision(
            task_id=task.task_id,
            chosen_node=chosen_node,
            chosen_score=chosen_score,
            runner_up_node=runner_up_node,
            runner_up_score=runner_up_score,
            weights_used=weights.to_dict(),
            decision_latency_ms=round(elapsed_ms, 3),
            fallback_chain=fallback_chain,
            filtered_out_nodes=rejected,
            used_fallback_policy=False,
        )

        logger.info(
            f"Placement decision computed for task {task.task_id}: {chosen_node} "
            f"(score={chosen_score:.4f}, latency={elapsed_ms:.2f}ms)",
            extra={
                "task_id": task.task_id,
                "node_id": chosen_node,
                "score": chosen_score,
                "decision_latency_ms": elapsed_ms,
                "sla_class": task.sla_class.value,
            }
        )

        return decision
