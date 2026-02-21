"""
Registry for custom policies, scenarios, and resources.

Enables programmatic registration of custom resources for internal use
while preserving official benchmark integrity.
"""

from __future__ import annotations

from typing import Any

from pi_bench.types import PolicyPack
from pi_bench.a2a.protocol import MultiTurnScenario


class Registry:
    """Central registry for custom PI-Bench resources."""

    _policies: dict[str, PolicyPack] = {}
    _scenarios: dict[str, MultiTurnScenario] = {}

    @classmethod
    def register_policy(cls, pack: PolicyPack, name: str) -> None:
        """Register a custom policy pack.

        Args:
            pack: PolicyPack to register
            name: Unique name for this policy

        Example:
            >>> my_pack = PolicyPack(...)
            >>> Registry.register_policy(my_pack, "my-policy")
        """
        cls._policies[name] = pack

    @classmethod
    def register_scenario(cls, scenario: MultiTurnScenario, name: str) -> None:
        """Register a custom scenario.

        Args:
            scenario: MultiTurnScenario to register
            name: Unique name for this scenario

        Example:
            >>> my_scenario = MultiTurnScenario(...)
            >>> Registry.register_scenario(my_scenario, "my-scenario")
        """
        cls._scenarios[name] = scenario

    @classmethod
    def get_policy(cls, name: str) -> PolicyPack:
        """Get policy by name (custom or official).

        Args:
            name: Policy name or dimension name

        Returns:
            PolicyPack for the given name

        Raises:
            KeyError: If policy not found
        """
        if name in cls._policies:
            return cls._policies[name]

        # Fall back to official dimension packs
        from pi_bench.packs import load_pack
        return load_pack(name)

    @classmethod
    def get_scenario(cls, name: str) -> MultiTurnScenario:
        """Get scenario by name.

        Args:
            name: Scenario name

        Returns:
            MultiTurnScenario for the given name

        Raises:
            KeyError: If scenario not found
        """
        if name not in cls._scenarios:
            raise KeyError(f"Scenario '{name}' not found. Register with Registry.register_scenario()")
        return cls._scenarios[name]

    @classmethod
    def list_policies(cls) -> list[str]:
        """List all available policy names (custom + official)."""
        from pi_bench.packs import CATEGORIES
        return list(CATEGORIES) + list(cls._policies.keys())

    @classmethod
    def list_scenarios(cls) -> list[str]:
        """List all custom scenario names."""
        return list(cls._scenarios.keys())

    @classmethod
    def clear(cls) -> None:
        """Clear all custom registrations (useful for testing)."""
        cls._policies.clear()
        cls._scenarios.clear()
