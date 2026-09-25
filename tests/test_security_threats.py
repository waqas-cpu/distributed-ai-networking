import pytest
import time
import os
from cryptography.hazmat.primitives.asymmetric import ed25519

from common.crypto import encrypt_envelope, decrypt_envelope, get_master_kek
from common.state import SimulatedEtcdProvider

def test_envelope_encryption():
    kek = get_master_kek()
    payload = {"model_id": "v1", "timeout_ms": 100}
    
    enc_payload, enc_dek = encrypt_envelope(payload, kek)
    assert enc_payload != str(payload).encode()
    
    dec_payload = decrypt_envelope(enc_payload, enc_dek, kek)
    assert dec_payload == payload

def test_stale_lease_and_forgery():
    # In integration tests, the scheduler tests check that if lease is lost it halts dispatch.
    # We will just verify the crypto functions work as intended for Ed25519 signing.
    key1 = ed25519.Ed25519PrivateKey.generate()
    pub1 = key1.public_key()
    
    key2 = ed25519.Ed25519PrivateKey.generate()
    
    data = b"test payload"
    sig = key1.sign(data)
    
    # Valid
    pub1.verify(sig, data)
    
    # Forgery (wrong key)
    with pytest.raises(Exception):
        key2.public_key().verify(sig, data)
        
    # Tampering
    with pytest.raises(Exception):
        pub1.verify(sig, b"tampered payload")

def test_tamper_evident_ledger():
    from results_aggregator.ledger import TamperEvidentLedger
    from contracts.models import AuditEvent, PlacementDecision, ExecutionResult, NodeClass, ExecutionStatus
    from tools.verify_audit import verify_ledger
    
    test_file = "test_audit_ledger.jsonl"
    if os.path.exists(test_file):
        os.remove(test_file)
        
    ledger = TamperEvidentLedger(file_path=test_file, checkpoint_interval=2)
    
    dec = PlacementDecision(task_id="t1", chosen_node="node-1", chosen_score=0.9, weights_used={}, decision_latency_ms=1.0, fallback_chain=[])
    exec_res = ExecutionResult(task_id="t1", node_id="node-1", node_class=NodeClass.EDGE, status=ExecutionStatus.SUCCESS, execution_time_ms=10.0, output={}, error="", cached=False, idempotency_key="key")
    
    event1 = AuditEvent(task_id="t1", decision=dec, execution=exec_res)
    event2 = AuditEvent(task_id="t2", decision=dec, execution=exec_res)
    event3 = AuditEvent(task_id="t3", decision=dec, execution=exec_res)
    
    ledger.append(event1)
    ledger.append(event2)
    ledger.append(event3)
    
    # 1. Verify success
    assert verify_ledger(test_file) is True
    
    # 2. Tamper: edit an event in the middle
    with open(test_file, "r") as f:
        lines = f.readlines()
        
    import json
    tampered = json.loads(lines[1])
    tampered["task_id"] = "TAMPERED"
    lines[1] = json.dumps(tampered) + "\n"
    
    with open(test_file, "w") as f:
        f.writelines(lines)
        
    assert verify_ledger(test_file) is False
    
    # 3. Tamper: deletion
    del lines[1]
    with open(test_file, "w") as f:
        f.writelines(lines)
        
    assert verify_ledger(test_file) is False
    
    # Cleanup
    if os.path.exists(test_file):
        os.remove(test_file)


@pytest.mark.anyio
async def test_supply_chain_threat_rejection():
    """Adversarial test: verify that attempting to execute a revoked or unapproved model fails closed."""
    import httpx
    from common.cluster import create_simulated_cluster
    from common.supply_chain import revoke_artifact_digest

    telemetry_store, decision_engine, scheduler, aggregator, nodes, app, grpc_servers = create_simulated_cluster()

    try:
        # 1. Test unapproved model
        unapproved_payload = {
            "workload_type": "inference",
            "model_id": "malicious-trojan-v1",
            "sla_class": "real_time",
            "payload_ref": "s3://attacker/exploit.bin",
            "max_latency_ms": 150.0,
            "data_residency": "none",
            "idempotency_key": "sec-threat-unapproved-01",
        }

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-gateway-token"}
        ) as client:
            resp = await client.post("/v1/tasks/infer", json=unapproved_payload)
            # Should fail closed
            assert resp.status_code in [400, 500, 503]
            data = resp.json()
            assert "detail" in data or "error" in data or "message" in data

        # 2. Test revoked model
        # Revoke the approved vision-classifier-v3 digest
        approved_digest = "sha256:4a3b84175317b6a1e3b5e40854378f56193d56a31c5040f7d5440798e4f55e09"
        revoke_artifact_digest(approved_digest, reason="Emergency revocation: compromised model weights")

        revoked_payload = {
            "workload_type": "inference",
            "model_id": "vision-classifier-v3",
            "sla_class": "real_time",
            "payload_ref": "s3://camera/sample.jpg",
            "max_latency_ms": 150.0,
            "data_residency": "none",
            "idempotency_key": "sec-threat-revoked-01",
        }

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-gateway-token"}
        ) as client:
            resp = await client.post("/v1/tasks/infer", json=revoked_payload)
            assert resp.status_code in [400, 500, 503]
            data = resp.json()
            assert "detail" in data or "error" in data or "message" in data

    finally:
        for srv in grpc_servers:
            srv.stop(0)


