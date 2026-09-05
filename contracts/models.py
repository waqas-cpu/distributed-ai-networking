"""Strongly typed data contracts for AI Workload Orchestration Platform.
Defines Pydantic v2 schemas for all system boundaries.
"""

from __future__ import annotations

import os
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


def generate_uuidv7() -> str:
    """Generate a UUIDv7-compatible string formatted with timestamp prefix."""
    # 48 bits of unix timestamp in ms
    ms = int(time.time() * 1000)
    # 16 bits of version (7) + pseudo-random sequence
    rand_bytes = os.urandom(10)
    # Pack into standard UUID 8-4-4-4-12 hex format
    time_hex = f"{ms:012x}"
    p1 = time_hex[0:8]
    p2 = time_hex[8:12]
    # Set version 7 (0111xxxx -> 7x)
    p3 = f"7{rand_bytes[0:2].hex()[1:4]}"
    # Set variant (10xxxxxx -> 8..b)
    var_byte = (rand_bytes[2] & 0x3F) | 0x80
    p4 = f"{var_byte:02x}{rand_bytes[3:4].hex()}"
    p5 = rand_bytes[4:10].hex()
    return f"{p1}-{p2}-{p3}-{p4}-{p5}"


class SLAClass(str, Enum):
    REAL_TIME = "real_time"
    INTERACTIVE = "interactive"
    BATCH = "batch"


class WorkloadType(str, Enum):
    INFERENCE = "inference"
    STREAMING = "streaming"
    EMBEDDING = "embedding"


class NodeClass(str, Enum):
    EDGE = "edge"
    CLOUD = "cloud"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"


class TaskRequest(BaseModel):
    """Client-facing ingress task request contract."""
    task_id: str = Field(default_factory=generate_uuidv7, description="UUIDv7 unique task identifier")
    workload_type: WorkloadType = Field(default=WorkloadType.INFERENCE, description="Type of AI workload")
    model_id: str = Field(..., description="Target model identifier (e.g. vision-classifier-v3)")
    sla_class: SLAClass = Field(default=SLAClass.REAL_TIME, description="SLA performance tier")
    payload_ref: str = Field(..., description="URI or inline data representation of inference input")
    max_latency_ms: float = Field(default=150.0, ge=1.0, description="Max tolerable end-to-end latency in ms")
    data_residency: Optional[str] = Field(default="none", description="Hard residency requirement (e.g. eu-only, us-only, none)")
    idempotency_key: str = Field(..., min_length=1, description="Client-generated key preventing duplicate execution")


class NodeTelemetrySnapshot(BaseModel):
    """Telemetry snapshot reported by a node agent or observed by gateway."""
    node_id: str = Field(..., description="Unique node identifier (e.g. edge-frankfurt-1)")
    node_class: NodeClass = Field(..., description="Node classification: edge or cloud")
    timestamp: float = Field(default_factory=time.time, description="Epoch timestamp of snapshot")
    rtt_ms: float = Field(..., ge=0.0, description="Observed round trip latency to node in ms")
    bandwidth_available_mbps: float = Field(..., ge=0.001, description="Available bandwidth headroom in Mbps")
    cpu_util_pct: float = Field(..., ge=0.0, le=100.0, description="Current CPU utilization percentage (0-100)")
    gpu_util_pct: float = Field(..., ge=0.0, le=100.0, description="Current GPU utilization percentage (0-100)")
    queue_depth: int = Field(..., ge=0, description="Number of tasks currently enqueued on node")
    cost_per_1k_inferences_usd: float = Field(..., ge=0.0, description="Cost per 1,000 inferences in USD")
    health: HealthStatus = Field(default=HealthStatus.HEALTHY, description="Current node operational health")
    last_heartbeat_age_ms: float = Field(..., ge=0.0, description="Elapsed ms since last received heartbeat")
    data_residency_zones: List[str] = Field(default_factory=lambda: ["global"], description="Regions/zones this node satisfies (e.g. eu-only)")
    gateway_observed_rtt_ms: Optional[float] = Field(default=None, description="Independent RTT measured by the gateway")

    @property
    def compute_utilization(self) -> float:
        """Composite compute utilization (weighted towards GPU if available)."""
        return max(self.cpu_util_pct, self.gpu_util_pct)


class PlacementDecision(BaseModel):
    """Auditable placement decision output from the Decision Engine."""
    task_id: str = Field(..., description="Identifier of the task evaluated")
    chosen_node: str = Field(..., description="Node selected for primary execution")
    chosen_score: float = Field(..., description="Composite normalized score of the winner (lower is better)")
    runner_up_node: Optional[str] = Field(default=None, description="Second-ranked candidate node")
    runner_up_score: Optional[float] = Field(default=None, description="Composite score of the runner-up")
    weights_used: Dict[str, float] = Field(..., description="SLA weights applied in scoring")
    decision_latency_ms: float = Field(..., description="Time taken to score and select in milliseconds")
    fallback_chain: List[str] = Field(default_factory=list, description="Ordered candidate chain [1st, 2nd, 3rd]")
    filtered_out_nodes: Dict[str, str] = Field(default_factory=dict, description="Nodes excluded by hard constraints and reasons")
    used_fallback_policy: bool = Field(default=False, description="Whether static fallback routing was triggered")


class ExecutionRequest(BaseModel):
    """Internal task dispatch request sent to edge/cloud node worker."""
    task_id: str
    node_id: str
    model_id: str
    payload_ref: str
    idempotency_key: str
    timeout_ms: float = 5000.0


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"


class ExecutionResult(BaseModel):
    """Inference execution result returned by a node."""
    task_id: str
    node_id: str
    node_class: NodeClass
    status: ExecutionStatus
    execution_time_ms: float
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    cached: bool = False
    idempotency_key: str


class AuditEvent(BaseModel):
    """Immutable audit record persisted for governance, tracing, and compliance."""
    event_id: str = Field(default_factory=generate_uuidv7)
    task_id: str
    timestamp: float = Field(default_factory=time.time)
    decision: PlacementDecision
    execution: ExecutionResult
    fallback_activated: bool = False
    attempts: int = 1
    gateway_rtt_observed_ms: Optional[float] = None
    is_shadow_mode: bool = False


class NodeRegistration(BaseModel):
    """Node registration payload when joining the cluster."""
    node_id: str
    node_class: NodeClass
    supported_models: List[str]
    data_residency_zones: List[str]
    hardware_specs: Dict[str, Any] = Field(default_factory=dict)
    auth_token: str


class HealthCheckResponse(BaseModel):
    """System health check envelope."""
    status: str
    service_name: str
    timestamp: float = Field(default_factory=time.time)
    version: str = "1.0.0"
    dependencies: Dict[str, str] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standardized error envelope."""
    error_code: str
    message: str
    task_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
