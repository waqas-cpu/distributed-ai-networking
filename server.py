import os
import uvicorn
from common.logger import setup_logging
from decision_engine.engine import DecisionEngine
from gateway.app import create_gateway_app
from gateway.grpc_server import serve_control_plane
from results_aggregator.aggregator import ResultsAggregator
from scheduler.dispatcher import TaskScheduler
from telemetry.redis_store import RedisTelemetryStore

# Setup structured logging
setup_logging()

# Initialize core components
redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
use_tls = os.environ.get("ENABLE_MTLS", "false").lower() == "true"

telemetry_store = RedisTelemetryStore(redis_url=redis_url, staleness_threshold_ms=3000.0)
decision_engine = DecisionEngine()
aggregator = ResultsAggregator()
scheduler = TaskScheduler(use_tls=use_tls)

# Start gRPC Control Plane in the background
grpc_server = serve_control_plane(telemetry_store, scheduler, port=50050, use_tls=use_tls)

# Create FastAPI app
app = create_gateway_app(
    telemetry_store=telemetry_store,
    decision_engine=decision_engine,
    scheduler=scheduler,
    aggregator=aggregator,
)

if __name__ == "__main__":
    try:
        uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
    finally:
        grpc_server.stop(0)
