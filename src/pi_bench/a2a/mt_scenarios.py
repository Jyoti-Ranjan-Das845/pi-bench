"""
Multi-turn assessment scenarios for PolicyBeats.

Scenario data only — no engine logic. Imported by engine.py.

All scenarios are now loaded from data/<category>/tasks.json via the loader.
Easy scenarios (>80% pass rate on GPT-4o-mini) are filtered out.
"""

from __future__ import annotations

from pi_bench.packs.loader import load_all, load_scenario_packs

# Load all scenarios from data/
_all_data = load_all()

# Build flat list of all scenarios
_all_scenarios_raw = []
for _cat, (_pack, _scenarios) in _all_data.items():
    _all_scenarios_raw.extend(_scenarios)

# Pack maps for engine.py's resolve_policy_fn
SURFACE_G_PACKS = load_scenario_packs("conflict_resolution")
ADV_GDPR_PACKS: dict = {}  # No longer separate — merged into robustness
HARD_SCENARIO_PACKS: dict = {}  # No longer separate — merged into categories

# IDs that always pass (>80% on GPT-4o-mini) — not discriminating
_EASY_IDS = frozenset({
    "PB-CON-002", "PB-AMB-001", "PB-AMB-002", "PB-AMB-003",
    "PB-AMB-004", "PB-XS-007", "PB-XS-008",
    "PB-XS-005", "PB-XS-006", "PB-ROB-002",
    "PB-ADP-001", "PB-ADP-002",
    "PB-ROB-003",
    "PB-RST-002",
    "PB-PROC-001", "PB-PROC-002", "PB-LOG-003",
    "PB-VER-001", "PB-VER-002", "PB-COMBO-003",
    "PB-MIX-001", "PB-MIX-002", "PB-MEGA-001", "PB-MEGA-002",
    "PB-CR-002", "PB-CR-003",
    "PB-CON-001",
})

ALL_SCENARIOS = [s for s in _all_scenarios_raw if s.scenario_id not in _EASY_IDS]

__all__ = [
    "ALL_SCENARIOS",
    "SURFACE_G_PACKS",
    "ADV_GDPR_PACKS",
    "HARD_SCENARIO_PACKS",
]
