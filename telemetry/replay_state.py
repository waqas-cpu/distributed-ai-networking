import time
import threading
from typing import Dict, Set

class ReplayProtectionState:
    def __init__(self, max_clock_skew_seconds: float = 5.0):
        self.max_clock_skew_seconds = max_clock_skew_seconds
        self._lock = threading.RLock()
        
        # State per node
        self._highest_sequence: Dict[str, int] = {}
        self._seen_nonces: Dict[str, Set[str]] = {}

    def validate_and_record(self, node_id: str, sequence_number: int, nonce: str, timestamp: float, expires_at: float) -> bool:
        """
        Validates the message against replay attacks.
        Returns True if valid, False if rejected.
        """
        now = time.time()
        
        # 1. Expiry check
        if now > expires_at:
            return False
            
        # 2. Clock skew check (timestamp cannot be too far in the future)
        if timestamp > now + self.max_clock_skew_seconds:
            return False
            
        with self._lock:
            # 3. Sequence number check
            highest_seq = self._highest_sequence.get(node_id, -1)
            if sequence_number <= highest_seq:
                return False
                
            # 4. Nonce check
            if node_id not in self._seen_nonces:
                self._seen_nonces[node_id] = set()
            
            if nonce in self._seen_nonces[node_id]:
                return False
                
            # Record state
            self._highest_sequence[node_id] = sequence_number
            self._seen_nonces[node_id].add(nonce)
            
            # Periodically clean up old nonces (for a real system, we'd remove nonces from expired messages)
            # Keeping it simple for simulation by bounding the set size
            if len(self._seen_nonces[node_id]) > 1000:
                self._seen_nonces[node_id].clear()
                self._seen_nonces[node_id].add(nonce)
                
            return True
