"""
PolicyBeats A2A Integration.

This module provides the A2A-compliant Green Agent interface for PolicyBeats,
enabling it to run as an assessor on the AgentBeats platform.

Components:
- server: FastAPI A2A server
- assessment: Assessment flow orchestration
- results: Convert PolicyBeats results to AgentBeats format
- scenarios: Policy compliance test scenarios
"""

from policybeats.a2a.results import to_agentbeats_results

__all__ = ["to_agentbeats_results"]
