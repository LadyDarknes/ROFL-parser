# Packet profiles and validation

ROFL2 stores packets in raw or Zstandard-compressed chunks and participant summaries in a JSON footer. Packet IDs and payload layouts belong to a specific game build. Use the exact build string and protocol header when selecting a profile.

The profile was verified on two local matches from `16.23.841.8428`, both with protocol header `8bbfcd5af2bc92db`. The reader handles the extra chunk byte and secondary packet timestamp observed in that build. The secondary timestamp is exported as read.

## The 16.23 combat profile

The [profile module](../src/rofl_parser/profiles/v16_23_841_8428.py) maps packet IDs to reader addresses and decoded object fields. Object offsets are measured after deserialization. Wire fields can shift with optional sections and payload variants.

| ID | Exported event | Main fields |
| --- | --- | --- |
| `0x0167` | `BasicAttackMinion` | Attacker, target, position |
| `0x0212` | `DamageEvent` | Source, target, amount, effect hash |
| `0x0234` | `SpellCast` | Caster, spell hash, cast sequence, timing, slot codes |
| `0x0277` | `BuffAdd2` | Caster, target, hash, slot |
| `0x027F` | `MissileTrajectory` | Caster, missile ID, cast sequence, positions |
| `0x0346` | `BuffRemove2` | Target, hash, slot |
| `0x03E0` | `BasicAttack` | Attacker, target, position |

The decoder selects packets by build and packet ID across the whole match. For example, every decoded `0x0234` row is a `SpellCast`, regardless of its caster. Buff rows with known hashes can get a more specific label. `EzrealWMarkApplied` is the label for the Essence Flux mark carried by a `BuffAdd2` row. Other buff applications still appear as `BuffAdd2`.

`RecallBuffApplied` and `RecallBuffRemoved` label buff transitions for any champion. A completed or interrupted recall can be classified once a separate finish signal is verified.

Event JSONL includes the replay build, match name, packet ID, timestamp and decoded fields. `chunk_file_offset` is relative to the file. `block_offset` and `payload_offset` are relative to the decompressed chunk. With `--raw`, the hex bytes begin at `payload_offset`.

## Adding a build

1. Verify raw framing on multiple replays from the build. Track counts by stream and keep keyframes out of event totals.
2. Record the full version and protocol header. Use repeatable reader signatures to propose packet identities, then store each confirmed mapping in a build profile.
3. Check that each reader consumes the entire payload on multiple occurrences, including optional-field variants. Compare the decoded fields against independent evidence from matches that were excluded from discovery.
4. Record the validation and sample coverage before listing a new capability in the support table. Preserving raw packets gives a useful fallback while a semantic mapping is being investigated.

For 16.23, opponent-champion damage reconstructed from packets agrees with the footer for 20 of 20 participants, using integer truncation of the summed amounts. The two replays also provide 131 paired Recall buff applications and removals. Future profile checks can use final inventory, champion deaths, and ability counters where the replay records them at matching scope.
