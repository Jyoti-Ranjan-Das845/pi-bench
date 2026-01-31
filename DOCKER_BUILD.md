# Docker Build Instructions

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
docker build -t ghcr.io/jyoti-ranjan-das845/pi-bench-green:latest .

# Test locally
docker run -p 9009:9009 ghcr.io/jyoti-ranjan-das845/pi-bench-green:latest

# Push
docker push ghcr.io/jyoti-ranjan-das845/pi-bench-green:latest
```

### Build for Multiple Architectures (Production)

```bash
# Create and use buildx builder (one-time setup)
docker buildx create --name multiarch --use
docker buildx inspect --bootstrap

# Build and push for multiple platforms
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/jyoti-ranjan-das845/pi-bench-green:latest \
  --push \
  .

# Verify multi-arch manifest
docker buildx imagetools inspect ghcr.io/jyoti-ranjan-das845/pi-bench-green:latest
```

### Build with Version Tags

```bash
# Tag with version
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/jyoti-ranjan-das845/pi-bench-green:latest \
  -t ghcr.io/jyoti-ranjan-das845/pi-bench-green:v0.1.0 \
  --push \
  .
```

## Make Image Public

After pushing:

1. Go to https://github.com/users/jyoti-ranjan-das845/packages/container/pi-bench-green/settings
2. Scroll to "Danger Zone"
3. Click "Change visibility" → "Public"

## Test the Image

```bash
# Test locally
docker run -p 9009:9009 ghcr.io/jyoti-ranjan-das845/pi-bench-green:latest

# Check health endpoint
curl http://localhost:9009/health

# Check agent card
curl http://localhost:9009/.well-known/agent.json

# Test with custom args
docker run -p 8888:8888 ghcr.io/jyoti-ranjan-das845/pi-bench-green:latest \
  --host 0.0.0.0 --port 8888 --card-url http://localhost:8888
```

## Troubleshooting

### Build fails on arm64
If you're on Apple Silicon (M1/M2) and build fails:
```bash
# Build for amd64 only
docker buildx build \
  --platform linux/amd64 \
  -t ghcr.io/jyoti-ranjan-das845/pi-bench-green:latest \
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

## Image Details

- **Name:** `ghcr.io/jyoti-ranjan-das845/pi-bench-green`
- **Tag:** `latest` (also version tags like `v0.1.0`)
- **Architectures:** `linux/amd64`, `linux/arm64`
- **Base:** `python:3.11-slim`
- **Size:** ~200-250 MB
- **Entry Point:** `policybeats-green` (from pyproject.toml)
- **Default Port:** 9009
