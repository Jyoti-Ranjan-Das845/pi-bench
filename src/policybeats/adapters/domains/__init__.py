"""
Domain tool implementations.

Each domain provides a set of pure tools for its specific use case.
"""

from policybeats.adapters.domains.mock import MockDomainRegistry, create_mock_domain

__all__ = [
    "MockDomainRegistry",
    "create_mock_domain",
]
