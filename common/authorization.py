from typing import Optional

def authorize_node(spiffe_id: Optional[str], expected_node_id: str) -> bool:
    """
    Verifies that the provided SPIFFE ID belongs to a node and matches the expected node_id.
    """
    if not spiffe_id:
        return False
    expected_spiffe_id = f"spiffe://distributed-ai.local/node/{expected_node_id}"
    return spiffe_id == expected_spiffe_id

def authorize_scheduler(spiffe_id: Optional[str]) -> bool:
    """
    Verifies that the provided SPIFFE ID belongs to the scheduler.
    """
    if not spiffe_id:
        return False
    return spiffe_id == "spiffe://distributed-ai.local/scheduler/master"

def authorize_gateway(spiffe_id: Optional[str]) -> bool:
    """
    Verifies that the provided SPIFFE ID belongs to the gateway.
    """
    if not spiffe_id:
        return False
    return spiffe_id.startswith("spiffe://distributed-ai.local/gateway/")
