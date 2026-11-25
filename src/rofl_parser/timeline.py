"""Summarize observed player state and killing blows at minute boundaries."""

import json
import math
import sys
from collections import Counter, defaultdict

from .transport import Replay

STATE_FIELDS = ("total_gold", "current_gold", "xp", "hp", "max_hp",
                "primary_resource", "max_primary_resource", "level")
CHECKPOINTS = (5, 10, 15)


def observation(value: int | float, time: float, measurement: str = "direct") -> dict:
    return {"value": value, "observed_at": time, "measurement": measurement}


def load_events(file, replay: Replay) -> list[dict]:
    events = []
    for line_number, line in enumerate(file, start=1):
        row = json.loads(line)
        if row.get("version") != replay.version or row.get("match") != replay.path.stem:
            raise ValueError(f"event line {line_number} does not match the replay build or name")
        time = row["t"]
        if not math.isfinite(time):
            raise ValueError(f"event line {line_number} has an invalid timestamp")
        if row["event"] in {"StatUpdate", "LevelUp", "MinionDeath", "UnitDeath"}:
            events.append(row)
    return sorted(events, key=lambda row: row["t"])


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
    differences = {}
    snapshots = []
    index = 0
    deaths_available = any(row["event"] in {"MinionDeath", "UnitDeath"} for row in events)
    if deaths_available:
        last_hit_time.update({entity: 0.0 for entity in reported})

    for minute in range(math.floor(duration / 60) + 1):
        time = minute * 60
        while index < len(events) and events[index]["t"] <= time:
            row = events[index]
            fields = row["fields"]
            observed_at = row["t"]
            index += 1
            if row["event"] == "StatUpdate":
                if fields["unresolved_records"]:
                    for values in known.values():
                        for name in STATE_FIELDS:
                            if name != "level":
                                values.pop(name, None)
                for update in fields["updates"]:
                    entity = update["entity_id"]
                    for name in STATE_FIELDS:
                        if name in update:
                            known[entity][name] = observation(update[name], observed_at)
            elif row["event"] == "LevelUp":
                known[fields["entity_id"]]["level"] = observation(fields["level"], observed_at)
            elif row["event"] == "MinionDeath" and fields["killer_id"] in champions:
                entity = fields["killer_id"]
                last_hits[entity] += 1
                last_hit_time[entity] = observed_at
        entries = []
        for entity in reported:
            fields = {name: known[entity].get(name) for name in STATE_FIELDS}
            entries.append({
                "entity_id": entity,
                **fields,
                "cs": None,
                "observed_lane_last_hits": observation(last_hits[entity], last_hit_time[entity], "derived")
                if deaths_available else None,
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
            "unresolved_stat_records": sum(
                row["fields"]["unresolved_records"] for row in events if row["event"] == "StatUpdate"
            ),
        },
    }


def run(args) -> int:
    try:
        replay = Replay.open(args.replay)
        with args.events.open(encoding="utf-8") as source:
            events = load_events(source, replay)
        duration = replay.metadata["gameLength"] / 1000
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("invalid match duration")
        report = build_report(events, duration, args.player_id, args.opponent_id)
        result = {"match": replay.path.stem, "version": replay.version, **report}
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
