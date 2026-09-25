"""Tamper-evident persistent auditing ledger.
Implements a hash-linked, append-only JSONL file for audit events.
"""

import json
import hashlib
import os
import threading
from typing import List, Optional
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from contracts.models import AuditEvent
from common.state import SimulatedEtcdProvider
from common.logger import get_logger

logger = get_logger("results_aggregator.ledger", component="results_aggregator")

class TamperEvidentLedger:
    def __init__(self, file_path: str = "audit_ledger.jsonl", checkpoint_interval: int = 10):
        self.file_path = file_path
        self.checkpoint_interval = checkpoint_interval
        self._lock = threading.RLock()
        self._etcd = SimulatedEtcdProvider()
        
        # Phase 6: Aggregator signing key for checkpoints
        self._signing_key = ed25519.Ed25519PrivateKey.generate()
        self._public_key_pem = self._signing_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')
        
        # Register public key
        self._etcd.put("/distributed-ai/audit/identity", self._public_key_pem)
        
        self.last_hash = b""
        self.events_since_checkpoint = 0
        self._current_merkle_leaves: List[bytes] = []
        
        # Ensure file exists and recover last hash
        self._recover_state()

    def _recover_state(self):
        """Read the ledger to find the last hash."""
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as f:
                pass
            return
            
        with open(self.file_path, "r") as f:
            last_line = None
            for line in f:
                line = line.strip()
                if line:
                    last_line = line
            
            if last_line:
                try:
                    data = json.loads(last_line)
                    self.last_hash = bytes.fromhex(data["event_hash"])
                except Exception as e:
                    logger.error(f"Failed to recover last hash from ledger: {e}")

    def _hash_event(self, event: AuditEvent, prev_hash: bytes) -> bytes:
        """Calculate domain-separated SHA-256 hash."""
        # Create a canonical dict without event_hash
        data = event.model_dump(mode="json")
        data.pop("event_hash", None)
        
        canonical_json = json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')
        
        h = hashlib.sha256()
        h.update(b"DISTRIBUTED_AI_AUDIT_V1")
        h.update(prev_hash)
        h.update(canonical_json)
        return h.digest()

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            event.previous_event_hash = self.last_hash.hex()
            
            current_hash = self._hash_event(event, self.last_hash)
            event.event_hash = current_hash.hex()
            
            self.last_hash = current_hash
            self._current_merkle_leaves.append(current_hash)
            
            # Append to durable storage
            with open(self.file_path, "a") as f:
                f.write(event.model_dump_json() + "\n")
                
            self.events_since_checkpoint += 1
            if self.events_since_checkpoint >= self.checkpoint_interval:
                self._create_checkpoint()

    def _create_checkpoint(self):
        if not self._current_merkle_leaves:
            return
            
        # Build a very simple Merkle root (just hashing all concatenated leaves for this simulation)
        h = hashlib.sha256()
        for leaf in self._current_merkle_leaves:
            h.update(leaf)
        merkle_root = h.digest()
        
        signature = self._signing_key.sign(merkle_root)
        
        checkpoint_id = f"ckpt_{int(self._current_merkle_leaves[-1][:4].hex(), 16)}"
        checkpoint_data = {
            "root": merkle_root.hex(),
            "signature": signature.hex(),
            "event_count": len(self._current_merkle_leaves)
        }
        
        self._etcd.put(f"/distributed-ai/audit/checkpoints/{checkpoint_id}", json.dumps(checkpoint_data))
        logger.info(f"Created signed Merkle checkpoint {checkpoint_id} with root {merkle_root.hex()[:16]}...")
        
        # Reset for next interval
        self.events_since_checkpoint = 0
        self._current_merkle_leaves = []

    def get_all(self, task_id: Optional[str] = None) -> List[AuditEvent]:
        """Reads the entire ledger. In a real system, use pagination."""
        events = []
        if not os.path.exists(self.file_path):
            return events
            
        with open(self.file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    event = AuditEvent.model_validate_json(line)
                    if task_id is None or event.task_id == task_id:
                        events.append(event)
        return events

    def clear(self):
        """For testing only."""
        with self._lock:
            if os.path.exists(self.file_path):
                os.remove(self.file_path)
            self.last_hash = b""
            self.events_since_checkpoint = 0
            self._current_merkle_leaves = []
