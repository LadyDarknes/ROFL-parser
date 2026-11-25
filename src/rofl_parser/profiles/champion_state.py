"""Read the champion stat groups identified in the 16.23 replay profile."""

import math
import struct

RECORD = struct.Struct("<BI")
GROUP = struct.Struct("<IB")
FLOAT = struct.Struct("<f")
CHAMPION_GROUP_MASKS = (0x0FFFFFFF, 0x7F, 0xFFFFFFFF, 0xFFFFFFFF, 0x3F, 0xFFFFFFFF)
GOLD_FIELDS = {0: "current_gold", 1: "total_gold"}
STATE_FIELDS = {
    0: "hp", 1: "max_hp", 3: "all_shield", 11: "xp", 15: "primary_resource", 16: "max_primary_resource",
}


def read_groups(buffer: bytes, count: int) -> list[tuple[int, dict[int, tuple[int, bytes]]]]:
    if count * RECORD.size > len(buffer):
        raise ValueError("replication record count exceeds its buffer")
    records = []
    offset = 0
    for _ in range(count):
        flags, entity = RECORD.unpack_from(buffer, offset)
        offset += RECORD.size
        if flags & 0x80:
            raise ValueError("unrecognized replication record flags")
        groups = {}
        for group in range(7):
            if flags & (1 << group):
                mask, length = GROUP.unpack_from(buffer, offset)
                offset += GROUP.size
                end = offset + length
                if end > len(buffer):
                    raise ValueError("truncated replication group")
                groups[group] = mask, buffer[offset:end]
                offset = end
        records.append((entity, groups))
    if offset != len(buffer):
        raise ValueError("replication records do not fill their buffer")
    return records


def read_values(
    mask: int, data: bytes, fields: dict[int, str], *, integer_fields: tuple[int, ...] = ()
) -> dict[str, float]:
    offset = 0
    values = {}
    # Read the prefix through the last verified field and retain later fields as opaque.
    for bit in range(max(fields) + 1):
        if not mask & (1 << bit):
            continue
        marker = data[offset]
        if marker == 0xFF:
            value = 0.0
            offset += 1
        elif bit in integer_fields:
            for _ in range(5):
                byte = data[offset]
                offset += 1
                if byte < 0x80:
                    break
            else:
                raise ValueError("invalid replication varint")
            continue
        else:
            if marker == 0xFE:
                offset += 1
            value, = FLOAT.unpack_from(data, offset)
            offset += FLOAT.size
        if bit in fields:
            if not math.isfinite(value):
                raise ValueError("invalid replicated stat value")
            values[fields[bit]] = value
    return values


def read_champion_updates(buffer: bytes, count: int, champions: set[int]) -> dict:
    try:
        records = read_groups(buffer, count)
    except (ValueError, struct.error):
        return {"record_count": count, "unresolved_records": count, "updates": []}

    updates = []
    unresolved = 0
    for entity, groups in records:
        full = tuple(groups.get(index, (None, b""))[0] for index in range(6)) == CHAMPION_GROUP_MASKS
        if full:
            champions.add(entity)
        if entity not in champions:
            continue
        values = {}
        try:
            if 0 in groups:
                values.update(read_values(*groups[0], GOLD_FIELDS))
            if 5 in groups:
                values.update(read_values(*groups[5], STATE_FIELDS, integer_fields=(10,)))
        except (ValueError, struct.error, IndexError):
            unresolved += 1
            continue
        if values:
            updates.append({"entity_id": entity, **values})
    return {"record_count": count, "unresolved_records": unresolved, "updates": updates}
