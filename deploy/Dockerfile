# Multi-stage lightweight production container
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install system dependencies for liboqs (PQC C-extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    ninja-build \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
