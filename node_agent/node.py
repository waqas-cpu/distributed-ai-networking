"""Simulated Edge and Cloud compute nodes with telemetry reporting."""

from __future__ import annotations

import time
import base64
from contracts.models import HealthStatus, NodeClass, NodeTelemetrySnapshot, AssuranceLevel, HardwareAttestation
from common.config import PqcConfig
from common.crypto import OqsSignatureProvider, OQS_AVAILABLE
import logging
from typing import Dict, List, Optional
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger("node_agent")


class SimulatedNode:
    """Represents an edge or cloud node capable of executing inference tasks and reporting telemetry."""

    def __init__(
        self,
        node_id: str,
        node_class: NodeClass,
        base_rtt_ms: float,
        bandwidth_mbps: float,
        cost_per_1k_usd: float,
        data_residency_zones: List[str],
        cpu_util_pct: float = 20.0,
        gpu_util_pct: float = 30.0,
        queue_depth: int = 0,
        health: HealthStatus = HealthStatus.HEALTHY,
        assurance_level: AssuranceLevel = AssuranceLevel.STANDARD,
    ) -> None:
        self.node_id = node_id
        self.node_class = node_class
        self.base_rtt_ms = base_rtt_ms
        self.bandwidth_mbps = bandwidth_mbps
        self.cost_per_1k_usd = cost_per_1k_usd
        self.data_residency_zones = data_residency_zones
        self.cpu_util_pct = cpu_util_pct
        self.gpu_util_pct = gpu_util_pct
        self.queue_depth = queue_depth
        self.health = health
        self.assurance_level = assurance_level
        self.last_heartbeat_time = time.time()
        self.is_offline = False
        self.fail_execution = False
        
        # Phase 4/5: Node signing identity
        self.signing_key = ed25519.Ed25519PrivateKey.generate()
        self.public_key_pem = self.signing_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')
        
        # Phase 8: PQC Setup
        self.pqc_config = PqcConfig.load()
        self.dual_required = self.pqc_config.get("PQC_MESSAGE_SIGNATURE_POLICY") == "dual_required"
        self.pq_signer = None
        if self.dual_required:
            if not OQS_AVAILABLE:
                logger.critical(f"Node {self.node_id}: dual_required signature policy requested but OQS provider is unavailable")
            else:
                self.pq_signer = OqsSignatureProvider(self.pqc_config.get("PQC_SIGNATURE", "ML-DSA-65"))
                self.pq_pubkey, self.pq_privkey = self.pq_signer.generate_keypair()
        
    def get_attestation_evidence(self) -> Optional[HardwareAttestation]:
        """Return dummy TPM/TEE evidence if node is HIGH_ASSURANCE."""
        if self.assurance_level != AssuranceLevel.HIGH_ASSURANCE:
            return None
        
        # In a real system, this interacts with /dev/tpm0 or TEE interface
        dummy_quote = base64.b64encode(b"simulated_tpm2_quote_data").decode('utf-8')
        dummy_sig = "dummy_signature_over_quote"
        return HardwareAttestation(
            evidence_type="tpm2_quote",
            quote=dummy_quote,
            pcr_banks={"sha256": "0x123456..."},
            signature=dummy_sig
        )

    def emit_snapshot(self, gateway_observed_rtt_ms: Optional[float] = None) -> NodeTelemetrySnapshot:
        """Produce current telemetry snapshot."""
        now = time.time()
        heartbeat_age_ms = (now - self.last_heartbeat_time) * 1000.0

        return NodeTelemetrySnapshot(
            node_id=self.node_id,
            node_class=self.node_class,
            timestamp=now,
            rtt_ms=self.base_rtt_ms,
            bandwidth_available_mbps=self.bandwidth_mbps,
            cpu_util_pct=self.cpu_util_pct,
            gpu_util_pct=self.gpu_util_pct,
            queue_depth=self.queue_depth,
            cost_per_1k_inferences_usd=self.cost_per_1k_usd,
            health=self.health if not self.is_offline else HealthStatus.UNREACHABLE,
            last_heartbeat_age_ms=heartbeat_age_ms,
            data_residency_zones=self.data_residency_zones,
            gateway_observed_rtt_ms=gateway_observed_rtt_ms,
            assurance_level=self.assurance_level,
        )

    def heartbeat(self) -> None:
        """Update last heartbeat timestamp."""
        self.last_heartbeat_time = time.time()
