"""Software and Model Supply-Chain Assurance Module.

Implements immutable digest verification, SLSA/in-toto provenance attestations,
cryptographic artifact signing (Cosign/KMS style with Ed25519), etcd authoritative
model registry, revocation checks, and strict pre-execution policy enforcement.
"""

from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Optional, Tuple
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from common.errors import ArtifactVerificationError
from common.logger import get_logger
from common.state import SimulatedEtcdProvider
from contracts.models import (
    ApprovedArtifactRecord,
    ArtifactProvenance,
    SupplyChainPolicy,
)

logger = get_logger("common.supply_chain")

# Regex for immutable digest: sha256:64hex
DIGEST_REGEX = re.compile(r"^sha256:[a-f0-9]{64}$", re.IGNORECASE)


def is_immutable_digest(digest: str) -> bool:
    """Validate that the artifact reference is an immutable SHA-256 digest, not a mutable tag."""
    if not digest or not isinstance(digest, str):
        return False
    return bool(DIGEST_REGEX.match(digest.strip()))


def canonical_provenance_bytes(provenance: ArtifactProvenance) -> bytes:
    """Deterministic, canonical JSON serialization of provenance for signature generation/verification."""
    # Ensure stable dictionary ordering
    data = {
        "artifact_name": provenance.artifact_name,
        "build_timestamp": provenance.build_timestamp,
        "builder_identity": provenance.builder_identity,
        "commit_sha": provenance.commit_sha,
        "digest": provenance.digest,
        "sbom_digest": provenance.sbom_digest,
        "source_repo": provenance.source_repo,
        "vulnerabilities_summary": dict(sorted(provenance.vulnerabilities_summary.items())),
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def create_provenance(
    artifact_name: str,
    digest: str,
    builder_identity: str = "spiffe://distributed-ai.local/ci-builder",
    commit_sha: str = "c0ffee1234567890abcdef1234567890abcdef12",
    sbom_digest: str = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    vulnerabilities_summary: Optional[Dict[str, int]] = None,
    source_repo: str = "https://github.com/distributed-ai/orchestration",
) -> ArtifactProvenance:
    """Generate a provenance attestation for a model or container artifact."""
    if not is_immutable_digest(digest):
        raise ArtifactVerificationError(
            f"Cannot create provenance: digest '{digest}' is not a valid immutable sha256 digest",
            artifact_id=artifact_name,
            digest=digest,
        )

    return ArtifactProvenance(
        artifact_name=artifact_name,
        digest=digest.lower(),
        builder_identity=builder_identity,
        source_repo=source_repo,
        commit_sha=commit_sha,
        build_timestamp=time.time(),
        sbom_digest=sbom_digest.lower(),
        vulnerabilities_summary=vulnerabilities_summary or {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0},
    )


def sign_artifact_provenance(
    provenance: ArtifactProvenance,
    signing_key: ed25519.Ed25519PrivateKey,
    key_id: str = "ci-release-signer-1",
) -> str:
    """Sign the canonical provenance bytes using an Ed25519 key (Cosign/KMS release signer)."""
    canonical_bytes = canonical_provenance_bytes(provenance)
    sig_bytes = signing_key.sign(canonical_bytes)
    return sig_bytes.hex()


def verify_artifact_signature(
    provenance: ArtifactProvenance,
    signature_hex: str,
    public_key_pem: str,
) -> bool:
    """Verify the signature against the canonical provenance using the builder's public key."""
    try:
        canonical_bytes = canonical_provenance_bytes(provenance)
        sig_bytes = bytes.fromhex(signature_hex)
        pub_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        pub_key.verify(sig_bytes, canonical_bytes)
        return True
    except Exception as ex:
        logger.warning(f"Signature verification failed for {provenance.artifact_name}: {ex}")
        return False


def get_supply_chain_policy(etcd: Optional[SimulatedEtcdProvider] = None) -> SupplyChainPolicy:
    """Fetch the active supply chain policy from etcd or return default."""
    etcd = etcd or SimulatedEtcdProvider()
    raw = etcd.get("/distributed-ai/policies/supply-chain")
    if raw:
        try:
            return SupplyChainPolicy.model_validate_json(raw)
        except Exception as ex:
            logger.error(f"Failed to parse supply chain policy from etcd: {ex}")
    return SupplyChainPolicy()


def set_supply_chain_policy(policy: SupplyChainPolicy, etcd: Optional[SimulatedEtcdProvider] = None) -> None:
    """Store active supply chain policy into authoritative control plane."""
    etcd = etcd or SimulatedEtcdProvider()
    etcd.put("/distributed-ai/policies/supply-chain", policy.model_dump_json())


def register_approved_model(
    model_id: str,
    digest: str,
    provenance: ArtifactProvenance,
    signing_key: ed25519.Ed25519PrivateKey,
    key_id: str = "ci-release-signer-1",
    etcd: Optional[SimulatedEtcdProvider] = None,
) -> ApprovedArtifactRecord:
    """Register and sign an approved model in authoritative state (etcd)."""
    etcd = etcd or SimulatedEtcdProvider()

    # Verify digest formatting
    if not is_immutable_digest(digest):
        raise ArtifactVerificationError(
            f"Cannot register model: digest '{digest}' is not an immutable digest",
            artifact_id=model_id,
            digest=digest,
        )

    # Store signing key PEM if not present
    pubkey_pem = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    etcd.put(f"/distributed-ai/ci/keys/{key_id}", pubkey_pem)

    sig_hex = sign_artifact_provenance(provenance, signing_key, key_id)

    record = ApprovedArtifactRecord(
        model_id=model_id,
        digest=digest.lower(),
        provenance=provenance,
        signature_algorithm="Ed25519",
        signature=sig_hex,
        signing_key_id=key_id,
        revoked=False,
    )

    etcd.put(f"/distributed-ai/artifacts/models/{model_id}", record.model_dump_json())
    logger.info(f"Registered approved model '{model_id}' with digest {digest}")
    return record


def revoke_artifact_digest(
    digest: str,
    reason: str = "Security advisory or compromise",
    etcd: Optional[SimulatedEtcdProvider] = None,
) -> None:
    """Mark an artifact digest as revoked in authoritative state."""
    etcd = etcd or SimulatedEtcdProvider()
    norm_digest = digest.lower()
    revocation_payload = {
        "digest": norm_digest,
        "revocation_time": time.time(),
        "reason": reason,
    }
    etcd.put(f"/distributed-ai/revocations/artifacts/{norm_digest}", json.dumps(revocation_payload))
    logger.warning(f"Artifact digest {norm_digest} REVOKED: {reason}")


def is_digest_revoked(digest: str, etcd: Optional[SimulatedEtcdProvider] = None) -> bool:
    """Check if an artifact digest is in the control plane revocation registry."""
    etcd = etcd or SimulatedEtcdProvider()
    return etcd.get(f"/distributed-ai/revocations/artifacts/{digest.lower()}") is not None


def verify_artifact_for_execution(
    model_id: str,
    digest: Optional[str] = None,
    etcd: Optional[SimulatedEtcdProvider] = None,
) -> ApprovedArtifactRecord:
    """Enforce pre-execution supply chain verification at the compute node.

    Evaluates:
    1. Immutable digest requirement (rejects mutable tag-only references).
    2. Model registration in authoritative control plane.
    3. Digest matching between task specification and approved registry.
    4. Revocation status check.
    5. Cryptographic signature and provenance verification.
    6. Supply chain policy admission (allowed builders, vulnerability thresholds).

    Raises ArtifactVerificationError if any check fails (fail closed).
    """
    etcd = etcd or SimulatedEtcdProvider()
    policy = get_supply_chain_policy(etcd)

    # 1. Require immutable digest if policy demands
    if policy.require_immutable_digest:
        if not digest or not is_immutable_digest(digest):
            raise ArtifactVerificationError(
                f"Execution rejected: model reference '{digest}' is not an immutable digest (mutable tags disallowed)",
                artifact_id=model_id,
                digest=digest,
            )

    # 2. Fetch authoritative model record
    raw_record = etcd.get(f"/distributed-ai/artifacts/models/{model_id}")
    if not raw_record:
        raise ArtifactVerificationError(
            f"Execution rejected: model '{model_id}' is not an approved registered artifact",
            artifact_id=model_id,
            digest=digest,
        )

    try:
        record = ApprovedArtifactRecord.model_validate_json(raw_record)
    except Exception as ex:
        raise ArtifactVerificationError(
            f"Execution rejected: corrupted approval record for '{model_id}': {ex}",
            artifact_id=model_id,
            digest=digest,
        )

    # 3. Check digest match
    if digest and record.digest.lower() != digest.lower():
        raise ArtifactVerificationError(
            f"Execution rejected: requested digest '{digest}' does not match approved digest '{record.digest}'",
            artifact_id=model_id,
            digest=digest,
            details={"approved_digest": record.digest, "requested_digest": digest},
        )

    # 4. Check revocation
    if record.revoked or is_digest_revoked(record.digest, etcd):
        raise ArtifactVerificationError(
            f"Execution rejected: artifact digest '{record.digest}' has been revoked",
            artifact_id=model_id,
            digest=record.digest,
        )

    # 5. Check signature
    if policy.require_signature:
        pubkey_pem = etcd.get(f"/distributed-ai/ci/keys/{record.signing_key_id}")
        if not pubkey_pem:
            raise ArtifactVerificationError(
                f"Execution rejected: signing key '{record.signing_key_id}' not found in control plane",
                artifact_id=model_id,
                digest=record.digest,
            )

        if not verify_artifact_signature(record.provenance, record.signature, pubkey_pem):
            raise ArtifactVerificationError(
                f"Execution rejected: signature verification failed for model '{model_id}'",
                artifact_id=model_id,
                digest=record.digest,
            )

    # 6. Policy checks: Builder identity
    if policy.allowed_builders and record.provenance.builder_identity not in policy.allowed_builders:
        raise ArtifactVerificationError(
            f"Execution rejected: builder identity '{record.provenance.builder_identity}' is not permitted by policy",
            artifact_id=model_id,
            digest=record.digest,
            details={"builder": record.provenance.builder_identity, "allowed": policy.allowed_builders},
        )

    # 7. Policy checks: Vulnerability thresholds
    vulns = record.provenance.vulnerabilities_summary
    crit_count = vulns.get("CRITICAL", 0)
    high_count = vulns.get("HIGH", 0)

    if crit_count > policy.max_allowed_critical_vulns:
        raise ArtifactVerificationError(
            f"Execution rejected: artifact contains {crit_count} CRITICAL vulnerabilities (max allowed: {policy.max_allowed_critical_vulns})",
            artifact_id=model_id,
            digest=record.digest,
            details={"vulnerabilities": vulns},
        )

    if high_count > policy.max_allowed_high_vulns:
        raise ArtifactVerificationError(
            f"Execution rejected: artifact contains {high_count} HIGH vulnerabilities (max allowed: {policy.max_allowed_high_vulns})",
            artifact_id=model_id,
            digest=record.digest,
            details={"vulnerabilities": vulns},
        )

    logger.debug(f"Pre-execution supply chain verification passed for {model_id} ({record.digest})")
    return record
