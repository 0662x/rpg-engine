# Story Validation Report: 2.1 Campaign and Save Ownership Contract

Generated: 2026-07-08T03:53:38+1000

Status: pass

Validated story: `_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md`

## Summary

Story 2.1 is ready for development. The story aligns with Epic 2 Story 2.1, PRD FR-13/FR-14/FR-17, and the foundation architecture rule that Campaign Package owns authored content while Save Package owns runtime facts.

No critical issues were found. No story edits were required during validation beyond the story created in the Create Story step.

## Checklist Results

| Area | Result | Notes |
| --- | --- | --- |
| Story metadata | pass | Story id, status, user story, acceptance criteria, tasks, dev notes, references, and test requirements are present. |
| Source alignment | pass | Matches Epic 2 Story 2.1: Campaign validation reports runtime artifacts, save init creates runtime package state, and ordinary play does not mutate source Campaign. |
| Current implementation accuracy | pass | The story accurately identifies `validate_campaign_package()`, `validate_no_v1_code_extensions()`, `init_v1_save()`, runtime `campaign.yaml`, `save.yaml.source_campaign_path`, `ProjectionService`, and current focused tests. |
| Reinvention risk | pass | The story explicitly requires reusing existing Campaign/Save services and forbids a second package model, save initializer, manifest format, or fact authority. |
| Authority boundary | pass | The story keeps source Campaign files as authored content and Save SQLite/events/projections as runtime fact/evidence state. |
| Player-safe boundary | pass | Ordinary play verification must use `SaveManager.player_turn()` / `SaveManager.player_confirm()` and must not substitute low-level `GMRuntime.commit_turn()` for player flow. |
| Regression evidence | pass | Focused gates cover campaign validation, save init/inspect/validate shape, SaveManager/starter paths, current native package boundaries, campaign smoke, markdown links, and whitespace. |
| LLM clarity | pass | Critical implementation constraints are explicit and scannable; tasks map directly to acceptance criteria. |

## Findings

Critical issues: 0

Enhancement opportunities: 0

Optional implementation note: choose error vs warning severity for runtime artifacts during dev, but keep it stable and documented. The story allows either because Epic 2.1 says runtime files are "rejected or warned" as inappropriate.

## Source Review

Validated against:

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/1-8-platform-forwarding-与审计边界.md`
- `_bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md`
- `_bmad-output/implementation-artifacts/1-4-save-fact-authority-and-runtime-state-boundary.md`
- `docs/project-context.md`
- `docs/save-and-campaign-packages.md`
- `docs/authoring-guide.md`
- `docs/data-models.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/campaign_validation.py`
- `rpg_engine/campaign.py`
- `rpg_engine/save_service.py`
- `rpg_engine/save_manager.py`
- `tests/test_campaign_validation.py`
- `tests/test_v1_cli.py`
- `tests/test_save_manager.py`
- `tests/test_package_save_condition_coverage.py`
- `tests/test_current_native_package.py`
- `tests/test_current_native_write_safety.py`

## Verification

Commands run:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml
story = Path('_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md')
text = story.read_text(encoding='utf-8')
checks = {
    'story_exists': story.exists(),
    'no_template_braces': '{{' not in text and '}}' not in text,
    'status_ready': 'Status: ready-for-dev' in text,
    'has_user_story': '## 用户故事' in text,
    'has_acceptance_criteria': '## 验收标准' in text,
    'has_tasks': '## 任务 / 子任务' in text,
    'has_dev_notes': '## 开发说明' in text,
    'mentions_campaign_validation': 'validate_campaign_package' in text and 'campaign_validation.py' in text,
    'mentions_save_init': 'init_v1_save' in text and 'save.yaml.source_campaign_path' in text,
    'mentions_no_source_mutation': 'source Campaign' in text and 'tree digest' in text,
    'mentions_player_safe': 'SaveManager.player_turn()' in text and 'SaveManager.player_confirm()' in text,
    'mentions_focused_gates': 'tests/test_campaign_validation.py' in text and 'tests/test_v1_cli.py' in text,
}
for key, value in checks.items():
    print(f'{key}={value}')
status = yaml.safe_load(Path('_bmad-output/implementation-artifacts/sprint-status.yaml').read_text(encoding='utf-8'))
print('epic_status=', status['development_status'].get('epic-2'))
print('story_status=', status['development_status'].get('2-1-campaign-and-save-ownership-contract'))
bad = [key for key, value in checks.items() if not value]
if bad or status['development_status'].get('epic-2') != 'in-progress' or status['development_status'].get('2-1-campaign-and-save-ownership-contract') != 'ready-for-dev':
    raise SystemExit(1)
PY
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md
```

Results:

- Story smoke checks: pass
- `git diff --check`: pass
- `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md`: `checked 87 markdown files; local links ok`

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
_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md
```
