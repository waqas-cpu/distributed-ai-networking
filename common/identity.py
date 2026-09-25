import os
import datetime
from typing import Tuple, Optional
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import grpc
import ipaddress

TRUST_DOMAIN = "distributed-ai.local"

def _generate_ca() -> Tuple[bytes, bytes]:
    """Generates an in-memory Root CA for testing/simulation."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"SPIFFE Simulated CA ({TRUST_DOMAIN})"),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=1)
    ).add_extension(
        x509.BasicConstraints(ca=True, path_length=None), critical=True,
    ).sign(private_key, hashes.SHA256())

    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    return key_bytes, cert_bytes

def _get_or_create_shared_ca() -> Tuple[bytes, bytes]:
    """Retrieves or creates a CA to be shared across local processes for testing."""
    os.makedirs(".secret", exist_ok=True)
    key_path = ".secret/simulated_ca.key"
    cert_path = ".secret/simulated_ca.crt"

    if os.path.exists(key_path) and os.path.exists(cert_path):
        with open(key_path, "rb") as f:
            key_bytes = f.read()
        with open(cert_path, "rb") as f:
            cert_bytes = f.read()
        return key_bytes, cert_bytes
    
    key_bytes, cert_bytes = _generate_ca()
    with open(key_path, "wb") as f:
        f.write(key_bytes)
    with open(cert_path, "wb") as f:
        f.write(cert_bytes)
    return key_bytes, cert_bytes

class SimulatedIdentityProvider:
    """Mints short-lived X.509 SVIDs signed by a simulated local CA."""
    def __init__(self):
        self.ca_key_bytes, self.ca_cert_bytes = _get_or_create_shared_ca()
        self.ca_key = serialization.load_pem_private_key(self.ca_key_bytes, password=None)

    def get_svid(self, spiffe_id: str) -> Tuple[bytes, bytes, bytes]:
        """Returns (private_key_pem, cert_chain_pem, ca_cert_pem)."""
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, spiffe_id),
        ])
        
        # SPIFFE ID goes in the URI SAN, also add localhost for gRPC hostname verification
        san = x509.SubjectAlternativeName([
            x509.UniformResourceIdentifier(spiffe_id),
            x509.DNSName("localhost"),
            x509.DNSName("test-node-1"),
            x509.DNSName("test-node-2"),
            x509.DNSName("wrong-node"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            x509.IPAddress(ipaddress.IPv6Address("::1"))
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            x509.load_pem_x509_certificate(self.ca_cert_bytes).subject
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(hours=1) # Short-lived SVID
        ).add_extension(
            san, critical=False
        ).sign(self.ca_key, hashes.SHA256())

        key_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )
        cert_bytes = cert.public_bytes(serialization.Encoding.PEM)

        return key_bytes, cert_bytes, self.ca_cert_bytes

def extract_spiffe_id(context: grpc.ServicerContext) -> Optional[str]:
    """Extracts the SPIFFE ID (URI SAN) from a mutually authenticated gRPC context."""
    auth_context = context.auth_context()
    # 'x509_subject_alternative_name' holds SANs. We look for URIs.
    # Depending on grpcio python, it might be presented differently.
    # Usually it's in 'x509_san_uri' or 'x509_subject_alternative_name' if it parses it.
    uris = auth_context.get("x509_san_uri")
    if uris:
        for uri in uris:
            decoded = uri.decode('utf-8')
            if decoded.startswith(f"spiffe://{TRUST_DOMAIN}/"):
                return decoded

    # Fallback to check common name if URI SAN parsing is missing in some grpc setups
    common_names = auth_context.get("x509_common_name")
    if common_names:
        for cn in common_names:
            decoded = cn.decode('utf-8')
            if decoded.startswith(f"spiffe://{TRUST_DOMAIN}/"):
                return decoded

    return None
