"""Independent verification tool for the Tamper-Evident Audit Ledger."""

import json
import hashlib
import os
import argparse
from typing import List

def _hash_event(event_dict: dict, prev_hash: bytes) -> bytes:
    """Calculate domain-separated SHA-256 hash using the same canonical method."""
    # Remove the event_hash to get the canonical form
    event_dict.pop("event_hash", None)
    
    canonical_json = json.dumps(event_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')
    
    h = hashlib.sha256()
    h.update(b"DISTRIBUTED_AI_AUDIT_V1")
    h.update(prev_hash)
    h.update(canonical_json)
    return h.digest()

def verify_ledger(file_path: str = "audit_ledger.jsonl"):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return False
        
    print(f"Verifying ledger: {file_path}")
    
    expected_prev_hash = b""
    line_number = 0
    errors = 0
    
    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
                
            line_number += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(f"Line {line_number}: Invalid JSON format")
                errors += 1
                continue
                
            # Verify previous hash link
            stated_prev_hash = bytes.fromhex(event.get("previous_event_hash", ""))
            if stated_prev_hash != expected_prev_hash:
                print(f"Line {line_number}: Hash chain broken! Expected previous_hash {expected_prev_hash.hex()[:16]}... but got {stated_prev_hash.hex()[:16]}...")
                errors += 1
                # We can't trust this event to continue the chain reliably, but we try to continue
                
            # Verify event hash
            stated_event_hash = bytes.fromhex(event.get("event_hash", ""))
            calculated_hash = _hash_event(event.copy(), stated_prev_hash)
            
            if stated_event_hash != calculated_hash:
                print(f"Line {line_number}: Event tampering detected! Calculated hash {calculated_hash.hex()[:16]}... does not match stated hash {stated_event_hash.hex()[:16]}...")
                errors += 1
                expected_prev_hash = calculated_hash # Use calculated hash for next link to see if rest of chain is intact
            else:
                expected_prev_hash = stated_event_hash
                
    if errors == 0:
        print(f"Verification successful! Checked {line_number} immutable events.")
        return True
    else:
        print(f"Verification failed! Found {errors} integrity errors.")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify the integrity of the audit ledger.")
    parser.add_argument("--file", default="audit_ledger.jsonl", help="Path to the audit ledger JSONL file.")
    args = parser.parse_args()
    verify_ledger(args.file)
