# PI-Bench Leaderboard Submission Guide

## Overview

The official PI-Bench leaderboard evaluates agents on **all 9 dimensions** using official scenarios.

## Requirements

✅ **All 9 dimensions must be evaluated:**
1. Compliance
2. Understanding
3. Robustness
4. Process
5. Restraint
6. Conflict Resolution
7. Detection
8. Explainability
9. Adaptation

✅ **Official scenarios only** (no modifications)
✅ **Results verification** (hash-based tamper detection)

## Submission Process

### Step 1: Run Official Benchmark

```bash
pi-bench leaderboard \
  --agent-url http://localhost:8080 \
  --agent-name "my-agent-v1" \
  --output results.json
```

This will:
- Test your agent on ~150 official scenarios
- Evaluate all 9 dimensions
- Generate `results.json` with scenario hashes

### Step 2: Verify Results

```bash
pi-bench verify results.json
```

This checks:
- All 9 dimensions present
- Scenario hashes match official scenarios
- Result format valid

### Step 3: Submit

(Submission process TBD - GitHub PR or web form)

## Results Format

```json
{
  "benchmark": "pi-bench",
  "version": "1.0.0",
  "agent": {
    "name": "my-agent-v1",
    "url": "http://localhost:8080"
  },
  "scores": {
    "overall": 0.85,
    "by_dimension": {
      "compliance": 0.90,
      "understanding": 0.82,
      "robustness": 0.78,
      "process": 0.88,
      "restraint": 0.91,
      "conflict_resolution": 0.75,
      "detection": 0.84,
      "explainability": 0.80,
      "adaptation": 0.87
    }
  },
  "scenario_hashes": {
    "compliance-001": "a3f2e1b4...",
    ...
  }
}
```

## What's NOT Allowed

❌ Modifying official scenarios
❌ Testing only subset of dimensions
❌ Tampering with scenario hashes
❌ Using custom policies for leaderboard

## Verification System

PI-Bench uses **deterministic scenario hashing** to prevent tampering:

- Each scenario has a hash (scenario_id + turns + instructions)
- Hashes computed during evaluation
- Verification compares submitted hashes vs official hashes
- Any mismatch = rejection

## Dry Run (Test Before Submission)

```bash
pi-bench leaderboard --dry-run --agent-url http://localhost:8080
```

Shows what will be tested without actually running.

## Common Issues

**Q: Can I test just one dimension?**
A: Not for leaderboard. Use `pi-bench run --scenarios compliance` for internal testing.

**Q: How long does evaluation take?**
A: ~30-60 minutes (depends on agent speed and rate limit).

**Q: Can I retry failed scenarios?**
A: No. Leaderboard requires single-run evaluation to prevent cherry-picking.
