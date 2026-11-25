"""Verified packet identities and decoded object layouts for build 16.23.841.8428."""

import math
import struct
from collections.abc import Callable

from .champion_state import read_champion_updates
from .waypoints import read_paths

VERSION = "16.23.841.8428"
PROTOCOL_HEADER = "8bbfcd5af2bc92db"
BINARY_SHA256 = "64a3d49aa9a3dbf69c6c2bda8e7abd42f33a0708aa655892b818476b609a161e"
OBJECT_SPAWN_ID = 0x00BB
LANE_MINION_SPAWN_ID = 0x00BD
NEUTRAL_SPAWN_ID = 0x0188
UNIT_DEATH_ID = 0x04AD
CHAMPION_DEATH_ID = 0x049F
STAT_UPDATE_ID = 0x0135
LEVEL_UP_ID = 0x03F3
CONTEXT_NOTIFICATION_ID = 0x002D
ITEM_ACQUISITION_ID = 0x0348
COOLDOWN_UPDATE_ID = 0x024F
MINION_CREDIT_ID = 0x030F
BUFF_ADD_ID = 0x0277
BUFF_REMOVE_ID = 0x0346
BUFF_STACK_ID = 0x0380
MISSILE_IMPACT_ID = 0x0310
MISSILE_REMOVE_ID = 0x00D5
MISSILE_DIMENSION_ID = 0x02AA
ATTACK_CONTROL_ID = 0x02D9
ITEM_SLOT_UPDATE_ID = 0x031D
ITEM_SWAP_ID = 0x00E2
PACKETS = {
    CONTEXT_NOTIFICATION_ID: ("ContextualNotification", 0x198AFD0, 0xE01EC0),
    0x0060: ("WaypointGroup", 0x19894B0, 0xE31D90),
    OBJECT_SPAWN_ID: ("ObjectSpawn", 0x198A088, 0xE2DA70),
    LANE_MINION_SPAWN_ID: ("LaneMinionSpawn", 0x198FC50, 0xE9F7B0),
    MISSILE_REMOVE_ID: ("MissileRemove", 0x198D368, 0xEDD7B0),
    ITEM_SWAP_ID: ("SwapItemAnswer", 0x1989B68, 0xE302C0),
    STAT_UPDATE_ID: ("ReplicatedFields", 0x19869B0, 0xCFA900),
    0x0167: ("BasicAttackPosMinion", 0x198CD60, 0xEA12C0),
    NEUTRAL_SPAWN_ID: ("NeutralSpawn", 0x1985660, 0xD05A30),
    0x0212: ("DamageEvent", 0x1986078, 0xD26E90),
    0x0234: ("SpellCast", 0x198CDC0, 0xEB8130),
    COOLDOWN_UPDATE_ID: ("SetCooldown", 0x19867E0, 0xCF6DF0),
    BUFF_ADD_ID: ("BuffAdd2", 0x198C770, 0xEB13D0),
    0x027F: ("MissileReplication", 0x198D258, 0xEAC290),
    MISSILE_DIMENSION_ID: ("MissileDimensionUpdate", 0x198D3F8, 0xEF9450),
    ATTACK_CONTROL_ID: ("AttackControl", 0x1985E18, 0xCF9A10),
    MINION_CREDIT_ID: ("IncrementMinionKills", 0x198A268, 0xDCF8A0),
    MISSILE_IMPACT_ID: ("MissileImpact", 0x198D2D8, 0xEC9DB0),
    ITEM_SLOT_UPDATE_ID: ("ItemSlotUpdate", 0x19899F8, 0xDCF280),
    BUFF_REMOVE_ID: ("BuffRemove2", 0x198C880, 0xEB45B0),
    ITEM_ACQUISITION_ID: ("BuyItemAnswer", 0x19899C8, 0xDC9680),
    BUFF_STACK_ID: ("BuffUpdateCount", 0x198C908, 0xEB68E0),
    0x03E0: ("BasicAttackPos", 0x198CD00, 0xEA1480),
    LEVEL_UP_ID: ("NpcLevelUp", 0x1985D28, 0xCFA4E0),
    CHAMPION_DEATH_ID: ("NpcHeroDie", 0x1985ED0, 0xCF93E0),
    UNIT_DEATH_ID: ("NpcDeathMapView", 0x1985EA0, 0xCF8B30),
}
EVENTS = {
    CONTEXT_NOTIFICATION_ID: "ContextualNotification",
    0x0060: "WaypointGroup",
    OBJECT_SPAWN_ID: "EntityCreate",
    LANE_MINION_SPAWN_ID: "EntityCreate",
    MISSILE_REMOVE_ID: "MissileRemove",
    ITEM_SWAP_ID: "InventorySwap",
    STAT_UPDATE_ID: "StatUpdate",
    0x0167: "BasicAttackMinion",
    NEUTRAL_SPAWN_ID: "EntityCreate",
    0x0212: "DamageEvent",
    0x0234: "SpellCast",
    COOLDOWN_UPDATE_ID: "CooldownUpdate",
    BUFF_ADD_ID: "BuffAdd2",
    0x027F: "MissileTrajectory",
    MISSILE_DIMENSION_ID: "MissileDimensionUpdate",
    ATTACK_CONTROL_ID: "AttackControl",
    MINION_CREDIT_ID: "MinionCreditIncrement",
    MISSILE_IMPACT_ID: "MissileImpact",
    ITEM_SLOT_UPDATE_ID: "InventorySlotUpdate",
    BUFF_REMOVE_ID: "BuffRemove2",
    ITEM_ACQUISITION_ID: "ItemAcquired",
    BUFF_STACK_ID: "BuffStackUpdate",
    0x03E0: "BasicAttack",
    LEVEL_UP_ID: "LevelUp",
    CHAMPION_DEATH_ID: "ChampionDeath",
    UNIT_DEATH_ID: "UnitDeath",
}
EZREAL_W_MARK_HASH = 0x00931FC8
EZREAL_Q_HASH = 0x0D18B851
EZREAL_PASSIVE_HASH = 0x073842B3
RECALL_HASH = 0x078B982C
RECALL_NOTIFICATIONS = {
    "RecallLeadIn": "RecallStarted",
    "RecallWindDown": "RecallCompleted",
    "RecallCancel": "RecallCanceled",
}
FACTORY_RVA = 0xCD99B0
ALLOCATOR_RVA = 0xF79190
FREE_RVAS = (0xF791C0, 0xF912D0)
SENDER_TABLE_RVA = 0x19A7640
MEMSET_RVA = 0x1870050
TEAM_REGISTRY_RVA = 0x1CFA918
TEAM_REGISTRY_COUNT = 4
IMPACT_POSITION_TABLE_RVA = 0x192E910
LANE_MINION_TYPES = {4: "melee_minion", 5: "caster_minion", 6: "cannon_minion", 7: "super_minion"}

U32 = struct.Struct("<I")
U16 = struct.Struct("<H")
F32 = struct.Struct("<f")
VEC3 = struct.Struct("<fff")
POINTER = struct.Struct("<Q")
STRING = struct.Struct("<QI")
IMPACT_ENTRY_SIZE = 24


def rotate_byte(value: int, bits: int) -> int:
    return ((value >> bits) | (value << (8 - bits))) & 0xFF


def impact_target_byte(value: int) -> int:
    value = rotate_byte(~rotate_byte(value ^ 0xE8, 4) & 0xFF, 7)
    value = ((value >> 1) & 0x55) | ((value & 0x55) << 1)
    return rotate_byte(value, 3)


IMPACT_TARGET_BYTES = bytes(impact_target_byte(value) for value in range(256))


def read_string(data: bytearray, offset: int, read_heap: Callable[[int, int], bytes]) -> str:
    pointer, size = STRING.unpack_from(data, offset)
    return read_heap(pointer, size).decode("utf-8") if size else ""


def decode_fields(
    packet_id: int, data: bytearray, read_heap: Callable[[int, int], bytes] | None = None,
    champions: set[int] | None = None,
    *, impact_position_bytes: bytes | None = None,
) -> dict:
    def uint(offset: int) -> int:
        return U32.unpack_from(data, offset)[0]

    def word(offset: int) -> int:
        return U16.unpack_from(data, offset)[0]

    def real(offset: int) -> float:
        return F32.unpack_from(data, offset)[0]

    def xyz(offset: int) -> tuple[float, float, float]:
        return VEC3.unpack_from(data, offset)

    if packet_id in {0x0060, OBJECT_SPAWN_ID, NEUTRAL_SPAWN_ID, STAT_UPDATE_ID, CONTEXT_NOTIFICATION_ID,
                     MISSILE_IMPACT_ID} and read_heap is None:
        raise ValueError("packet reader requires access to its decoded heap buffer")

    if packet_id == CONTEXT_NOTIFICATION_ID:
        return {"entity_id": uint(0x0C), "name": read_string(data, 0x10, read_heap)}

    if packet_id == STAT_UPDATE_ID:
        count, size = uint(0x28), uint(0x20)
        pointer, = POINTER.unpack_from(data, 0x18)
        buffer = read_heap(pointer, size) if size else b""
        return read_champion_updates(buffer, count, champions if champions is not None else set())

    if packet_id == LEVEL_UP_ID:
        return {"entity_id": uint(0x0C), "level": data[0x11], "type_code": data[0x10]}

    if packet_id == ITEM_ACQUISITION_ID:
        return {
            "entity_id": uint(0x0C),
            "item_id": uint(0x20),
            "slot": uint(0x24),
            "price_paid": real(0x88),
            "gold_after": real(0x10),
        }

    if packet_id == COOLDOWN_UPDATE_ID:
        return {
            "entity_id": uint(0x0C), "slot": data[0x18],
            "remaining_seconds": real(0x14), "display_duration_seconds": real(0x20),
        }

    if packet_id == MINION_CREDIT_ID:
        return {"entity_id": uint(0x10), "delta": 1}

    if packet_id == CHAMPION_DEATH_ID:
        position = xyz(0x34)
        return {
            "entity_id": uint(0x0C), "killer_id": uint(0x50) or None, "respawn_seconds": real(0x20),
            "position": position if position[0] or position[2] else None,
        }

    if packet_id == MISSILE_IMPACT_ID:
        count = uint(0x20)
        pointer, = POINTER.unpack_from(data, 0x18)
        impacts = read_heap(pointer, count * IMPACT_ENTRY_SIZE) if count else b""
        targets = [
            U32.unpack(impacts[offset + 20:offset + 24].translate(IMPACT_TARGET_BYTES))[0]
            for offset in range(0, len(impacts), IMPACT_ENTRY_SIZE)
        ]
        result = {"missile_id": uint(0x0C), "targets": targets}
        if impact_position_bytes is not None:
            result["impacts"] = []
            for index, target in enumerate(targets):
                offset = index * IMPACT_ENTRY_SIZE + 8
                position = VEC3.unpack(impacts[offset:offset + VEC3.size].translate(impact_position_bytes))
                result["impacts"].append({
                    "target_id": target, "position": position if all(math.isfinite(x) for x in position) else None,
                })
        return result

    if packet_id == MISSILE_REMOVE_ID:
        return {"missile_id": uint(0x0C), "reason_code": data[0x10]}

    if packet_id == MISSILE_DIMENSION_ID:
        return {"missile_id": uint(0x0C), "dimension_code": data[0x10]}

    if packet_id == ATTACK_CONTROL_ID:
        return {
            "attacker": uint(0x0C), "other_entity_id": uint(0x10) or None,
            "sequence": uint(0x18), "flags": [data[0x14], *data[0x1C:0x1F]],
        }

    if packet_id == ITEM_SLOT_UPDATE_ID:
        return {
            "entity_id": uint(0x0C), "slot": data[0x16], "remaining_quantity": data[0x15],
            "gold_after": real(0x10), "action_code": data[0x14],
        }

    if packet_id == ITEM_SWAP_ID:
        return {"entity_id": uint(0x0C), "from_slot": data[0x10], "to_slot": data[0x11]}

    if packet_id == BUFF_STACK_ID:
        return {
            "target": uint(0x0C), "caster": uint(0x1C), "slot": data[0x11],
            "stacks": data[0x10], "duration_seconds": real(0x14), "elapsed_seconds": real(0x18),
        }

    if packet_id == 0x0060:
        size = uint(0x20)
        pointer, = POINTER.unpack_from(data, 0x18)
        buffer = read_heap(pointer, size) if size else b""
        return {"sequence": uint(0x10), "paths": read_paths(buffer, word(0x14))}

    if packet_id == OBJECT_SPAWN_ID:
        return {
            "kind": "object",
            "entity_id": uint(0x0C),
            "owner_id": uint(0x14) or None,
            "position": xyz(0x1C),
            "name": read_string(data, 0x38, read_heap),
            "skin": read_string(data, 0x68, read_heap),
            "spawn_time": real(0x8C),
        }

    if packet_id == LANE_MINION_SPAWN_ID:
        return {
            "kind": "lane_minion",
            "entity_id": uint(0x0C),
            "spawner_id": uint(0x1C),
            "spawn_time": real(0x24),
            "minion_type": LANE_MINION_TYPES.get(data[0x18]),
        }

    if packet_id == NEUTRAL_SPAWN_ID:
        return {
            "kind": "jungle", "entity_id": uint(0x0C), "position": xyz(0x18),
            "name": read_string(data, 0x38, read_heap), "skin": read_string(data, 0x90, read_heap),
            "mode_hint": read_string(data, 0xB0, read_heap) or None,
        }

    if packet_id == UNIT_DEATH_ID:
        position = xyz(0x34)
        return {
            "entity_id": uint(0x0C),
            "killer_id": uint(0x50) or None,
            "position": position if any(position) else None,
        }

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
    if packet_id == BUFF_ADD_ID:
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
    if packet_id == BUFF_REMOVE_ID:
        return {"target": uint(0x0C), "buff_hash": uint(0x10), "slot": data[0x18]}
    if packet_id == 0x027F:
        missile = {
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
        if missile["cast_spell_hash"] == EZREAL_Q_HASH:
            missile["q_launch_xyz"] = xyz(0x1B4)
        return missile
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
    if packet_id == CONTEXT_NOTIFICATION_ID:
        return RECALL_NOTIFICATIONS.get(fields["name"], "ContextualNotification")
    if packet_id == ITEM_ACQUISITION_ID and fields["price_paid"] > 0:
        return "ItemPurchase"
    if packet_id == BUFF_ADD_ID:
        if fields["buff_hash"] == EZREAL_W_MARK_HASH:
            return "EzrealWMarkApplied"
        if fields["buff_hash"] == RECALL_HASH:
            return "RecallBuffApplied"
    if packet_id == BUFF_REMOVE_ID and fields["buff_hash"] == RECALL_HASH:
        return "RecallBuffRemoved"
    return EVENTS[packet_id]
