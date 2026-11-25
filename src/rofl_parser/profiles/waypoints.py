"""Read waypoint entries from a decoded match movement buffer.

The entry format is documented by ROFL-X, building on Mowokuma's parser.
https://github.com/Toastaspiring/ROFL-X/blob/main/src/packet/handlers/waypoints.rs
"""

import math
import struct

ENTRY = struct.Struct("<HIf")
ABSOLUTE = struct.Struct("<h")
DELTA = struct.Struct("<b")


def read_coordinate(data: bytes, offset: int, delta: bool, previous: int) -> tuple[int, int]:
    encoding = DELTA if delta else ABSOLUTE
    coordinate, = encoding.unpack_from(data, offset)
    if delta:
        coordinate = (previous + coordinate + 0x8000) % 0x10000 - 0x8000
    return coordinate, offset + encoding.size


def read_paths(data: bytes, count: int) -> list[dict]:
    """Parse exactly the advertised entry count and buffer length."""
    if count * ENTRY.size > len(data):
        raise ValueError("waypoint entry count exceeds its buffer")

    offset = 0
    paths = []
    try:
        for _ in range(count):
            flags, unit, speed = ENTRY.unpack_from(data, offset)
            offset += ENTRY.size + (flags & 1)
            if not math.isfinite(speed) or speed < 0:
                raise ValueError("invalid waypoint movement speed")

            point_count = (flags & 0xFF) >> 1
            bitmap_size = (point_count + 2) // 4 if point_count > 1 else 0
            if offset + bitmap_size > len(data):
                raise ValueError("truncated waypoint flags")
            bitmap = int.from_bytes(data[offset:offset + bitmap_size], "little")
            offset += bitmap_size
            points = []
            x = z = 0
            for index in range(point_count):
                mask = bitmap >> (2 * (index - 1)) if index else 0
                x, offset = read_coordinate(data, offset, bool(mask & 1), x)
                z, offset = read_coordinate(data, offset, bool(mask & 2), z)
                points.append([x * 2 + 7358, z * 2 + 7412])
            paths.append({"unit": unit, "speed": speed, "points": points})
    except struct.error as exc:
        raise ValueError("truncated waypoint entry") from exc

    if offset != len(data):
        raise ValueError("waypoint entries do not fill their buffer")
    return paths
