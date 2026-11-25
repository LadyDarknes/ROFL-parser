"""Decode supported event packet classes from matching 16.23.841.8428 ROFL2 files.

Requires the optional combat dependencies and the local PE snapshot identified by the build profile.
The PE is read as data. Only the packet factory and deserializers run, in
Unicorn, with no game process, network, or native library calls.

The isolation and plaintext capture approach follows ROFL-X:
https://github.com/Toastaspiring/ROFL-X/blob/main/docs/DECODING.md
Adapted emulator setup retains the following upstream notice.

MIT License

Copyright (c) 2026 Toastaspiring

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from hashlib import sha256
import json
from pathlib import Path
import re
import struct
import sys
from typing import TextIO

try:
    import pefile
    from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
    from unicorn import UC_MODE_64, Uc, UcError
    from unicorn.x86_const import UC_X86_REG_GS_BASE, UC_X86_REG_R8, UC_X86_REG_R9
    from unicorn.x86_const import UC_X86_REG_RAX, UC_X86_REG_RCX, UC_X86_REG_RDX
    from unicorn.x86_const import UC_X86_REG_RIP, UC_X86_REG_RSP
except ImportError:
    raise ImportError("install the combat extra with python -m pip install .[combat]") from None

from .profiles.v16_23_841_8428 import (
    ALLOCATOR_RVA,
    BINARY_SHA256,
    FACTORY_RVA,
    FREE_RVAS,
    LANE_MINION_SPAWN_ID,
    MEMSET_RVA,
    OBJECT_SPAWN_ID,
    PACKETS,
    PROTOCOL_HEADER,
    SENDER_TABLE_RVA,
    TEAM_REGISTRY_COUNT,
    TEAM_REGISTRY_RVA,
    UNIT_DEATH_ID,
    VERSION,
    decode_fields,
    event_name,
)
from .transport import Replay

STACK, STACK_SIZE = 0x7FFF_0000_0000, 0x10_0000
HEAP, HEAP_SIZE = 0x7FFE_0000_0000, 0x400_0000
STOP = 0x7FFD_0000_0000
TEB = 0x7FFC_0000_0000
STUB = 0x7FFB_0000_0000
PTR = struct.Struct("<Q")
U32 = struct.Struct("<I")
I32 = struct.Struct("<i")


class DecodeError(ValueError):
    """The file identity or packet did not match the verified decoder."""


class Decoder:
    def __init__(self, binary_path: Path):
        raw = binary_path.read_bytes()
        if sha256(raw).hexdigest() != BINARY_SHA256:
            raise DecodeError(f"PE snapshot SHA-256 must be {BINARY_SHA256}")
        pe = pefile.PE(data=raw, fast_load=True)
        pe.parse_data_directories(
            directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_TLS"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_LOAD_CONFIG"],
            ]
        )
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.image_size = pe.OPTIONAL_HEADER.SizeOfImage
        self.machine = Uc(UC_ARCH_X86, UC_MODE_64)
        self.machine.mem_map(self.base, (self.image_size + 0xFFF) & ~0xFFF)
        self.cursor = HEAP
        self.capture_start = self.capture_end = 0
        self.reads: set[int] = set()
        self.plain: dict[int, int] = {}
        self.champions: set[int] = set()
        for section in pe.sections:
            self.machine.mem_write(self.base + section.VirtualAddress, section.get_data())
        for address, size in (
            (STACK, STACK_SIZE), (HEAP, HEAP_SIZE), (STOP, 0x1000), (TEB, 0x4000), (STUB, 0x1000)
        ):
            self.machine.mem_map(address, size)
        self.machine.mem_write(STOP, b"\xf4")
        self.machine.mem_write(STUB, b"\x31\xc0\xc3")
        self._set_import_stubs(pe)
        self._set_thread_environment(pe)
        self._set_team_registry()

        for rva in FREE_RVAS:
            self.machine.mem_write(self.base + rva, b"\xc3")
        allocator = self.base + ALLOCATOR_RVA
        self.machine.mem_write(allocator, b"\xc3")
        self.machine.hook_add(UC_HOOK_CODE, self._allocate_hook, begin=allocator, end=allocator)
        memset = self.base + MEMSET_RVA
        self.machine.mem_write(memset, b"\xc3")
        self.machine.hook_add(UC_HOOK_CODE, self._memset_hook, begin=memset, end=memset)
        dispatch_slot = pe.DIRECTORY_ENTRY_LOAD_CONFIG.struct.GuardCFDispatchFunctionPointer
        dispatch = self.read_ptr(dispatch_slot)
        self.machine.hook_add(UC_HOOK_CODE, self._dispatch_hook, begin=dispatch, end=dispatch)

        self.machine.hook_add(
            UC_HOOK_MEM_READ, self._capture_read, begin=HEAP, end=HEAP + 0x10000
        )
        self.machine.hook_add(
            UC_HOOK_MEM_WRITE, self._capture_write, begin=HEAP, end=HEAP + 0x10000
        )
        byte_table = bytes(self.machine.mem_read(self.base + SENDER_TABLE_RVA, 256))
        self.sender_encoding = self._sender_encoding(byte_table)

    def _set_import_stubs(self, pe: pefile.PE) -> None:
        code = next(section for section in pe.sections if section.Name.rstrip(b"\0") == b".text")
        for match in re.finditer(rb"(?:\xff\x15|\xff\x25|\x48\xff\x25)(....)", code.get_data(), re.S):
            displacement = I32.unpack(match.group(1))[0]
            slot = self.base + code.VirtualAddress + match.end() + displacement
            try:
                ptr = self.read_ptr(slot)
            except UcError:
                continue
            if not self.base <= ptr < self.base + self.image_size:
                self.machine.mem_write(slot, PTR.pack(STUB))

    def _set_thread_environment(self, pe: pefile.PE) -> None:
        tls = pe.DIRECTORY_ENTRY_TLS.struct
        length = tls.EndAddressOfRawData - tls.StartAddressOfRawData
        tls_data = bytes(self.machine.mem_read(tls.StartAddressOfRawData, length))
        self.machine.mem_write(TEB + 0x2000, tls_data)
        self.machine.mem_write(TEB + 0x1000, PTR.pack(TEB + 0x2000) * 64)
        self.machine.mem_write(TEB + 0x10, PTR.pack(STACK))
        self.machine.mem_write(TEB + 0x30, PTR.pack(TEB))
        self.machine.mem_write(TEB + 0x58, PTR.pack(TEB + 0x1000))
        self.machine.reg_write(UC_X86_REG_GS_BASE, TEB)

    def _allocate(self, size: int) -> int:
        address = (self.cursor + 15) & ~15
        size = max(size, 1)
        self.cursor = address + size
        if self.cursor > HEAP + HEAP_SIZE:
            raise DecodeError("emulated packet heap exhausted")
        self.machine.mem_write(address, bytes(size))
        return address

    def _set_team_registry(self) -> None:
        # Enum readers use the initialized session table's readiness flag and team count.
        registry = TEB + 0x3000
        self.machine.mem_write(self.base + TEAM_REGISTRY_RVA, PTR.pack(registry))
        self.machine.mem_write(registry + 0x08, bytes([TEAM_REGISTRY_COUNT]))
        self.machine.mem_write(registry + 0x70, b"\x01")

    def _allocate_hook(self, machine: Uc, address: int, size: int, data: object) -> None:
        machine.reg_write(UC_X86_REG_RAX, self._allocate(machine.reg_read(UC_X86_REG_RCX)))

    def _memset_hook(self, machine: Uc, address: int, size: int, data: object) -> None:
        # Replace the AVX implementation with the same byte writes inside the emulator.
        destination = machine.reg_read(UC_X86_REG_RCX)
        value = machine.reg_read(UC_X86_REG_RDX) & 0xFF
        length = machine.reg_read(UC_X86_REG_R8)
        if length > HEAP_SIZE:
            raise DecodeError("emulated memory fill exceeds the work area")
        if length:
            machine.mem_write(destination, bytes([value]) * length)
        machine.reg_write(UC_X86_REG_RAX, destination)

    def _dispatch_hook(self, machine: Uc, address: int, size: int, data: object) -> None:
        target = machine.reg_read(UC_X86_REG_RAX)
        spans = (
            (self.base, self.base + self.image_size),
            (HEAP, HEAP + HEAP_SIZE),
            (STACK, STACK + STACK_SIZE),
            (STUB, STUB + 0x1000),
        )
        if not any(start <= target < end for start, end in spans):
            machine.reg_write(UC_X86_REG_RAX, STUB)

    def _capture_read(self, machine: Uc, access: int, address: int, size: int, *_: object) -> None:
        if self.capture_start <= address < self.capture_end:
            self.reads.update(range(address, address + size))

    def _capture_write(
        self, machine: Uc, access: int, address: int, size: int, value: int, data: object
    ) -> None:
        if self.capture_start <= address < self.capture_end:
            # Bytewise read-modify-write after a plaintext store is the object's re-encoding pass.
            reencoding = size == 1 and address in self.reads
            for index in range(address, address + size):
                if not reencoding:
                    self.plain[index] = (value >> (8 * (index - address))) & 255
                self.reads.discard(index)

    @staticmethod
    def _sender_encoding(table: bytes) -> bytes:
        inverse = bytearray(256)
        for wire in range(256):
            intermediate = (table[wire ^ 255] + 0x54) & 255
            rotated = ((intermediate << 1) | (intermediate >> 7)) & 255
            decoded = table[(table[rotated] - 0x4C) & 255]
            inverse[decoded] = wire
        if len(set(inverse)) != 256:
            raise DecodeError("sender transform is not a byte permutation")
        return bytes(inverse)

    def _sender_prefix(self, sender: int) -> bytes:
        value = sender ^ 0x40000000 if sender & 0xFFFFFF else sender
        prefix = bytearray()
        while value >= 128:
            prefix.append(self.sender_encoding[(value & 127) | 128])
            value >>= 7
        prefix.append(self.sender_encoding[value])
        return bytes(prefix)

    def read_ptr(self, address: int) -> int:
        return PTR.unpack(self.machine.mem_read(address, PTR.size))[0]

    def _read_heap(self, address: int, size: int) -> bytes:
        if size < 0 or not HEAP <= address <= self.cursor - size:
            raise DecodeError("decoded field points outside the packet heap")
        return bytes(self.machine.mem_read(address, size))

    def _call(self, address: int, *arguments: int) -> int:
        stack = STACK + STACK_SIZE - 0x2008
        self.machine.mem_write(stack, PTR.pack(STOP))
        self.machine.reg_write(UC_X86_REG_RSP, stack)
        registers = (UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9)
        for register, argument in zip(registers, arguments):
            self.machine.reg_write(register, argument)
        self.machine.emu_start(address, STOP, count=5_000_000)
        if self.machine.reg_read(UC_X86_REG_RIP) != STOP:
            raise DecodeError("emulated packet function did not return")
        return self.machine.reg_read(UC_X86_REG_RAX)

    def decode(self, packet_id: int, sender: int, payload: bytes) -> dict:
        _, vtable_rva, function_rva = PACKETS[packet_id]
        self.cursor = HEAP
        out = self._allocate(16)
        self._call(self.base + FACTORY_RVA, out, packet_id)
        packet = self.read_ptr(out)
        vtable = self.read_ptr(packet)
        function = self.read_ptr(vtable + 8)
        if vtable != self.base + vtable_rva or function != self.base + function_rva:
            raise DecodeError("factory returned an unexpected packet class")
        packet_size = self.cursor - packet
        stream = self._sender_prefix(sender) + payload
        start = self._allocate(len(stream))
        self.machine.mem_write(start, stream)
        cursor = self._allocate(8)
        self.machine.mem_write(cursor, PTR.pack(start))
        end = start + len(stream)

        self.capture_start, self.capture_end = packet, packet + packet_size
        self.reads.clear()
        self.plain.clear()
        try:
            result = self._call(function, packet, cursor, end)
        finally:
            self.capture_start = self.capture_end = 0
        if result & 255 != 1 or self.read_ptr(cursor) != end:
            raise DecodeError("packet deserializer did not accept the entire payload")
        data = self.machine.mem_read(packet, packet_size)
        for address, value in self.plain.items():
            if packet <= address < packet + packet_size:
                data[address - packet] = value
        if U32.unpack_from(data, 0x0C)[0] != sender:
            raise DecodeError("decoded sender differs from the replay block header")
        return decode_fields(packet_id, data, self._read_heap, self.champions)


def write_rows(args: argparse.Namespace) -> None:
    replay = Replay.open(args.replay)
    if (replay.version, replay.protocol_header) != (VERSION, PROTOCOL_HEADER):
        raise DecodeError(f"replay version/protocol must be {VERSION} / {PROTOCOL_HEADER}")
    decoder = Decoder(args.binary)
    if args.output and args.output.resolve() in {args.replay.resolve(), args.binary.resolve()}:
        raise DecodeError("output path must differ from both inputs")
    destination = args.output.open("x", encoding="utf-8") if args.output else nullcontext(sys.stdout)
    try:
        with destination as output:
            export_rows(replay, decoder, args, output)
    except BaseException:
        if args.output:
            args.output.unlink()
        raise


def export_rows(replay: Replay, decoder: Decoder, args: argparse.Namespace, output: TextIO) -> None:
    count = 0
    decoder.champions.clear()
    selected = set(args.packet_id or PACKETS)
    read_ids = selected.copy()
    lane_minions: set[int] = set()
    if UNIT_DEATH_ID in selected:
        read_ids.update((LANE_MINION_SPAWN_ID, OBJECT_SPAWN_ID))
    for packet in replay.iter_packets(
        streams={1}, packet_ids=read_ids, include_payload=True
    ):
        packet_id = packet.packet_id
        try:
            fields = decoder.decode(packet_id, packet.param, packet.payload)
        except (UcError, ValueError) as exc:
            raise DecodeError(
                f"chunk {packet.chunk.chunk_id}, block 0x{packet.block_offset:x}, "
                f"ID 0x{packet_id:04x}: {exc}"
            ) from exc
        event = event_name(packet_id, fields)
        if UNIT_DEATH_ID in selected:
            if packet_id == LANE_MINION_SPAWN_ID:
                lane_minions.add(fields["entity_id"])
            elif packet_id == OBJECT_SPAWN_ID:
                lane_minions.discard(fields["entity_id"])
            elif packet_id == UNIT_DEATH_ID and fields["entity_id"] in lane_minions:
                event = "MinionDeath"
                lane_minions.remove(fields["entity_id"])
        if packet_id not in selected:
            continue
        row = {
            "version": VERSION,
            "match": replay.path.stem,
            "stream": "game_chunk",
            "chunk": packet.chunk.chunk_id,
            "chunk_file_offset": packet.chunk.file_offset,
            "block_offset": packet.block_offset,
            "payload_offset": packet.payload_offset,
            "t": packet.timestamp,
            "pid": packet_id,
            "packet_name": PACKETS[packet_id][0],
            "event": event,
            "sender": packet.param,
            "length": packet.payload_size,
            "fields": fields,
        }
        if args.raw:
            row["raw_payload_hex"] = packet.payload.hex()
        output.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
        count += 1
        if args.limit is not None and count >= args.limit:
            break


def run(args: argparse.Namespace) -> int:
    try:
        write_rows(args)
    except (OSError, ValueError, UcError, pefile.PEFormatError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
