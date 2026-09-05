"""SLA weight profiles configuration and validation.
Supports real_time, interactive, and batch SLA classes.
"""

from __future__ import annotations

from typing import Dict
from pydantic import BaseModel, Field, model_validator
from contracts.models import SLAClass


class SLAWeights(BaseModel):
    """Normalized weight factors for multi-criteria placement scoring.
    All weights must be non-negative and sum to 1.0 (with slight float tolerance).
    """
    w_lat: float = Field(..., ge=0.0, le=1.0, description="Weight for normalized latency")
    w_bw: float = Field(..., ge=0.0, le=1.0, description="Weight for normalized inverse bandwidth")
    w_cmp: float = Field(..., ge=0.0, le=1.0, description="Weight for normalized compute utilization")
    w_queue: float = Field(..., ge=0.0, le=1.0, description="Weight for normalized queue depth")
    w_cost: float = Field(..., ge=0.0, le=1.0, description="Weight for normalized cost per unit")

    @model_validator(mode="after")
    def validate_sum(self) -> "SLAWeights":
        total = self.w_lat + self.w_bw + self.w_cmp + self.w_queue + self.w_cost
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"SLA weights must sum to 1.0, got {total:.4f}")
        return self

    def to_dict(self) -> Dict[str, float]:
        return {
            "latency": self.w_lat,
            "bandwidth": self.w_bw,
            "compute": self.w_cmp,
            "queue": self.w_queue,
            "cost": self.w_cost,
        }


# Default profiles adhering strictly to specification
DEFAULT_SLA_PROFILES: Dict[SLAClass, SLAWeights] = {
    SLAClass.REAL_TIME: SLAWeights(
        w_lat=0.50,
        w_bw=0.15,
        w_cmp=0.15,
        w_queue=0.15,
        w_cost=0.05,
    ),
    SLAClass.INTERACTIVE: SLAWeights(
        w_lat=0.35,
        w_bw=0.15,
        w_cmp=0.20,
        w_queue=0.15,
        w_cost=0.15,
    ),
    SLAClass.BATCH: SLAWeights(
        w_lat=0.10,
        w_bw=0.10,
        w_cmp=0.20,
        w_queue=0.20,
        w_cost=0.40,
    ),
}


def get_sla_weights(sla_class: SLAClass, custom_profiles: Dict[SLAClass, SLAWeights] | None = None) -> SLAWeights:
    """Retrieve weights for an SLA class from custom profiles or defaults."""
    if custom_profiles and sla_class in custom_profiles:
        return custom_profiles[sla_class]
    if sla_class in DEFAULT_SLA_PROFILES:
        return DEFAULT_SLA_PROFILES[sla_class]
    return DEFAULT_SLA_PROFILES[SLAClass.INTERACTIVE]
