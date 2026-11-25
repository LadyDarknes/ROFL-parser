import struct
import unittest

from rofl_parser.event_reports import (
    attack_history, death_windows, ezreal_q_history, ezreal_w_history, position_history, predeath_availability,
)
from rofl_parser.profiles.v16_23_841_8428 import EZREAL_Q_HASH, EZREAL_W_MARK_HASH, decode_fields


def event(t, kind, **fields):
    return {"t": t, "event": kind, "fields": fields}


class EventReportsTests(unittest.TestCase):
    def test_q_uses_missile_identity_target_and_expiry(self):
        events = []
        for time, seq in [(1, 71), (3, 72), (5, 73), (7, 74), (9, 74)]:
            events.append(event(time, "SpellCast", caster=7, cast_seq=seq, spell_hash=EZREAL_Q_HASH, code_92=0))
        for time, seq, missile in [(1.2, 71, 51), (3.2, 72, 52), (5.2, 73, 53)]:
            events.append(event(time, "MissileTrajectory", caster=7, cast_seq=seq,
                                cast_spell_hash=EZREAL_Q_HASH, missile_id=missile,
                                q_launch_xyz=[100, 0, 100], source_xyz=[500, 0, 100], aim_xyz=[1300, 0, 100]))
        events.extend([
            event(1.4, "MissileImpact", missile_id=51, targets=[14],
                  impacts=[{"target_id": 14, "position": [550, 0, 100]}]),
            event(1.4, "DamageEvent", source=7, target=14, effect=EZREAL_Q_HASH, amount=95),
            event(1.4, "DamageEvent", source=7, target=15, effect=EZREAL_Q_HASH, amount=95),
            event(3.801, "MissileRemove", missile_id=52, reason_code=1),
            event(5.3, "MissileImpact", missile_id=53, targets=[17]),
            event(5.3, "DamageEvent", source=7, target=18, effect=EZREAL_Q_HASH, amount=95),
        ])
        events.sort(key=lambda row: row["t"])
        report = ezreal_q_history(events, [7], {}, {14: {"name": "Cannon minion", "kind": "cannon_minion"}})[0]
        self.assertEqual(report["counts"], {"hit": 1, "miss": 1, "blocked": None, "unknown": 3})
        self.assertEqual(report["observations"][0]["damage"]["target"], 14)
        self.assertEqual(report["hits_by_target_type"]["cannon_minion"], 1)
        self.assertEqual(report["observations"][0]["geometry"]["hit_distance"], 450)
        self.assertEqual(report["aim_distance_counts"]["medium"], 3)
        self.assertEqual(report["observations"][1]["terminal"]["event"], "MissileRemove")
        self.assertEqual(report["observations"][2]["impact_targets"], [17])
        self.assertEqual(report["summary"]["observed_hit_fraction"], .2)
        self.assertIsNone(report["summary"]["champion_intended_shot_accuracy"])
        self.assertIsNone(report["summary"]["conditional_all_target_hit_fraction_bounds"])
        with_footer = ezreal_q_history(events, [7], {7: {"SKIN": "Ezreal", "SPELL1_CAST": "10"}})[0]
        self.assertEqual(with_footer["summary"]["conditional_all_target_hit_fraction_bounds"], [.1, .9])
        self.assertEqual(with_footer["summary"]["unobserved_footer_casts"], 5)
        inconsistent = ezreal_q_history(events, [7], {7: {"SKIN": "Ezreal", "SPELL1_CAST": "4"}})[0]
        self.assertIsNone(inconsistent["summary"]["unobserved_footer_casts"])


    def test_impact_target_is_in_encoded_buffer(self):
        obj = bytearray(0x28)
        struct.pack_into("<I", obj, 0x0C, 0x40000ABC)
        struct.pack_into("<QI", obj, 0x18, 0x1200, 1)
        impact = bytearray(24)
        impact[20:24] = bytes.fromhex("1837171f")
        self.assertEqual(decode_fields(0x0310, obj, lambda pointer, size: bytes(impact)), {
            "missile_id": 0x40000ABC, "targets": [0x4000015A],
        })

    def test_w_keeps_damage_without_a_mark_and_validates_same_slot_removal(self):
        events = [
            event(1, "EzrealWMarkApplied", caster=7, target=20, slot=4, duration_seconds=4),
            event(2, "DamageEvent", source=7, target=20, effect=0x0D18B857, amount=80),
            event(2, "BuffRemove2", target=20, slot=4, buff_hash=EZREAL_W_MARK_HASH),
            event(3, "DamageEvent", source=7, target=21, effect=0x0D18B857, amount=85),
        ]
        report = ezreal_w_history(events, [7])[0]
        self.assertEqual(report["marks"][0]["validation"], "same_source_target_with_removal")
        self.assertEqual(report["unassigned_detonation_damage"][0]["target"], 21)

    def test_attack_report_links_projectile_and_preserves_unknown_cancellation(self):
        report = attack_history([
            event(1, "BasicAttack", attacker=7, target=20, attack_sequence_candidate=3, id_3c=100),
            event(1.2, "MissileDimensionUpdate", missile_id=100),
            event(1.3, "AttackControl", attacker=7, sequence=3, flags=[1, 1, 0, 0]),
            event(1.6, "MissileRemove", missile_id=100, reason_code=1),
            event(1.6, "DamageEvent", source=7, target=20, effect=30, amount=30),
        ], [7])[0]
        self.assertEqual(report["coverage"]["same_tick_damage"], 1)
        self.assertIsNone(report["coverage"]["cancel_count"])
        self.assertAlmostEqual(report["observations"][0]["projectile_delay_seconds"], .2)
        self.assertEqual(report["observations"][0]["control"][0]["flags"], [1, 1, 0, 0])

    def test_death_window_keeps_damage_and_state_without_waypoint_interpolation(self):
        events = [
            event(5, "StatUpdate", unresolved_records=0, updates=[
                {"entity_id": 7, "hp": 500, "primary_resource": 201},
            ]),
            event(12, "StatUpdate", unresolved_records=0, updates=[
                {"entity_id": 7, "hp": 400, "primary_resource": 186},
            ]),
            event(20, "CooldownUpdate", entity_id=7, slot=0, remaining_seconds=31.0),
            event(30, "WaypointGroup", paths=[{"unit": 7, "points": [[200, 300]]}]),
            event(32, "BasicAttack", attacker=7, target=2, position=[102, 17, 410], target_xz=[120, 600]),
            event(36, "DamageEvent", source=2, target=7, amount=400, effect=19),
            event(40, "ChampionDeath", entity_id=7, killer_id=2, position=[106, 17, 500]),
            event(42, "StatUpdate", unresolved_records=0, updates=[{"entity_id": 7, "hp": 1}]),
        ]
        points = position_history(events, [7])
        report = death_windows(events, [7], points)[0]
        self.assertEqual(report["start"], 10)
        self.assertEqual(report["start_state"]["hp"]["value"], 500)
        self.assertEqual(report["last_state_before_death"]["hp"]["observed_at"], 12)
        self.assertEqual(report["last_state_before_death"]["primary_resource"]["value"], 186)
        self.assertEqual(report["last_state_before_death"]["cooldowns"][0]["remaining_seconds"], 11)
        self.assertEqual([x["xz"] for x in report["position_observations"]], [[102, 410], [106, 500]])
        self.assertTrue(any(row["fields"].get("amount") == 400 for row in report["events"]))
        self.assertIsNone(report["coverage"]["continuous_position"])

    def test_predeath_spell_projection_uses_known_spell_and_invalidates_stale_cooldown(self):
        rows = [
            event(5, "SpellCast", caster=7, code_92=2),
            event(18, "SpellCast", caster=7, code_92=4),
            event(19, "BuffAdd2", caster=8, target=7, slot=1, buff_hash=123),
        ]
        state = {"primary_resource": {"value": 55.0, "observed_at": 19.5}}
        cooldowns = {
            2: event(6, "CooldownUpdate", remaining_seconds=10.0),
            4: event(0, "CooldownUpdate", remaining_seconds=0.0),
        }
        report = predeath_availability(rows, 7, {"SKIN": "Ezreal", "SUMMONER_SPELL_1": "4"}, state, cooldowns, 20)
        e, flash, _ = report["spells"]
        self.assertTrue(e["cooldown_ready"])
        self.assertFalse(e["mana_sufficient_at_observation"])
        self.assertIsNone(e["can_cast"])
        self.assertIsNone(flash["cooldown_ready"])
        self.assertIsNone(report["cc"]["active"])
        self.assertEqual(report["cc"]["buffs_without_observed_removal"][0]["buff_hash"], 123)


if __name__ == "__main__":
    unittest.main()
