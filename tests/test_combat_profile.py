import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

from rofl_parser.profiles.v16_23_841_8428 import RECALL_HASH, decode_fields, event_name


class CombatProfileTests(unittest.TestCase):
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
