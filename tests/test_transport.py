import io
import json
import struct
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import zstandard

from rofl_parser import Replay
from rofl_parser.cli import main
from rofl_parser.transport import EXTENDED_LAYOUT_HEADER, RoflFormatError


def make_replay(version, protocol, chunks, extended=False):
    header = b"RIOT\x02\x00" + bytes.fromhex(protocol) + bytes([len(version)]) + version.encode("ascii")
    metadata = json.dumps({
        "gameLength": 45000,
        "statsJson": json.dumps([{"SKIN": "Ezreal", "SPELL1_CAST": "4"}]),
    }).encode()
    stored_chunks = []
    for chunk_id, stream, body, compressed in chunks:
        stored = zstandard.ZstdCompressor().compress(body) if compressed else body
        chunk_header = struct.pack("<IBIII", chunk_id, 0, stream << 24, len(body), len(stored) if compressed else 0)
        stored_chunks.append(chunk_header + (b"\x04" if extended else b"") + stored)
    return (
        header + b"".join(stored_chunks) + bytes(256) + metadata + struct.pack("<I", len(metadata))
    )


def absolute_block(timestamp, packet_id, param, payload, secondary=None):
    header = struct.pack("<Bf", 0, timestamp)
    if secondary is not None:
        header += struct.pack("<f", secondary)
    return header + struct.pack("<IHI", len(payload), packet_id, param) + payload


class ReplayTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / "match.rofl"

    def test_classic_offsets_and_param_deltas_across_chunks(self):
        first = absolute_block(3.0, 0x005F, 0x400000AE, b"abc")
        delta = struct.pack("<BBBb", 0xF0, 50, 1, -1) + b"z"
        keyframe = absolute_block(4.0, 0x005F, 0x400000AE, b"keyframe")
        self.path.write_bytes(make_replay("16.19.823.0722", "6bfab33e871a4a58", [
            (1, 1, first + delta, True),
            (2, 2, keyframe, False),
        ]))
        replay = Replay.open(self.path)
        self.assertEqual(replay.participants[0]["SPELL1_CAST"], "4")
        packets = list(replay.iter_packets(streams={1}, packet_ids={0x005F}, include_payload=True))
        self.assertEqual([(p.packet_id, p.param, p.payload) for p in packets], [
            (0x005F, 0x400000AE, b"abc"),
            (0x005F, 0x400000AD, b"z"),
        ])
        self.assertAlmostEqual(packets[1].timestamp, 3.05)
        self.assertEqual((packets[1].block_offset, packets[1].payload_offset), (len(first), len(first) + 4))
        self.assertEqual(len(list(replay.iter_packets())), 3)

    def test_extended_timestamp_with_compressed_and_raw_chunks(self):
        version, protocol = EXTENDED_LAYOUT_HEADER
        first = absolute_block(10.0, 0x0277, 0x40000154, b"example", secondary=27.0)
        delta = struct.pack("<BBfBb", 0xF0, 25, 27.025, 1, 0) + b"x"
        other = absolute_block(12.0, 0x0346, 0x40000154, b"end", secondary=29.0)
        self.path.write_bytes(make_replay(version, protocol, [
            (1, 1, first + delta, True),
            (2, 1, other, False),
        ], extended=True))
        packets = list(Replay.open(self.path).iter_packets())
        self.assertEqual([p.packet_id for p in packets], [0x0277, 0x0277, 0x0346])
        self.assertEqual([p.payload_size for p in packets], [7, 1, 3])
        self.assertEqual([p.payload for p in packets], [None, None, None])
        self.assertAlmostEqual(packets[1].timestamp, 10.025)
        self.assertAlmostEqual(packets[1].secondary_timestamp, 27.025, places=4)
        self.assertEqual(packets[2].block_offset, 0)

    def test_inspect_exports_filters_and_optional_footer(self):
        block = absolute_block(3.0, 0x005F, 0x400000AE, b"abc")
        self.path.write_bytes(make_replay("16.19.823.0722", "6bfab33e871a4a58", [(1, 1, block, False)]))
        output = self.directory / "packets.jsonl"
        with redirect_stdout(io.StringIO()) as stdout:
            code = main([
                "inspect", str(self.path), "--packet-id", "0x005f", "--stream", "1",
                "--raw-hex", "--jsonl", str(output), "--stats",
            ])
        self.assertEqual(code, 0)
        inventory, = json.loads(stdout.getvalue())
        self.assertEqual(inventory["SelectedPacketCount"], 1)
        self.assertEqual(inventory["Participants"][0]["SKIN"], "Ezreal")
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["RawPayloadHex"], "616263")

    def test_truncated_block_does_not_replace_existing_output(self):
        block = absolute_block(3.0, 0x005F, 0x400000AE, b"abc")[:-1]
        self.path.write_bytes(make_replay("16.19.823.0722", "6bfab33e871a4a58", [(1, 1, block, False)]))
        output = self.directory / "packets.jsonl"
        output.write_text("existing file", encoding="utf-8")
        with self.assertRaisesRegex(RoflFormatError, "truncated payload"):
            list(Replay.open(self.path).iter_packets())
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["inspect", str(self.path), "--jsonl", str(output)]), 1)
        self.assertEqual(output.read_text(encoding="utf-8"), "existing file")


if __name__ == "__main__":
    unittest.main()
