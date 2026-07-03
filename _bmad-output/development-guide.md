# 开发与运维指南

文档状态：**DRAFT：GDS full_rescan exhaustive development scan**
日期：2026-07-04
工作流：`gds-document-project`

本文件是 BMAD/GDS exhaustive rescan 的开发/运维产物。长期权威入口仍是
[`docs/development-guide.md`](../docs/development-guide.md) 和
[`docs/testing-and-quality-gates.md`](../docs/testing-and-quality-gates.md)。

## BMAD Provenance

- Skill：`.agents/skills/gds-document-project/SKILL.md`
- Resolver：
  `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/gds-document-project --key workflow`
- Mode：`full_rescan`
- Scan level：`exhaustive`
- Evidence：`README.md`、`pyproject.toml`、`.github/workflows/ci.yml`、
  `docs/development-guide.md`、`docs/testing-and-quality-gates.md`、CLI help output

## Environment

Project requires Python `>=3.11`.

Recommended local setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -e ".[dev,mcp]"
```

Use `python3` in docs and scripts unless a CI context explicitly invokes `python`.

## Common Commands

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m coverage run -m pytest -q
python3 -m coverage report
python3 -m build
python3 -m twine check dist/*
```

CLI entrypoints:

```bash
aigm --help
rpg_engine --help
python3 -m rpg_engine --help
```

## Documentation-Only Verification

For documentation and BMAD output changes:

```bash
git add -N docs _bmad-output
git diff --check
python3 -m json.tool _bmad-output/project-scan-report.json >/dev/null
python3 scripts/check_markdown_links.py docs _bmad-output
```

## CI

`.github/workflows/ci.yml` runs on Python 3.11 and 3.12:

- install `.[dev,mcp]`
- `python -m pytest -q`
- `python -m ruff check .`
- `python -m coverage run -m pytest -q`
- `python -m coverage report`
- installed CLI V1 flow:
  - `aigm campaign copy-example`
  - `aigm campaign validate`
  - `aigm campaign test`
  - `aigm save init`
  - `aigm save validate`
- `python -m build`
- `python -m twine check dist/*`

No Docker, Kubernetes, Terraform, or deployment target config was found in this scan.

## BMAD Development Gate

High-risk changes require BMAD planning/review before implementation:

- Runtime / SaveManager / commit / projection / validation
- AI intent, preflight cache, arbiter, binder, semantic routing
- MCP / CLI / platform sidecar public behavior, permissions, or parameters
- Campaign Package / Save Package schema, migrations, import/export
- hidden / GM-only content boundaries
- player confirmation, pending action, or durable fact commit timing

Strict BMAD invocation rules are now recorded in [`../AGENTS.md`](../AGENTS.md).

## Test Clusters

Focused clusters from canonical docs:

```bash
python3 -m pytest tests/test_current_native_*.py tests/test_cross_layer_regression.py
```

```bash
python3 -m pytest \
  tests/test_cross_layer_regression.py \
  tests/test_validation_pipeline.py \
  tests/test_projection_service.py \
  tests/test_save_manager.py
```

```bash
python3 -m pytest -q \
  tests/test_ai_intent.py \
  tests/test_runtime.py \
  tests/test_mcp_adapter.py \
  tests/test_preflight_cache.py \
  tests/test_platform_prewarm.py \
  tests/test_platform_ai_simulation.py \
  tests/test_platform_sidecar.py \
  tests/test_save_manager.py \
  tests/test_v1_cli.py \
  tests/test_current_native_context.py \
  tests/test_context_quality.py
```

Campaign smoke:

```bash
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
```

## Public Repository Boundaries

Safe to commit:

- source code,
- tests and fixtures,
- packaged schemas/migrations/examples,
- canonical docs,
- BMAD output artifacts,
- current public campaign package source.

Do not commit:

- real player saves,
- private `.aigm/` state,
- platform session bindings,
- preflight cache contents,
- raw player SQLite databases,
- secrets/private config,
- save-like local runtime output such as `run1/` unless explicitly sanitized into an example.

## Operational Notes

- Current native package tests may refer to `/Users/oliver/.hermes/rp/...`; writing tests must copy
  formal packages to temp dirs before mutation.
- Packaged migrations under `rpg_engine/resources/migrations/` are the installed runtime source.
- Root `migrations/` and `schemas/` are mirrors/history and should be checked against packaged
  resources before being cited as authoritative.
- `_bmad-output/` documents are working artifacts. Durable decisions should be promoted into
  `docs/` canonical documents when they become long-lived.

## Rescan Findings

- Round 1 output used `python`; current canonical docs consistently prefer `python3`.
- Round 1 output still said docs would be migrated later; that is stale after Round 4C. Current
  docs are canonical, while old `architecture/`, `specs/`, and `guides/` paths are stubs/archive.
- No standalone CONTRIBUTING or deployment guide was found.
