# 数据模型

文档状态：**DRAFT：GDS full_rescan exhaustive data model scan**
日期：2026-07-04
工作流：`gds-document-project`

本文件是 BMAD/GDS exhaustive rescan 的数据模型产物。它记录当前代码事实，不直接替代
长期 canonical 文档 [`docs/data-models.md`](../docs/data-models.md)。

## BMAD Provenance

- Skill：`.agents/skills/gds-document-project/SKILL.md`
- Resolver：
  `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/gds-document-project --key workflow`
- Mode：`full_rescan`
- Scan level：`exhaustive`
- Evidence：`rpg_engine/db.py`、`rpg_engine/resources/migrations/`、
  `rpg_engine/resources/schemas/`、`rpg_engine/save_manager.py`、`rpg_engine/runtime.py`、
  `rpg_engine/preflight_cache.py`、`rpg_engine/platform_sidecar.py`

## 权威关系

Save Package 内的 SQLite 数据库是当前事实权威。Events、JSONL、snapshots、
cards、memory summaries、reports、registry、archive manifest、preflight cache 都是
审计、投影、索引、运行时状态或 advisory evidence，不能绕过写入校验。

一句话边界：

```text
AI proposes. Kernel verifies. Player confirms. Engine commits.
```

## SQLite Migrations

当前打包迁移权威目录是 `rpg_engine/resources/migrations/`。

| Migration | Responsibility |
| --- | --- |
| `0001_init.sql` | 基础事实库、turns/events/entities/facts/items/locations/routes/clocks/rules/context。 |
| `0002_world_settings.sql` | World settings key/value store。 |
| `0003_write_reliability.sql` | `turns.command_*`、`schema_migrations.checksum`、`outbox`、`projection_state`。 |
| `0004_discovery_proposals.sql` | `discovery_states`、`proposal_queue`。 |
| `0005_archivist_proposal_queue.sql` | `archivist_suggestions`。 |
| `0006_intent_preflight_cache.sql` | `intent_preflight_cache` base table and status/message indexes。 |
| `0007_intent_preflight_identity_hardening.sql` | Preflight context/provider/model/backend/fallback/profile identity fields。 |
| `0008_intent_joiner_message_only.sql` | Message-only join fields and message join index。 |

Root-level `migrations/` currently mirrors only `0001` through `0005`; installed runtime
resource loading uses the packaged migration directory.

## Core Tables

`0001_init.sql` creates these tables:

| Table | Role |
| --- | --- |
| `meta` | Save/content/projection schema versions and current campaign state. |
| `turns` | Turn audit records, command id/hash, expected turn id after later migration. |
| `events` | Durable event stream for committed changes. |
| `entities` | Generic factual entity rows with visibility, owner/location, summary and details JSON. |
| `aliases` | Name/alias lookup. |
| `facts` | Subject-predicate facts with visibility and validity windows. |
| `characters` | Character-specific details. |
| `items` | Item quantities/category/owner/location fields. |
| `locations` | Location hierarchy and description fields. |
| `routes` | Traversal links between locations. |
| `crop_plots` | Farming/crop state. |
| `clocks` | Progress clocks. |
| `rules` | Campaign/runtime rule rows. |
| `memory_summaries` | Long-term memory summaries. |
| `context_runs` | Context build audit. |
| `context_items` | Items loaded into a context packet. |

## Projection and Reliability Tables

`0003_write_reliability.sql` adds:

- `outbox` for post-commit projection work.
- `projection_state` for projection status/version/error metadata.
- `turns.command_id`, `turns.command_hash`, `turns.expected_turn_id`.
- Schema/content/projection version metadata.

`ProjectionService` is responsible for derived snapshots/cards/memory/report projection status.
Projection failure must not be confused with fact commit failure.

## Intent and Preflight State

`intent_preflight_cache` stores advisory internal intent review results. It includes:

- lifecycle status (`pending`, `ready`, failed/bypassed/late-ready variants),
- platform/session/message identity,
- save/base turn/context identity,
- provider/model/backend/fallback/profile identity,
- candidate/review/helper payloads.

This cache may improve later routing, but final authority remains in runtime validation and
player confirmation.

## JSON Schemas

Packaged schemas under `rpg_engine/resources/schemas/`:

| Schema | Required Fields |
| --- | --- |
| `campaign.schema.json` | `id`, `name`, `engine_version`, `package_version`, `content_schema_version`, `capabilities`, `initial_location_id`, `defaults`, `content` |
| `turn_delta.schema.json` | `user_text`, `intent`, `summary` |
| `intent_candidate.schema.json` | `kind`, `mode`, `action`, `slots`, `plan`, `confidence`, `missing_slots`, `needs_confirmation`, `safety_flags`, `reason` |
| `internal_intent_review.schema.json` | Intent candidate fields plus `agreement_with_external`, `disagreements`, `external_candidate_quality` |
| `semantic_suggestion.schema.json` | `mode`, `submode`, `targets`, `entities_mentioned`, `missing_confirmations`, `notes`, `confidence` |
| `save_patch.schema.json` | `operations` |
| `state_audit.schema.json` | `ok`, `risk`, `findings`, `missing_structured_changes`, `requires_human_review` |
| `archivist.schema.json` | `turn_summary`, candidate arrays, contradiction/context hints, `review_required` |
| `reflection_draft.schema.json` | `title`, `summary`, `key_points`, `source_event_ids` |
| `random_tables.schema.json` | `random_tables` |
| `smoke.schema.json` | `smoke_tests` |
| `capabilities.schema.json` | Array of capability strings |
| `content_delta.schema.json` | Content maintenance delta shape |

Root-level `schemas/` mirrors most but not all packaged schemas; packaged resources include
`intent_candidate.schema.json` and `internal_intent_review.schema.json`, which are absent from
root `schemas/`.

## Package Data

Campaign Package inputs are YAML/Markdown resources under example packages:

- `campaign.yaml`
- `content/*.yaml`
- `prompts/gm.md`
- `templates/action.md`
- `templates/query.md`
- `tests/smoke.yaml`
- optional author notes/prompts and content palettes

Packaged examples are under both `examples/` and `rpg_engine/resources/examples/`.

## Runtime State Outside Save Package

Workspace/player state can include:

- `.aigm/save-registry.json`
- `.aigm/pending-player-action.json`
- `.aigm/pending-player-clarification.json`
- `.aigm/game-session-bindings.json`

These files are runtime/workspace state, not Campaign Package source truth. They may bind
platform/session/actor identity and must not become public source-of-truth docs.

## Rescan Findings

- The current canonical data model document is directionally aligned with code.
- Any future docs should clarify that packaged migrations are currently ahead of root migration
  mirror files.
- Earlier BMAD output docs in `_bmad-output/` were Round 1 draft material; this file adds strict
  skill provenance for the new rescan.
