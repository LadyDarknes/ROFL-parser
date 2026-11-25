"""Summarize observed player state and killing blows at minute boundaries."""

import json
import math
import sys
from collections import Counter, defaultdict

from .profiles.v16_23_841_8428 import EZREAL_PASSIVE_HASH
from .transport import Replay

STATE_FIELDS = ("total_gold", "current_gold", "xp", "hp", "max_hp",
                "primary_resource", "max_primary_resource", "level")
CHECKPOINTS = (5, 10, 15)
TIMELINE_EVENTS = {"StatUpdate", "LevelUp", "MinionDeath", "UnitDeath", "MinionCreditIncrement"}
BUFF_EVENTS = {
    "BuffAdd2", "BuffRemove2", "BuffStackUpdate", "EzrealWMarkApplied",
    "RecallBuffApplied", "RecallBuffRemoved",
}


def observation(value: int | float, time: float, measurement: str = "direct") -> dict:
    return {"value": value, "observed_at": time, "measurement": measurement}


def load_events(file, replay: Replay, *, extra_events: set[str] | None = None) -> list[dict]:
    selected = TIMELINE_EVENTS | (extra_events or set())
    events = []
    for line_number, line in enumerate(file, start=1):
        row = json.loads(line)
        if row.get("version") != replay.version or row.get("match") != replay.path.stem:
            raise ValueError(f"event line {line_number} does not match the replay build or name")
        time = row["t"]
        if not math.isfinite(time):
            raise ValueError(f"event line {line_number} has an invalid timestamp")
        if row["event"] in selected:
            events.append(row)
    return sorted(events, key=lambda row: row["t"])


def apply_state(known: dict, row: dict) -> None:
    fields = row["fields"]
    if row["event"] == "LevelUp":
        known[fields["entity_id"]]["level"] = observation(fields["level"], row["t"])
        return
    if fields["unresolved_records"]:
        for values in known.values():
            for name in STATE_FIELDS:
                if name != "level":
                    values.pop(name, None)
    for update in fields["updates"]:
        entity = update["entity_id"]
        for name in STATE_FIELDS:
            if name in update:
                known[entity][name] = observation(update[name], row["t"])


def build_report(events: list[dict], duration: float, player: int | None, opponent: int | None) -> dict:
    champions = {
        update["entity_id"]
        for row in events if row["event"] == "StatUpdate"
        for update in row["fields"]["updates"]
    }
    for entity in (player, opponent):
        if entity is not None and entity not in champions:
            raise ValueError(f"no champion stat observations for entity {entity:#010x}")
    reported = sorted(champions) if player is None else [player]
    if opponent is not None:
        reported.append(opponent)

    known = defaultdict(dict)
    last_hits: Counter[int] = Counter()
    last_hit_time: dict[int, float] = {}
    credits: Counter[int] = Counter()
    credit_time: dict[int, float] = {}
    differences = {}
    snapshots = []
    index = 0
    deaths_available = any(row["event"] == "MinionDeath" for row in events)
    credits_available = any(row["event"] == "MinionCreditIncrement" for row in events)
    if deaths_available:
        last_hit_time.update({entity: 0.0 for entity in reported})

    for minute in range(math.floor(duration / 60) + 1):
        time = minute * 60
        while index < len(events) and events[index]["t"] <= time:
            row = events[index]
            fields = row["fields"]
            observed_at = row["t"]
            index += 1
            if row["event"] in {"StatUpdate", "LevelUp"}:
                apply_state(known, row)
            elif row["event"] == "MinionDeath" and fields["killer_id"] in champions:
                entity = fields["killer_id"]
                last_hits[entity] += 1
                last_hit_time[entity] = observed_at
            elif row["event"] == "MinionCreditIncrement":
                entity = fields["entity_id"]
                credits[entity] += fields["delta"]
                credit_time[entity] = observed_at
        entries = []
        for entity in reported:
            fields = {name: known[entity].get(name) for name in STATE_FIELDS}
            entries.append({
                "entity_id": entity,
                **fields,
                "cs": None,
                "observed_lane_last_hits": observation(last_hits[entity], last_hit_time[entity], "derived")
                if deaths_available else None,
                "observed_credit_increments": {
                    "value": credits[entity], "observed_at": credit_time.get(entity), "measurement": "derived",
                } if credits_available else None,
            })
        snapshots.append({"minute": minute, "t": time, "players": entries})
        if player is not None and opponent is not None and minute in CHECKPOINTS:
            deltas = {}
            for name in ("total_gold", "xp"):
                own = known[player].get(name)
                enemy = known[opponent].get(name)
                deltas[name] = (
                    {"value": own["value"] - enemy["value"],
                     "observed_at": [own["observed_at"], enemy["observed_at"]]}
                    if own is not None and enemy is not None else None
                )
            differences[str(minute)] = {**deltas, "cs": None}

    return {
        "observed_champions": len(champions),
        "snapshots": snapshots,
        "differences": (
            {str(minute): differences.get(str(minute)) for minute in CHECKPOINTS}
            if player is not None and opponent is not None else None
        ),
        "coverage": {
            "primary_resource_type": None,
            "cs_history_complete": False,
            "unresolved_stat_records": sum(
                row["fields"]["unresolved_records"] for row in events if row["event"] == "StatUpdate"
            ),
        },
    }


def footer_by_entity(terminal: dict, participants: tuple[dict, ...]) -> dict:
    by_stats = defaultdict(list)
    for participant in participants:
        try:
            stats = tuple(int(participant[field]) for field in ("GOLD_EARNED", "EXP", "LEVEL"))
        except (KeyError, TypeError, ValueError):
            continue
        by_stats[stats].append(participant)

    matches = defaultdict(list)
    for entity, state in terminal.items():
        fields = ("total_gold", "xp", "level")
        if all(field in state for field in fields):
            stats = tuple(math.trunc(state[field]["value"]) for field in fields)
            matches[stats].append(entity)
    return {
        entities[0]: by_stats[stats][0]
        for stats, entities in matches.items()
        if len(entities) == 1 and len(by_stats.get(stats, ())) == 1
    }


def matched_footers(events: list[dict], participants: tuple[dict, ...]) -> dict:
    terminal = defaultdict(dict)
    for row in events:
        if row["event"] in {"StatUpdate", "LevelUp"}:
            apply_state(terminal, row)
    return footer_by_entity(terminal, participants)


def footer_counter(footer: dict, key: str) -> int | None:
    value = footer.get(key)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    try:
        count = int(value)
    except ValueError:
        return None
    return count if count >= 0 else None


def build_final_cs(entities: list[int], footers: dict) -> list[dict]:
    result = []
    for entity in entities:
        footer = footers.get(entity, {})
        lane = footer_counter(footer, "MINIONS_KILLED")
        neutral = footer_counter(footer, "NEUTRAL_MINIONS_KILLED")
        result.append({
            "entity_id": entity, "lane": lane, "neutral": neutral,
            "total": lane + neutral if lane is not None and neutral is not None else None,
        })
    return result


def build_cast_report(events: list[dict], entities: list[int], footers: dict) -> list[dict]:
    known = defaultdict(dict)
    casts = defaultdict(list)
    other_slots = Counter()
    available = False
    for row in events:
        if row["event"] == "StatUpdate":
            apply_state(known, row)
        elif row["event"] == "SpellCast":
            available = True
            fields = row["fields"]
            caster = fields["caster"]
            slot = fields["code_92"]
            if 0 <= slot < 4:
                casts[caster, slot].append({
                    "t": row["t"], "spell_hash": fields["spell_hash"], "cast_seq": fields["cast_seq"],
                    "primary_resource_observation": known[caster].get("primary_resource"),
                    "mana_cost_candidate": fields.get("mana_cost_candidate"),
                })
            else:
                other_slots[caster] += 1
    reports = []
    for entity in entities:
        slots = {}
        for index, slot in enumerate("QWER"):
            rows = casts[entity, index] if available else None
            footer_count = footer_counter(footers.get(entity, {}), f"SPELL{index + 1}_CAST")
            slots[slot] = {
                "observed_count": len(rows) if rows is not None else None,
                "footer_count": footer_count,
                "packet_count_agrees": len(rows) == footer_count
                if rows is not None and footer_count is not None else None,
                "observations": rows,
            }
        reports.append({
            "entity_id": entity,
            "slots": slots,
            "other_slot_rows": other_slots[entity] if available else None,
        })
    return reports


def cooldown_history(events: list[dict], entities: list[int]) -> list[dict]:
    histories = {entity: [] for entity in entities}
    for row in events:
        if row["event"] != "CooldownUpdate":
            continue
        fields = row["fields"]
        if fields["entity_id"] in histories:
            histories[fields["entity_id"]].append({
                "t": row["t"], "slot": fields["slot"], "remaining_seconds": fields["remaining_seconds"],
                "display_duration_seconds": fields["display_duration_seconds"],
                "projected_ready_at": row["t"] + max(0.0, fields["remaining_seconds"]),
            })
    return [{"entity_id": entity, "updates": rows or None} for entity, rows in histories.items()]


def ezreal_passive_history(rows: list[dict], duration: float) -> dict | None:
    history = []
    started = None
    max_started = None
    active_seconds = max_stack_seconds = 0.0
    episode_max_seconds = 0.0
    observed_stacks = False
    unresolved = 0
    for row in rows:
        if row.get("buff_hash") != EZREAL_PASSIVE_HASH or not 0 <= row["t"] <= duration:
            continue
        time = row["t"]
        if row["event"] == "BuffAdd2":
            if started is not None:
                unresolved += 1
            started = time
            max_started = None
            episode_max_seconds = 0.0
            history.append({"t": time, "stacks": 1, "event": row["event"]})
        elif row["event"] == "BuffRemove2":
            if started is None:
                unresolved += 1
            else:
                active_seconds += time - started
                if max_started is not None:
                    episode_max_seconds += time - max_started
                max_stack_seconds += episode_max_seconds
            started = max_started = None
            history.append({"t": time, "stacks": 0, "event": row["event"]})
        elif row["event"] == "BuffStackUpdate":
            stacks = row["stacks"]
            observed_stacks = True
            if started is None:
                unresolved += 1
            elif stacks == 5:
                if max_started is None:
                    max_started = time
            elif max_started is not None:
                episode_max_seconds += time - max_started
                max_started = None
            history.append({"t": time, "stacks": stacks, "event": row["event"]})
    if not history:
        return None
    return {
        "history": history,
        "observed_active_seconds": active_seconds,
        "observed_max_stack_seconds": max_stack_seconds if observed_stacks else None,
        "observed_uptime_fraction": active_seconds / duration if duration else None,
        "unresolved_transitions": unresolved + (started is not None),
    }


def buff_history(events: list[dict], entities: list[int], duration: float) -> list[dict]:
    histories = {entity: [] for entity in entities}
    for row in events:
        if row["event"] in BUFF_EVENTS and row["fields"]["target"] in histories:
            histories[row["fields"]["target"]].append({
                "t": row["t"], "event": row["event"], **row["fields"],
            })
    return [
        {"entity_id": entity, "updates": rows or None, "ezreal_passive": ezreal_passive_history(rows, duration)}
        for entity, rows in histories.items()
    ]


def run(args) -> int:
    try:
        replay = Replay.open(args.replay)
        extra_events = set()
        if args.casts:
            extra_events.add("SpellCast")
        if args.cooldowns:
            extra_events.add("CooldownUpdate")
        if args.buffs:
            extra_events.update(BUFF_EVENTS)
        with args.events.open(encoding="utf-8") as source:
            events = load_events(source, replay, extra_events=extra_events)
        duration = replay.metadata["gameLength"] / 1000
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("invalid match duration")
        report = build_report(events, duration, args.player_id, args.opponent_id)
        entities = [row["entity_id"] for row in report["snapshots"][0]["players"]]
        footers = matched_footers(events, replay.participants)
        report["final_cs"] = build_final_cs(entities, footers)
        if args.casts:
            report["casts"] = build_cast_report(events, entities, footers)
        if args.cooldowns:
            report["cooldowns"] = cooldown_history(events, entities)
        if args.buffs:
            report["buffs"] = buff_history(events, entities, duration)
        result = {"match": replay.path.stem, "version": replay.version, **report}
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
