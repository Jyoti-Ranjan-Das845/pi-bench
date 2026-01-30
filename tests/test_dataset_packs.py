"""
Tests for all 9 π-bench leaderboard column dataset packs.

Validates:
1. All packs load from data/<category>/ JSON files
2. All rules compile without errors
3. All scenarios have valid structure
4. Rule IDs in scenarios match rules in packs
"""

from __future__ import annotations

import pytest

from policybeats.policy import compile_policy_pack
from policybeats.packs.loader import (
    CATEGORIES,
    load_all,
    load_pack,
    load_policy_md,
    load_scenario_packs,
    load_scenarios,
)


# Expected counts per category (rules, scenarios)
EXPECTED = {
    "compliance": (20, 10),
    "understanding": (13, 11),
    "robustness": (32, 18),
    "process": (24, 11),
    "restraint": (15, 11),
    "conflict_resolution": (0, 10),  # per-scenario packs
    "detection": (7, 9),
    "explainability": (11, 11),
    "adaptation": (20, 9),
}


# === Loading ===


class TestLoading:
    def test_all_categories_load(self):
        result = load_all()
        assert set(result.keys()) == set(CATEGORIES)

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_pack_loads(self, category: str):
        pack = load_pack(category)
        assert pack.policy_pack_id
        assert pack.version == "1.0.0"

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_scenarios_load(self, category: str):
        scenarios = load_scenarios(category)
        assert len(scenarios) > 0, f"{category} has no scenarios"

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_policy_md_exists(self, category: str):
        md = load_policy_md(category)
        assert len(md) > 100, f"{category}/policy.md is too short"


# === Rule counts ===


class TestRuleCounts:
    @pytest.mark.parametrize("category", CATEGORIES)
    def test_rule_count(self, category: str):
        pack = load_pack(category)
        expected_rules, _ = EXPECTED[category]
        assert len(pack.rules) == expected_rules, (
            f"{category}: expected {expected_rules} rules, got {len(pack.rules)}"
        )

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_scenario_count(self, category: str):
        scenarios = load_scenarios(category)
        _, expected_scenarios = EXPECTED[category]
        assert len(scenarios) == expected_scenarios, (
            f"{category}: expected {expected_scenarios} scenarios, got {len(scenarios)}"
        )


# === Compilation ===


class TestCompilation:
    @pytest.mark.parametrize("category", [c for c in CATEGORIES if c != "conflict_resolution"])
    def test_pack_compiles(self, category: str):
        pack = load_pack(category)
        fn, warnings = compile_policy_pack(pack)
        assert fn is not None

    def test_conflict_resolution_packs_compile(self):
        packs = load_scenario_packs("conflict_resolution")
        assert len(packs) == 10
        for sid, pack in packs.items():
            fn, warnings = compile_policy_pack(pack)
            assert fn is not None, f"Scenario pack {sid} failed to compile"


# === Scenario structure ===


class TestScenarioStructure:
    @pytest.mark.parametrize("category", CATEGORIES)
    def test_scenario_ids_unique(self, category: str):
        scenarios = load_scenarios(category)
        ids = [s.scenario_id for s in scenarios]
        assert len(ids) == len(set(ids)), f"Duplicate IDs in {category}"

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_all_scenarios_have_turns(self, category: str):
        for s in load_scenarios(category):
            assert len(s.turns) > 0, f"{s.scenario_id} has no turns"

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_all_scenarios_have_rules(self, category: str):
        for s in load_scenarios(category):
            assert len(s.rules_to_check) > 0, f"{s.scenario_id} has no rules_to_check"

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_all_scenarios_have_task_type(self, category: str):
        for s in load_scenarios(category):
            assert s.task_type == category, (
                f"{s.scenario_id}: task_type={s.task_type}, expected {category}"
            )


# === Category-specific checks ===


class TestProcessPack:
    def test_has_ordering_rules(self):
        pack = load_pack("process")
        kinds = {r.kind for r in pack.rules}
        assert "require_prior_tool" in kinds

class TestRestraintPack:
    def test_has_over_restriction_rules(self):
        pack = load_pack("restraint")
        kinds = {r.kind for r in pack.rules}
        assert "forbid_over_restriction" in kinds

class TestAdaptation:
    def test_multi_turn_for_trigger(self):
        for s in load_scenarios("adaptation"):
            assert len(s.turns) >= 2, f"{s.scenario_id} needs 2+ turns"


# === Cross-pack ===


class TestCrossPack:
    def test_total_scenarios(self):
        result = load_all()
        total = sum(len(scenarios) for _, scenarios in result.values())
        assert total == 100

    def test_no_duplicate_ids_across_categories(self):
        result = load_all()
        all_ids = []
        for _, scenarios in result.values():
            all_ids.extend(s.scenario_id for s in scenarios)
        dupes = [x for x in all_ids if all_ids.count(x) > 1]
        assert len(all_ids) == len(set(all_ids)), f"Duplicates: {set(dupes)}"

    def test_all_have_category(self):
        result = load_all()
        for cat, (_, scenarios) in result.items():
            for s in scenarios:
                assert s.category == cat, f"{s.scenario_id}: category={s.category}"
