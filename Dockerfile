# PI-Bench Green Agent Dockerfile
# Multi-architecture support: linux/amd64, linux/arm64
FROM python:3.11-slim

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only runtime files (no tests, docs, scripts, results)
COPY pyproject.toml .
COPY README.md .
COPY src/ src/
COPY data/ data/

# Install package with A2A dependencies
RUN pip install --no-cache-dir -e ".[a2a]"

# Create output directory for results
RUN mkdir -p /app/output

# Expose default port
EXPOSE 9009

# Entry point: pi-bench-green defined in pyproject.toml
# Expects: --host <host> --port <port> --card-url <url>
ENTRYPOINT ["pi-bench-green"]
CMD ["--host", "0.0.0.0", "--port", "9009"]
