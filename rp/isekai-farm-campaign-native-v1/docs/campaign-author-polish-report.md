# Campaign Author Polish Report

Date: 2026-07-01

Scope: `rp/isekai-farm-campaign-native-v1`

This pass keeps the package native to the current engine. It adds content only through supported V1 surfaces: `entities`, `rules`, `random_tables`, `palettes`, `tests`, and docs.

Boundary correction: relationship state, current companion status, current trap state, current plant location, and current project progress are save-owned. Campaign content may define rules, procedures, palettes, and generic authoring patterns, but must not encode one save's developed relationships as package defaults.

## Goals

- Keep approved save adjudications in the save package unless they are stable world rules.
- Add reusable relationship handling rules without adding current relationship records.
- Expand palette candidates without making them current save facts.
- Improve long-term sandbox play hooks using mature tabletop RPG prep patterns.
- Split the large item content source for maintainability.
- Prepare, but not apply, semantic ID migration for `v1-*` IDs.

## Applied Content Changes

- Corrected `plant:antiaris-toxicaria` and `project:v1-569a730495` so current location/recovery/sample status are save-owned.
- Corrected M1 wording so current trap status is save-owned and the campaign cannot auto-trigger old migrated trap records.
- Removed save-specific `project:t2-observation-feeding` from the campaign package.
- Kept `relationships.yaml` empty; current relationship records belong in saves.
- Added one generic authoring-pattern reference card.
- Added relationship, node-clue, home-life, and palette-deployment random tables.
- Expanded material, species, faction, and encounter palettes with discovery modes, confirmation methods, risks, and `save_as` targets.
- Added rules for relationship delta boundaries and palette candidate deployment.
- Added smoke tests for generic authoring-pattern and random-table content.

## Borrowed Design Patterns

- Situation prep rather than fixed plot: content provides nodes, motives, pressures, clues, and choices, not a predetermined event chain.
- Three-clue redundancy: important conclusions should have multiple routes, such as location review, NPC inquiry, and material testing.
- Progress clocks and faction clocks: ongoing risks and external actors should advance through visible or hidden clocks instead of sudden arbitrary events.
- Relationship boundaries: campaign rules define when relationship deltas must be saved; actual posture, promises, trust, and companion progress live in saves.
- Regional random tables: random outcomes should express local ecology, pressure, and actionable leads instead of generic encounters.

Reference URLs:

- https://thealexandrian.net/wordpress/53341/roleplaying-games/is-node-based-design-prepping-a-plot
- https://thealexandrian.net/wordpress/7985/roleplaying-games/node-based-scenario-design-part-3-inverting-the-three-clue-rule
- https://bladesinthedark.com/progress-clocks
- https://bladesinthedark.com/faction-game
- https://www.dungeonworldsrd.com/gamemastering/fronts/
- https://www.roleplayingtips.com/rptn/random-encounter-tables/

## Maintenance Changes

- Split old `content/items.yaml` into:
  - `content/items/ammunition.yaml`
  - `content/items/dangerous-tools.yaml`
  - `content/items/food-and-kitchen.yaml`
  - `content/items/craft-materials.yaml`
  - `content/items/herbs-and-magic-plants.yaml`
  - `content/items/containers-and-mementos.yaml`
- Updated `campaign.yaml` to reference the split item files.
- Added `docs/v1-id-mapping.md` with a draft mapping for all current `v1-*` IDs.

## Deliberately Not Done

- Did not batch-rename `v1-*` IDs, because current save references must be migrated together.
- Did not advance current save time, location, inventory, clocks, or relationship progress.
- Did not confirm unresolved world facts such as external factions, T5 identity, T2 trust, current M1 state, antiaris current location, or antiaris sample availability.
