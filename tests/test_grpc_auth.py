import pytest
import grpc
from concurrent import futures
import os

from contracts.proto import orchestrator_pb2, orchestrator_pb2_grpc
from common.tls import get_server_credentials, get_client_credentials
from common.identity import SimulatedIdentityProvider
from scheduler.dispatcher import TaskScheduler
from gateway.grpc_server import NodeRegistryServicer

@pytest.fixture
def mock_registry_server():
    scheduler = TaskScheduler(node_targets={})
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    orchestrator_pb2_grpc.add_NodeRegistryServicer_to_server(NodeRegistryServicer(scheduler), server)
    
    creds = get_server_credentials("spiffe://distributed-ai.local/gateway/master")
    port = server.add_secure_port("[::]:0", creds)
    server.start()
    
    yield f"localhost:{port}"
    
    server.stop(0)

def test_node_registration_success(mock_registry_server):
    # Dial as a valid node identity
    creds = get_client_credentials("spiffe://distributed-ai.local/node/test-node-1")
    channel = grpc.secure_channel(mock_registry_server, creds)
    stub = orchestrator_pb2_grpc.NodeRegistryStub(channel)
    
    req = orchestrator_pb2.NodeRegistrationRequest(
        node_id="test-node-1",
        node_class="edge",
        supported_models=[],
        data_residency_zones=["us-only"],
        hardware_specs_json="{}",
        public_signing_key="dummy-key-1"
    )
    
    resp = stub.RegisterNode(req)
    assert resp.status == "success"

def test_node_registration_invalid_identity(mock_registry_server):
    # Dial as a node but try to register as another node
    creds = get_client_credentials("spiffe://distributed-ai.local/node/wrong-node")
    channel = grpc.secure_channel(mock_registry_server, creds)
    stub = orchestrator_pb2_grpc.NodeRegistryStub(channel)
    
    req = orchestrator_pb2.NodeRegistrationRequest(
        node_id="test-node-1",
        node_class="edge",
        supported_models=[],
        data_residency_zones=["us-only"],
        hardware_specs_json="{}",
        public_signing_key="dummy-key-2"
    )
    
    resp = stub.RegisterNode(req)
    assert resp.status == "rejected"
    assert "Invalid authentication identity" in resp.message

def test_node_registration_unauthorized_role(mock_registry_server):
    # Dial as an aggregator (not a node)
    creds = get_client_credentials("spiffe://distributed-ai.local/aggregator/1")
    channel = grpc.secure_channel(mock_registry_server, creds)
    stub = orchestrator_pb2_grpc.NodeRegistryStub(channel)
    
    req = orchestrator_pb2.NodeRegistrationRequest(
        node_id="test-node-1",
        node_class="edge",
        supported_models=[],
        data_residency_zones=["us-only"],
        hardware_specs_json="{}",
        public_signing_key="dummy-key-3"
    )
    
    resp = stub.RegisterNode(req)
    assert resp.status == "rejected"
    assert "Invalid authentication identity" in resp.message
