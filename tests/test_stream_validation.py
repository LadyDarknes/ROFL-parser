import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from rofl_parser.timeline import verify_event_stream, resolve_riot_id
from rofl_parser.profiles.v16_23_841_8428 import VERSION, PROTOCOL_HEADER


class StreamValidationTests(unittest.TestCase):
    def test_complete_gzip_and_reject_partial_duplicate_and_reordered(self):
        packets = [SimpleNamespace(chunk=SimpleNamespace(file_offset=50), block_offset=i,
                   payload_offset=i+1, packet_id=0x212, param=7, payload_size=2, timestamp=float(i))
                   for i in (10, 20)]
        replay = SimpleNamespace(version=VERSION, protocol_header=PROTOCOL_HEADER,
                                 path=Path('match.rofl'), sha256='test', iter_packets=lambda **kw: iter(packets))
        rows = [dict(version=VERSION, match='match', chunk_file_offset=p.chunk.file_offset,
                     block_offset=p.block_offset, payload_offset=p.payload_offset, pid=p.packet_id,
                     sender=p.param, length=p.payload_size, t=p.timestamp) for p in packets]
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'events.jsonl.gz'
            for variant in (rows, rows[:1], rows+rows[:1], rows[::-1], [rows[0], rows[0]]):
                with gzip.open(path, 'wt') as stream:
                    for row in variant:
                        stream.write(json.dumps(row)+'\n')
                if variant == rows:
                    self.assertEqual(verify_event_stream(path, replay)['verified_packet_rows'], 2)
                else:
                    with self.assertRaises(ValueError):
                        verify_event_stream(path, replay)

    def test_riot_id_unique_case_insensitive_and_ambiguous(self):
        player = {'RIOT_ID_GAME_NAME': 'Limitless', 'RIOT_ID_TAG_LINE': 'EZZ'}
        self.assertEqual(resolve_riot_id('limitless#ezz', {42: player}), 42)
        for query, data in [('Limitless', {42: player}), ('Other#EZZ', {42: player}),
                            ('Limitless#EZZ', {42: player, 43: player})]:
            with self.assertRaises(ValueError):
                resolve_riot_id(query, data)
