# Docker Build Instructions - Purple Agent (Nebius GPT-OSS-SG-120B)

## Multi-Architecture Build

This Docker image supports multiple architectures: `linux/amd64` and `linux/arm64`.

### Prerequisites

1. Install Docker Desktop (includes buildx by default)
2. Create a GitHub Personal Access Token with `write:packages` permission
3. Login to GitHub Container Registry:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u jyoti-ranjan-das845 --password-stdin
```

### Build for Single Architecture (Fast - for testing)

```bash
# For current architecture only
docker build -f Dockerfile.purple-nebius -t ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest .

# Test locally (requires NEBIUS_API_KEY)
docker run -p 8002:8002 \
  -e NEBIUS_API_KEY="your-nebius-api-key" \
  ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest

# Push
docker push ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest
```

### Build for Multiple Architectures (Production)

```bash
# Create and use buildx builder (one-time setup)
docker buildx create --name multiarch --use
docker buildx inspect --bootstrap

# Build and push for multiple platforms
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest \
  -f Dockerfile.purple-nebius \
  --push \
  .

# Verify multi-arch manifest
docker buildx imagetools inspect ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest
```

### Build with Version Tags

```bash
# Tag with version
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest \
  -t ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:v0.1.0 \
  -f Dockerfile.purple-nebius \
  --push \
  .
```

## Make Image Public

After pushing:

1. Go to https://github.com/users/jyoti-ranjan-das845/packages/container/gpt-oss-sg-120b/settings
2. Scroll to "Danger Zone"
3. Click "Change visibility" → "Public"

## Test the Image

```bash
# Test locally (requires NEBIUS_API_KEY)
docker run -p 8002:8002 \
  -e NEBIUS_API_KEY="your-nebius-api-key" \
  ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest

# Check health endpoint
curl http://localhost:8002/health

# Check agent card
curl http://localhost:8002/.well-known/agent.json

# Test with custom args
docker run -p 9999:9999 \
  -e NEBIUS_API_KEY="your-nebius-api-key" \
  ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest \
  --host 0.0.0.0 --port 9999 --card-url http://localhost:9999
```

## Environment Variables

**Required:**
- `NEBIUS_API_KEY` - Your Nebius API key from https://studio.nebius.com

**Example:**
```bash
docker run -p 8002:8002 \
  -e NEBIUS_API_KEY="nb-xxx-yyy-zzz" \
  ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest
```

## Troubleshooting

### Build fails on arm64
If you're on Apple Silicon (M1/M2) and build fails:
```bash
# Build for amd64 only
docker buildx build \
  --platform linux/amd64 \
  -t ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest \
  -f Dockerfile.purple-nebius \
  --push \
  .
```

### "buildx not found"
Install Docker Desktop or update Docker:
```bash
# Check version
docker buildx version

# If missing, update Docker Desktop
```

### "NEBIUS_API_KEY not set" error
The purple agent requires a Nebius API key:
```bash
# Get your API key from: https://studio.nebius.com
export NEBIUS_API_KEY="your-nebius-api-key"

# Or pass it directly to docker run:
docker run -p 8002:8002 \
  -e NEBIUS_API_KEY="your-key" \
  ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest
```

## Image Details

- **Name:** `ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b`
- **Tag:** `latest` (also version tags like `v0.1.0`)
- **Architectures:** `linux/amd64`, `linux/arm64`
- **Base:** `python:3.11-slim`
- **Size:** ~250-300 MB
- **Entry Point:** `gpt-oss-sg-120b` (from pyproject.toml)
- **Default Port:** 8002
- **Model:** Nebius GPT-OSS-Safeguard-120B
- **API:** https://api.studio.nebius.com/v1
- **Framework:** Unified 9-dimensional policy compliance

## Agent Information

This is a **Purple Agent** (assessee) for the PolicyBeats benchmark. It:
- Implements A2A protocol for agent-to-agent communication
- Accepts policy packs and scenario instructions
- Makes tool calls for actions (data access, escalation, etc.)
- Returns responses that are evaluated for policy compliance
- Tests 9 dimensions: Compliance, Understanding, Robustness, Process, Restraint, Conflict Resolution, Detection, Explainability, Adaptation

## Usage with PolicyBeats

```bash
# 1. Start the purple agent
docker run -p 8002:8002 \
  -e NEBIUS_API_KEY="your-key" \
  ghcr.io/jyoti-ranjan-das845/gpt-oss-sg-120b:latest

# 2. In another terminal, run PolicyBeats green agent assessment
curl -X POST http://localhost:9009/assess/multi-turn \
  -H "Content-Type: application/json" \
  -d '{"purple_agent_url": "http://localhost:8002"}'
```
