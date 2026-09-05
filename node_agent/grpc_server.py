"""gRPC Server for Node Agent Execution Service.
Listens for inference dispatch requests from the Scheduler.
"""

import json
import logging
import time
import grpc
from concurrent import futures

from common.logger import get_logger
from common.tls import get_server_credentials
from contracts.models import ExecutionRequest, NodeClass
from contracts.proto import orchestrator_pb2, orchestrator_pb2_grpc
from node_agent.node import SimulatedNode
from node_agent.worker import InferenceWorker

logger = get_logger("node_agent.grpc_server")

import os

EXPECTED_AUTH_TOKEN = os.environ.get("CLUSTER_AUTH_TOKEN", "default-insecure-token-123")

def _authenticate(context: grpc.ServicerContext) -> bool:
    """Extract and validate the auth token from gRPC metadata."""
    metadata = dict(context.invocation_metadata())
    token = metadata.get("authorization", "")
    if token == f"Bearer {EXPECTED_AUTH_TOKEN}":
        return True
    
    logger.warning("Unauthenticated ExecutionRequest rejected.")
    context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid or missing auth token")
    return False

class ExecutionServiceServicer(orchestrator_pb2_grpc.ExecutionServicer):
    def __init__(self, worker: InferenceWorker):
        self.worker = worker

    def ExecuteTask(self, request: orchestrator_pb2.ExecutionRequest, context: grpc.ServicerContext) -> orchestrator_pb2.ExecutionResponse:
        _authenticate(context)
        
        metadata = dict(context.invocation_metadata())
        trace_id = metadata.get("x-trace-id", "unknown-trace")
        
        logger.info(
            f"Received ExecutionRequest for task {request.task_id} on model {request.model_id}",
            extra={"task_id": request.task_id, "trace_id": trace_id}
        )
        
        exec_req = ExecutionRequest(
            task_id=request.task_id,
            node_id=request.node_id,
            model_id=request.model_id,
            payload_ref=request.payload_ref,
            idempotency_key=request.idempotency_key,
            timeout_ms=request.timeout_ms,
        )
        
        try:
            result = self.worker.execute(exec_req)
            return orchestrator_pb2.ExecutionResponse(
                task_id=result.task_id,
                node_id=result.node_id,
                node_class=result.node_class.value,
                status=result.status.value,
                execution_time_ms=result.execution_time_ms,
                output_json=json.dumps(result.output) if result.output else "",
                error=result.error or "",
                cached=result.cached,
                idempotency_key=result.idempotency_key,
            )
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            return orchestrator_pb2.ExecutionResponse(
                task_id=request.task_id,
                node_id=request.node_id,
                node_class=self.worker.node.node_class.value,
                status="failed",
                execution_time_ms=0.0,
                output_json="",
                error=str(e),
                cached=False,
                idempotency_key=request.idempotency_key,
            )

def serve(worker: InferenceWorker, port: int = 50051, use_tls: bool = True):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    orchestrator_pb2_grpc.add_ExecutionServicer_to_server(ExecutionServiceServicer(worker), server)
    
    address = f"[::]:{port}"
    if use_tls:
        creds = get_server_credentials()
        server.add_secure_port(address, creds)
        logger.info(f"Starting Secure gRPC ExecutionService on {address}")
    else:
        server.add_insecure_port(address)
        logger.info(f"Starting Insecure gRPC ExecutionService on {address}")
        
    server.start()
    return server
