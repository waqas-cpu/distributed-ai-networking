"""Network Gateway Service for AI Workload Orchestration Platform.
Provides client authentication, ingress validation, static fail-open routing, and observability endpoints.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from common.errors import (
    ConstraintViolationError,
    DecisionEngineUnavailableError,
    FallbackExhaustionError,
    OrchestrationError,
)
from common.logger import get_logger
from contracts.models import (
    AuditEvent,
    ErrorResponse,
    HealthCheckResponse,
    NodeTelemetrySnapshot,
    SLAClass,
    TaskRequest,
    ExecutionResult,
    ExecutionStatus,
    NodeClass,
)
from contracts.sla_profiles import SLAWeights
from decision_engine.engine import DecisionEngine
from results_aggregator.aggregator import ResultsAggregator
from scheduler.dispatcher import TaskScheduler
from telemetry.store import TelemetryStore
from prometheus_client import make_asgi_app, Histogram, Counter
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

logger = get_logger("gateway", component="gateway")

PLACEMENT_LATENCY = Histogram(
    "ai_orchestration_placement_latency_ms",
    "Time taken by the Decision Engine to score and select a candidate node",
    ["sla_class"]
)

FALLBACK_EXHAUSTION = Counter(
    "ai_orchestration_fallback_exhaustion_total",
    "Number of times a task failed to execute across the entire fallback chain",
    ["sla_class"]
)


def create_gateway_app(
    telemetry_store: TelemetryStore,
    decision_engine: DecisionEngine,
    scheduler: TaskScheduler,
    aggregator: ResultsAggregator,
) -> FastAPI:
    """Factory creating configured Gateway FastAPI application."""
    app = FastAPI(
        title="AI Workload Orchestration Gateway",
        version="1.0.0",
        description="Edge/Cloud hybrid inference orchestration platform gateway.",
    )

    # State flag to simulate Decision Engine outages for testing fail-open behavior
    app.state.decision_engine_enabled = True
    
    import os
    app.state.shadow_mode_enabled = os.environ.get("SHADOW_MODE", "false").lower() == "true"
    
    # Mount Prometheus metrics endpoint
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            f"{request.method} {request.url.path} completed with status {response.status_code} in {duration_ms:.2f}ms",
            extra={"duration_ms": duration_ms, "status_code": response.status_code}
        )
        return response

    @app.get("/v1/health", response_model=HealthCheckResponse)
    async def health_check() -> HealthCheckResponse:
        """Health check endpoint for Kubernetes liveness/readiness probes."""
        snapshots = telemetry_store.get_all_snapshots()
        de_status = "healthy" if app.state.decision_engine_enabled else "disabled"
        return HealthCheckResponse(
            status="healthy",
            service_name="network-gateway",
            dependencies={
                "decision_engine": de_status,
                "telemetry_nodes_count": str(len(snapshots)),
                "scheduler_workers_count": str(len(scheduler.node_targets)),
            },
        )

    @app.get("/v1/telemetry/nodes", response_model=List[NodeTelemetrySnapshot])
    async def get_node_telemetry() -> List[NodeTelemetrySnapshot]:
        """Inspect current cluster node telemetry state."""
        return telemetry_store.get_all_snapshots()

    @app.post("/v1/telemetry/snapshot", status_code=status.HTTP_201_CREATED)
    async def record_telemetry(snapshot: NodeTelemetrySnapshot) -> Dict[str, str]:
        """Ingest node agent telemetry snapshot."""
        telemetry_store.record_snapshot(snapshot)
        return {"status": "recorded", "node_id": snapshot.node_id}

    @app.post("/v1/tasks/infer")
    async def submit_inference_task(task: TaskRequest) -> Dict[str, Any]:
        """Primary inference ingress endpoint."""
        span = tracer.start_span("submit_inference_task")
        span.set_attribute("task.id", task.task_id)
        span.set_attribute("task.sla_class", task.sla_class.value)
        span.set_attribute("task.model_id", task.model_id)
        
        gateway_observed_rtt_ms = 5.0  # Simulated gateway-ingress latency

        # Step 1: Query telemetry store for active candidate nodes
        candidates = telemetry_store.get_all_snapshots()

        # Step 2: Placement decision with fail-open guarantee
        decision = None
        shadow_decision = None
        start_time = time.perf_counter()
        
        # Always run real engine to shadow the scoring
        try:
            shadow_decision = decision_engine.evaluate_placement(task, candidates)
        except Exception as ex:
            logger.error(
                f"Decision Engine evaluation threw error: {str(ex)}",
                extra={"task_id": task.task_id}
            )

        if app.state.shadow_mode_enabled:
            logger.info("SHADOW_MODE active: using static policy for actual routing", extra={"task_id": task.task_id})
            decision = decision_engine.get_static_fallback_decision(task, reason="shadow_mode_active")
            
            # Log shadow audit event manually
            if shadow_decision:
                shadow_event = AuditEvent(
                    task_id=task.task_id,
                    timestamp=time.time(),
                    decision=shadow_decision,
                    execution=ExecutionResult(task_id=task.task_id, node_id="none", node_class=NodeClass.EDGE, status=ExecutionStatus.SUCCESS, execution_time_ms=0.0, output={}, error="", cached=False, idempotency_key=""),
                    is_shadow_mode=True
                )
                aggregator._audit_log.append(shadow_event)
        elif not app.state.decision_engine_enabled:
            logger.warning(
                "Decision engine is marked disabled/unavailable; failing open to static policy",
                extra={"task_id": task.task_id}
            )
            decision = decision_engine.get_static_fallback_decision(
                task, reason="decision_engine_service_offline"
            )
        else:
            if shadow_decision:
                decision = shadow_decision
            else:
                logger.error("Decision engine evaluation failed, triggering fail-open static routing", extra={"task_id": task.task_id})
                decision = decision_engine.get_static_fallback_decision(task, reason="decision_engine_error")
                
        # Record placement latency
        PLACEMENT_LATENCY.labels(sla_class=task.sla_class.value).observe((time.perf_counter() - start_time) * 1000.0)

        # Step 3: Dispatch task via TaskScheduler along candidate fallback chain
        try:
            with tracer.start_as_current_span("scheduler_dispatch") as dispatch_span:
                execution_result, fallback_activated, attempts = scheduler.dispatch(task, decision)
                dispatch_span.set_attribute("fallback_activated", fallback_activated)
                dispatch_span.set_attribute("attempts", attempts)
        except FallbackExhaustionError as fee:
            FALLBACK_EXHAUSTION.labels(sla_class=task.sla_class.value).inc()
            logger.critical(
                f"Scheduler exhausted fallback chain for task {task.task_id}: {fee.message}",
                extra={"task_id": task.task_id}
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=ErrorResponse(
                    error_code="FALLBACK_CHAIN_EXHAUSTED",
                    message=fee.message,
                    task_id=task.task_id,
                    details=fee.details,
                ).model_dump(),
            )
        except Exception as ex:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=ErrorResponse(
                    error_code="EXECUTION_FAILURE",
                    message=f"Execution failed: {str(ex)}",
                    task_id=task.task_id,
                ).model_dump(),
            )

        # Step 4: Aggregate result, normalize envelope, emit audit record
        response_payload = aggregator.aggregate(
            task_id=task.task_id,
            decision=decision,
            execution=execution_result,
            fallback_activated=fallback_activated,
            attempts=attempts,
            gateway_observed_rtt_ms=gateway_observed_rtt_ms,
        )

        span.set_attribute("task.selected_node", decision.chosen_node)
        span.set_attribute("task.execution_latency", execution_result.execution_time_ms)
        span.set_attribute("task.decision_latency", decision.decision_latency_ms)
        span.set_attribute("task.fallback_attempts", attempts)
        span.set_attribute("task.status", response_payload["status"])
        span.end()

        return response_payload

    @app.get("/v1/audit/events", response_model=List[AuditEvent])
    async def get_audit_events(task_id: Optional[str] = None) -> List[AuditEvent]:
        """Query immutable placement and execution audit log."""
        return aggregator.get_audit_trail(task_id)

    @app.post("/v1/admin/sla-weights")
    async def update_sla_weights(sla_class: SLAClass, weights: SLAWeights) -> Dict[str, Any]:
        """Dynamic hot-reloading of SLA weight profiles."""
        decision_engine.update_sla_profiles({sla_class: weights})
        return {"status": "updated", "sla_class": sla_class.value, "weights": weights.to_dict()}

    return app
