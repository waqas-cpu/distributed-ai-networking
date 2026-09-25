"""Unit and adversarial tests for Software and Model Supply-Chain Assurance (Phase 7).

Verifies:
- Immutable digest requirement (rejects mutable tags like 'latest')
- SLSA/in-toto provenance attestation generation & canonical serialization
- Ed25519 artifact signature creation & verification (Cosign/KMS model)
- Pre-execution admission policy enforcement
- Revocation registry checks
- Tampered signature & digest detection
- Policy threshold checks (builder identities, critical vulnerabilities)
- Inclusion of verified model digest in ExecutionResult and AuditEvent
"""

import pytest
import time
from cryptography.hazmat.primitives.asymmetric import ed25519

from common.errors import ArtifactVerificationError
from common.state import SimulatedEtcdProvider
from common.supply_chain import (
    canonical_provenance_bytes,
    create_provenance,
    get_supply_chain_policy,
    is_immutable_digest,
    register_approved_model,
    revoke_artifact_digest,
    set_supply_chain_policy,
    sign_artifact_provenance,
    verify_artifact_for_execution,
    verify_artifact_signature,
)
from contracts.models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    NodeClass,
    SupplyChainPolicy,
)
from node_agent.node import SimulatedNode
from node_agent.worker import InferenceWorker


@pytest.fixture
def clean_etcd():
    etcd = SimulatedEtcdProvider()
    etcd.clear()
    yield etcd
    etcd.clear()


@pytest.fixture
def signer_keys():
    signing_key = ed25519.Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    pubkey_pem = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return signing_key, pubkey_pem


def test_immutable_digest_validation():
    """Verify that immutable SHA-256 digests are accepted and mutable tags are rejected."""
    valid_digest = "sha256:4a3b84175317b6a1e3b5e40854378f56193d56a31c5040f7d5440798e4f55e09"
    assert is_immutable_digest(valid_digest) is True
    assert is_immutable_digest("sha256:" + "a" * 64) is True

    # Reject mutable tags
    assert is_immutable_digest("latest") is False
    assert is_immutable_digest("v1.0.0") is False
    assert is_immutable_digest("vision:prod") is False
    assert is_immutable_digest("sha256:short") is False
    assert is_immutable_digest("") is False
    assert is_immutable_digest(None) is False


def test_provenance_signature_and_verification(signer_keys):
    """Verify that provenance can be canonically signed and verified, and tampering is detected."""
    signing_key, pubkey_pem = signer_keys
    digest = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
    
    provenance = create_provenance(
        artifact_name="resnet-50",
        digest=digest,
        builder_identity="spiffe://distributed-ai.local/ci-builder",
        commit_sha="c0ffee1234567890abcdef1234567890abcdef12",
        sbom_digest="sha256:2222222222222222222222222222222222222222222222222222222222222222",
    )

    sig_hex = sign_artifact_provenance(provenance, signing_key)
    assert len(sig_hex) == 128  # 64 bytes in hex

    # Verify signature
    assert verify_artifact_signature(provenance, sig_hex, pubkey_pem) is True

    # Tampering: modify a field in provenance
    tampered_provenance = provenance.model_copy(update={"commit_sha": "attacker1234567890abcdef1234567890abcdef"})
    assert verify_artifact_signature(tampered_provenance, sig_hex, pubkey_pem) is False

    # Tampering: wrong public key
    other_key = ed25519.Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    other_pubkey_pem = other_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    assert verify_artifact_signature(provenance, sig_hex, other_pubkey_pem) is False


def test_approved_model_registration_and_execution_pass(clean_etcd, signer_keys):
    """Verify that an approved model passes pre-execution verification on the worker."""
    signing_key, pubkey_pem = signer_keys
    model_id = "defect-detector-v1"
    digest = "sha256:abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd"

    provenance = create_provenance(
        artifact_name=model_id,
        digest=digest,
        builder_identity="spiffe://distributed-ai.local/ci-builder",
        commit_sha="1234567890abcdef1234567890abcdef12345678",
        sbom_digest="sha256:9999999999999999999999999999999999999999999999999999999999999999",
    )

    register_approved_model(
        model_id=model_id,
        digest=digest,
        provenance=provenance,
        signing_key=signing_key,
        key_id="ci-signer",
        etcd=clean_etcd,
    )

    # Pre-execution check
    record = verify_artifact_for_execution(model_id=model_id, digest=digest, etcd=clean_etcd)
    assert record.model_id == model_id
    assert record.digest == digest

    # Execute on worker
    node = SimulatedNode("test-node-1", NodeClass.EDGE, 10.0, 100.0, 0.005, ["global"])
    worker = InferenceWorker(node)
    req = ExecutionRequest(
        task_id="t-001",
        node_id="test-node-1",
        model_id=model_id,
        model_digest=digest,
        payload_ref="inline://test",
        idempotency_key="key-pass-1",
    )
    res = worker.execute(req)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.model_digest == digest
    assert res.output["node_metadata"]["model_digest"] == digest


def test_reject_mutable_tag_without_immutable_digest(clean_etcd, signer_keys):
    """Adversarial scenario: Client attempts to dispatch using mutable tag 'latest'."""
    signing_key, _ = signer_keys
    model_id = "model-mutable"
    digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    provenance = create_provenance(artifact_name=model_id, digest=digest)
    register_approved_model(model_id, digest, provenance, signing_key, etcd=clean_etcd)

    node = SimulatedNode("test-node-1", NodeClass.EDGE, 10.0, 100.0, 0.005, ["global"])
    worker = InferenceWorker(node)

    # Request with mutable tag "latest"
    req = ExecutionRequest(
        task_id="t-bad-tag",
        node_id="test-node-1",
        model_id=model_id,
        model_digest="latest",
        payload_ref="inline://test",
        idempotency_key="key-tag-fail",
    )

    with pytest.raises(ArtifactVerificationError) as exc_info:
        worker.execute(req)
    assert "mutable tags disallowed" in exc_info.value.message


def test_reject_unregistered_model(clean_etcd):
    """Adversarial scenario: Dispatch an unapproved model not present in the control plane."""
    node = SimulatedNode("test-node-1", NodeClass.EDGE, 10.0, 100.0, 0.005, ["global"])
    worker = InferenceWorker(node)

    req = ExecutionRequest(
        task_id="t-unreg",
        node_id="test-node-1",
        model_id="unregistered-backdoor-model",
        model_digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        payload_ref="inline://test",
        idempotency_key="key-unreg-fail",
    )

    with pytest.raises(ArtifactVerificationError) as exc_info:
        worker.execute(req)
    assert "not an approved registered artifact" in exc_info.value.message


def test_reject_tampered_model_digest(clean_etcd, signer_keys):
    """Adversarial scenario: Attacker substitutes task digest with another image digest."""
    signing_key, _ = signer_keys
    model_id = "model-secure"
    legit_digest = "sha256:3333333333333333333333333333333333333333333333333333333333333333"
    fake_digest = "sha256:4444444444444444444444444444444444444444444444444444444444444444"

    provenance = create_provenance(artifact_name=model_id, digest=legit_digest)
    register_approved_model(model_id, legit_digest, provenance, signing_key, etcd=clean_etcd)

    node = SimulatedNode("test-node-1", NodeClass.EDGE, 10.0, 100.0, 0.005, ["global"])
    worker = InferenceWorker(node)

    req = ExecutionRequest(
        task_id="t-tamper",
        node_id="test-node-1",
        model_id=model_id,
        model_digest=fake_digest,
        payload_ref="inline://test",
        idempotency_key="key-tamper-fail",
    )

    with pytest.raises(ArtifactVerificationError) as exc_info:
        worker.execute(req)
    assert "does not match approved digest" in exc_info.value.message


def test_reject_revoked_model_digest(clean_etcd, signer_keys):
    """Adversarial scenario: Model is revoked in control plane due to newly discovered vulnerability."""
    signing_key, _ = signer_keys
    model_id = "vulnerable-model"
    digest = "sha256:5555555555555555555555555555555555555555555555555555555555555555"

    provenance = create_provenance(artifact_name=model_id, digest=digest)
    register_approved_model(model_id, digest, provenance, signing_key, etcd=clean_etcd)

    # Revoke the model digest
    revoke_artifact_digest(digest, reason="CVE-2026-9999 Critical buffer overflow", etcd=clean_etcd)

    node = SimulatedNode("test-node-1", NodeClass.EDGE, 10.0, 100.0, 0.005, ["global"])
    worker = InferenceWorker(node)

    req = ExecutionRequest(
        task_id="t-revoked",
        node_id="test-node-1",
        model_id=model_id,
        model_digest=digest,
        payload_ref="inline://test",
        idempotency_key="key-revoked-fail",
    )

    with pytest.raises(ArtifactVerificationError) as exc_info:
        worker.execute(req)
    assert "has been revoked" in exc_info.value.message


def test_reject_unapproved_builder_identity(clean_etcd, signer_keys):
    """Adversarial scenario: Artifact was built by an untrusted external builder."""
    signing_key, _ = signer_keys
    model_id = "model-bad-builder"
    digest = "sha256:6666666666666666666666666666666666666666666666666666666666666666"

    # Attestation claims rogue builder
    provenance = create_provenance(
        artifact_name=model_id,
        digest=digest,
        builder_identity="spiffe://rogue-domain.local/untrusted-builder",
    )
    register_approved_model(model_id, digest, provenance, signing_key, etcd=clean_etcd)

    node = SimulatedNode("test-node-1", NodeClass.EDGE, 10.0, 100.0, 0.005, ["global"])
    worker = InferenceWorker(node)

    req = ExecutionRequest(
        task_id="t-bad-builder",
        node_id="test-node-1",
        model_id=model_id,
        model_digest=digest,
        payload_ref="inline://test",
        idempotency_key="key-builder-fail",
    )

    with pytest.raises(ArtifactVerificationError) as exc_info:
        worker.execute(req)
    assert "builder identity" in exc_info.value.message
    assert "is not permitted by policy" in exc_info.value.message


def test_reject_critical_vulnerabilities_exceeding_policy(clean_etcd, signer_keys):
    """Adversarial scenario: Artifact contains critical CVEs exceeding security policy."""
    signing_key, _ = signer_keys
    model_id = "model-with-cves"
    digest = "sha256:7777777777777777777777777777777777777777777777777777777777777777"

    provenance = create_provenance(
        artifact_name=model_id,
        digest=digest,
        vulnerabilities_summary={"CRITICAL": 2, "HIGH": 1, "MEDIUM": 0, "LOW": 0},
    )
    register_approved_model(model_id, digest, provenance, signing_key, etcd=clean_etcd)

    node = SimulatedNode("test-node-1", NodeClass.EDGE, 10.0, 100.0, 0.005, ["global"])
    worker = InferenceWorker(node)

    req = ExecutionRequest(
        task_id="t-cve-fail",
        node_id="test-node-1",
        model_id=model_id,
        model_digest=digest,
        payload_ref="inline://test",
        idempotency_key="key-cve-fail",
    )

    with pytest.raises(ArtifactVerificationError) as exc_info:
        worker.execute(req)
    assert "contains 2 CRITICAL vulnerabilities" in exc_info.value.message
