# Multi-stage lightweight production container
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    fastapi==0.141.1 \
    uvicorn==0.52.4 \
    pydantic==2.13.4 \
    pyyaml==6.0.3 \
    httpx==0.28.1 \
    pytest==9.1.1

# Copy source repository
COPY contracts/ ./contracts/
COPY common/ ./common/
COPY config/ ./config/
COPY telemetry/ ./telemetry/
COPY decision_engine/ ./decision_engine/
COPY scheduler/ ./scheduler/
COPY node_agent/ ./node_agent/
COPY results_aggregator/ ./results_aggregator/
COPY gateway/ ./gateway/
COPY server.py ./
COPY run_demo.py ./

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["python", "server.py"]
