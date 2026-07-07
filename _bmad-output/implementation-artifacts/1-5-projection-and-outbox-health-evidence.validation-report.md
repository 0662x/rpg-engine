# Story Validation Report: 1.5 Projection and Outbox Health Evidence

Generated: 2026-07-07T03:02:55+1000

Status: pass

Validated story: `_bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md`

## Summary

Story 1.5 is ready for development. The story aligns with Epic 1 Story 1.5, PRD FR-3/FR-14/FR-15, and the execution-chain architecture rule that SQLite commits are facts while projection/outbox artifacts are repairable evidence.

No critical issues were found. No story edits were required during validation.

## Checklist Results

| Area | Result | Notes |
| --- | --- | --- |
| Story metadata | pass | Story id, status, user story, acceptance criteria, tasks, dev notes, references, and test requirements are present. |
| Source alignment | pass | Matches Epic 1 Story 1.5: projection/outbox failures must be visible, reportable, repairable, and non-authoritative. |
| Current implementation accuracy | pass | The story accurately identifies `PROJECTION_VERSIONS`, required projections, `projection_state`, `outbox`, `ProjectionService`, `ProjectionReport`, `inspect_save_package()`, and CLI projection repair behavior. |
| Reinvention risk | pass | The story explicitly requires reusing existing `ProjectionService`, `ProjectionReport`, `ProjectionItemReport`, `projection_state`, and `outbox` instead of creating a parallel health service or fact table. |
| Authority boundary | pass | The story keeps `data/game.sqlite` and SQLite `events` authoritative and treats JSONL, snapshots, cards, search, projection reports, `projection_state`, and `outbox` as derived evidence. |
| Repair boundary | pass | Repair is constrained to maintenance/admin projection surfaces and must not write turns, events, entities, clocks, pending actions, confirmations, or commit approvals. |
| Regression evidence | pass | Focused gates cover projection reports, failed/dirty/stale/behind reporting, CLI validation/repair, targeted repair with unrelated failures, and current-native temp-copy repair safety. |
| LLM clarity | pass | Critical implementation constraints are explicit and scannable; the story gives the dev agent enough file-level and behavior-level guidance. |

## Findings

Critical issues: 0

Enhancement opportunities: 0

Optional implementation note: keep the public command naming clear during implementation. The story uses the canonical surface label `aigm projection repair`, while current tests invoke the CLI as `projection repair` through the project test helper. This is not a blocker because both refer to the same projection/outbox maintenance surface.

## Source Review

Validated against:

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/1-4-save-fact-authority-and-runtime-state-boundary.md`
- `docs/project-context.md`
- `docs/save-and-campaign-packages.md`
- `docs/data-models.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/projections.py`
- `rpg_engine/projection_service.py`
- `rpg_engine/save_validation.py`
- `rpg_engine/cli.py`
- `rpg_engine/commit_service.py`
- `rpg_engine/unit_of_work.py`
- `rpg_engine/surface_inventory.py`
- `tests/test_projection_service.py`
- `tests/test_v1_cli.py`
- `tests/test_current_native_write_safety.py`

## Verification

Commands run:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml
story = Path('_bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md')
text = story.read_text(encoding='utf-8')
checks = {
    'story_exists': story.exists(),
    'no_template_braces': '{{' not in text and '}}' not in text,
    'status_ready': 'Status: ready-for-dev' in text,
    'has_acceptance_criteria': '## 验收标准' in text or '## Acceptance Criteria' in text,
    'has_tasks': '## 任务 / 子任务' in text or '## Tasks / Subtasks' in text,
    'has_dev_notes': '## 开发说明' in text or '## Dev Notes' in text,
    'mentions_required_projections': all(name in text for name in ('events_jsonl', 'search', 'snapshots', 'cards')),
    'mentions_projection_state_outbox': 'projection_state' in text and 'outbox' in text,
    'mentions_authority_boundary': 'SQLite' in text and 'fact authority' in text,
    'mentions_repair_evidence': 'repair evidence' in text,
    'mentions_focused_gates': 'tests/test_projection_service.py' in text and 'tests/test_v1_cli.py' in text,
}
for key, value in checks.items():
    print(f'{key}={value}')
status = yaml.safe_load(Path('_bmad-output/implementation-artifacts/sprint-status.yaml').read_text(encoding='utf-8'))
print('story_status=', status['development_status'].get('1-5-projection-and-outbox-health-evidence'))
bad = [key for key, value in checks.items() if not value]
if bad or status['development_status'].get('1-5-projection-and-outbox-health-evidence') != 'ready-for-dev':
    raise SystemExit(1)
PY
python3 -m pytest -q tests/test_projection_service.py tests/test_v1_cli.py tests/test_current_native_write_safety.py
```

Results:

- Story smoke checks: pass
- `tests/test_projection_service.py tests/test_v1_cli.py tests/test_current_native_write_safety.py`: `34 passed, 5 subtests passed`

## BMAD Provenance

- User trigger: `bmad-create-story validate`
- Assumed target from previous `bmad-help` recommendation: Story 1.5
- Catalog/menu row: `[VS] Validate Story`, skill `bmad-create-story`, action `validate`
- Skill path read: `.agents/skills/bmad-create-story/SKILL.md`
- Checklist read: `.agents/skills/bmad-create-story/checklist.md`
- Customization resolved: `workflow.activation_steps_prepend=[]`, `workflow.activation_steps_append=[]`, persistent facts include `file:{project-root}/**/project-context.md`, `workflow.on_complete=""`
- Config loaded: `_bmad/bmm/config.yaml`
- Persistent fact loaded: `docs/project-context.md`

## Next Step

Run `bmad-dev-story` against:

```text
_bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md
```
