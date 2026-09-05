"""Configuration loader supporting YAML files and environment variable overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List
import yaml

from contracts.models import SLAClass
from contracts.sla_profiles import SLAWeights

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def load_yaml_config(file_path: Path | str) -> Dict[str, Any]:
    """Safely load a YAML configuration file."""
    path = Path(file_path)
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_sla_weights_from_file(config_path: Path | str | None = None) -> Dict[SLAClass, SLAWeights]:
    """Load configurable SLA weight profiles."""
    path = config_path or (CONFIG_DIR / "sla_weights.yaml")
    data = load_yaml_config(path)
    profiles: Dict[SLAClass, SLAWeights] = {}

    profiles_data = data.get("profiles", {})
    for sla_key, weights_dict in profiles_data.items():
        try:
            sla_class = SLAClass(sla_key)
            profiles[sla_class] = SLAWeights(**weights_dict)
        except Exception:
            continue
    return profiles


def load_static_routing_policy(config_path: Path | str | None = None) -> Dict[str, Any]:
    """Load pre-cached static fallback routing policy."""
    path = config_path or (CONFIG_DIR / "static_routing.yaml")
    data = load_yaml_config(path)
    return {
        "default_fallback_chain": data.get("default_fallback_chain", ["edge-frankfurt-1", "cloud-aws-eu-central"]),
        "residency_overrides": data.get("residency_overrides", {}),
    }
