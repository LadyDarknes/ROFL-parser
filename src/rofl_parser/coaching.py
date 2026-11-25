"""Entity labels, distance buckets, and observed farming evidence for match reports."""

from collections import Counter, defaultdict
from math import dist, isfinite

LANE_TYPES = {"lane_minion", "melee_minion", "caster_minion", "cannon_minion", "super_minion"}
Q_TARGET_TYPES = ("champion", "melee_minion", "caster_minion", "cannon_minion",
                  "jungle", "super_minion", "lane_minion", "object", "unknown")
Q_DISTANCE_BANDS = ("short", "medium", "long")
NEUTRAL_MODELS = {
    "sru_blue", "sru_red", "sru_gromp", "sru_murkwolf", "sru_murkwolfmini",
    "sru_razorbeak", "sru_razorbeakmini", "sru_krug", "sru_krugmini", "sru_krugminimini",
    "sru_crab", "sru_baron", "sru_riftherald", "sru_voidgrub", "sru_atakhan",
}
SUMMONER_NAMES = {
    1: "Cleanse", 3: "Exhaust", 4: "Flash", 6: "Ghost", 7: "Heal", 11: "Smite",
    12: "Teleport", 13: "Clarity", 14: "Ignite", 21: "Barrier", 32: "Mark",
}


def entity_catalog(events: list[dict], footers: dict) -> dict[int, dict]:
    catalog = {
        entity: {"name": footer.get("SKIN"), "kind": "champion", "source": "footer"}
        for entity, footer in footers.items()
    }
    for row in events:
        if row["event"] != "EntityCreate":
            continue
        fields = row["fields"]
        entity = fields["entity_id"]
        kind = fields["kind"]
        if kind == "lane_minion":
            kind = fields.get("minion_type") or kind
            name = kind.replace("_", " ").capitalize()
        else:
            name = fields.get("skin") or fields.get("name") or None
            if kind == "object" and not fields.get("owner_id") and name:
                model = name.split(".", 1)[0].lower()
                if model in NEUTRAL_MODELS or model.startswith("sru_dragon_"):
                    kind = "jungle"
        if catalog.get(entity, {}).get("source") == "footer":
            continue
        candidate = {"name": name, "kind": kind, "source": "spawn"}
        existing = catalog.get(entity)
        if existing is not None and existing != candidate:
            candidate = {"name": None, "kind": "unknown", "source": "conflicting_spawns"}
        catalog[entity] = candidate
    return catalog


def entity_label(catalog: dict, entity: int | None) -> dict:
    item = catalog.get(entity, {})
    return {"entity_id": entity, "name": item.get("name"), "kind": item.get("kind", "unknown")}


def distance_bucket(value: float | None) -> str | None:
    if value is None:
        return None
    if value < 400:
        return "short"
    if value < 800:
        return "medium"
    return "long"


def horizontal_distance(origin: list | None, point: list | None) -> float | None:
    if not origin or not point or not all(isfinite(value) for value in (*origin, *point)):
        return None
    if not (origin[0] or origin[2]) or not (point[0] or point[2]):
        return None
    return dist((origin[0], origin[2]), (point[0], point[2]))


def minion_history(events: list[dict], entities: list[int], catalog: dict) -> list[dict]:
    selected = set(entities)
    seen_damage = defaultdict(dict)
    latest = {}
    observations = defaultdict(list)
    has_deaths = False
    for row in events:
        fields = row["fields"]
        timestamp = row["t"]
        kind = row["event"]
        if kind == "DamageEvent" and fields["amount"] > 0:
            victim = fields["target"]
            if catalog.get(victim, {}).get("kind") in LANE_TYPES:
                latest[victim] = row
                if fields["source"] in selected:
                    seen_damage[victim][fields["source"]] = timestamp
        elif kind == "MinionDeath":
            has_deaths = True
            victim = fields["entity_id"]
            killer = fields["killer_id"]
            recent = seen_damage.pop(victim, {})
            last_damage = latest.pop(victim, None)
            if killer in selected or recent:
                for player in recent.keys() | ({killer} & selected):
                    delay = timestamp - recent[player] if player in recent else None
                    if player != killer and (delay is None or not 0 <= delay <= 4):
                        continue
                    effect = None
                    if (last_damage is not None and last_damage["fields"]["source"] == killer
                            and abs(last_damage["t"] - timestamp) <= .001):
                        effect = last_damage["fields"]["effect"]
                    observations[player].append({
                        "t": timestamp, "minion": entity_label(catalog, victim), "killer": entity_label(catalog, killer),
                        "outcome": "killing_blow" if player == killer else "damaged_before_other_kill",
                        "killing_effect_hash": effect, "seconds_since_player_damage": delay,
                    })
    result = []
    for entity in entities:
        rows = observations[entity]
        counts = Counter(row["outcome"] for row in rows)
        by_type = defaultdict(Counter)
        by_minute = defaultdict(Counter)
        for row in rows:
            by_type[row["minion"]["kind"]][row["outcome"]] += 1
            by_minute[int(row["t"] // 60)][row["outcome"]] += 1
        def summarize(values):
            return {key: {outcome: count[outcome] for outcome in
                          ("killing_blow", "damaged_before_other_kill")}
                    for key, count in sorted(values.items())}
        result.append({
            "entity_id": entity, "measurement": "derived",
            "validation": "observed lane minion deaths; opportunity and CS credit require additional evidence",
            "coverage": {"observed_minions": len(rows), "full_cs": None, "lane_death_rows_seen": has_deaths},
            "killing_blows": counts["killing_blow"] if has_deaths else None,
            "damaged_before_other_kill": counts["damaged_before_other_kill"] if has_deaths else None,
            "by_minion_type": summarize(by_type) if has_deaths else None,
            "by_minute": summarize(by_minute) if has_deaths else None,
            "minute_bucket_definition": "floor(death_timestamp / 60); only observed evidence; absent bucket is not confirmed zero",
            "missed_last_hit_opportunities": None, "observations": rows or None,
        })
    return result
