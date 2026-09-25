import os
import pytest

@pytest.fixture(autouse=True, scope="session")
def setup_test_env():
    os.environ["GATEWAY_AUTH_TOKEN"] = "test-gateway-token"
    os.environ["CLUSTER_AUTH_TOKEN"] = "test-token-123"
    os.environ["APP_ENV"] = "development"

@pytest.fixture(autouse=True)
def clear_etcd():
    from common.state import SimulatedEtcdProvider
    SimulatedEtcdProvider().clear()
