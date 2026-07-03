# Public Surface Contracts

文档状态：**DRAFT：GDS full_rescan exhaustive surface scan**
日期：2026-07-04
工作流：`gds-document-project`

本文件是 BMAD/GDS exhaustive rescan 的 surface contract 产物。RPG Engine 没有
HTTP REST API；这里的 “API” 指可被用户、AI client、MCP client、CLI wrapper 和
后续开发调用的公开入口。

## BMAD Provenance

- Skill：`.agents/skills/gds-document-project/SKILL.md`
- Resolver：
  `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/gds-document-project --key workflow`
- Mode：`full_rescan`
- Scan level：`exhaustive`
- Evidence：`pyproject.toml`、`rpg_engine/cli.py`、`rpg_engine/cli_v1.py`、
  `rpg_engine/mcp_adapter.py`、`rpg_engine/save_manager.py`、`rpg_engine/runtime.py`、
  `README.md`、`.github/workflows/ci.yml`

## Console Scripts

`pyproject.toml` exposes two equivalent console scripts:

| Script | Target |
| --- | --- |
| `aigm` | `rpg_engine.cli:main` |
| `rpg_engine` | `rpg_engine.cli:main` |

`python3 -m rpg_engine` delegates to the same CLI entry.

## Primary CLI Groups

Current top-level CLI groups include:

| Group | Contract Role |
| --- | --- |
| `campaign` | V1 Campaign Package validation, smoke tests, example copy, authoring helpers. |
| `save` | Save initialization, inspect/validate, import/export, safe maintenance patch. |
| `player` | Player-facing registry, active save, natural-language turn, pending confirmation. |
| `play` | Lower-level runtime play commands: preflight, start-turn, query, preview, validate, commit. |
| `mcp` | MCP stdio server and client config generation. |
| `platform` | Platform message prewarm, start/act/confirm, metrics, binding maintenance. |
| `eval` | Deterministic intent and MCP transcript eval suites. |

Legacy/admin groups remain available for maintenance, migration, diagnostics, package work,
content maintenance, backup, projection repair, simulation, plugin inspection, and importers.
They must not become ordinary player workflow shortcuts.

## Player-Safe Flow

The player-safe natural language flow is:

```text
player turn -> pending action / clarification / query / blocked
player confirm <session_id> -> commit confirmed pending action
```

Key code owners:

| Surface | Owner |
| --- | --- |
| CLI `player turn` / `player confirm` | `rpg_engine/cli_v1.py` |
| Workspace and pending state | `rpg_engine/save_manager.py` |
| Runtime preview/commit | `rpg_engine/runtime.py` |
| Commit implementation | `rpg_engine/commit_service.py` |

`SaveManager.player_turn()` may create a pending action but does not commit game facts.
`SaveManager.player_confirm()` validates the pending `session_id`, save binding, TTL, and
optional platform identity before commit.

## MCP Tools

`rpg_engine/mcp_adapter.py` defines profile-gated MCP tool surfaces.

Player profile tools:

```text
workspace_inspect
campaign_list
save_list
save_current
save_create
save_switch
start_or_continue
intent_manifest
player_turn
player_confirm
campaign_validate
save_inspect
health
```

Low-level tools are available only to `developer`, `trusted_gm`, `maintenance`, or `admin`:

```text
player_query
player_act
start_turn
intent_preflight
query
preview_from_text
preview_action
validate_delta
commit_turn
```

Hidden-read views are limited to `trusted_gm`, `maintenance`, and `admin`.

## Runtime Surface

`GMRuntime` owns low-level kernel behavior:

| Runtime Method | Role |
| --- | --- |
| `start_turn` | Build context and classify a player turn. |
| `query` | Read-only query path. |
| `intent_preflight` | Advisory internal intent preflight. |
| `preview_from_text` / `preview_action` | Produce preview/TurnProposal candidates without saving. |
| `validate_delta` | Validate proposed deltas through schema, refs, action contract, and policy. |
| `commit_turn` | Commit a validated `TurnProposal` and refresh projections. |

The player/default profile should not bypass `player_turn -> player_confirm`.

## Platform Surface

Platform sidecar code handles passive platform message context:

| Owner | Role |
| --- | --- |
| `rpg_engine/platform_prewarm.py` | Message prewarm, binding store, preflight gate. |
| `rpg_engine/platform_sidecar.py` | Platform start/act/confirm entry and session conflict checks. |
| `rpg_engine/preflight_cache.py` | Advisory preflight cache, identity binding, pending/ready lifecycle. |

Platform prewarm is advisory. It must not grant commit authority or override player confirmation.

## CI Surface

`.github/workflows/ci.yml` verifies:

- Python 3.11 and 3.12
- install with `.[dev,mcp]`
- `pytest -q`
- `ruff check .`
- coverage run/report
- installed CLI V1 campaign/save flow
- package build and `twine check`

## Contract Risks

- Root `migrations/` stops at `0005`; packaged migrations under
  `rpg_engine/resources/migrations/` continue through `0008` and are the installed runtime
  source used by resource loading.
- `_bmad-output/round-*` reports before this run may describe BMAD-style work without strict
  skill provenance. Treat them as evidence, not proof of standard skill execution.
- Current canonical docs already state archive/stub precedence; this rescan should preserve
  that rule.
