# Packet profiles and validation

ROFL2 stores packets in raw or Zstandard-compressed chunks and participant summaries in a JSON footer. Packet IDs and payload layouts belong to a specific game build. Use the exact build string and protocol header when selecting a profile.

The profile was verified on two local matches from `16.23.841.8428`, both with protocol header `8bbfcd5af2bc92db`. The reader handles the extra chunk byte and secondary packet timestamp observed in that build. The secondary timestamp is exported as read.

## The 16.23 combat profile

The [profile module](../src/rofl_parser/profiles/v16_23_841_8428.py) maps packet IDs to reader addresses and decoded object fields. Object offsets are measured after deserialization. Wire fields can shift with optional sections and payload variants.

| ID | Exported event | Main fields |
| --- | --- | --- |
| `0x002D` | `ContextualNotification` / Recall outcomes | Unit, contextual notification name |
| `0x0060` | `WaypointGroup` | Sequence, unit IDs, movement speeds, X/Z points |
| `0x00BB` | `EntityCreate` | Object ID, owner ID, position, object and skin names, spawn time |
| `0x00BD` | `EntityCreate` | Lane minion ID, spawner ID, spawn time |
| `0x0135` | `StatUpdate` | Observed champion gold, XP, health and primary resource updates |
| `0x0167` | `BasicAttackMinion` | Attacker, target, position |
| `0x0212` | `DamageEvent` | Source, target, amount, effect hash |
| `0x0234` | `SpellCast` | Caster, spell hash, cast sequence, timing, slot codes |
| `0x024F` | `CooldownUpdate` | Unit, spell slot, remaining cooldown and display duration |
| `0x0277` | `BuffAdd2` | Caster, target, hash, slot |
| `0x027F` | `MissileTrajectory` | Caster, missile ID, cast sequence, positions |
| `0x030F` | `MinionCreditIncrement` | Unit and +1 credit to the lane minion counter |
| `0x0346` | `BuffRemove2` | Target, hash, slot |
| `0x0348` | `ItemAcquired` / `ItemPurchase` | Unit, item, slot, price paid, gold after acquisition |
| `0x0380` | `BuffStackUpdate` | Target, caster, slot, stack count and timing |
| `0x03E0` | `BasicAttack` | Attacker, target, position |
| `0x03F3` | `LevelUp` | Unit, resulting level, update type code |
| `0x04AD` | `UnitDeath` / `MinionDeath` | Victim ID, killer ID, position when available |

The decoder selects packets by build and packet ID across the whole match. For example, every decoded `0x0234` row is a `SpellCast`, regardless of its caster. Buff rows with known hashes can get a more specific label. `EzrealWMarkApplied` is the label for the Essence Flux mark carried by a `BuffAdd2` row. Other buff applications still appear as `BuffAdd2`.

`RecallBuffApplied` and `RecallBuffRemoved` label buff transitions for any champion. The contextual notifications `RecallLeadIn`, `RecallWindDown` and `RecallCancel` emit `RecallStarted`, `RecallCompleted` and `RecallCanceled` respectively. The two validation replays had 97 completions and 34 cancellations, each matching a Recall buff lifetime.

Event JSONL includes the replay build, match name, packet ID, timestamp and decoded fields. `chunk_file_offset` is relative to the file. `block_offset` and `payload_offset` are relative to the decompressed chunk. With `--raw`, the hex bytes begin at `payload_offset`.

### Movement and spawn joins

Each `WaypointGroup` contains a `paths` array. Each path has a `unit`, `speed` and `points` array. `points` represents the route update sent to the client. Join `unit` to `entity_id` from an `EntityCreate` event within the same match. Spawn coverage currently comes from two packet classes. `kind` distinguishes `object` from `lane_minion`. Objects have an `owner_id` when one is present. Lane minions have a `spawner_id`.

On two 16.23 replays, the decoder consumed 50,494 waypoint groups and read 189,432 paths. Every one of the 3,300 recorded lane minion spawns matched a unit ID in the waypoint stream. The object spawn class contributed another 1,222 rows. The waypoint entry format is credited to [ROFL-X](https://github.com/Toastaspiring/ROFL-X/blob/main/src/packet/handlers/waypoints.rs).

### Unit deaths

`0x04AD` exports a death event with the replay block time in `t`, the victim in `fields.entity_id`, and the killing unit in `fields.killer_id`. An earlier live lane-minion spawn for the same entity ID gives the event the `MinionDeath` label. Other victims, including those with an unavailable spawn, use `UnitDeath`. The exporter reads the spawn context even when filtering the output to `--packet-id 0x04AD`. The position is `null` when the packet leaves it unset.

The two validation replays contained 4,327 death records, including 3,190 joined to lane minion spawns. Each of the 3,190 killer IDs matched the source of the final decoded damage to that minion in the same replay tick. The end-of-match CS comparison still had gaps. This event provides the killing unit, and player CS credit is tracked separately. [Historical packet family](https://github.com/Toastaspiring/ROFL-X/blob/main/src/packet/handlers/npc_die.rs)

The client handler for `0x030F` adds one to the resolved player's lane minion counter. The packet occurred 26 times across the two replays. Both lane and neutral CS totals are available in the footer. Exact minute CS remains `null` because neither event stream provides complete scoring.

### Player state and economy

The replication buffer groups field masks and length-prefixed records by entity. A full champion record identifies an entity for subsequent stat updates. The exporter reports decoded champion fields in `updates` and retains an unresolved-record count. The structure and the field order for earlier builds are documented by [rofl-parser's replication analysis](https://github.com/shyunku-libraries/rofl-parser#champion-state-replication).

In the two 16.23 samples, the last observed total gold and XP agree with the footer after integer truncation for all 20 players. The last observed levels agree as integers. The minute report keeps each field's last observed timestamp. Primary resource represents the champion's resource bar, which can contain mana, energy or another resource. `cs` remains `null`. Observed lane killing blows are reported separately.

The item acquisition packet exports the item ID, slot, price and remaining gold. A positive price gives the event the `ItemPurchase` label. Use the acquisition rows to follow item additions. Sale, undo, and component removal still require their own event mappings.

### Ability cast observations

`timeline --casts` groups a champion's `SpellCast` rows into Q, W, E and R using slot codes 0–3. It keeps the replay timestamp, spell hash and cast sequence for every row, including repeated sequence values. Some abilities emit multiple rows or show fewer rows than their final cast counters, so the report carries both counts when available. Footer rows are joined by a unique match on final earned gold, XP and level. Missing or ambiguous footer matches leave the final counts `null`. In the two validation replays, all 20 champions joined to a footer row and packet counts agreed for 57 of the 80 champion-slot combinations.

Each cast includes the latest observed primary resource in replay order and its observation time. The reported resource can precede the cast by more than one replay tick. The raw `mana_cost_candidate` remains available for comparison.

### Cooldowns and buff stacks

The client cooldown handler selects the slot at decoded object offset `+0x18` and adds the duration at `+0x14` to the current game clock. The float at `+0x20` supplies a display duration. `timeline --cooldowns` reports a ready time projected from each packet. Later updates can move that time. The two validation matches included 4,263 cooldown updates.

`BuffStackUpdate` links to the active application by target, slot and caster. A missing application leaves `buff_hash` as `null`. The join resolved 16,629 of 17,334 stack updates across the two replays. `timeline --buffs` also reports the Rising Spell Force stack history when it sees the `EzrealPassiveStacks` hash. Passive uptime is a lower bound based on closed application/removal intervals. The report counts unresolved transitions and leaves maximum-stack time `null` if no stack update is present. [Ezreal game data](https://raw.communitydragon.org/latest/game/data/characters/ezreal/ezreal.bin.json)

## Adding a build

1. Verify raw framing on multiple replays from the build. Track counts by stream and keep keyframes out of event totals.
2. Record the full version and protocol header. Use repeatable reader signatures to propose packet identities, then store each confirmed mapping in a build profile.
3. Check that each reader consumes the entire payload on multiple occurrences, including optional-field variants. Compare the decoded fields against independent evidence from matches that were excluded from discovery.
4. Record the validation and sample coverage before listing a new capability in the support table. Preserving raw packets gives a useful fallback while a semantic mapping is being investigated.

For 16.23, opponent-champion damage reconstructed from packets agrees with the footer for 20 of 20 participants, using integer truncation of the summed amounts. The two replays also provide 131 paired Recall buff applications and removals. Future profile checks can use final inventory, champion deaths, and ability counters where the replay records them at matching scope.
