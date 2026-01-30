"""Tests for Environment from_dict/to_dict round-trip with custom fields."""

from policybeats.a2a.protocol import Environment


class TestEnvironmentExtraFields:
    def test_from_dict_routes_unknown_keys_to_extra(self):
        env = Environment.from_dict({
            "user_id": "u1",
            "marketing_consent": False,
            "actor_role": "admin",
        })
        assert env.user_id == "u1"
        assert env.extra == {"marketing_consent": False, "actor_role": "admin"}

    def test_to_dict_flattens_extra(self):
        env = Environment.from_dict({
            "user_id": "u1",
            "fraud_detected": True,
        })
        d = env.to_dict()
        assert d["user_id"] == "u1"
        assert d["fraud_detected"] is True
        assert "extra" not in d  # flattened, not nested

    def test_round_trip_preserves_custom_fields(self):
        original = {
            "user_id": "u1",
            "user_region": "EU",
            "actor_role": "support",
            "high_value_transaction": True,
            "data_processing_consent": False,
        }
        env = Environment.from_dict(original)
        d = env.to_dict()
        for key in ("actor_role", "high_value_transaction", "data_processing_consent"):
            assert d[key] == original[key], f"{key} lost in round-trip"

    def test_apply_updates_stores_custom_in_extra(self):
        env = Environment()
        env.apply_updates({"fraud_detected": True})
        assert env.extra["fraud_detected"] is True
        assert env.to_dict()["fraud_detected"] is True
