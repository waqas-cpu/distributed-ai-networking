import grpc
from common.identity import SimulatedIdentityProvider

def get_server_credentials(spiffe_id: str) -> grpc.ServerCredentials:
    """
    Creates gRPC ServerCredentials enforcing mTLS using a dynamic SVID.
    """
    provider = SimulatedIdentityProvider()
    server_key, server_cert, ca_cert = provider.get_svid(spiffe_id)

    return grpc.ssl_server_credentials(
        [(server_key, server_cert)],
        root_certificates=ca_cert,
        require_client_auth=True
    )

def get_client_credentials(spiffe_id: str) -> grpc.ChannelCredentials:
    """
    Creates gRPC ChannelCredentials for mTLS client connections using a dynamic SVID.
    """
    provider = SimulatedIdentityProvider()
    client_key, client_cert, ca_cert = provider.get_svid(spiffe_id)

    return grpc.ssl_channel_credentials(
        root_certificates=ca_cert,
        private_key=client_key,
        certificate_chain=client_cert
    )
