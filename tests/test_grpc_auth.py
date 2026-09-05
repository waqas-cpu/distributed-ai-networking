import pytest
import grpc
import threading
from concurrent import futures
import os

from contracts.proto import orchestrator_pb2, orchestrator_pb2_grpc
from common.tls import get_client_credentials
from node_agent.node import SimulatedNode
from contracts.models import NodeClass
from scheduler.dispatcher import TaskScheduler
from gateway.grpc_server import NodeRegistryServicer

EXPECTED_AUTH_TOKEN = os.environ.get("CLUSTER_AUTH_TOKEN", "default-insecure-token-123")

@pytest.fixture
def mock_registry_server():
    scheduler = TaskScheduler(node_targets={})
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    orchestrator_pb2_grpc.add_NodeRegistryServicer_to_server(NodeRegistryServicer(scheduler), server)
    port = server.add_insecure_port("[::]:0")
    server.start()
    
    yield f"localhost:{port}"
    
    server.stop(0)

def test_node_registration_success(mock_registry_server):
    channel = grpc.insecure_channel(mock_registry_server)
    stub = orchestrator_pb2_grpc.NodeRegistryStub(channel)
    
    req = orchestrator_pb2.NodeRegistrationRequest(
        node_id="test-node-1",
        node_class="edge",
        supported_models=[],
        data_residency_zones=["us-only"],
        hardware_specs_json="{}",
        auth_token=EXPECTED_AUTH_TOKEN
    )
    
    metadata = (('authorization', f'Bearer {EXPECTED_AUTH_TOKEN}'),)
    
    resp = stub.RegisterNode(req, metadata=metadata)
    assert resp.status == "success"

def test_node_registration_invalid_token(mock_registry_server):
    channel = grpc.insecure_channel(mock_registry_server)
    stub = orchestrator_pb2_grpc.NodeRegistryStub(channel)
    
    req = orchestrator_pb2.NodeRegistrationRequest(
        node_id="test-node-2",
        node_class="edge",
        supported_models=[],
        data_residency_zones=["us-only"],
        hardware_specs_json="{}",
        auth_token="wrong-token-123"
    )
    
    metadata = (('authorization', f'Bearer {EXPECTED_AUTH_TOKEN}'),)
    
    resp = stub.RegisterNode(req, metadata=metadata)
    assert resp.status == "rejected"
    assert "Invalid authentication token" in resp.message
