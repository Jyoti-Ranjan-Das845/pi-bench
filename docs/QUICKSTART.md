# PI-Bench Quick Start

## Installation

```bash
pip install pi-bench
```

## Two Use Cases

PI-Bench serves two enterprise goals:

### 1. Official Leaderboard (Fixed Benchmark)

Compare your agent against others on **all 9 dimensions** using official scenarios.

```bash
# Run official benchmark
pi-bench leaderboard \
  --agent-url http://localhost:8080 \
  --agent-name "my-agent" \
  --output results.json

# Verify submission
pi-bench verify results.json
```

**Leaderboard Requirements:**
- Must evaluate ALL 9 dimensions
- Must use official scenarios (cannot modify)
- Results undergo hash verification

### 2. Custom Runner (Extensible Platform)

Use PI-Bench for internal testing with custom policies and scenarios.

```bash
# Run custom evaluation
pi-bench run \
  --agent-url http://localhost:8080 \
  --scenarios compliance,robustness \
  --output custom-results.json
```

## Basic Commands

```bash
# List available resources
pi-bench list policies
pi-bench list scenarios
pi-bench list dimensions

# Show version
pi-bench version

# Dry-run (see what will be tested)
pi-bench leaderboard --dry-run --agent-url http://localhost:8080
```

## Next Steps

- **Leaderboard submission:** See [LEADERBOARD.md](LEADERBOARD.md)
- **Custom policies/scenarios:** See [CUSTOM_RUNNER.md](CUSTOM_RUNNER.md)
- **Python API:** See [API.md](API.md) (coming soon)
