from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..campaign_validation import validate_campaign_package
from ..packages.service import load_package_source
from ..validation_issues import issue_from_message


GENERATED_PATHS = ("data", "cards", "snapshots", "memory", "reports", "backups")
RUNTIME_MANIFEST_FIELDS = ("database", "events", "current_snapshot", "current_snapshot_json", "cards")
LARGE_YAML_WARNING_LINES = 2000
LARGE_YAML_SUGGESTION_LINES = 800
CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")


@dataclass(frozen=True)
class AuthorRepairOption:
    label: str
    kind: str = "manual_edit"
    example: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "kind": self.kind, "example": self.example}


@dataclass(frozen=True)
class AuthorIssue:
    severity: str
    code: str
    title: str
    message: str
    why_it_matters: str
    file: str = ""
    path: str = ""
    repair_options: tuple[AuthorRepairOption, ...] = ()
    raw_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "why_it_matters": self.why_it_matters,
            "file": self.file,
            "path": self.path,
            "repair_options": [option.to_dict() for option in self.repair_options],
            "raw_message": self.raw_message,
        }


@dataclass(frozen=True)
class AuthorDoctorResult:
    ok: bool
    status: str
    campaign_id: str
    errors: int
    warnings: int
    suggestions: int
    issues: tuple[AuthorIssue, ...]
    strict: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "campaign_id": self.campaign_id,
            "strict": self.strict,
            "summary": {
                "errors": self.errors,
                "warnings": self.warnings,
                "suggestions": self.suggestions,
            },
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def run_campaign_doctor(
    campaign_dir: str | Path,
    *,
    strict: bool = False,
    ai_checks: bool = False,
) -> AuthorDoctorResult:
    root = Path(campaign_dir).expanduser().resolve()
    issues: list[AuthorIssue] = []
    campaign_id = ""

    save_issue = detect_save_package(root)
    if save_issue:
        issues.append(save_issue)
        return doctor_result("", issues, strict=strict)

    validation = validate_campaign_package(root)
    campaign_id = validation.campaign_id
    for message in validation.errors:
        issues.append(issue_from_validation_error(message))
    for message in validation.warnings:
        issues.append(issue_from_validation_warning(message))

    manifest = read_yaml_if_exists(root / "campaign.yaml")
    if isinstance(manifest, dict):
        campaign_id = str(manifest.get("id") or campaign_id)
        issues.extend(check_runtime_manifest_fields(manifest))
    issues.extend(check_generated_paths(root))
    issues.extend(check_large_yaml_files(root))
    issues.extend(check_author_docs(root))
    records_by_type = load_records_safely(root)
    issues.extend(check_start_playability(root, manifest if isinstance(manifest, dict) else {}, records_by_type))
    issues.extend(check_cjk_aliases(records_by_type))
    if ai_checks:
        issues.extend(check_ai_generated_content(records_by_type))
    return doctor_result(campaign_id, dedupe_issues(issues), strict=strict)


def doctor_result(campaign_id: str, issues: list[AuthorIssue], *, strict: bool) -> AuthorDoctorResult:
    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    suggestions = sum(1 for issue in issues if issue.severity == "suggestion")
    ok = errors == 0 and (not strict or warnings == 0)
    if errors:
        status = "needs_fix"
    elif warnings:
        status = "warnings"
    else:
        status = "ok"
    return AuthorDoctorResult(
        ok=ok,
        status=status,
        campaign_id=campaign_id,
        errors=errors,
        warnings=warnings,
        suggestions=suggestions,
        issues=tuple(issues),
        strict=strict,
    )


def detect_save_package(root: Path) -> AuthorIssue | None:
    if (root / "save.yaml").exists() and (root / "data" / "game.sqlite").exists():
        source_hint = ""
        save_data = read_yaml_if_exists(root / "save.yaml")
        if isinstance(save_data, dict) and save_data.get("source_campaign_path"):
            source_hint = f" Source campaign path: {save_data['source_campaign_path']}."
        return AuthorIssue(
            severity="error",
            code="SAVE_PACKAGE_PASSED_TO_CAMPAIGN_DOCTOR",
            title="Save Package was passed to campaign doctor",
            message="This directory looks like a Save Package, not a Campaign Package." + source_hint,
            why_it_matters="Campaign authoring tools must not edit a playthrough's authoritative runtime state.",
            file="save.yaml",
            repair_options=(
                AuthorRepairOption("Validate this directory as a save", "run_command", f"aigm save validate {root}"),
                AuthorRepairOption("Open the source campaign path and run doctor there", "open_source_campaign"),
                AuthorRepairOption("Use save patch or play commit for save maintenance", "use_save_tools"),
            ),
        )
    return None


def issue_from_validation_error(message: str) -> AuthorIssue:
    issue = issue_from_message(message, default_code="CAMPAIGN_VALIDATION_ERROR")
    return AuthorIssue(
        severity="error",
        code=issue.code,
        title=title_for_code(issue.code),
        message=message,
        why_it_matters=why_for_code(issue.code),
        file=issue.file,
        path=issue.path,
        raw_message=message,
        repair_options=(AuthorRepairOption(issue.suggestion, "manual_edit"),),
    )


def issue_from_validation_warning(message: str) -> AuthorIssue:
    issue = issue_from_message(message, default_code="CAMPAIGN_VALIDATION_WARNING")
    return AuthorIssue(
        severity="warning",
        code=issue.code,
        title=title_for_code(issue.code),
        message=message,
        why_it_matters="Warnings do not always block play, but they usually make the campaign harder to maintain.",
        file=issue.file,
        path=issue.path,
        raw_message=message,
        repair_options=(AuthorRepairOption(issue.suggestion, "manual_edit"),),
    )


def check_runtime_manifest_fields(manifest: dict[str, Any]) -> list[AuthorIssue]:
    issues: list[AuthorIssue] = []
    for field in RUNTIME_MANIFEST_FIELDS:
        if field not in manifest:
            continue
        issues.append(
            AuthorIssue(
                severity="suggestion",
                code="RUNTIME_FIELD_IN_CAMPAIGN_MANIFEST",
                title="Runtime path field exposed in campaign.yaml",
                message=f"campaign.yaml contains `{field}`. New author templates should rely on engine defaults.",
                why_it_matters="Runtime path fields make a Campaign Package look like a Save Package and add noise for non-coding authors.",
                file="campaign.yaml",
                path=field,
                repair_options=(
                    AuthorRepairOption(
                        f"Remove `{field}` unless this is a legacy/admin package.",
                        "edit_field",
                        f"# remove {field}: ...",
                    ),
                ),
            )
        )
    return issues


def check_generated_paths(root: Path) -> list[AuthorIssue]:
    issues: list[AuthorIssue] = []
    for name in GENERATED_PATHS:
        if not (root / name).exists():
            continue
        issues.append(
            AuthorIssue(
                severity="warning",
                code="GENERATED_PATH_IN_CAMPAIGN",
                title="Generated or save-only path found in Campaign Package",
                message=f"`{name}/` is usually generated by saves or operational tools, not authored content.",
                why_it_matters="Mixing generated files with author files makes sharing and reviewing a campaign harder.",
                file=name,
                repair_options=(
                    AuthorRepairOption(f"Move `{name}/` out of the Campaign Package if it is generated.", "move_path"),
                ),
            )
        )
    return issues


def check_large_yaml_files(root: Path) -> list[AuthorIssue]:
    issues: list[AuthorIssue] = []
    for path in sorted(root.rglob("*.yaml")):
        if "__pycache__" in path.parts:
            continue
        try:
            line_count = len(path.read_text(encoding="utf-8").splitlines())
        except UnicodeDecodeError:
            continue
        relative = relative_path(root, path)
        if line_count > LARGE_YAML_WARNING_LINES:
            severity = "warning"
        elif line_count > LARGE_YAML_SUGGESTION_LINES:
            severity = "suggestion"
        else:
            continue
        issues.append(
            AuthorIssue(
                severity=severity,
                code="LARGE_AUTHOR_YAML",
                title="Large YAML file may be hard to maintain",
                message=f"`{relative}` has {line_count} lines.",
                why_it_matters="Large monolithic YAML files are harder for authors, reviewers and AI assistants to edit safely.",
                file=relative,
                repair_options=(
                    AuthorRepairOption(
                        "Split content by type or region.",
                        "split_file",
                        "content/locations/*.yaml, content/characters/*.yaml, content/items/*.yaml",
                    ),
                ),
            )
        )
    return issues


def check_author_docs(root: Path) -> list[AuthorIssue]:
    issues: list[AuthorIssue] = []
    for relative, title in [
        ("AUTHOR_NOTES.md", "Author notes are missing"),
        ("AUTHOR_AI_PROMPT.md", "Author AI prompt is missing"),
    ]:
        if (root / relative).exists():
            continue
        issues.append(
            AuthorIssue(
                severity="suggestion",
                code="MISSING_AUTHOR_HELPER_DOC",
                title=title,
                message=f"`{relative}` is not present.",
                why_it_matters="These files help non-coding authors and external AI assistants understand what to edit.",
                file=relative,
                repair_options=(AuthorRepairOption(f"Add `{relative}` from an Author Kit template.", "add_file"),),
            )
        )
    return issues


def check_start_playability(root: Path, manifest: dict[str, Any], records_by_type: dict[str, list[dict[str, Any]]]) -> list[AuthorIssue]:
    issues: list[AuthorIssue] = []
    entities = records_by_type.get("entity", [])
    entity_by_id = {str(record.get("id")): record for record in entities if record.get("id")}
    initial_location_id = str(manifest.get("initial_location_id") or "")
    player_id = str((manifest.get("defaults") or {}).get("player_entity_id") or "") if isinstance(manifest.get("defaults"), dict) else ""
    location = entity_by_id.get(initial_location_id)
    player = entity_by_id.get(player_id)
    if not location or str(location.get("type")) != "location":
        return issues
    if not player:
        return issues
    signals = start_affordance_count(location, entities)
    if signals < 2:
        issues.append(
            AuthorIssue(
                severity="warning",
                code="LOW_STARTING_AFFORDANCE",
                title="Starting scene has few obvious actions",
                message=f"`{initial_location_id}` has fewer than two obvious action hooks.",
                why_it_matters="A first scene should make it obvious what the player can inspect, who they can talk to, or where they can go.",
                file="campaign.yaml",
                path="initial_location_id",
                repair_options=(
                    AuthorRepairOption("Add an NPC, route exit, resource, clue, or active project to the starting location.", "add_content"),
                ),
            )
        )
    return issues


def check_cjk_aliases(records_by_type: dict[str, list[dict[str, Any]]]) -> list[AuthorIssue]:
    entities = records_by_type.get("entity", [])
    if not any(has_cjk(str(record.get("name", "")) + str(record.get("summary", ""))) for record in entities):
        return []
    issues: list[AuthorIssue] = []
    for record in entities:
        if str(record.get("visibility", "known")) != "known":
            continue
        if str(record.get("type")) not in {"location", "character", "item", "project", "material", "reference"}:
            continue
        if record.get("aliases"):
            continue
        issues.append(
            AuthorIssue(
                severity="suggestion",
                code="CJK_ENTITY_WITHOUT_ALIAS",
                title="Chinese entity should have short aliases",
                message=f"`{record.get('id')}` has a Chinese-facing name or summary but no aliases.",
                why_it_matters="Short aliases make natural-language search and AI-assisted play more reliable.",
                file="content",
                path=str(record.get("id", "")),
                repair_options=(AuthorRepairOption("Add 1-3 short aliases.", "edit_field", "aliases: [营地, 起点]"),),
            )
        )
    return issues[:20]


def check_ai_generated_content(records_by_type: dict[str, list[dict[str, Any]]]) -> list[AuthorIssue]:
    issues: list[AuthorIssue] = []
    for record in records_by_type.get("entity", []):
        summary = str(record.get("summary") or "")
        if str(record.get("visibility", "known")) == "known" and "隐藏" in summary:
            issues.append(
                AuthorIssue(
                    severity="warning",
                    code="POSSIBLE_HIDDEN_LEAK_IN_SUMMARY",
                    title="Possible hidden information in known summary",
                    message=f"`{record.get('id')}` is known but its summary mentions hidden information.",
                    why_it_matters="Known summaries can appear in player-facing context.",
                    file="content",
                    path=str(record.get("id", "")),
                    repair_options=(AuthorRepairOption("Move hidden information into details.unknowns or a hidden entity.", "edit_field"),),
                )
            )
        if len(summary) > 420:
            issues.append(
                AuthorIssue(
                    severity="suggestion",
                    code="LONG_ENTITY_SUMMARY",
                    title="Entity summary is long",
                    message=f"`{record.get('id')}` summary is {len(summary)} characters.",
                    why_it_matters="Long summaries are harder to scan and consume context budget quickly.",
                    file="content",
                    path=str(record.get("id", "")),
                    repair_options=(AuthorRepairOption("Move detail into structured details and keep summary brief.", "edit_field"),),
                )
            )
    return issues


def render_doctor_result(result: AuthorDoctorResult) -> str:
    lines = [
        "# Campaign Doctor",
        "",
        f"- status: `{result.status.upper()}`",
        f"- campaign: `{result.campaign_id}`",
        f"- errors: `{result.errors}`",
        f"- warnings: `{result.warnings}`",
        f"- suggestions: `{result.suggestions}`",
    ]
    for severity, heading in [
        ("error", "Errors"),
        ("warning", "Warnings"),
        ("suggestion", "Suggestions"),
    ]:
        items = [issue for issue in result.issues if issue.severity == severity]
        if not items:
            continue
        lines.extend(["", f"## {heading}", ""])
        for issue in items:
            target = f" ({issue.file}{':' + issue.path if issue.path else ''})" if issue.file else ""
            lines.append(f"- `{issue.code}`{target}: {issue.message}")
            if issue.why_it_matters:
                lines.append(f"  - Why: {issue.why_it_matters}")
            for option in issue.repair_options:
                suffix = f" Example: {option.example}" if option.example else ""
                lines.append(f"  - Fix: {option.label}{suffix}")
    lines.extend(
        [
            "",
            "## Next Steps",
            "",
            "1. Fix errors first.",
            "2. Rerun `aigm campaign doctor <campaign>`.",
            "3. Run `aigm campaign test <campaign>` before sharing or playtesting.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def load_records_safely(root: Path) -> dict[str, list[dict[str, Any]]]:
    try:
        return load_package_source(root).records_by_type
    except Exception:
        return {}


def read_yaml_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None


def start_affordance_count(location: dict[str, Any], entities: list[dict[str, Any]]) -> int:
    location_id = str(location.get("id"))
    count = 0
    loc_details = location.get("location", {}) if isinstance(location.get("location"), dict) else {}
    if loc_details.get("exits"):
        count += len(loc_details.get("exits") or [])
    if loc_details.get("resources"):
        count += len(loc_details.get("resources") or [])
    for entity in entities:
        if str(entity.get("location_id")) != location_id:
            continue
        if str(entity.get("type")) in {"character", "project", "reference", "item", "material"}:
            count += 1
    return count


def has_cjk(text: str) -> bool:
    return bool(CJK_PATTERN.search(text))


def title_for_code(code: str) -> str:
    return {
        "MISSING_REQUIRED_VALUE": "Missing required value",
        "MISSING_REFERENCE": "Missing reference",
        "UNSUPPORTED_CAPABILITY": "Unsupported capability",
        "INVALID_VISIBILITY": "Invalid visibility",
        "INVALID_RANDOM": "Invalid random table",
        "INVALID_CLOCK": "Invalid clock",
        "DUPLICATE_ID": "Duplicate id",
    }.get(code, "Campaign validation issue")


def why_for_code(code: str) -> str:
    return {
        "MISSING_REQUIRED_VALUE": "The engine needs this value to load, initialize or test the campaign.",
        "MISSING_REFERENCE": "Broken references prevent entities, routes or relationships from resolving during play.",
        "UNSUPPORTED_CAPABILITY": "Capabilities declare which gameplay tools the runtime may use.",
        "INVALID_VISIBILITY": "Visibility controls what the player can see and protects hidden GM information.",
        "INVALID_RANDOM": "Random tables must be structured so rolls are reproducible and auditable.",
        "INVALID_CLOCK": "Progress clocks must have valid segment counts to track pressure safely.",
        "DUPLICATE_ID": "Stable IDs must be unique so saves and future updates can identify records.",
    }.get(code, "This issue can make the campaign harder to run or maintain.")


def dedupe_issues(issues: list[AuthorIssue]) -> list[AuthorIssue]:
    result: list[AuthorIssue] = []
    seen: set[tuple[str, str, str, str]] = set()
    for issue in issues:
        key = (issue.severity, issue.code, issue.file, issue.message)
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result


def relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
