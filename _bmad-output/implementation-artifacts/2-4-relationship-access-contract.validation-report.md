# Story Validation Report: 2.4 Relationship Access Contract

Generated: 2026-07-09T00:00:00+1000

Status: pass

Validated story: `_bmad-output/implementation-artifacts/2-4-relationship-access-contract.md`

## Summary

This is the pre-dev story validation report for Story 2.4. At validation time, the story was ready for development and aligned with Epic 2 Story 2.4, PRD FR-7/FR-13/FR-17, AR-21/AR-23, and the foundation architecture rule that Relationship is a first-class access contract while v1 continues to use relationship entities plus normalized details.

No critical issues were found. The story explicitly avoids a dedicated relationship SQL table, preserves `entities.id` as the endpoint identity anchor, reuses the Story 2.3 `entity_access` visibility/status contract, and keeps relationship suggestions non-authoritative until they enter existing validation/proposal/maintenance paths.

## Checklist Results

| Area | Result | Notes |
| --- | --- | --- |
| Story metadata | pass | Story id, status, user story, acceptance criteria, tasks, dev notes, references, and test requirements are present. |
| Source alignment | pass | Matches Epic 2 Story 2.4: first-class relationship reads, endpoint visibility/reference handling, and non-authoritative AI/maintenance suggestions. |
| Current implementation accuracy | pass | Identifies current relationship storage in `entities.type='relationship'`, normalized details, package/content endpoint validators, and the missing runtime delta endpoint validation gap. |
| Reinvention risk | pass | Requires a named access contract without adding a second relationship identity table, new delta key, or direct storage dependency for callers. |
| Authority boundary | pass | Relationship access remains read/validation support; fact writes still go through Campaign import, package maintenance, or runtime validation/commit. |
| Visibility boundary | pass | Requires player-safe filtering for relationship rows and endpoints, while GM/maintenance hidden reads must be explicit. |
| Regression evidence | pass | Focused gates cover relationship access, entity access, validation pipeline, campaign/package relationship validation, current native visibility/write safety, campaign smoke, docs links, py_compile, and whitespace. |
| LLM clarity | pass | Tasks are scoped to 2.4 and explicitly defer Relationship context inclusion, Progress access, cross-campaign smoke, and proposal queue apply/revert semantics. |

## Findings

Critical issues: 0

Enhancement opportunities: 0

Optional implementation note: keep relationship access as a small contract layer over the current entity-backed storage. If endpoint checks need shared code with package/content validation, extract only the common validation helper; do not create another package source loader or merge policy table.

## Source Review

Validated against:

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md`
- `_bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md`
- `_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`
- `docs/project-context.md`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/save-and-campaign-packages.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/entity_access.py`
- `rpg_engine/delta_schema.py`
- `rpg_engine/content_types/core.py`
- `rpg_engine/content_validation.py`
- `rpg_engine/packages/service.py`
- `tests/test_entity_access.py`
- `tests/test_campaign_validation.py`
- `tests/test_package_cli.py`

## Verification

Commands run at create/validate-story time:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml
story = Path('_bmad-output/implementation-artifacts/2-4-relationship-access-contract.md')
text = story.read_text(encoding='utf-8')
checks = {
    'story_exists': story.exists(),
    'no_template_braces': '{{' not in text and '}}' not in text,
    'status_ready': 'Status: ready-for-dev' in text,
    'has_user_story': '## 用户故事' in text,
    'has_acceptance_criteria': '## 验收标准' in text,
    'has_tasks': '## 任务 / 子任务' in text,
    'has_dev_notes': '## 开发说明' in text,
    'mentions_relationship_access': 'Relationship Access Contract' in text and 'relationship_access.py' in text,
    'mentions_entity_access_reuse': 'entity_access.py' in text and 'read_entity()' in text,
    'mentions_endpoint_visibility': 'hidden/archived/off-view endpoints' in text or 'hidden/archived/off-view' in text,
    'mentions_delta_validation': 'validate_delta_schema' in text and 'details.source_id' in text,
    'mentions_no_direct_ai_fact': 'suggestion alone' in text or 'suggestion != fact' in text,
    'mentions_focused_gates': 'tests/test_relationship_access.py' in text and 'tests/test_validation_pipeline.py' in text,
}
for key, value in checks.items():
    print(f'{key}={value}')
status = yaml.safe_load(Path('_bmad-output/implementation-artifacts/sprint-status.yaml').read_text(encoding='utf-8'))
print('epic_status=', status['development_status'].get('epic-2'))
print('story_status=', status['development_status'].get('2-4-relationship-access-contract'))
bad = [key for key, value in checks.items() if not value]
if bad:
    raise SystemExit(f'failed checks: {bad}')
if status['development_status'].get('epic-2') != 'in-progress':
    raise SystemExit('epic-2 not in-progress')
if status['development_status'].get('2-4-relationship-access-contract') != 'ready-for-dev':
    raise SystemExit('story not ready-for-dev')
PY
git diff --check
```

Results:

- Story smoke checks: pass
- `git diff --check`: pass

## BMAD Provenance

- User trigger: `bmad-story-cycle-auto with review subagents and apply every patch`
- Catalog/menu row: `[VS] Validate Story`, skill `bmad-create-story`, action `validate`
- Skill path read: `.agents/skills/bmad-create-story/SKILL.md`
- Checklist read: `.agents/skills/bmad-create-story/checklist.md`
- Customization resolved: `workflow.activation_steps_prepend=[]`, `workflow.activation_steps_append=[]`, persistent facts include `file:{project-root}/**/project-context.md`, `workflow.on_complete=""`
- Config loaded: `_bmad/bmm/config.yaml`
- Persistent fact loaded: `docs/project-context.md`

## Next Step

Run `bmad-dev-story` against:

```text
_bmad-output/implementation-artifacts/2-4-relationship-access-contract.md
```
