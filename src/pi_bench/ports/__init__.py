"""
Port definitions - abstract interfaces for hexagonal architecture.

Ports define the boundaries between the functional core and the imperative shell.
Adapters implement these protocols to connect to real I/O systems.
"""

from pi_bench.ports.llm import LLMPort
from pi_bench.ports.tools import ToolRegistryPort
from pi_bench.ports.tasks import TaskLoaderPort

__all__ = [
    "LLMPort",
    "TaskLoaderPort",
    "ToolRegistryPort",
]
