#!/usr/bin/env python3
"""CLI tool for verifying software and model supply-chain integrity, provenance, and signatures."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

# Ensure workspace root is in sys.path
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from common.errors import ArtifactVerificationError
from common.logger import get_logger
from common.state import SimulatedEtcdProvider
from common.supply_chain import (
    get_supply_chain_policy,
    is_immutable_digest,
    verify_artifact_for_execution,
    verify_artifact_signature,
)
from contracts.models import ApprovedArtifactRecord

logger = get_logger("tools.verify_supply_chain")


def inspect_and_verify_model(
    model_id: str,
    digest: Optional[str] = None,
    etcd: Optional[SimulatedEtcdProvider] = None,
) -> bool:
    """Verify an artifact against control-plane policy, signatures, provenance, and revocation."""
    etcd = etcd or SimulatedEtcdProvider()
    print(f"\n========================================================")
    print(f"Supply Chain Verification: Model '{model_id}'")
    print(f"========================================================")

    # 1. Check Policy
    policy = get_supply_chain_policy(etcd)
    print(f"[*] Active Supply Chain Policy:")
    print(f"    - Require Immutable Digest : {policy.require_immutable_digest}")
    print(f"    - Require Signature        : {policy.require_signature}")
    print(f"    - Allowed Builders         : {policy.allowed_builders}")
    print(f"    - Max Critical Vulns       : {policy.max_allowed_critical_vulns}")
    print(f"    - Max High Vulns           : {policy.max_allowed_high_vulns}")

    # 2. Check Digest
    if not digest:
        raw_rec = etcd.get(f"/distributed-ai/artifacts/models/{model_id}")
        if raw_rec:
            try:
                parsed = json.loads(raw_rec)
                digest = parsed.get("digest")
                print(f"[*] Resolved Registered Digest: {digest}")
            except Exception:
                pass

    if digest:
        if not is_immutable_digest(digest):
            print(f"[!] FAILED: Digest '{digest}' is not a valid immutable sha256 digest!")
            return False
        print(f"[*] Target Digest: {digest}")

    # 3. Perform Full Pre-execution Verification
    try:
        record = verify_artifact_for_execution(model_id=model_id, digest=digest, etcd=etcd)
        print(f"[+] Model Approved in Authoritative Control Plane:")
        print(f"    - Immutable Digest : {record.digest}")
        print(f"    - Signing Key ID   : {record.signing_key_id}")
        print(f"    - Signature Alg    : {record.signature_algorithm}")
        print(f"    - Signature (hex)  : {record.signature[:32]}...")
        print(f"[+] Build Provenance:")
        print(f"    - Builder Identity : {record.provenance.builder_identity}")
        print(f"    - Source Repo      : {record.provenance.source_repo}")
        print(f"    - Commit SHA       : {record.provenance.commit_sha}")
        print(f"    - SBOM Digest      : {record.provenance.sbom_digest}")
        print(f"    - Vulnerabilities  : {record.provenance.vulnerabilities_summary}")
        print(f"[+] Revocation Status  : {'REVOKED' if record.revoked else 'ACTIVE / NOT REVOKED'}")
        print(f"\n[SUCCESS] Artifact passes all supply chain verification gates!\n")
        return True
    except ArtifactVerificationError as ave:
        print(f"\n[!] VERIFICATION FAILED: {ave.message}")
        if ave.details:
            print(f"    Details: {json.dumps(ave.details, indent=2)}")
        print()
        return False
    except Exception as ex:
        print(f"\n[!] UNEXPECTED ERROR: {ex}\n")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Model and Container Artifact Supply Chain")
    parser.add_argument("--model-id", required=True, help="Model identifier (e.g. vision-classifier-v3)")
    parser.add_argument("--digest", default=None, help="Optional expected immutable SHA-256 digest")
    args = parser.parse_args()

    # Bootstrap default cluster if empty for simulation
    from common.cluster import bootstrap_supply_chain
    bootstrap_supply_chain()

    success = inspect_and_verify_model(model_id=args.model_id, digest=args.digest)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
