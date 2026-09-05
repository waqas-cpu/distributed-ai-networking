import os
import grpc

def get_server_credentials(certs_dir: str = "certs") -> grpc.ServerCredentials:
    """
    Creates gRPC ServerCredentials enforcing mTLS.
    """
    with open(os.path.join(certs_dir, "server.key"), "rb") as f:
        server_key = f.read()
    with open(os.path.join(certs_dir, "server.crt"), "rb") as f:
        server_cert = f.read()
    with open(os.path.join(certs_dir, "ca.crt"), "rb") as f:
        ca_cert = f.read()

    return grpc.ssl_server_credentials(
        [(server_key, server_cert)],
        root_certificates=ca_cert,
        require_client_auth=True
    )

def get_client_credentials(certs_dir: str = "certs") -> grpc.ChannelCredentials:
    """
    Creates gRPC ChannelCredentials for mTLS client connections.
    """
    with open(os.path.join(certs_dir, "client.key"), "rb") as f:
        client_key = f.read()
    with open(os.path.join(certs_dir, "client.crt"), "rb") as f:
        client_cert = f.read()
    with open(os.path.join(certs_dir, "ca.crt"), "rb") as f:
        ca_cert = f.read()

    return grpc.ssl_channel_credentials(
        root_certificates=ca_cert,
        private_key=client_key,
        certificate_chain=client_cert
    )
