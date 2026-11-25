"""Verified packet identities and decoded object layouts for build 16.23.841.8428."""

import struct

VERSION = "16.23.841.8428"
PROTOCOL_HEADER = "8bbfcd5af2bc92db"
BINARY_SHA256 = "64a3d49aa9a3dbf69c6c2bda8e7abd42f33a0708aa655892b818476b609a161e"
PACKETS = {
    0x0167: ("BasicAttackPosMinion", 0x198CD60, 0xEA12C0),
    0x0212: ("DamageEvent", 0x1986078, 0xD26E90),
    0x0234: ("SpellCast", 0x198CDC0, 0xEB8130),
    0x0277: ("BuffAdd2", 0x198C770, 0xEB13D0),
    0x027F: ("MissileReplication", 0x198D258, 0xEAC290),
    0x0346: ("BuffRemove2", 0x198C880, 0xEB45B0),
    0x03E0: ("BasicAttackPos", 0x198CD00, 0xEA1480),
}
EVENTS = {
    0x0167: "BasicAttackMinion",
    0x0212: "DamageEvent",
    0x0234: "SpellCast",
    0x0277: "BuffAdd2",
    0x027F: "MissileTrajectory",
    0x0346: "BuffRemove2",
    0x03E0: "BasicAttack",
}
EZREAL_W_MARK_HASH = 0x00931FC8
RECALL_HASH = 0x078B982C
FACTORY_RVA = 0xCD99B0
ALLOCATOR_RVA = 0xF79190
FREE_RVAS = (0xF791C0, 0xF912D0)
SENDER_TABLE_RVA = 0x19A7640

U32 = struct.Struct("<I")
U16 = struct.Struct("<H")
F32 = struct.Struct("<f")
VEC3 = struct.Struct("<fff")


def decode_fields(packet_id: int, data: bytearray) -> dict:
    def uint(offset: int) -> int:
        return U32.unpack_from(data, offset)[0]

    def word(offset: int) -> int:
        return U16.unpack_from(data, offset)[0]

    def real(offset: int) -> float:
        return F32.unpack_from(data, offset)[0]

    def xyz(offset: int) -> tuple[float, float, float]:
        return VEC3.unpack_from(data, offset)

    if packet_id == 0x0212:
        return {
            "source": uint(0x28),
            "target": uint(0x18),
            "amount": real(0x10),
            "effect": uint(0x2C),
            "damage_meta_14": word(0x14),
            "damage_meta_1c": uint(0x1C),
            "damage_meta_20": data[0x20],
            "damage_meta_21": data[0x21],
            "damage_meta_24": uint(0x24),
        }
    if packet_id == 0x0234:
        return {
            "caster": uint(0x30),
            "spell_hash": uint(0x40),
            "spell_hash_148": uint(0x148),
            "source_xyz_candidate": xyz(0x34),
            "aim_xyz": xyz(0x5C),
            "code_92": data[0x92],
            "code_140": word(0x140),
            "cast_seq": uint(0x13C),
            "cast_t": real(0xD8),
            "cooldown_candidate": real(0x84),
            "mana_cost_candidate": real(0xDC),
            "id_94": uint(0x94),
            "id_c0": uint(0xC0),
            "id_28": uint(0x28),
            "id_b0": uint(0xB0),
            "target_count": uint(0xF0),
            "code_2c": uint(0x2C),
            "spell_flags_8c": uint(0x8C),
            "time_138": real(0x138),
        }
    if packet_id == 0x0277:
        buff = {
            "target": uint(0x0C),
            "buff_hash": uint(0x18),
            "caster": uint(0x20),
            "slot": data[0x38],
            "duration_candidate": real(0x60),
        }
        if buff["buff_hash"] == EZREAL_W_MARK_HASH:
            buff["duration_seconds"] = buff.pop("duration_candidate")
        return buff
    if packet_id == 0x0346:
        return {"target": uint(0x0C), "buff_hash": uint(0x10), "slot": data[0x18]}
    if packet_id == 0x027F:
        return {
            "trajectory_position": xyz(0x14),
            "caster": uint(0x70),
            "missile_id": uint(0xD4),
            "id_100": uint(0x100),
            "id_f0": uint(0xF0),
            "hash_80": uint(0x80),
            "cast_spell_hash": uint(0x188),
            "cast_seq": uint(0x17C),
            "cast_slot": word(0x180),
            "source_xyz": xyz(0x74),
            "aim_xyz": xyz(0x9C),
        }
    attack = {
        "attacker": uint(0x0C),
        "target": uint(0x44),
        "position": xyz(0x1C),
        "attack_sequence_candidate": uint(0x18),
        "id_3c": uint(0x3C),
        "attack_flags_38": data[0x38],
        "attack_flags_40": data[0x40],
    }
    if packet_id == 0x03E0:
        attack["target_xz"] = (real(0x48), real(0x4C))
    return attack


def event_name(packet_id: int, fields: dict) -> str:
    if packet_id == 0x0277:
        if fields["buff_hash"] == EZREAL_W_MARK_HASH:
            return "EzrealWMarkApplied"
        if fields["buff_hash"] == RECALL_HASH:
            return "RecallBuffApplied"
    if packet_id == 0x0346 and fields["buff_hash"] == RECALL_HASH:
        return "RecallBuffRemoved"
    return EVENTS[packet_id]
