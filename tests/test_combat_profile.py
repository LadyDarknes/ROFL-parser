import argparse
import importlib.util
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from rofl_parser.transport import Chunk, Packet
from rofl_parser.profiles.v16_23_841_8428 import RECALL_HASH, decode_fields, event_name
from rofl_parser.profiles.waypoints import read_paths


class CombatProfileTests(unittest.TestCase):
    def test_unit_death_preserves_killer_and_uses_null_for_absent_position(self):
        body = bytearray(0x58)
        struct.pack_into("<I", body, 0x0C, 0x400002E6)
        struct.pack_into("<I", body, 0x50, 0x40000154)
        self.assertEqual(decode_fields(0x04AD, body), {
            "entity_id": 0x400002E6, "killer_id": 0x40000154, "position": None,
        })
        struct.pack_into("<fff", body, 0x34, 1200.0, 15.0, 3400.0)
        self.assertEqual(decode_fields(0x04AD, body)["position"], (1200.0, 15.0, 3400.0))

    @unittest.skipUnless(
        importlib.util.find_spec("unicorn") and importlib.util.find_spec("pefile"),
        "combat extra is optional",
    )
    def test_filtered_deaths_use_spawn_context_and_stop_at_the_row_limit(self):
        from rofl_parser.combat import export_rows

        lane, unknown, reused = 0x400002E6, 0x400002E7, 0x400002E8
        chunk = Chunk(1, 0, 1 << 24, 100, 0, 12, 30, None)
        source = (
            (0x00BD, lane), (0x00BD, reused), (0x00BB, reused),
            (0x04AD, lane), (0x04AD, unknown), (0x04AD, reused), (0x04AD, lane),
        )
        packets = [
            Packet(chunk, index, index, 0, index, None, packet_id, entity, 1, b"x")
            for index, (packet_id, entity) in enumerate(source, start=1)
        ]
        replay = Mock(path=Path("sample.rofl"))
        replay.iter_packets.return_value = iter(packets)
        decoder = Mock()
        decoder.decode.side_effect = lambda packet_id, sender, payload: {"entity_id": sender}
        output = io.StringIO()
        export_rows(replay, decoder, argparse.Namespace(packet_id=[0x04AD], raw=False, limit=3), output)

        replay.iter_packets.assert_called_once_with(
            streams={1}, packet_ids={0x00BD, 0x00BB, 0x04AD}, include_payload=True,
        )
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r["event"] for r in rows], ["MinionDeath", "UnitDeath", "UnitDeath"])
        self.assertEqual([r["fields"]["entity_id"] for r in rows], [lane, unknown, reused])
        self.assertEqual(decoder.decode.call_count, 6)

    def test_waypoint_group_decodes_signed_deltas_and_multiple_units(self):
        first = struct.pack("<HIf", 0x0205, 0x40000051, 350.0)
        first += b"\x00\x01" + struct.pack("<hhbh", -100, 100, -5, 160)
        second = struct.pack("<HIfhh", 2, 0x40000052, 0.0, 0, -50)
        data = first + second
        body = bytearray(0x28)
        struct.pack_into("<IIQI", body, 0x10, 941, 2, 0x500, len(data))

        def read_heap(address, size):
            self.assertEqual((address, size), (0x500, len(data)))
            return data

        self.assertEqual(decode_fields(0x0060, body, read_heap), {
            "sequence": 941,
            "paths": [
                {"unit": 0x40000051, "speed": 350.0, "points": [[7158, 7612], [7148, 7732]]},
                {"unit": 0x40000052, "speed": 0.0, "points": [[7358, 7312]]},
            ],
        })

    def test_waypoint_buffer_must_have_exactly_the_advertised_entries(self):
        entry = struct.pack("<HIfhh", 2, 0x40000051, 350.0, 0, 0)
        with self.assertRaisesRegex(ValueError, "truncated waypoint"):
            read_paths(entry[:-1], 1)
        with self.assertRaisesRegex(ValueError, "do not fill"):
            read_paths(entry + b"\x00", 1)

    def test_object_and_lane_spawns_report_distinct_entity_relationships(self):
        obj = bytearray(0x98)
        struct.pack_into("<II", obj, 0x0C, 0x40000071, 1)
        struct.pack_into("<I", obj, 0x14, 0x40000051)
        struct.pack_into("<fff", obj, 0x1C, 1000.0, -15.0, 3500.0)
        struct.pack_into("<QI", obj, 0x38, 0x120, 13)
        struct.pack_into("<QI", obj, 0x68, 0x150, 9)
        struct.pack_into("<f", obj, 0x8C, 32.0)
        strings = {0x120: b"YellowTrinket", 0x150: b"SightWard"}
        fields = decode_fields(0x00BB, obj, lambda address, size: strings[address][:size])
        self.assertEqual(fields, {
            "kind": "object",
            "entity_id": 0x40000071,
            "owner_id": 0x40000051,
            "position": (1000.0, -15.0, 3500.0),
            "name": "YellowTrinket",
            "skin": "SightWard",
            "spawn_time": 32.0,
        })
        lane_minion = bytearray(0x2C)
        struct.pack_into("<I", lane_minion, 0x0C, 0x400002E6)
        struct.pack_into("<I", lane_minion, 0x1C, 0x4000012C)
        struct.pack_into("<f", lane_minion, 0x24, 30.0)
        self.assertEqual(decode_fields(0x00BD, lane_minion), {
            "kind": "lane_minion",
            "entity_id": 0x400002E6,
            "spawner_id": 0x4000012C,
            "spawn_time": 30.0,
        })
        self.assertEqual(event_name(0x00BB, fields), "EntityCreate")

    def test_damage_object_keeps_source_and_target_distinct(self):
        body = bytearray(0x30)
        struct.pack_into("<f", body, 0x10, 18.5)
        struct.pack_into("<I", body, 0x18, 0x40000033)
        struct.pack_into("<II", body, 0x28, 0x40000037, 0x07123456)
        fields = decode_fields(0x0212, body)
        self.assertEqual(fields["amount"], 18.5)
        self.assertEqual(fields["source"], 0x40000037)
        self.assertEqual(fields["target"], 0x40000033)
        self.assertEqual(fields["effect"], 0x07123456)

    def test_recall_linkage_preserves_target_hash_and_slot(self):
        target = 0x40000052
        slot = 12
        add = bytearray(0x68)
        remove = bytearray(0x20)
        struct.pack_into("<I", add, 0x0C, target)
        struct.pack_into("<I", add, 0x18, RECALL_HASH)
        struct.pack_into("<I", add, 0x20, target)
        add[0x38] = slot
        struct.pack_into("<IIB", remove, 0x0C, target, RECALL_HASH, 0)
        remove[0x18] = slot
        added = decode_fields(0x0277, add)
        removed = decode_fields(0x0346, remove)
        self.assertEqual(event_name(0x0277, added), "RecallBuffApplied")
        self.assertEqual(event_name(0x0346, removed), "RecallBuffRemoved")
        self.assertEqual({key: added[key] for key in ("target", "buff_hash", "slot")}, removed)
        self.assertEqual(event_name(0x0346, {**removed, "buff_hash": 1}), "BuffRemove2")

    @unittest.skipUnless(
        importlib.util.find_spec("unicorn") and importlib.util.find_spec("pefile"),
        "combat extra is optional",
    )
    def test_binary_fingerprint_checked_before_pe_parsing(self):
        from rofl_parser.combat import DecodeError, Decoder

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unrecognized.exe"
            path.write_bytes(b"synthetic")
            with self.assertRaisesRegex(DecodeError, "SHA-256"):
                Decoder(path)


if __name__ == "__main__":
    unittest.main()
