# ROFL Parser

Read League of Legends replay files from disk. Inspect packet IDs, timestamps, sizes and raw payloads. On supported builds, combat export covers all champions in the recorded match stream.

Nearly all of this project's original code, tests, and documentation were AI-generated with OpenAI Codex.

## Install

```sh
python -m pip install .
```

Python 3.10 or newer is required. Install the combat extra to use the build-specific decoder.

```sh
python -m pip install ".[combat]"
```

## Usage

```sh
rofl-parser inspect match.rofl --stats
rofl-parser inspect match.rofl --stream 1 --packet-id 0x0212 --jsonl packets.jsonl --raw-hex
rofl-parser combat match.rofl --binary client-snapshot.exe --output combat.jsonl
rofl-parser match-report match.rofl --events combat.jsonl --output match_report.json
rofl-parser timeline match.rofl --events combat.jsonl
rofl-parser timeline match.rofl --events combat.jsonl --casts --cooldowns --buffs
rofl-parser timeline match.rofl --events combat.jsonl --positions --attacks --ezreal-q --ezreal-w --death-windows
```

`inspect` writes a JSON packet inventory to stdout. `--stats` also includes the participant records from the replay footer. `--stream 1` selects the match event stream. Leave that filter out to inspect keyframes and startup blocks as well.

`combat` writes one JSON object per event. It checks the exact replay build, protocol header and SHA-256 of the local PE snapshot. The snapshot is an input you supply. The decoder runs the relevant packet readers in an offline emulator.

`timeline` samples recorded gold, XP, HP, primary resource and level by minute. Select two entity IDs with `--player-id` and `--opponent-id` for gold and XP differences at 5, 10 and 15 minutes. When the footer match is unique, the report includes final lane, neutral and total CS. The minute report includes observed killing blows and recorded minion credits. Complete CS history is unavailable.

`--casts` adds observed Q/W/E/R packet timestamps and spell hashes for each selected champion. It includes the match footer's final cast counts when the participant can be identified. Use a full combat export to compare the observed history with the footer.

`--cooldowns` adds remaining cooldown and projected ready times by slot. `--buffs` adds applications, removals and stack updates, including Ezreal's Rising Spell Force history and observed uptime.

`--positions` adds timestamped attack and death coordinates where the replay supplies them. `--death-windows` includes the last 30 seconds of player-related events, resource observations and cooldown projections before each recorded champion death. `--ezreal-q` links observed Mystic Shot casts to missile impacts and range expiry. `--ezreal-w` reports Essence Flux marks and detonation damage, including damage without a matching mark.

`--attacks` shows observed basic attack records, linked projectile observations, and same-tick damage at projectile removal. Cancel counts remain unavailable.

`match-report` combines the timeline sections, entity names, per-minion evidence, and replay coverage into a versioned JSON document. Its default output is `match_report.json`. Use `--player-id` to select a player while keeping the entity catalog for opponents and units.

## Verified support

| Replay build | Container and raw packets | Combat events |
| --- | --- | --- |
| `16.19.823.0722` | Verified on one replay | Raw export |
| `16.23.841.8428` | Verified on two replays | Combat, movement, unit lifetimes, champion stat updates, level-ups, Recall and item acquisitions |

Spell casts, damage, attacks, missiles and buffs use shared packet types. Known buff effects can also receive [specific labels](docs/decoding.md#the-1623-combat-profile).

Waypoint groups contain unit IDs, movement speeds and X/Z route points. Spawn events identify lane minions, wards, plants and other objects. Death events carry the killer ID and use earlier spawns to identify lane minion deaths.

Calculating ability hit rates is a separate analysis step. Some abilities require their own rules to link casts with damage, missiles or applied effects. Item sales, inventory slot changes and full CS credit are open work. Resource cost and source position fields in spell cast rows retain their candidate labels.

See [packet profiles and output](docs/decoding.md) for field provenance and build validation.

The [analytics roadmap](docs/roadmap.md) tracks upcoming metrics, data requirements, and validation checks.

## Development

```sh
python -m pip install -e ".[combat]"
python -m unittest discover -s tests -v
```

Tests generate small synthetic replay files.

Credit to [ROFL-X](https://github.com/Toastaspiring/ROFL-X) for the transport specification and offline decoder research. The adapted emulator carries the upstream MIT notice in [combat.py](src/rofl_parser/combat.py).

### Verified coaching reports

```sh
rofl-parser match-report match.rofl --events combat.jsonl --riot-id "Limitless#EZZ" --verify-events --output match_report.json
```

`--verify-events` checks the ordered identity of every supported gameplay packet against the original replay, rejecting partial, filtered, duplicate or reordered exports. This verifies packet coverage, not the semantic correctness of decoded fields. The report records the replay SHA-256 and packet count. Existing unverified reports retain a null completeness flag. `.jsonl.gz` inputs are also accepted. `--riot-id` requires a unique participant linked by terminal statistics; it fails rather than guessing. Q summaries distinguish observed all-target hit fractions from conditional bounds that assume the observed casts are distinct footer uses. Champion-intended accuracy remains null. Farm evidence is grouped by minion type and minute; damage before another unit's killing blow is not a confirmed missed opportunity.
