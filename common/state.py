import threading
import time
from typing import Optional, Dict

class SimulatedEtcdProvider:
    """
    In-memory mock of an etcd cluster for simulating authoritative state.
    Provides key/value storage, CAS (Compare-And-Swap), and Leases.
    """
    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SimulatedEtcdProvider, cls).__new__(cls)
                cls._instance.kv = {}
                cls._instance.leases = {}
                cls._instance.lease_id_counter = 1
        return cls._instance
        
    def clear(self) -> None:
        """Clears all state. Used only for testing."""
        with self._lock:
            self.kv.clear()
            self.leases.clear()
            self.lease_id_counter = 1

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self.kv[key] = value

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            return self.kv.get(key)

    def delete(self, key: str) -> None:
        with self._lock:
            if key in self.kv:
                del self.kv[key]

    def grant_lease(self, ttl: int) -> int:
        """Grants a new lease with a TTL in seconds."""
        with self._lock:
            lease_id = self.lease_id_counter
            self.lease_id_counter += 1
            expiry = time.time() + ttl
            self.leases[lease_id] = expiry
            return lease_id

    def revoke_lease(self, lease_id: int) -> None:
        with self._lock:
            if lease_id in self.leases:
                del self.leases[lease_id]

    def is_lease_valid(self, lease_id: int) -> bool:
        with self._lock:
            if lease_id not in self.leases:
                return False
            if time.time() > self.leases[lease_id]:
                del self.leases[lease_id]
                return False
            return True

    def put_with_lease(self, key: str, value: str, lease_id: int) -> bool:
        """Puts a key if the lease is valid."""
        with self._lock:
            if not self.is_lease_valid(lease_id):
                return False
            self.kv[key] = value
            return True

    def compare_and_swap(self, key: str, expected_value: Optional[str], new_value: str, lease_id: Optional[int] = None) -> bool:
        """Atomic CAS. If expected_value is None, succeeds only if key does not exist."""
        with self._lock:
            if lease_id is not None and not self.is_lease_valid(lease_id):
                return False
                
            current_value = self.kv.get(key)
            if current_value == expected_value:
                self.kv[key] = new_value
                return True
            return False
