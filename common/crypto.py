import json
import os
import logging
from typing import Tuple, List, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from common.errors import SecurityError
from common.config import PqcConfig

logger = logging.getLogger("crypto")

try:
    import oqs
    OQS_AVAILABLE = True
except (ImportError, SystemExit, Exception) as e:
    logger.warning(f"OQS not available: {e}")
    OQS_AVAILABLE = False

class CryptoConfig:
    """Manages cryptographic agility and algorithm allowlists."""
    SUPPORTED_SIGNATURES: List[str] = ["Ed25519", "ECDSA_P256"]
    SUPPORTED_KEM: List[str] = ["X25519"]
    
    # Placeholders for Phase 8 Post-Quantum Agility
    PQ_SIGNATURES: List[str] = ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"]
    PQ_KEM: List[str] = ["ML-KEM-512", "ML-KEM-768", "ML-KEM-1024"]

    @classmethod
    def validate_signature_algorithm(cls, algorithm: str) -> None:
        pqc_config = PqcConfig.load()
        if algorithm in cls.PQ_SIGNATURES:
            if not pqc_config.get("PQC_ALLOW_OQS_PROVIDER"):
                raise NotImplementedError(f"Post-Quantum signature algorithm {algorithm} requested but OQS provider is disabled by policy.")
            if not OQS_AVAILABLE:
                raise SecurityError(f"Post-Quantum signature algorithm {algorithm} requested but liboqs-python is not installed.")
            return # Valid PQ algorithm
        if algorithm not in cls.SUPPORTED_SIGNATURES:
            raise SecurityError(f"Unsupported signature algorithm: {algorithm}")

    @classmethod
    def validate_kem_algorithm(cls, algorithm: str) -> None:
        pqc_config = PqcConfig.load()
        if algorithm in cls.PQ_KEM:
            if not pqc_config.get("PQC_ALLOW_OQS_PROVIDER"):
                raise NotImplementedError(f"Post-Quantum KEM algorithm {algorithm} requested but OQS provider is disabled by policy.")
            if not OQS_AVAILABLE:
                raise SecurityError(f"Post-Quantum KEM algorithm {algorithm} requested but liboqs-python is not installed.")
            return # Valid PQ KEM
        if algorithm not in cls.SUPPORTED_KEM:
            raise SecurityError(f"Unsupported KEM algorithm: {algorithm}")

class OqsSignatureProvider:
    """Provider for ML-DSA signatures using liboqs."""
    def __init__(self, alg_name: str = "ML-DSA-65"):
        self.alg_name = alg_name

    def generate_keypair(self) -> Tuple[bytes, bytes]:
        with oqs.Signature(self.alg_name) as signer:
            public_key = signer.generate_keypair()
            private_key = signer.export_secret_key()
            return public_key, private_key

    def sign(self, message: bytes, private_key: bytes) -> bytes:
        with oqs.Signature(self.alg_name, secret_key=private_key) as signer:
            return signer.sign(message)

    def verify(self, message: bytes, signature: bytes, public_key: bytes) -> bool:
        with oqs.Signature(self.alg_name) as verifier:
            return verifier.verify(message, signature, public_key)


def get_master_kek() -> bytes:
    """
    Retrieves a Master KEK (Key Encryption Key) used for simulation.
    In a real system, this would be retrieved from a KMS like AWS KMS or Hashicorp Vault.
    For this simulation, we use a static derived key or fetch it from our simulated state.
    """
    # For simulation purposes, use a static 32-byte key
    return b"master_kek_000000000000000000000"

def encrypt_envelope(payload: dict, kek: bytes) -> Tuple[bytes, bytes]:
    """
    Encrypts a payload using AES-256-GCM.
    Generates a Data Encryption Key (DEK).
    Returns (encrypted_payload, wrapped_dek).
    """
    # Generate 256-bit (32 bytes) DEK
    dek = AESGCM.generate_key(bit_length=256)
    
    # Encrypt payload with DEK
    aesgcm_dek = AESGCM(dek)
    nonce_dek = os.urandom(12)
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    encrypted_payload = nonce_dek + aesgcm_dek.encrypt(nonce_dek, payload_bytes, None)
    
    # Wrap DEK with KEK
    aesgcm_kek = AESGCM(kek)
    nonce_kek = os.urandom(12)
    wrapped_dek = nonce_kek + aesgcm_kek.encrypt(nonce_kek, dek, None)
    
    return encrypted_payload, wrapped_dek

def decrypt_envelope(encrypted_payload: bytes, wrapped_dek: bytes, kek: bytes) -> dict:
    """
    Decrypts the envelope by unwrapping the DEK using the KEK,
    then decrypting the payload using the DEK.
    """
    # Unwrap DEK
    aesgcm_kek = AESGCM(kek)
    nonce_kek = wrapped_dek[:12]
    ciphertext_dek = wrapped_dek[12:]
    dek = aesgcm_kek.decrypt(nonce_kek, ciphertext_dek, None)
    
    # Decrypt payload
    aesgcm_dek = AESGCM(dek)
    nonce_dek = encrypted_payload[:12]
    ciphertext_payload = encrypted_payload[12:]
    payload_bytes = aesgcm_dek.decrypt(nonce_dek, ciphertext_payload, None)
    
    return json.loads(payload_bytes.decode('utf-8'))
