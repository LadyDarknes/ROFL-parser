# ROFL Parser

Read League of Legends replay files from disk. Inspect packet IDs, timestamps, sizes and raw payloads. On supported builds, combat export covers all champions in the recorded match stream.

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
```

`inspect` writes a JSON packet inventory to stdout. `--stats` also includes the participant records from the replay footer. `--stream 1` selects the match event stream. Leave that filter out to inspect keyframes and startup blocks as well.

`combat` writes one JSON object per event. It checks the exact replay build, protocol header and SHA-256 of the local PE snapshot. The snapshot is an input you supply. The decoder runs the relevant packet readers in an offline emulator.

## Verified support

| Replay build | Container and raw packets | Combat events |
| --- | --- | --- |
| `16.19.823.0722` | Verified on one replay | Raw export |
| `16.23.841.8428` | Verified on two replays | Spell casts, damage, basic attacks, missiles, buff applications and removals |

Spell casts, damage, attacks, missiles and buffs use shared packet types. Known buff effects can also receive [specific labels](docs/decoding.md#the-1623-combat-profile).

Calculating ability hit rates is a separate analysis step. Some abilities require their own rules to link casts with damage, missiles or applied effects. Recall completion, stat histories, movement routes and item timelines are open work. Cooldown, resource cost and cast positions retain candidate labels where their meaning is still being checked.

See [packet profiles and output](docs/decoding.md) for field provenance and build validation.

## Development

```sh
python -m pip install -e ".[combat]"
python -m unittest discover -s tests -v
```

Tests generate small synthetic replay files. Local game data and exported events belong in the ignored `local/` directory.

Credit to [ROFL-X](https://github.com/Toastaspiring/ROFL-X) for the transport specification and offline decoder research. The adapted emulator carries the upstream MIT notice in [combat.py](src/rofl_parser/combat.py).
