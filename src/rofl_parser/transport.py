#!/usr/bin/env python3
"""Inspect local League of Legends ROFL2 files and export framed replay packets.

The legacy framing follows the public ROFL-X transport specification:
https://github.com/Toastaspiring/ROFL-X/blob/main/docs/ROFL_FORMAT.md
The extended framing is validated on build 16.23.841.8428, protocol header
8bbfcd5af2bc92db. Payload bytes are preserved without interpreting game events.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Collection, Iterator, TextIO

import zstandard


U16 = struct.Struct("<H")
U32 = struct.Struct("<I")
F32 = struct.Struct("<f")
I8 = struct.Struct("<b")
CHUNK_HEADER = struct.Struct("<IBIII")
EXTENDED_LAYOUT_HEADER = ("16.23.841.8428", "8bbfcd5af2bc92db")
STREAM_NAMES = {
    1: "game_chunk",
    2: "keyframe",
    3: "initial_keyframe",
    4: "start_sentinel",
}


class RoflFormatError(ValueError):
    """A file or a block did not satisfy its replay framing."""


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: int
    slot: int
    stream_tag: int
    raw_size: int
    compressed_size: int
    file_offset: int
    body_offset: int
    extension: int | None

    @property
    def stream(self) -> int:
        return self.stream_tag >> 24

    @property
    def stored_size(self) -> int:
        return self.compressed_size or self.raw_size


@dataclass(frozen=True, slots=True)
class Packet:
    chunk: Chunk
    block_offset: int
    payload_offset: int
    marker: int
    timestamp: float
    secondary_timestamp: float | None
    packet_id: int
    param: int
    payload_size: int
    payload: bytes | None


@dataclass(frozen=True, slots=True)
class Replay:
    path: Path
    version: str
    protocol_header: str
    metadata: dict
    participants: tuple[dict, ...]
    chunks: tuple[Chunk, ...]
    _data: bytes

    @classmethod
    def open(cls, path: str | Path) -> Replay:
        path = Path(path)
        data = path.read_bytes()
        if len(data) < 276 or data[:6] != b"RIOT\x02\x00":
            raise RoflFormatError(f"{path.name}: expected a ROFL2 container")

        chunks_start = 15 + data[14]
        metadata_size = U32.unpack_from(data, len(data) - 4)[0]
        metadata_start = len(data) - 4 - metadata_size
        chunks_end = metadata_start - 256
        if chunks_start == 15 or chunks_start >= chunks_end or metadata_size == 0:
            raise RoflFormatError(f"{path.name}: invalid header/metadata boundary")

        version = data[15:chunks_start].decode("ascii")
        protocol_header = data[6:14].hex()
        extended = (version, protocol_header) == EXTENDED_LAYOUT_HEADER
        metadata = json.loads(data[metadata_start:-4])
        if not isinstance(metadata, dict):
            raise RoflFormatError(f"{path.name}: metadata is not a JSON object")
        players = metadata.get("statsJson")
        if isinstance(players, str):
            players = json.loads(players)
        if not isinstance(players, list) or any(not isinstance(row, dict) for row in players):
            raise RoflFormatError(f"{path.name}: invalid statsJson participant list")

        chunks = tuple(iter_chunks(data, chunks_start, chunks_end, extended))
        return cls(path, version, protocol_header, metadata, tuple(players), chunks, data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self._data).hexdigest()

    def iter_packets(
        self,
        *,
        streams: Collection[int] | None = None,
        packet_ids: Collection[int] | None = None,
        include_payload: bool = False,
    ) -> Iterator[Packet]:
        decompressor = zstandard.ZstdDecompressor()
        for chunk in self.chunks:
            if streams is not None and chunk.stream not in streams:
                continue
            begin = chunk.body_offset
            stored = self._data[begin:begin + chunk.stored_size]
            body = stored
            if chunk.compressed_size:
                try:
                    content_size = zstandard.frame_content_size(stored)
                    if content_size not in (-1, chunk.raw_size):
                        raise RoflFormatError(
                            f"chunk at 0x{chunk.file_offset:x}: Zstandard size {content_size} "
                            f"differs from declared size {chunk.raw_size}"
                        )
                    body = decompressor.decompress(
                        stored, max_output_size=chunk.raw_size, allow_extra_data=False
                    )
                except zstandard.ZstdError as exc:
                    raise RoflFormatError(
                        f"chunk at 0x{chunk.file_offset:x}: {exc}"
                    ) from exc
            if len(body) != chunk.raw_size:
                raise RoflFormatError(f"chunk at 0x{chunk.file_offset:x}: wrong decoded size")
            yield from iter_blocks(chunk, body, packet_ids, include_payload)


def iter_chunks(data: bytes, start: int, end: int, extended: bool) -> Iterator[Chunk]:
    cursor = start
    header_size = CHUNK_HEADER.size + int(extended)
    while cursor < end:
        if cursor + header_size > end:
            raise RoflFormatError(f"truncated chunk header at 0x{cursor:x}")
        chunk_id, slot, stream, raw_size, compressed_size = CHUNK_HEADER.unpack_from(data, cursor)
        extension = data[cursor + CHUNK_HEADER.size] if extended else None
        if extended and extension != 4:
            raise RoflFormatError(f"unexpected chunk extension at 0x{cursor:x}")
        body_offset = cursor + header_size
        chunk = Chunk(
            chunk_id, slot, stream, raw_size, compressed_size, cursor, body_offset, extension
        )
        next_cursor = body_offset + chunk.stored_size
        if next_cursor > end:
            raise RoflFormatError(
                f"chunk at 0x{cursor:x} runs into signature; check the replay version"
            )
        yield chunk
        cursor = next_cursor


def iter_blocks(
    chunk: Chunk,
    body: bytes,
    packet_ids: Collection[int] | None,
    include_payload: bool,
) -> Iterator[Packet]:
    cursor = 0
    timestamp = 0.0
    packet_id = 0
    param = 0
    extended = chunk.extension is not None
    secondary_timestamp = None
    while cursor < len(body):
        start = cursor
        marker = body[cursor]
        cursor += 1
        try:
            if marker & 0x80:
                timestamp += body[cursor] / 1000
                cursor += 1
            else:
                timestamp = F32.unpack_from(body, cursor)[0]
                cursor += F32.size
            if extended:
                secondary_timestamp = F32.unpack_from(body, cursor)[0]
                cursor += F32.size
            if marker & 0x10:
                length = body[cursor]
                cursor += 1
            else:
                length = U32.unpack_from(body, cursor)[0]
                cursor += U32.size
            if not marker & 0x40:
                packet_id = U16.unpack_from(body, cursor)[0]
                cursor += U16.size
            if marker & 0x20:
                delta = I8.unpack_from(body, cursor)[0]
                param = (param + delta) & 0xFFFFFFFF
                cursor += I8.size
            else:
                param = U32.unpack_from(body, cursor)[0]
                cursor += U32.size
        except (IndexError, struct.error) as exc:
            raise RoflFormatError(
                f"chunk at 0x{chunk.file_offset:x}: truncated block header at +0x{start:x}"
            ) from exc
        if not math.isfinite(timestamp) or (
            secondary_timestamp is not None and not math.isfinite(secondary_timestamp)
        ):
            raise RoflFormatError(
                f"chunk at 0x{chunk.file_offset:x}: non-finite timestamp at +0x{start:x}"
            )
        payload_end = cursor + length
        if payload_end > len(body):
            raise RoflFormatError(
                f"chunk at 0x{chunk.file_offset:x}: truncated payload at +0x{start:x}"
            )
        if packet_ids is None or packet_id in packet_ids:
            payload = body[cursor:payload_end] if include_payload else None
            yield Packet(
                chunk, start, cursor, marker, timestamp, secondary_timestamp, packet_id,
                param, length, payload
            )
        cursor = payload_end


def stream_name(stream: int) -> str:
    return STREAM_NAMES.get(stream, f"stream_{stream}")


def packet_row(replay: Replay, packet: Packet) -> dict:
    row = {
        "Replay": replay.path.name,
        "Version": replay.version,
        "Stream": stream_name(packet.chunk.stream),
        "ChunkID": packet.chunk.chunk_id,
        "ChunkFileOffset": packet.chunk.file_offset,
        "BlockOffsetInDecodedChunk": packet.block_offset,
        "PayloadOffsetInDecodedChunk": packet.payload_offset,
        "TimestampSeconds": packet.timestamp,
        "SecondaryTimestampRaw": packet.secondary_timestamp,
        "Marker": f"0x{packet.marker:02X}",
        "PacketID": f"0x{packet.packet_id:04X}",
        "Param": f"0x{packet.param:08X}",
        "PayloadSize": packet.payload_size,
    }
    if packet.payload is not None:
        row["RawPayloadHex"] = packet.payload.hex()
    return row


def inventory(
    replay: Replay,
    streams: Collection[int] | None = None,
    packet_ids: Collection[int] | None = None,
    packet_output: TextIO | None = None,
    include_payload: bool = False,
    include_stats: bool = False,
) -> dict:
    size_counts: dict[tuple[int, int], Counter[int]] = {}
    stream_counts: Counter[str] = Counter()
    for packet in replay.iter_packets(
        streams=streams,
        packet_ids=packet_ids,
        include_payload=packet_output is not None and include_payload,
    ):
        key = (packet.chunk.stream, packet.packet_id)
        sizes = size_counts.get(key)
        if sizes is None:
            sizes = size_counts[key] = Counter()
        sizes[packet.payload_size] += 1
        stream_counts[stream_name(packet.chunk.stream)] += 1
        if packet_output is not None:
            print(json.dumps(packet_row(replay, packet), separators=(",", ":")), file=packet_output)

    items = []
    for (stream, packet_id), sizes in sorted(size_counts.items()):
        items.append({
            "Stream": stream_name(stream),
            "PacketID": f"0x{packet_id:04X}",
            "Count": sizes.total(),
            "PayloadSizeMin": min(sizes),
            "PayloadSizeMax": max(sizes),
            "PayloadSizeFrequency": dict(sorted(sizes.items())),
        })
    result = {
        "Replay": replay.path.name,
        "Version": replay.version,
        "ProtocolHeaderHex": replay.protocol_header,
        "SHA256": replay.sha256,
        "GameLengthMs": replay.metadata.get("gameLength"),
        "ParticipantCount": len(replay.participants),
        "ContainerChunks": dict(Counter(stream_name(chunk.stream) for chunk in replay.chunks)),
        "SelectedStreams": sorted(streams) if streams is not None else None,
        "SelectedPacketIDs": sorted(packet_ids) if packet_ids is not None else None,
        "SelectedPacketCount": stream_counts.total(),
        "PacketCountByStream": dict(stream_counts),
        "DistinctPacketIDsByStream": dict(Counter(item["Stream"] for item in items)),
        "PacketInventory": items,
    }
    if include_stats:
        result["Participants"] = replay.participants
    return result


def number(value: str, maximum: int) -> int:
    try:
        parsed = int(value, 16 if value.lower().startswith("0x") else 10)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid decimal or hexadecimal value: {value}") from None
    if not 0 <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"expected a value between 0 and {maximum}")
    return parsed


def check_output_path(path: Path, inputs: list[Path]) -> None:
    for source in inputs:
        if path.resolve() == source.resolve() or (path.exists() and path.samefile(source)):
            raise ValueError(f"output path is a replay source: {path}")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("replays", type=Path, nargs="+")
    parser.add_argument("--stream", action="append", type=lambda value: number(value, 0xFF),
                        help="repeatable stream ID; 1 is the game stream, 2 the keyframes")
    parser.add_argument("--packet-id", action="append", type=lambda value: number(value, 0xFFFF),
                        help="repeatable numeric or 0x-prefixed packet ID")
    parser.add_argument("--jsonl", type=Path, help="write one line per matching packet to PATH")
    parser.add_argument("--raw-hex", action="store_true", help="include full payload hex in JSONL")
    parser.add_argument("--stats", action="store_true", help="include participant stats from the replay footer")


def run(args: argparse.Namespace) -> int:
    if args.raw_hex and args.jsonl is None:
        print("error: --raw-hex requires --jsonl", file=sys.stderr)
        return 2

    streams = set(args.stream) if args.stream is not None else None
    packet_ids = set(args.packet_id) if args.packet_id is not None else None
    provisional = None
    try:
        if args.jsonl is not None:
            check_output_path(args.jsonl, args.replays)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=args.jsonl.parent,
                prefix=f".{args.jsonl.name}.", suffix=".part", delete=False
            ) as destination:
                provisional = Path(destination.name)
                results = [
                    inventory(
                        Replay.open(path), streams, packet_ids, destination, args.raw_hex, args.stats
                    )
                    for path in args.replays
                ]
            os.replace(provisional, args.jsonl)
        else:
            results = [
                inventory(Replay.open(path), streams, packet_ids, include_stats=args.stats)
                for path in args.replays
            ]
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if provisional is not None:
            provisional.unlink(missing_ok=True)

    print(json.dumps(results, indent=2))
    return 0
