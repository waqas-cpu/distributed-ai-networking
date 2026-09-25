import pytest
from common.crypto import CryptoConfig, OqsSignatureProvider, OQS_AVAILABLE
from common.errors import SecurityError
import os

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv("PQC_ALLOW_OQS_PROVIDER", "false")

def test_supported_signature_algorithms():
    # Should not raise any exception for valid algorithms
    CryptoConfig.validate_signature_algorithm("Ed25519")
    CryptoConfig.validate_signature_algorithm("ECDSA_P256")

def test_unsupported_signature_algorithms():
    with pytest.raises(SecurityError) as exc_info:
        CryptoConfig.validate_signature_algorithm("RSA2048")
    assert "Unsupported signature algorithm" in str(exc_info.value)

def test_post_quantum_signature_algorithms_fail_closed():
    # Should raise NotImplementedError since OQS is disabled by default policy
    with pytest.raises(NotImplementedError) as exc_info:
        CryptoConfig.validate_signature_algorithm("ML-DSA-44")
    assert "OQS provider is disabled by policy" in str(exc_info.value)

def test_post_quantum_signature_algorithms_enabled(monkeypatch):
    monkeypatch.setenv("PQC_ALLOW_OQS_PROVIDER", "true")
    if not OQS_AVAILABLE:
        with pytest.raises(SecurityError) as exc_info:
            CryptoConfig.validate_signature_algorithm("ML-DSA-44")
        assert "liboqs-python is not installed" in str(exc_info.value)
    else:
        CryptoConfig.validate_signature_algorithm("ML-DSA-44")

def test_supported_kem_algorithms():
    CryptoConfig.validate_kem_algorithm("X25519")

def test_unsupported_kem_algorithms():
    with pytest.raises(SecurityError) as exc_info:
        CryptoConfig.validate_kem_algorithm("RSA1024")
    assert "Unsupported KEM algorithm" in str(exc_info.value)

def test_post_quantum_kem_algorithms_fail_closed():
    with pytest.raises(NotImplementedError) as exc_info:
        CryptoConfig.validate_kem_algorithm("ML-KEM-768")
    assert "OQS provider is disabled by policy" in str(exc_info.value)

def test_post_quantum_kem_algorithms_enabled(monkeypatch):
    monkeypatch.setenv("PQC_ALLOW_OQS_PROVIDER", "true")
    if not OQS_AVAILABLE:
        with pytest.raises(SecurityError) as exc_info:
            CryptoConfig.validate_kem_algorithm("ML-KEM-768")
        assert "liboqs-python is not installed" in str(exc_info.value)
    else:
        CryptoConfig.validate_kem_algorithm("ML-KEM-768")

@pytest.mark.skipif(not OQS_AVAILABLE, reason="liboqs-python is not properly installed")
def test_oqs_signature_provider():
    # Test real ML-DSA-65 signing/verification
    provider = OqsSignatureProvider("ML-DSA-65")
    pub, priv = provider.generate_keypair()
    
    msg = b"test message"
    sig = provider.sign(msg, priv)
    
    assert provider.verify(msg, sig, pub) is True
    
    # Tampered message
    assert provider.verify(b"tampered", sig, pub) is False
