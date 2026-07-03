# P0 Stop-Loss Acceptance - 2026-07-02

This records the stop-loss audit requested after the current architecture and multi-expert repair review.

## Baseline

- `ruff check .`: passed.
- `python3 -m pytest -q`: `190 passed, 103 skipped, 183 subtests passed`.
- `python3 -m coverage report --format=total`: `50`.
- Added hard P0 acceptance gate: `tests/test_p0_stop_loss_acceptance.py`.

## P0 Failures Found

1. Original player input `巡视领地，看看大家都在做什么` still routed to `craft/needs_confirmation` instead of `routine/ready`.
2. `Campaign.content_files()` allowed absolute paths and `..` parent escapes.
3. A committed `TurnProposal` could be replayed into a second new turn.
4. Hidden entities generated default card files and those derived files could enter normal save export.
5. Hidden character memories were written to the default memory index and could be retrieved by player-facing context lookup.

## Fix Order

1. Root-contain campaign content paths.
2. Fix the original patrol intent regression.
3. Add write guards to resolver-proposed deltas and reject already-committed proposal commands.
4. Stop default player projections from materializing hidden cards/memories.
5. Re-run the P0 gate and full regression suite.

## Acceptance Command

```bash
python3 -m pytest -q tests/test_p0_stop_loss_acceptance.py
```

## Remediation Result

Implemented in the same stop-loss pass:

- `Campaign.content_files()` now resolves content paths under the campaign/save root.
- `save init` now copies campaign content files into the save package instead of writing `../` links back to the source campaign.
- The original patrol phrase routes to `routine/ready`.
- Runtime-generated resolver deltas now receive `expected_turn_id` and `command_id`; `commit_turn_proposal()` rejects already-committed proposal commands.
- Default player card projection skips hidden entities, filters hidden entity IDs from visible card details, and save validation only requires player-readable cards.
- Default memory summary generation and lookup exclude hidden subject entities.

Final verification:

- `python3 -m pytest -q tests/test_p0_stop_loss_acceptance.py`: `5 passed, 2 subtests passed`.
- `python3 -m pytest -q`: `195 passed, 103 skipped, 185 subtests passed`.
- `ruff check .`: passed.
- `python3 -m coverage report --format=total`: `50`.
