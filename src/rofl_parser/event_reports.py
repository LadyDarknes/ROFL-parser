"""Evidence-based reports for recorded positions, spell outcomes, and deaths."""

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import math

from .coaching import Q_DISTANCE_BANDS, Q_TARGET_TYPES, SUMMONER_NAMES, distance_bucket, entity_label, horizontal_distance
from .profiles.v16_23_841_8428 import EZREAL_Q_HASH, EZREAL_W_MARK_HASH

Q_EVENTS = {"SpellCast", "MissileTrajectory", "MissileImpact", "MissileRemove", "DamageEvent"}
W_EVENTS = {"EzrealWMarkApplied", "BuffRemove2", "DamageEvent"}
EZREAL_W_HASH = 0x0D18B857
POSITION_EVENTS = {"BasicAttack", "BasicAttackMinion", "ChampionDeath", "MissileTrajectory"}
ATTACK_EVENTS = {
    "BasicAttack", "BasicAttackMinion", "AttackControl", "MissileDimensionUpdate", "MissileRemove", "DamageEvent",
}
DEATH_EVENTS = POSITION_EVENTS | {
    "SpellCast", "DamageEvent", "CooldownUpdate", "AttackControl", "BuffAdd2", "BuffRemove2",
    "BuffStackUpdate", "EzrealWMarkApplied", "RecallBuffApplied", "RecallBuffRemoved",
    "RecallStarted", "RecallCompleted", "RecallCanceled", "ItemAcquired", "ItemPurchase",
    "InventorySlotUpdate", "InventorySwap", "StatUpdate", "LevelUp", "UnitDeath", "MinionDeath",
}
DEATH_STATE_FIELDS = ("hp", "max_hp", "all_shield", "primary_resource", "max_primary_resource")
BUFF_ADDITIONS = {"BuffAdd2", "EzrealWMarkApplied", "RecallBuffApplied"}
BUFF_REMOVALS = {"BuffRemove2", "RecallBuffRemoved"}


def row_reference(row: dict) -> dict:
    return {key: row[key] for key in ("t", "pid", "chunk", "block_offset") if key in row}


def observed_point(point: list | tuple | None) -> bool:
    return bool(point and any(point) and all(math.isfinite(value) for value in point))


def replay_order(row: dict) -> tuple:
    return row["t"], row.get("chunk", 0), row.get("block_offset", 0)


def position_history(events: list[dict], entities: list[int]) -> dict:
    observed = {entity: [] for entity in entities}
    for row in events:
        kind = row["event"]
        if kind not in POSITION_EVENTS:
            continue
        f = row["fields"]
        anchors = []
        if kind == "ChampionDeath":
            if observed_point(f["position"]):
                x, _, z = f["position"]
                anchors.append((f["entity_id"], [x, z], "death_position"))
        elif kind == "MissileTrajectory":
            launch = f.get("q_launch_xyz")
            if launch and observed_point((launch[0], launch[2])):
                anchors.append((f["caster"], [launch[0], launch[2]], "mystic_shot_launch"))
        else:
            x, _, z = f["position"]
            if observed_point((x, z)):
                anchors.append((f["attacker"], [x, z], "attack_origin"))
            if observed_point(f.get("target_xz")):
                anchors.append((f["target"], list(f["target_xz"]), "attack_target_position"))
        for entity, position, source in anchors:
            if entity in observed:
                observed[entity].append({
                    **row_reference(row), "xz": position, "source": source, "measurement": "direct",
                })
    return {
        "measurement": "direct",
        "validation": "packet coordinates; continuous coverage unavailable",
        "players": [
            {"entity_id": entity, "coverage": {"observations": len(rows), "continuous": None},
             "observations": rows or None}
            for entity, rows in observed.items()
        ],
    }


def rows_near(rows: list[dict], index: list[float], time: float, before: float, after: float) -> list[dict]:
    return rows[bisect_left(index, time - before):bisect_right(index, time + after)]


def shot_geometry(missile: dict, impact: dict | None, target: int | None) -> dict:
    fields = missile["fields"]
    origin = fields.get("q_launch_xyz")
    shot = horizontal_distance(origin, fields.get("aim_xyz"))
    aim = horizontal_distance(origin, fields.get("source_xyz"))
    impact_position = None
    if target is not None and impact is not None:
        points = [r["position"] for r in impact["fields"].get("impacts", ()) if r["target_id"] == target]
        if len(points) == 1:
            impact_position = points[0]
    hit = horizontal_distance(origin, impact_position)
    return {
        "measurement": "derived_from_coordinates",
        "launch_xyz": origin, "aim_point_xyz": fields.get("source_xyz"),
        "trajectory_end_xyz": fields.get("aim_xyz"), "impact_xyz": impact_position,
        "shot_distance": shot, "shot_distance_category": distance_bucket(shot),
        "aim_distance": aim, "aim_distance_category": distance_bucket(aim),
        "hit_distance": hit, "hit_distance_category": distance_bucket(hit),
    }


def ezreal_q_history(
    events: list[dict], entities: list[int], footers: dict, catalog: dict | None = None,
) -> list[dict]:
    catalog = catalog if catalog is not None else {}
    casts = defaultdict(list)
    missiles = defaultdict(list)
    terminals = defaultdict(list)
    damage = defaultdict(list)
    for row in events:
        f = row["fields"]
        kind = row["event"]
        if kind == "SpellCast" and f["spell_hash"] == EZREAL_Q_HASH and f["code_92"] == 0:
            casts[f["caster"]].append(row)
        elif kind == "MissileTrajectory" and f["cast_spell_hash"] == EZREAL_Q_HASH:
            missiles[f["caster"], f["cast_seq"]].append(row)
        elif kind in {"MissileImpact", "MissileRemove"}:
            terminals[f["missile_id"]].append(row)
        elif kind == "DamageEvent" and f["effect"] == EZREAL_Q_HASH and f["amount"] > 0:
            damage[f["source"]].append(row)

    result = []
    for entity in entities:
        footer = footers.get(entity, {})
        if not casts[entity] and (footer.get("SKIN") or "").lower() != "ezreal":
            continue
        hits = damage[entity]
        hit_times = [row["t"] for row in hits]
        by_sequence = defaultdict(list)
        for row in casts[entity]:
            by_sequence[row["fields"]["cast_seq"]].append(row)

        observations = []
        used = set()
        outcomes = Counter()
        target_types = Counter()
        shot_bands = Counter()
        aim_bands = Counter()
        hit_bands = Counter()
        for cast in casts[entity]:
            seq = cast["fields"]["cast_seq"]
            launch = [row for row in missiles.get((entity, seq), ()) if 0 <= row["t"] - cast["t"] < 1]
            missile = launch[0] if len(launch) == 1 else None
            if missile is not None and sum(0 <= missile["t"] - row["t"] < 1 for row in by_sequence[seq]) != 1:
                missile = None

            detail = {"cast": row_reference(cast), "sequence": seq, "missile_id": None,
                      "launch": None, "terminal": None, "impact_targets": None, "damage": None,
                      "hit_target": None, "geometry": None}
            outcome = "unknown"
            reason = "missile_not_uniquely_linked"
            if missile is not None:
                missile_id = missile["fields"]["missile_id"]
                used.add(missile_id)
                start = missile["t"]
                detail.update(missile_id=missile_id, launch=row_reference(missile))
                hit_target = None
                impact = None
                reason = "terminal_not_uniquely_linked"
                terminal = [row for row in terminals.get(missile_id, ()) if 0 <= row["t"] - start < 1]
                if len(terminal) == 1:
                    end = terminal[0]
                    duration = end["t"] - start
                    detail["terminal"] = {**row_reference(end), "event": end["event"]}
                    impact_hits = rows_near(hits, hit_times, end["t"], .001, .001)
                    if end["event"] == "MissileImpact":
                        impact = end
                        reason = "impact_without_unique_positive_damage"
                        targets = end["fields"]["targets"]
                        detail["impact_targets"] = targets
                        matched = [row for row in impact_hits if row["fields"]["target"] in targets]
                        if len(matched) == 1:
                            hit = matched[0]
                            detail["damage"] = {**row_reference(hit), **hit["fields"]}
                            hit_target = hit["fields"]["target"]
                            detail["hit_target"] = entity_label(catalog, hit_target)
                            target_types[detail["hit_target"]["kind"]] += 1
                            outcome = "hit"
                            reason = "impact_and_same_tick_damage"
                    elif (end["fields"]["reason_code"] == 1 and .58 <= duration <= .65
                          and not rows_near(hits, hit_times, end["t"], .04, .04)):
                        outcome = "miss"
                        reason = "observed_range_expiry"
                    else:
                        reason = "removal_without_verified_expiry"
                geometry = shot_geometry(missile, impact, hit_target)
                detail["geometry"] = geometry
                if geometry["shot_distance_category"] is not None:
                    shot_bands[geometry["shot_distance_category"]] += 1
                if geometry["aim_distance_category"] is not None:
                    aim_bands[geometry["aim_distance_category"]] += 1
                if geometry["hit_distance_category"] is not None:
                    hit_bands[geometry["hit_distance_category"]] += 1
            detail["outcome"] = outcome
            detail["outcome_reason"] = reason
            outcomes[outcome] += 1
            observations.append(detail)

        recorded_missiles = {row["fields"]["missile_id"] for (actor, _), rows in missiles.items()
                             if actor == entity for row in rows}
        cast_times = [row["t"] for row in casts[entity]]
        missile_only = {}
        for (actor, _), rows in missiles.items():
            if actor != entity:
                continue
            for missile in rows:
                missile_id = missile["fields"]["missile_id"]
                if missile_id not in used and not rows_near(casts[entity], cast_times, missile["t"], 1, .05):
                    missile_only[missile_id] = {**row_reference(missile), "missile_id": missile_id}
        try:
            footer_casts = int(footer["SPELL1_CAST"])
        except (KeyError, TypeError, ValueError):
            footer_casts = None
        observed = len(observations)
        resolved = outcomes["hit"] + outcomes["miss"]
        # Only a conditional range: assumes each observed cast is a distinct footer use.
        missing = footer_casts - observed if footer_casts is not None and footer_casts >= observed else None
        summary = {
            "observed_hit_fraction": outcomes["hit"] / observed if observed else None,
            "resolved_hit_fraction": outcomes["hit"] / resolved if resolved else None,
            "cast_coverage_fraction": observed / footer_casts if footer_casts and missing is not None else None,
            "unobserved_footer_casts": missing,
            "conditional_all_target_hit_fraction_bounds": (
                [outcomes["hit"] / footer_casts, (footer_casts - outcomes["miss"]) / footer_casts]
                if footer_casts and missing is not None else None),
            "champion_intended_shot_accuracy": None,
            "validation": "all-target observed outcomes; conditional bounds assume distinct casts counted by footer; aim intent unknown",
        }
        result.append({
            "entity_id": entity,
            "champion_name": footer.get("SKIN"),
            "summary": summary,
            "coverage": {"cast_rows": len(observations), "footer_casts": footer_casts,
                         "linked_missiles": len(used), "missiles_without_unique_cast": len(recorded_missiles - used),
                         "missile_only_uses": len(missile_only), "shot_distances": sum(shot_bands.values()),
                         "aim_distances": sum(aim_bands.values()),
                         "hit_distances": sum(hit_bands.values())},
            "validation": "observed casts, unique missile links and verified terminal patterns",
            "measurement": "derived",
            "counts": {"hit": outcomes["hit"], "miss": outcomes["miss"],
                       "blocked": None, "unknown": outcomes["unknown"]},
            "hits_by_target_type": {kind: target_types[kind] for kind in Q_TARGET_TYPES},
            "shot_distance_counts": {band: shot_bands[band] for band in Q_DISTANCE_BANDS},
            "aim_distance_counts": {band: aim_bands[band] for band in Q_DISTANCE_BANDS},
            "hit_distance_counts": {band: hit_bands[band] for band in Q_DISTANCE_BANDS},
            "missile_only": sorted(missile_only.values(), key=lambda row: row["t"]),
            "observations": observations,
        })
    return result


def ezreal_w_history(events: list[dict], entities: list[int]) -> list[dict]:
    marks = defaultdict(list)
    removals = defaultdict(list)
    damage = defaultdict(list)
    for row in events:
        kind, f = row["event"], row["fields"]
        if kind == "EzrealWMarkApplied":
            marks[f["caster"], f["target"]].append(row)
        elif kind == "BuffRemove2" and f["buff_hash"] == EZREAL_W_MARK_HASH:
            removals[f["target"], f["slot"]].append(row)
        elif kind == "DamageEvent" and f["effect"] == EZREAL_W_HASH and f["amount"] > 0:
            damage[f["source"], f["target"]].append(row)

    found = {entity: {"marks": [], "unassigned_damage": []} for entity in entities}
    for caster, target in sorted(marks.keys() | damage.keys()):
        if caster not in found:
            continue
        pair_marks = marks[caster, target]
        pair_damage = damage[caster, target]
        damage_times = [row["t"] for row in pair_damage]
        used = set()
        for index, mark in enumerate(pair_marks):
            f = mark["fields"]
            end = mark["t"] + f["duration_seconds"] + .001
            if index + 1 < len(pair_marks):
                end = min(end, pair_marks[index + 1]["t"] - .001)
            first = bisect_left(damage_times, mark["t"] - .001)
            last = bisect_right(damage_times, end)
            hits = [i for i in range(first, last) if i not in used]
            observation = {
                "mark": row_reference(mark), "target": target, "slot": f["slot"],
                "detonation": None, "validation": "unresolved",
            }
            if len(hits) == 1:
                hit = pair_damage[hits[0]]
                used.add(hits[0])
                observation["detonation"] = {**row_reference(hit), **hit["fields"]}
                observation["validation"] = "same_source_target_in_mark_window"
                if any(abs(hit["t"] - row["t"]) <= .1 for row in removals[target, f["slot"]]):
                    observation["validation"] = "same_source_target_with_removal"
            found[caster]["marks"].append(observation)
        found[caster]["unassigned_damage"].extend(
            {**row_reference(row), **row["fields"]} for i, row in enumerate(pair_damage) if i not in used
        )
    report = []
    for entity, rows in found.items():
        marks = sorted(rows["marks"], key=lambda row: row["mark"]["t"])
        unassigned = sorted(rows["unassigned_damage"], key=lambda row: row["t"])
        if marks or unassigned:
            report.append({
                "entity_id": entity, "measurement": "derived",
                "coverage": {
                    "marks": len(marks),
                    "linked_detonations": sum(row["detonation"] is not None for row in marks),
                    "unassigned_detonation_damage": len(unassigned),
                },
                "marks": marks, "unassigned_detonation_damage": unassigned,
            })
    return report


def attack_history(events: list[dict], entities: list[int], catalog: dict | None = None) -> list[dict]:
    catalog = catalog if catalog is not None else {}
    starts = {entity: [] for entity in entities}
    control = defaultdict(list)
    projectiles = defaultdict(list)
    removals = defaultdict(list)
    damage = defaultdict(list)
    for row in events:
        kind, f = row["event"], row["fields"]
        if kind in {"BasicAttack", "BasicAttackMinion"} and f["attacker"] in starts:
            starts[f["attacker"]].append(row)
        elif kind == "AttackControl" and f["attacker"] in starts:
            control[f["attacker"], f["sequence"]].append(row)
        elif kind == "MissileDimensionUpdate":
            projectiles[f["missile_id"]].append(row)
        elif kind == "MissileRemove":
            removals[f["missile_id"]].append(row)
        elif kind == "DamageEvent" and f["source"] in starts and f["amount"] > 0:
            damage[f["source"], f["target"]].append(row)
    damage_times = {key: [row["t"] for row in rows] for key, rows in damage.items()}
    report = []
    for actor, rows in starts.items():
        counts = Counter()
        observations = []
        unit = entity_label(catalog, actor)
        ezreal = (unit["name"] or "").lower() == "ezreal"
        for start in rows:
            f = start["fields"]
            seq = f["attack_sequence_candidate"]
            signals = [r for r in control.get((actor, seq), ()) if -.05 <= r["t"] - start["t"] <= 1]
            missile_id = f["id_3c"]
            projectile = next((r for r in projectiles.get(missile_id, ()) if 0 <= r["t"] - start["t"] <= 1), None)
            cancel_candidate = (
                projectile is None and len(signals) == 1 and signals[0]["fields"]["flags"] == [1, 0, 1, 0]
            ) if ezreal and signals else None
            counts["cancel_candidates"] += cancel_candidate is True
            observation = {
                "start": row_reference(start), "target": f["target"], "sequence_candidate": seq,
                "target_entity": entity_label(catalog, f["target"]),
                "control": [{**row_reference(r), "flags": r["fields"]["flags"]} for r in signals],
                "projectile_first_observed": None, "projectile_removal": None, "projectile_delay_seconds": None,
                "same_tick_damage": None, "canceled": None, "cancel_candidate": cancel_candidate,
            }
            if projectile is not None:
                counts["projectile_observed"] += 1
                launch = projectile["t"]
                observation["projectile_first_observed"] = {**row_reference(projectile), "missile_id": missile_id}
                observation["projectile_delay_seconds"] = launch - start["t"]
                terminal = [r for r in removals.get(missile_id, ()) if 0 <= r["t"] - launch <= 2]
                if len(terminal) == 1:
                    counts["projectile_removed"] += 1
                    end = terminal[0]
                    observation["projectile_removal"] = row_reference(end)
                    key = actor, f["target"]
                    hits = rows_near(damage.get(key, []), damage_times.get(key, []), end["t"], .001, .001)
                    if len(hits) == 1:
                        counts["same_tick_damage"] += 1
                        observation["same_tick_damage"] = {**row_reference(hits[0]), **hits[0]["fields"]}
            observations.append(observation)
        report.append({
            "entity_id": actor, "unit": unit,
            "coverage": {"attack_rows": len(rows), "projectile_first_observed": counts["projectile_observed"],
                         "projectile_removed": counts["projectile_removed"],
                         "same_tick_damage": counts["same_tick_damage"], "cancel_count": None,
                         "cancel_candidates": counts["cancel_candidates"] if ezreal else None,
                         "total_attack_speed": None},
            "validation": "matched projectile ID; Ezreal cancel candidates use a control flag without a linked missile",
            "measurement": {"packet_observations": "direct", "projectile_delay_seconds": "derived"},
            "observations": observations or None,
        })
    return report


def actor_events(events: list[dict], entities: list[int]) -> dict:
    indexed = {entity: [] for entity in entities}
    for row in events:
        if row["event"] not in DEATH_EVENTS:
            continue
        f = row["fields"]
        if row["event"] == "StatUpdate":
            if f["unresolved_records"]:
                for group in indexed.values():
                    group.append({**row_reference(row), "event": "StatGap", "fields": {}})
            for update in f["updates"]:
                actor = update["entity_id"]
                if actor in indexed:
                    indexed[actor].append({**row_reference(row), "event": "StatUpdate", "fields": update})
            continue
        actors = {f.get(key) for key in ("source", "target", "entity_id", "killer_id", "caster", "attacker")}
        for actor in actors & indexed.keys():
            indexed[actor].append(row)
    return indexed


def death_state(row: dict, state: dict, cooldowns: dict, victim: int) -> None:
    f = row["fields"]
    kind = row["event"]
    if kind == "StatGap":
        state.clear()
    elif kind == "StatUpdate":
        for name in DEATH_STATE_FIELDS:
            if name in f:
                state[name] = {"value": f[name], "observed_at": row["t"], "measurement": "direct"}
    elif kind == "CooldownUpdate" and f["entity_id"] == victim:
        cooldowns[f["slot"]] = row


def state_at(state: dict, cooldowns: dict, timestamp: float) -> dict:
    return {
        **{name: state.get(name) for name in DEATH_STATE_FIELDS},
        "cooldowns": [
            {"slot": slot, "observed_at": row["t"], "measurement": "estimated",
             "remaining_seconds": max(0.0, row["fields"]["remaining_seconds"] - (timestamp - row["t"]))}
            for slot, row in sorted(cooldowns.items())
        ] or None,
    }


def predeath_availability(
    rows: list[dict], victim: int, footer: dict, state: dict, cooldowns: dict, timestamp: float,
) -> dict:
    casts = {}
    buffs = {}
    for row in rows:
        fields = row["fields"]
        kind = row["event"]
        if kind == "SpellCast" and fields["caster"] == victim:
            casts[fields["code_92"]] = row
        elif fields.get("target") == victim:
            if kind in BUFF_ADDITIONS:
                buffs[fields["slot"]] = row
            elif kind in BUFF_REMOVALS:
                active = buffs.get(fields["slot"])
                if active is not None and active["fields"]["buff_hash"] == fields["buff_hash"]:
                    del buffs[fields["slot"]]
    spells = []
    for slot in (2, 4, 5):
        update = cooldowns.get(slot)
        cast = casts.get(slot)
        remaining = None
        name = None
        configured = False
        spell_id = None
        mana = None
        if slot == 2:
            if (footer.get("SKIN") or "").lower() != "ezreal":
                continue
            name = "Arcane Shift"
            configured = cast is not None or bool(update and update["fields"]["remaining_seconds"] > 0)
            mana = state.get("primary_resource")
        else:
            raw = footer.get(f"SUMMONER_SPELL_{slot - 3}")
            try:
                spell_id = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                pass
            name = SUMMONER_NAMES.get(spell_id)
            configured = bool(spell_id)
        if configured and update is not None and (cast is None or replay_order(cast) <= replay_order(update)):
            remaining = max(0.0, update["fields"]["remaining_seconds"] - (timestamp - update["t"]))
        spells.append({
            "slot": slot, "name": name, "summoner_spell_id": spell_id,
            "cooldown_ready": remaining <= 0 if remaining is not None else None,
            "projected_remaining_seconds": remaining,
            "cooldown_observed_at": update["t"] if update else None,
            "last_cast_at": cast["t"] if cast else None,
            "mana_observed": mana,
            "mana_sufficient_at_observation": mana["value"] >= 70 if mana is not None else None,
            "can_cast": None,
        })
    return {
        "measurement": "cooldown_projection_and_direct_buff_observations",
        "spells": spells,
        "cc": {"active": None, "buffs_without_observed_removal": [
            {**row_reference(row), "buff_hash": row["fields"]["buff_hash"], "slot": slot,
             "caster": row["fields"].get("caster")}
            for slot, row in sorted(buffs.items())
            if "duration_seconds" not in row["fields"] or row["t"] + row["fields"]["duration_seconds"] >= timestamp
        ]},
    }


def death_windows(
    events: list[dict], entities: list[int], positions: dict,
    footers: dict | None = None, catalog: dict | None = None,
) -> list[dict]:
    footers = footers if footers is not None else {}
    catalog = catalog if catalog is not None else {}
    points = {p["entity_id"]: p["observations"] or [] for p in positions["players"]}
    point_times = {entity: [row["t"] for row in rows] for entity, rows in points.items()}
    result = []
    for actor, rows in actor_events(events, entities).items():
        timestamps = [row["t"] for row in rows]
        state, cooldowns = {}, {}
        index = 0
        for end_index, death in enumerate(rows):
            if death["event"] != "ChampionDeath" or death["fields"]["entity_id"] != actor:
                continue
            end = death["t"]
            start = max(0.0, end - 30)
            start_index = bisect_left(timestamps, start)
            while index < start_index:
                death_state(rows[index], state, cooldowns, actor)
                index += 1
            starting_state = state_at(state, cooldowns, start)
            final_state, final_cooldowns = state.copy(), cooldowns.copy()
            window = []
            for row in rows[start_index:end_index]:
                death_state(row, final_state, final_cooldowns, actor)
                window.append({**row_reference(row), "event": row["event"], "fields": row["fields"]})
            positions_before = [
                row for row in rows_near(points[actor], point_times[actor], end, end - start, 0.0)
                if replay_order(row) <= replay_order(death)
            ]
            result.append({
                "entity_id": actor, "start": start, "end": end,
                "death": {**row_reference(death), **death["fields"]},
                "victim": entity_label(catalog, actor),
                "killer": entity_label(catalog, death["fields"].get("killer_id")),
                "start_state": starting_state,
                "last_state_before_death": state_at(final_state, final_cooldowns, end),
                "availability_at_death": predeath_availability(
                    rows[:end_index], actor, footers.get(actor, {}), final_state, final_cooldowns, end,
                ),
                "events": window, "position_observations": positions_before or None,
                "coverage": {"events": len(window), "position_observations": len(positions_before),
                             "primary_resource_type": None, "continuous_position": None},
                "validation": "recorded champion death with packet observations",
                "measurement": {"events_and_positions": "direct", "remaining_cooldowns": "estimated"},
            })
    return sorted(result, key=lambda row: row["end"])
