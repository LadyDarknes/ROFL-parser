import struct
import unittest

from rofl_parser.profiles.champion_state import CHAMPION_GROUP_MASKS, read_champion_updates
from rofl_parser.profiles.v16_23_841_8428 import decode_fields, event_name
from rofl_parser.timeline import build_cast_report, build_report


def update(time, entity, **values):
    return {
        "t": time, "event": "StatUpdate",
        "fields": {"updates": [{"entity_id": entity, **values}], "unresolved_records": 0},
    }


class PlayerStateTests(unittest.TestCase):
    def test_replication_identifies_champion_and_decodes_later_deltas(self):
        entity = 0x40000210
        state = struct.pack("<ff", 800.0, 900.0) + bytes([0xFF]) * 9
        state += struct.pack("<f", 660.0) + bytes([0xFF]) * 3 + struct.pack("<ff", 300.0, 400.0)
        data_by_group = {0: struct.pack("<ff", 500.0, 1400.0), 5: state}
        full = bytearray(struct.pack("<BI", 0x3F, entity))
        for group, mask in enumerate(CHAMPION_GROUP_MASKS):
            data = data_by_group.get(group, b"")
            full.extend(struct.pack("<IB", mask, len(data)) + data)
        champions = set()
        first = read_champion_updates(full, 1, champions)
        self.assertEqual(champions, {entity})
        self.assertEqual(first["updates"], [{
            "entity_id": entity, "current_gold": 500.0, "total_gold": 1400.0, "hp": 800.0,
            "max_hp": 900.0, "xp": 660.0, "primary_resource": 300.0, "max_primary_resource": 400.0,
        }])
        delta = struct.pack("<BIIB", 0x20, entity, 1, 1) + b"\xff"
        self.assertEqual(read_champion_updates(delta, 1, champions)["updates"], [{
            "entity_id": entity, "hp": 0.0,
        }])
        self.assertEqual(read_champion_updates(delta[:-1], 1, champions)["unresolved_records"], 1)

    def test_level_recall_and_item_labels_use_their_decoded_fields(self):
        level = bytearray(0x14)
        struct.pack_into("<IBB", level, 0x0C, 0x40000210, 1, 5)
        self.assertEqual(decode_fields(0x03F3, level), {
            "entity_id": 0x40000210, "level": 5, "type_code": 1,
        })
        self.assertEqual(event_name(0x002D, {"name": "RecallWindDown"}), "RecallCompleted")
        self.assertEqual(event_name(0x002D, {"name": "RecallCancel"}), "RecallCanceled")
        item = bytearray(0x90)
        struct.pack_into("<If", item, 0x0C, 0x40000210, 50.0)
        struct.pack_into("<II", item, 0x20, 1036, 2)
        struct.pack_into("<f", item, 0x88, 350.0)
        fields = decode_fields(0x0348, item)
        self.assertEqual(fields, {
            "entity_id": 0x40000210, "item_id": 1036, "slot": 2,
            "price_paid": 350.0, "gold_after": 50.0,
        })
        self.assertEqual(event_name(0x0348, fields), "ItemPurchase")
        self.assertEqual(event_name(0x0348, {**fields, "price_paid": 0}), "ItemAcquired")

    def test_report_keeps_observation_times_and_missing_cs(self):
        events = [
            update(0, 1, total_gold=500, xp=0, hp=500),
            update(0, 2, total_gold=500, xp=0),
            {"t": 15, "event": "LevelUp", "fields": {"entity_id": 1, "level": 2}},
            {"t": 60, "event": "MinionDeath", "fields": {"killer_id": 1}},
            update(297, 2, total_gold=1600, xp=800),
            update(299, 1, total_gold=1700, xp=850),
            {"t": 310, "event": "StatUpdate", "fields": {"updates": [], "unresolved_records": 2}},
        ]
        data = build_report(events, 370, 1, 2)
        player = data["snapshots"][1]["players"][0]
        self.assertEqual(player["level"]["value"], 2)
        self.assertEqual(player["observed_lane_last_hits"]["value"], 1)
        self.assertIsNone(player["cs"])
        self.assertEqual(data["differences"], {
            "5": {
                "total_gold": {"value": 100, "observed_at": [299, 297]},
                "xp": {"value": 50, "observed_at": [299, 297]},
                "cs": None,
            },
            "10": None, "15": None,
        })
        self.assertEqual(data["coverage"]["unresolved_stat_records"], 2)
        self.assertIsNone(data["snapshots"][6]["players"][0]["hp"])
        self.assertEqual(data["snapshots"][6]["players"][0]["level"]["value"], 2)

    def test_cast_report_preserves_repeated_sequences_and_ambiguous_footer(self):
        events = [
            update(0, 40, total_gold=500.8, xp=600.1),
            update(0, 10, total_gold=500.8, xp=600.1),
            {"t": 1, "event": "LevelUp", "fields": {"entity_id": 40, "level": 2}},
            {"t": 1, "event": "LevelUp", "fields": {"entity_id": 10, "level": 3}},
        ]
        for time, slot in [(5, 0), (8, 0), (10, 5)]:
            events.append({
                "t": time, "event": "SpellCast",
                "fields": {"caster": 40, "code_92": slot, "spell_hash": 27, "cast_seq": 31},
            })
        participants = (
            {"GOLD_EARNED": "500", "EXP": "600", "LEVEL": "3", "SPELL1_CAST": "4"},
            {"GOLD_EARNED": "500", "EXP": "600", "LEVEL": "2", "SPELL1_CAST": "1"},
        )
        report = build_cast_report(events, [40], participants)[0]
        self.assertEqual(report["slots"]["Q"], {
            "observed_count": 2, "footer_count": 1, "packet_count_agrees": False,
            "observations": [
                {"t": 5, "spell_hash": 27, "cast_seq": 31}, {"t": 8, "spell_hash": 27, "cast_seq": 31},
            ],
        })
        self.assertEqual(report["other_slot_rows"], 1)
        ambiguous = build_cast_report(events, [40], (*participants, participants[1]))[0]
        self.assertIsNone(ambiguous["slots"]["Q"]["footer_count"])
        absent = build_cast_report(events[:4], [40], participants)[0]
        self.assertIsNone(absent["slots"]["Q"]["observed_count"])
        self.assertEqual(absent["slots"]["Q"]["footer_count"], 1)


if __name__ == "__main__":
    unittest.main()
