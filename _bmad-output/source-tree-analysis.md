# 源码树分析

文档状态：**DRAFT：GDS full_rescan exhaustive source tree scan**
日期：2026-07-04
工作流：`gds-document-project`

本文件是 BMAD/GDS exhaustive rescan 的源码树产物。它记录当前仓库结构，不直接替代
长期 canonical 文档 [`docs/source-tree-analysis.md`](../docs/source-tree-analysis.md)。

## BMAD Provenance

- Skill：`.agents/skills/gds-document-project/SKILL.md`
- Resolver：
  `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/gds-document-project --key workflow`
- Mode：`full_rescan`
- Scan level：`exhaustive`
- Evidence：top-level `find` scan、`rpg_engine/` directory scan、`docs/` scan、
  `_bmad-output/` scan、`pyproject.toml`、CLI/MCP/runtime owner files

## 顶层结构

```text
.
├── .agents/                  # Codex/Hermes installed BMAD skills
├── .github/workflows/         # GitHub Actions CI
├── _bmad/                     # BMAD install, config, modules, customization support
├── _bmad-output/              # BMAD scan, planning, implementation, test artifacts
├── docs/                      # canonical docs, compatibility stubs, active prompts, archive
├── examples/                  # source example Campaign Packages
├── migrations/                # root migration mirror/history; packaged runtime migrations are under rpg_engine/resources
├── reports/                   # time-boxed probes and research reports
├── rp/                        # current public campaign/source material
├── rpg_engine/                # Python package and kernel implementation
├── run1/                      # save-like local runtime data; not a canonical doc/source truth
├── schemas/                   # root schema mirror/history
├── scripts/                   # local probes and quality/helper scripts
├── test_deltas/               # delta samples
└── tests/                     # pytest suite and fixtures
```

## `rpg_engine/` Package

```text
rpg_engine/
├── actions/                   # action resolver contracts and builtin action implementations
├── admin/                     # admin/maintenance plugin manifest inspection
├── ai/                        # AI provider/config/policy/schema validation/audit helpers
├── ai_intent/                 # AI intent candidate, review, arbitration, binding, slot contracts
├── authoring/                 # author-facing campaign tools
├── compat/                    # compatibility import paths and adapters
├── content_types/             # content runtime registry and seed handlers
├── context/                   # context collection, budgets, semantic routing, rendering, validation
├── importers/                 # importer abstractions
├── legacy/                    # legacy compatibility behavior
├── packages/                  # package archive, lock, merge, service utilities
├── resources/                 # packaged migrations, schemas, examples, eval fixtures
├── cli.py                     # top-level CLI and legacy/admin groups
├── cli_v1.py                  # V1 campaign/save/play/player/platform/mcp/eval command groups
├── runtime.py                 # GMRuntime facade and player turn mechanics
├── save_manager.py            # player workspace, active save, pending action/clarification
├── mcp_adapter.py             # MCP profile-gated tool surface
├── platform_prewarm.py        # platform message prewarm and binding store
├── platform_sidecar.py        # platform start/act/confirm sidecar
├── preflight_cache.py         # advisory intent preflight cache
├── validation_pipeline.py     # delta validation and policy checks
├── commit_service.py          # commit path
└── projection_service.py      # post-commit projection repair/refresh status
```

## Documentation Tree

```text
docs/
├── index.md                   # canonical documentation entry
├── README.md                  # compatibility entry pointing to index
├── project-context.md         # AI/BMAD project constitution
├── architecture.md            # current architecture authority
├── ai-intent-chain.md         # AI intent authority
├── save-and-campaign-packages.md
├── cli-contracts.md
├── mcp-contracts.md
├── data-models.md
├── authoring-guide.md
├── prompt-contracts.md
├── testing-and-quality-gates.md
├── component-inventory.md
├── source-tree-analysis.md
├── project-overview.md
├── development-guide.md
├── governance/
│   ├── bmad-workflow.md
│   └── content-generation.md
├── prompts/                   # active prompt artifacts, not archive
├── architecture/              # Round 4C compatibility stubs
├── specs/                     # Round 4C compatibility stubs
├── guides/                    # Round 4C compatibility stubs
└── archive/                   # historical/pre-BMAD source material
```

Current rule: if archive source text conflicts with code or canonical docs, current code and
canonical docs win.

## BMAD Tree

```text
_bmad/
├── _config/                   # bmad-help catalog and manifest
├── bmm/                       # BMad Method module config
├── core/                      # Core module config
├── gds/                       # Game Dev Studio module config
├── tea/                       # Test Architecture Enterprise config
├── custom/                    # team/user config and skill overrides
└── scripts/                   # customization resolver

_bmad-output/
├── index.md                   # BMAD output index
├── project-scan-report.json   # resumability state for this run
├── api-contracts.md           # full_rescan surface scan
├── data-models.md             # full_rescan data model scan
├── source-tree-analysis.md    # this file
├── planning-artifacts/
├── implementation-artifacts/
├── test-artifacts/
└── .archive/                  # archived old scan state
```

## Test Tree

`tests/` currently contains 50 top-level `test_*.py` files plus fixtures. Coverage areas include:

- current native package/save/player workflows,
- CLI V1 and official example flows,
- Runtime and validation pipeline,
- AI intent, intent manifest, preflight cache, internal/external helper paths,
- MCP profile/transcript boundaries,
- platform prewarm and sidecar behavior,
- SaveManager pending/session confirmation,
- projection service and outbox repair,
- content registry, authoring tools, package merge/service,
- cross-layer regression and condition combinations.

## Resource Tree

`rpg_engine/resources/` includes:

- `migrations/0001_init.sql` through `0008_intent_joiner_message_only.sql`
- `schemas/*.schema.json`
- `examples/blank_campaign`
- `examples/small_cn_campaign`
- `examples/v1_minimal_adventure`
- `evals/*`

Packaged resources are installed with the Python package. Root `migrations/` and `schemas/`
are useful mirrors/history but are not ahead of packaged resources.

## Runtime Data and Public Repo Boundary

The following should not become canonical documentation or public source truth:

- `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`
- `.aigm/`, local `saves/`, platform session bindings
- `run1/` save-like runtime output
- raw player Save Packages or private player databases
- preflight cache contents

Example Campaign Packages and packaged schema/migration resources are source material; live
runtime state is not.

## Rescan Findings

- `_bmad-output/source-tree-analysis.md` from Round 1 was stale because it still described
  `docs/` as pending migration. This rescan updates the tree to reflect canonical docs,
  stubs, archive, and active prompt artifacts.
- The project remains a single Python package rather than a multi-part workspace.
- The strongest boundaries are service ownership, profile-gated surfaces, and archive/canonical
  documentation precedence.
