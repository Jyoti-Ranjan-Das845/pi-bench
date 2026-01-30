"""
Adapters - imperative shell implementations.

Adapters implement the ports protocols and handle actual I/O.
"""

from policybeats.adapters.litellm import LiteLLMAdapter
from policybeats.adapters.runner import run_simulation

__all__ = [
    "LiteLLMAdapter",
    "run_simulation",
]
