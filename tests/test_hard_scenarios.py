"""
Tests for the Hard Scenarios pack (18 scenarios across 3 tiers).

Validates:
1. All 18 scenarios import and have correct structure
2. All rules compile without errors
3. Scenario IDs are unique
4. Rules referenced in scenarios exist in the pack
5. Turn counts match tier expectations
"""

from __future__ import annotations

import pytest

from pi_bench.policy import compile_policy_pack
from pi_bench.packs.hard_scenarios import (
    ALL_HARD_SCENARIOS,
    HARD_PACK,
    HARD_RULES,
    HARD_SCENARIOS,
    HARD_SCENARIO_PACKS,
)


class TestHardPackStructure:
    def test_pack_id(self):
        assert HARD_PACK.policy_pack_id == "hard-scenarios-v1.0.0"

    def test_rules_count(self):
        # Should have many rules — union of all 18 scenarios
        assert len(HARD_RULES) > 30

    def test_all_rules_compile(self):
        fn, warnings = compile_policy_pack(HARD_PACK)
        assert fn is not None


class TestHardScenarios:
    def test_scenario_count(self):
        assert len(HARD_SCENARIOS) == 18

    def test_scenario_ids_unique(self):
        ids = [s.scenario_id for s in HARD_SCENARIOS]
        assert len(ids) == len(set(ids))

    def test_all_scenarios_have_turns(self):
        for s in HARD_SCENARIOS:
            assert len(s.turns) > 0, f"{s.scenario_id} has no turns"

    def test_scenario_packs_exist(self):
        assert len(HARD_SCENARIO_PACKS) == len(ALL_HARD_SCENARIOS)

    def test_scenario_packs_have_rules(self):
        """Each scoped pack should contain at least 1 rule."""
        for sid, pack in HARD_SCENARIO_PACKS.items():
            assert len(pack.rules) > 0, f"{sid} scoped pack has no rules"

    def test_rules_to_check_resolve(self):
        """Every rule_id in rules_to_check must exist in the scoped pack."""
        all_rule_ids = {r.rule_id for r in HARD_RULES}
        for s in HARD_SCENARIOS:
            for rid in s.rules_to_check:
                assert rid in all_rule_ids, (
                    f"{s.scenario_id} references unknown rule '{rid}'"
                )

    def test_scoped_packs_compile(self):
        """Each scoped pack should compile without error."""
        for sid, pack in HARD_SCENARIO_PACKS.items():
            fn, warnings = compile_policy_pack(pack)
            assert fn is not None, f"{sid} scoped pack failed to compile"


class TestTierExpectations:
    """Verify turn counts match tier difficulty."""

    # Dynamically split scenarios into 3 tiers of 6 by order
    _ALL_IDS = None

    @classmethod
    def _load_ids(cls):
        if cls._ALL_IDS is None:
            cls._ALL_IDS = [s.scenario_id for s in HARD_SCENARIOS]
        return cls._ALL_IDS

    @property
    def TIER1_IDS(self):
        return set(self._load_ids()[:6])

    @property
    def TIER2_IDS(self):
        return set(self._load_ids()[6:12])

    @property
    def TIER3_IDS(self):
        return set(self._load_ids()[12:18])

    def _get(self, sid: str):
        return next(s for s in HARD_SCENARIOS if s.scenario_id == sid)

    def test_tier1_turn_count(self):
        """Tier 1: 2-3 turns."""
        for sid in self.TIER1_IDS:
            s = self._get(sid)
            assert 2 <= len(s.turns) <= 3, (
                f"{sid} should have 2-3 turns (has {len(s.turns)})"
            )

    def test_tier2_turn_count(self):
        """Tier 2: 3-4 turns."""
        for sid in self.TIER2_IDS:
            s = self._get(sid)
            assert 3 <= len(s.turns) <= 4, (
                f"{sid} should have 3-4 turns (has {len(s.turns)})"
            )

    def test_tier3_turn_count(self):
        """Tier 3: 5+ turns."""
        for sid in self.TIER3_IDS:
            s = self._get(sid)
            assert len(s.turns) >= 5, (
                f"{sid} should have 5+ turns (has {len(s.turns)})"
            )

    def test_tier3_multi_rule(self):
        """Tier 3 scenarios should check 2+ rules."""
        for sid in self.TIER3_IDS:
            s = self._get(sid)
            assert len(s.rules_to_check) >= 2, (
                f"{sid} should check 2+ rules (has {len(s.rules_to_check)})"
            )
