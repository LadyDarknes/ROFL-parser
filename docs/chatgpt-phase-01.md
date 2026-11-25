# ChatGPT continuation 01 — 0.2.1

Base: supplied local ZIP (0.2.0, 26 tests). No decoder packet mappings or roadmap changed.

- Strict opt-in `--verify-events`: matches ordered packet identities (file/block/payload offsets, ID, sender, length and timestamp) for all supported gameplay packets. Does not independently validate decoded field semantics. Legacy exports without verification still report unknown completeness.
- `--riot-id` selects only a unique participant matched by terminal stats. No guessing.
- Accept gzip event inputs; output JSON stays compatible (additive fields).
- Q summary: observed and resolved hit fractions, coverage, missing footer cast difference and conditional all-target bounds; champion-intended accuracy remains null.
- Farm: recorded last hits and recent-damage-before-other-kill grouped by minion type and minute. Not a missed-CS detector. Exact minute CS stays null.

Validation: 28 unit tests passed (including strict gzip completeness, truncated/duplicate/reordered rows, unique Riot ID selection, Q bounds and farm groups). Actual replay EUW1-8056654902, exact 16.23.841.8428 profile: full combat export 92,771 supported packets, verified against raw packet identities. Previously truncated export of 60,248 rows rejected. Gzip report verified. Selected Ezreal entity 1073742169. Q: 63 hit, 22 miss, 1 unknown, 86 observed / 93 footer. Farm: 54 observed killing blows, 17 damage-before-other-kill; final CS 62. No claim of complete semantic coverage or exact missed last hits. No independent replay/video accuracy labeling done in this phase.

Next: automatic replay-to-report pipeline and further controlled validation of Q/AA/farm semantics; continuous positions, CC, true windup and exact CS remain open. Only offline post-match analysis.
