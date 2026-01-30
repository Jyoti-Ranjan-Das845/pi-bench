#!/bin/bash
#
# Test Script for GPT-5.2 Purple Agent
#
# This script:
# 1. Loads API keys from .env file
# 2. Starts GPT-5.2 purple agent (port 8001)
# 3. Starts green agent (port 8000)
# 4. Runs assessment with all 54 unified scenarios
# 5. Saves results to JSON
# 6. Cleans up servers
#
# Usage:
#   ./scripts/test_gpt52.sh
#
# Note: API keys are loaded from .env file in project root
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Configuration
PURPLE_PORT=8001
GREEN_PORT=8000
PURPLE_PID=""
GREEN_PID=""
RESULTS_DIR="results"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
RESULT_FILE="${RESULTS_DIR}/gpt52_unified_results_${TIMESTAMP}.json"

echo -e "${BLUE}================================================================${NC}"
echo -e "${BLUE}  PolicyBeats Benchmark - GPT-5.2 Purple Agent${NC}"
echo -e "${BLUE}================================================================${NC}"
echo ""

# Load environment variables from .env file
if [ -f "${PROJECT_ROOT}/.env" ]; then
    echo -e "${GREEN}✓${NC} Loading API keys from .env file..."
    set -a  # Automatically export all variables
    source "${PROJECT_ROOT}/.env"
    set +a
else
    echo -e "${YELLOW}⚠${NC}  No .env file found at ${PROJECT_ROOT}/.env"
    echo -e "${YELLOW}⚠${NC}  Checking for environment variables..."
fi
echo ""

# Add src to Python path so modules can be imported
export PYTHONPATH="${PROJECT_ROOT}/src:$PYTHONPATH"
echo -e "${GREEN}✓${NC} Python path configured"
echo ""

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}Cleaning up...${NC}"

    if [ -n "$PURPLE_PID" ]; then
        echo "Stopping GPT-5.2 purple agent (PID: $PURPLE_PID)..."
        kill $PURPLE_PID 2>/dev/null || true
        wait $PURPLE_PID 2>/dev/null || true
    fi

    if [ -n "$GREEN_PID" ]; then
        echo "Stopping green agent (PID: $GREEN_PID)..."
        kill $GREEN_PID 2>/dev/null || true
        wait $GREEN_PID 2>/dev/null || true
    fi

    echo -e "${GREEN}Cleanup complete${NC}"
}

# Register cleanup on exit
trap cleanup EXIT INT TERM

# Check environment variables
if [ -z "$OPENAI_API_KEY" ]; then
    echo -e "${RED}ERROR: OPENAI_API_KEY environment variable not set${NC}"
    echo ""
    echo "Set it with:"
    echo "  export OPENAI_API_KEY='sk-...'"
    exit 1
fi

echo -e "${GREEN}✓${NC} Environment variables OK"
echo ""

# Create results directory
mkdir -p "$RESULTS_DIR"

# Start GPT-5.2 purple agent
echo -e "${BLUE}Starting GPT-5.2 purple agent on port ${PURPLE_PORT}...${NC}"
python -m policybeats.purple.gpt52_unified_agent --port $PURPLE_PORT > /dev/null 2>&1 &
PURPLE_PID=$!
echo "Purple agent PID: $PURPLE_PID"

# Wait for purple agent to be ready
echo -n "Waiting for purple agent to be healthy..."
MAX_ATTEMPTS=30
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -s http://localhost:${PURPLE_PORT}/health > /dev/null 2>&1; then
        echo -e " ${GREEN}OK${NC}"
        break
    fi
    echo -n "."
    sleep 1
    ATTEMPT=$((ATTEMPT + 1))
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo -e " ${RED}FAILED${NC}"
    echo -e "${RED}Purple agent failed to start within ${MAX_ATTEMPTS} seconds${NC}"
    exit 1
fi

echo ""

# Start green agent
echo -e "${BLUE}Starting green agent on port ${GREEN_PORT}...${NC}"
python -m policybeats.a2a.server --port $GREEN_PORT > /dev/null 2>&1 &
GREEN_PID=$!
echo "Green agent PID: $GREEN_PID"

# Wait for green agent to be ready
echo -n "Waiting for green agent to be healthy..."
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -s http://localhost:${GREEN_PORT}/health > /dev/null 2>&1; then
        echo -e " ${GREEN}OK${NC}"
        break
    fi
    echo -n "."
    sleep 1
    ATTEMPT=$((ATTEMPT + 1))
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo -e " ${RED}FAILED${NC}"
    echo -e "${RED}Green agent failed to start within ${MAX_ATTEMPTS} seconds${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}================================================================${NC}"
echo -e "${BLUE}  Running Assessment (54 scenarios)${NC}"
echo -e "${BLUE}================================================================${NC}"
echo ""

# Run assessment using Python script
python3 << EOF
import asyncio
import json
import sys
from datetime import datetime
from collections import defaultdict
import time

# Add src to path
sys.path.insert(0, 'src')

from policybeats.a2a.mt_scenarios import ALL_SCENARIOS
from policybeats.a2a.engine import AssessmentEngine

# Progress tracking wrapper
class ProgressTracker:
    def __init__(self, total):
        self.total = total
        self.completed = 0
        self.start_time = time.time()
        self.lock = asyncio.Lock()

    async def increment(self):
        async with self.lock:
            self.completed += 1
            elapsed = time.time() - self.start_time
            rate = self.completed / elapsed if elapsed > 0 else 0
            eta = (self.total - self.completed) / rate if rate > 0 else 0
            print(f"Progress: {self.completed}/{self.total} scenarios completed "
                  f"({self.completed*100//self.total}%) | "
                  f"Rate: {rate:.1f} scenarios/sec | "
                  f"ETA: {int(eta)}s", flush=True)

async def run_assessment():
    print(f"Loaded {len(ALL_SCENARIOS)} scenarios")
    print()

    # Create assessment engine
    engine = AssessmentEngine(requests_per_minute=60)

    # Wrap _run_one to add progress tracking
    tracker = ProgressTracker(len(ALL_SCENARIOS))
    original_run_one = engine._run_one

    async def tracked_run_one(*args, **kwargs):
        result = await original_run_one(*args, **kwargs)
        await tracker.increment()
        return result

    engine._run_one = tracked_run_one

    # Run assessment
    print("Running assessment...")
    print()
    report = await engine.assess("http://localhost:${PURPLE_PORT}", ALL_SCENARIOS)
    print()
    print(f"✓ All {len(ALL_SCENARIOS)} scenarios completed!")

    # Extract results by category from report
    # Group scenarios by category based on scenario_id prefix mapping
    category_map = {
        'PB-CON': 'compliance',
        'PB-UC': 'understanding',
        'PB-ROB': 'robustness',
        'PB-PROC': 'process',
        'PB-LOG': 'process',
        'PB-VER': 'process',
        'PB-RST': 'restraint',
        'PB-CR': 'conflict_resolution',
        'PB-DET': 'detection',
        'PB-EXPL': 'explainability',
        'PB-ADP': 'adaptation',
        'PB-AMB': 'conflict_resolution',
        'PB-XS': 'robustness',
        'PB-COMBO': 'robustness',
        'PB-MIX': 'adaptation',
        'PB-MEGA': 'adaptation',
    }

    # Count passes/total per category
    category_stats = defaultdict(lambda: {'passed': 0, 'total': 0})

    for scenario_id, result in report.scenario_results.items():
        # Determine category from scenario_id prefix
        category = None
        for prefix, cat in category_map.items():
            if scenario_id.startswith(prefix):
                category = cat
                break
        if not category:
            continue

        category_stats[category]['total'] += 1
        # Check if scenario passed (no error)
        if 'error' not in result:
            category_stats[category]['passed'] += 1

    # Compute dimension scores
    dimension_scores = {}
    for cat, stats in category_stats.items():
        if stats['total'] > 0:
            dimension_scores[cat] = stats['passed'] / stats['total']

    # Overall score
    overall = sum(dimension_scores.values()) / len(dimension_scores) if dimension_scores else 0.0

    # Build simplified output
    output = {
        "model": "gpt-5.2",
        "framework": "unified",
        "timestamp": datetime.now().isoformat(),
        "total_scenarios": len(ALL_SCENARIOS),
        "total_violations": report.total_violations,
        "dimension_scores": dimension_scores,
        "overall_score": overall,
        "scenario_results": report.scenario_results,
    }

    # Save to file
    with open("${RESULT_FILE}", "w") as f:
        json.dump(output, f, indent=2)

    # Display summary
    print()
    print("=" * 64)
    print("  RESULTS SUMMARY")
    print("=" * 64)
    print()
    print(f"Total Scenarios: {len(ALL_SCENARIOS)}")
    print(f"Total Violations: {report.total_violations}")
    print()
    print("Dimension Scores (0-1, higher = better):")
    for dim, score in sorted(dimension_scores.items()):
        print(f"  {dim:20s}: {score:.3f}")
    print(f"  {'─' * 30}")
    print(f"  {'Overall':20s}: {overall:.3f}")
    print()
    print(f"Results saved to: ${RESULT_FILE}")
    print()

    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(run_assessment())
    sys.exit(exit_code)
EOF

ASSESSMENT_EXIT_CODE=$?

echo ""
echo -e "${BLUE}================================================================${NC}"

if [ $ASSESSMENT_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}  Assessment completed successfully${NC}"
    echo -e "${BLUE}================================================================${NC}"
    exit 0
else
    echo -e "${RED}  Assessment failed with exit code $ASSESSMENT_EXIT_CODE${NC}"
    echo -e "${BLUE}================================================================${NC}"
    exit $ASSESSMENT_EXIT_CODE
fi
