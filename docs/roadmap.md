# Replay Analytics Roadmap

The long-term goal is one tool that can analyze any League of Legends replay, across accounts, regions, champions, game modes, and patches. A supported replay should produce a player timeline that connects farming, ability use, movement, fights, and map decisions. Each metric should link back to its source events and report how much of the match it covers.

The tool should detect the container and build from each file, select the matching profile, and report support per metric. When a build profile is unavailable, compatible files can still yield metadata and raw packets. Files with an unknown container layout should get a clear diagnostic. Coverage grows as new layouts and event profiles are validated.

## Current verification

The current `16.23.841.8428` profile exports casts, damage, basic attacks, missiles, buff applications and removals, Recall buff transitions, waypoint groups, and two spawn families. The initial validation set contains two EUW replays of that build. Across those samples, all 3,300 recorded lane minion spawns matched a waypoint unit ID, and damage to opposing champions reconciled with the replay footer for all 20 participants. Raw packet export has also been verified on a TR replay from `16.19.823.0722`. [Current profile and validation](decoding.md)

## 1. Match clock, entity identity, and player state

The 16.23 profile now exports lane minion deaths and killer IDs. Next, validate player CS credit and add `StatUpdate` for counters and resources, then `LevelUp`. Farm and lane comparisons depend on these events. [Current death-event coverage](decoding.md#unit-deaths)

- Build entity lifetimes from creation and removal events. Track the match, entity ID, and lifetime when joining records. Use keyframes to restore state and record the source of each restoration.
- Reconstruct per-player timelines for CS, total gold earned, unspent gold, XP, HP, mana, level, and attack speed. Track which updates set an absolute value and which report a delta.
- Sample **CS, gold, XP, HP, mana, and level by minute**. Carry the last value forward only across intervals with verified state continuity. Report **CS, gold, and XP differences at 5, 10, and 15 minutes** against a selected opponent. Allow the user to choose an opponent when the lane matchup is uncertain. If the match ends before a checkpoint, set that checkpoint to `null`.
- Link **minion death timestamps and killer IDs** to spawn identity and minion type. Store the killing unit and the player credited with CS as distinct fields when the replay establishes both.

**Acceptance check** — Verify deaths and CS credit against a hand-labeled lane segment. Reconcile CS and level with the end-of-game totals and compare minute samples with Match-V5 timeline data where the fields and time scopes agree. Measure death-event coverage by unit type. An older ROFL-X profile documents gaps in its map-view death stream. [Riot Match-V5](https://developer.riotgames.com/apis#match-v5) · [ROFL-X packet catalog](https://github.com/Toastaspiring/ROFL-X/blob/main/docs/PACKETS.md)

## 2. Farming and waves

| Output | Inputs and method |
| --- | --- |
| **Missed minions, missed cannon minions, and potential gold lost** | Join minion type, death, lane, and player position. Estimate which minions were reachable last-hit opportunities. Count eligible deaths with confirmed CS credit elsewhere or confirmed absence of player credit. Keep a separate cannon count. Sum their potential gold using the rules for the replay's patch and mode. |
| **Last-hit rate by minion type** | Divide credited last hits by observed eligible opportunities for melee, caster, cannon, and super minions. Include the counts behind the rate. Use `null` when the opportunity denominator is unavailable. |
| **Minions last-hit with basic attacks and with abilities** | Join the death and CS credit to the damage instance that caused the death. Report basic attack, ability, or unknown source. Preserve ambiguous simultaneous damage as unresolved. |
| **Last-hit rate under turret** | Identify enemy minions eligible for last hits under the player's turret. Use turret attacks to identify tower-assisted opportunities and report those separately from the broader under-turret sample. |
| **Minions lost during Recall** | Count eligible lane deaths during the Recall channel and, separately, during a successful Recall's return-to-lane window. Deduplicate these minions in the overall farming report. |
| **Wave position and size** | Group spawns by team, lane, and wave. Update surviving minion counts and estimate wave position from observed movement. Report gaps in lifetime or position coverage. |

**Acceptance check** — Use hand-labeled cannon waves, last hits under turret, CS ceded to a teammate, and interrupted Recalls. Validate credited last hits and estimated missed opportunities separately.

## 3. Abilities, basic attacks, and Ezreal

| Output | Inputs and method |
| --- | --- |
| **Q/W/E/R cast timestamps and total casts** | Join slot, spell hash, cast sequence, and champion form. Define how each ability handles recasts and toggles. Report counts from observed records alongside the footer counters where available. |
| **Ability hit, miss, and block rates** | Join casts to missiles, confirmed contacts, damage, buffs, and block signals. Assign `hit`, `miss`, `blocked`, or `unknown` per eligible cast. Display outcome rates over resolved casts and the unresolved share over all eligible casts. |
| **Champion/minion hit split, hit rate by distance, average damage, and targets per cast** | Resolve target types from the entity timeline. Use observed cast origin and contact position for distance buckets. Sum damage per cast, report average damage over eligible casts with known outcomes, and count distinct targets. Include the number of casts in each bucket. |
| **Cooldown history, time spent ready, and mana at cast time** | Apply cooldown updates, resets, charges, and resource updates in order. Measure ready time until the next use, capped by the observed window. Read mana from the last applicable resource state before the cast. |
| **Ezreal W mark rate, detonation rate, and W + AA/Q/E/R combinations** | Measure confirmed marks per eligible observed W cast and detonations per observed mark. Join the mark, detonation, and triggering action on the same target. Keep the combination unknown when more than one trigger fits. |
| **Ezreal E direction, distance, and position before/after** | Join the cast to nearby observations before and after displacement. Report the endpoints, direction, distance, and observation gap. Mark reconstructed endpoints as estimates. |
| **Death within 5 or 10 seconds after Ezreal E** | Link each E cast to the following death windows. Record how much of the window was observable, including casts near match end. |
| **Cooldown reduction from Ezreal Q** | Join a confirmed Q hit to a cooldown change. Account for resets and other possible causes. Leave attribution unresolved when several causes fit. |
| **Ezreal passive stack history, uptime, and time fighting at maximum stacks** | Rebuild application, refresh, expiration, and stack changes. Measure uptime over observed time. Measure maximum-stack fight time over the player's observed time inside the fight window. |
| **Total basic attacks, attacks on champions/minions, and canceled attacks** | Link attack starts, missiles or contacts, and explicit cancel signals where attack identity is available. Break totals down by target type and outcome. Report starts with insufficient follow-up as unresolved. |
| **Time between attacks, time between attacks and casts, movement after attacking, and attack speed history** | Use the shared match clock. Associate adjacent casts and attacks, then measure the first observed or inferred movement after each attack. Read attack speed from the player-state history. |
| **Estimated missed attack opportunities and kiting efficiency** | Estimate attack windows from target eligibility, range, attack speed, animation timing, and crowd control. Report observed attacks per estimated opportunity and displacement between attacks. Include the rule version and data coverage. |

**Acceptance check** — Verify normal hits, misses, blocks, cancels, contact effects without damage, multi-target casts, and Ezreal W chains separately. Group repeated damage and multiple targets under their originating cast. Report the gap between observed casts and footer counters.

## 4. Position, vision, and effects

- Export **timestamped player positions**, **direction changes**, **positions for heatmaps**, and **time by lane or map region**. Preserve observed coordinates and label positions interpolated from waypoint routes. End interpolation at dashes, teleports, deaths, and gaps beyond the chosen window.
- Calculate **distance to enemies and teammates**, **time in auto-attack range**, and **time in enemy turret range** from time-aligned positions and the applicable range and hitbox rules. Include range provenance and observed time.
- Build **visibility history** and **time in areas without vision**. First recover intervals in which a team saw a particular entity. Estimate map-area visibility separately from wards, terrain, and visibility rules when those inputs are available.
- Build **buff and debuff history**, **stack and duration history**, and **applied and received crowd control** from source, target, effect identity, application, refresh, stack changes, and removal. Track duration observed in the replay and confirm shortened or blocked effects where possible.
- Measure **stationary time and distance traveled during fights** using the fight windows in phase 5. Report the share of time with observed positions, interpolated positions, and missing data.

**Acceptance check** — Verify movement around gaps, dashes, teleports, visibility changes, and movement speed changes. Test that reconstruction leaves gaps across discontinuities and handles entity lifetimes consistently.

## 5. Trades, teamfights, and deaths

- Attribute **damage sources and types** and **damage dealt and received per trade**. Group affiliated damage by source, target, effect, and physical, magic, or true damage type. Define trade windows and participant rules.
- Identify **teamfight start/end times**, **delay before each player joins**, and **pre-fight poke damage**. Version the definitions for meaningful combat, participation, gap between events, and the poke window. Compare the fight segments produced by alternative thresholds.
- Report **damage**, **DPS**, **ability hit rate**, **basic attack count**, **target distribution**, and **survival time** per teamfight. Specify active observed time for DPS and apply the same ability-outcome rules as the match report.
- For each death, export the **preceding 5, 10, 15, and 30 seconds of events**, **movement and positions**, and **nearby enemy and teammate counts** using a recorded distance threshold. Attach **ability cooldowns** and **Flash and other summoner spell states** at death. Export **summoner spell usage history** for the whole match.

**Acceptance check** — Use annotated short trades, disengages and re-entry, poke, and split fights. Reconcile each fight's damage total with the underlying damage rows. Label fight segmentation and participant classification as estimates.

## 6. Recall, items, lanes, and objectives

| Output | Inputs and method |
| --- | --- |
| **Recall start, completion, and cancellation times** | Match cast and buff application to the start. Classify removal with a verified finish/interrupt signal or a confirmed arrival at base. Record unclassified endings as `null`. This event history also feeds recall-related farm loss in phase 2. |
| **Item purchases, sales, completions, passive triggers, and unspent gold** | Reconstruct inventory from purchase, sale, undo, and slot events. Join component changes to item recipes and passive effects to their triggers. Report spendable gold over time alongside total gold earned. |
| **Level-up times** | Use level updates with timestamps. Deduplicate repeated values and reconcile the last known level with the replay footer. |
| **Time the support spends out of lane** | Identify the support and lane boundaries. Measure observed time when the player is in lane and the support is outside it. Make the treatment of Recall and death intervals explicit. |
| **Enemy jungler gank times and outcomes** | Estimate gank windows using jungler identity, lane entry, proximity, and enemy interaction. Record damage, kills, deaths, and summoner spells from the same window. |
| **Ward placements and destruction** | Identify ward type and owner from creation events. Use confirmed removal or expiration to close the lifetime and record the reason. Keep visibility changes as their own events. |
| **Objective participation and damage** | Identify neutral objectives and structures. Report damage, direct interaction, and proximity separately. Link objective damage and the death or completion event to the objective's entity ID. |
| **Turret plate and turret destruction times** | Join changes to turret identity, team, and timestamp. Check the gold event before assigning plate credit to a player. |

**Acceptance check** — Compare final inventory and objective counts against match summaries. Verify successful and canceled Recalls, undo purchases, ward expiration, and jungler visits with labeled examples.

## Coverage and validation

Every metric includes a value, unit, measurement method, validation status, coverage, and references to its source events.

| Field | Contract |
| --- | --- |
| `measurement` | `direct` for values read from a decoded record, `derived` for deterministic calculations on verified events, and `estimated` for interpolation or heuristic classification. |
| `validation` | `verified`, `partial`, `unverified`, or `unsupported`. Record status per metric, build, and game mode. |
| `coverage` | Record the observation window, valid and expected counts or durations, and known gaps. Use `null` for unavailable values or ratios without a valid denominator. Use `0` for a confirmed zero within a sufficiently observed scope. |
| `evidence` | Keep source packet references, the build profile, the analysis rule version, and any independent validation source. |

For each stream and packet ID, count packets seen, successfully decoded, undecodable, and structurally decoded but semantically unclassified. Also count ambiguous event joins in metrics that use them. A partially observed metric retains its denominator and scope.

## Delivery order

1. **First pull request** — Add `MinionDeath`, killer IDs, and the join to spawned minions. Identify the packet and its variants in discovery replays. Verify the mapping on separate replays and check CS credit in a manually labeled lane segment. Export a death table with coverage counts.
2. **First player report** — Add minute-level state samples and 5/10/15-minute lane differences, then farm results by minion type. Enable recall-related farm loss and other position-dependent metrics once their inputs are verified.
3. **Combat and map reports** — Start with shared ability and attack events plus the Ezreal cases. Add movement, buffs, visibility, deaths, fights, and objectives as the corresponding event families are verified.
4. **Patch maintenance throughout** — Keep packet layouts in build profiles and metrics in shared analysis code. Propose mappings on new builds, then check payload consumption, run regressions, and verify gameplay meaning against independent evidence. Expand the validation set across builds, regions, champions, and game modes. Use the same metrics on each newly supported build to measure cross-patch reuse. [Profile validation process](decoding.md#adding-a-build)

Start with local event JSONL and metric JSON. Add CSV views for minute samples and entity histories as their schemas settle. Charts and heatmaps can read the same data.
