from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .audit import run_audit
from .archivist import run_archivist_workflow, suggest_archivist
from .backup import create_backup, list_backups, render_backup_list, restore_backup
from .campaign import load_campaign
from .commit_service import commit_turn_delta
from .cli_v1 import action_options_from_args, add_v1_parsers, handle_v1_command
from .context_builder import build_context
from .content_factory import (
    audit_content_quality,
    make_content_delta,
    make_content_delta_from_palette,
    render_content_quality,
    split_csv,
    write_content_delta,
)
from .content_types.registry import render_content_type_detail, render_content_type_list
from .content_delta import apply_content_delta, load_content_delta
from .content_validation import validate_content_delta, validate_content_sources
from .content_sync import sync_campaign_content, sync_specs_for_names
from .db import connect, init_database
from .delta_draft import (
    check_delta_response_consistency,
    load_and_draft_delta,
    render_consistency_report,
    render_delta_diff,
)
from .delta_schema import load_schema_text, render_delta_validation, validate_delta_schema
from .ai.config import AI_HELPER_BACKENDS, AI_HELPER_FALLBACK_BACKENDS
from .compat.importers.registry import (
    get_default_importer_registry,
    render_importer_detail,
    render_importer_list,
    run_importer,
)
from .migrations import apply_pending_migrations, migration_status, render_migration_status
from .ops_report import write_ops_report
from .packages.archive import build_package_archive, render_package_build, render_package_test, test_package_source
from .packages.service import (
    adopt_existing_package_lock,
    apply_package_upgrade,
    diff_package_against_campaign,
    install_package_to_new_campaign,
    load_package_source,
    reconcile_package_adoption,
    render_package_adoption,
    render_package_apply,
    render_package_diff,
    render_package_install,
    render_package_validation,
    validate_package_source,
)
from .palette import render_palette_suggestions
from .admin.plugins import discover_plugin_manifests, render_plugin_list, render_plugin_validation
from .proposal import load_json_payload, load_turn_proposal, validate_turn_proposal
from .proposal_queue import (
    batch_review_proposals,
    create_proposal,
    get_proposal,
    list_proposals,
    mark_proposal_applied,
    proposal_report,
    render_proposal_report,
    render_proposal_list,
    render_rollback_plan,
    review_proposal,
)
from .projection_service import ProjectionReport, ProjectionService, _format_outbox_report_row
from .projections import render_projection_status
from .render import render_entity, render_scene
from .reflection import draft_reflection
from .response_acceptance import accept_response
from .response_lint import lint_response, load_response_text, load_turn_contract_from_context
from .runtime import GMRuntime
from .save import load_delta
from .simulation import write_simulation_report
from .turn_assistant import TurnAssistantOptions, run_turn_assistant
from .validators import run_checks
from .validation_pipeline import run_validation_pipeline
from .actions import get_default_action_registry
from .actions.base import ActionOptionSpec
from .actions.registry import render_action_resolver_detail, render_action_resolver_list
from .ai.defaults import (
    DEFAULT_AI_MODEL,
    DEFAULT_AI_PROVIDER,
    DEFAULT_ARCHIVIST_TIMEOUT_SECONDS,
    DEFAULT_INTENT_TIMEOUT_SECONDS,
    DEFAULT_REFLECTION_TIMEOUT_SECONDS,
    DEFAULT_SEMANTIC_TIMEOUT_SECONDS,
)
from .cli_text import add_user_text_source_args, resolve_user_text_arg


def add_action_option(parser: argparse.ArgumentParser, option: ActionOptionSpec) -> None:
    if option.name == "user_text":
        add_user_text_source_args(parser, required=option.required, help_text=option.help)
        return
    flag = "--" + (option.dest or option.name).replace("_", "-")
    kwargs: dict[str, object] = {
        "dest": option.name,
        "help": option.help,
        "required": option.required,
    }
    if option.default is not None:
        kwargs["default"] = option.default
    parser.add_argument(flag, **kwargs)


def add_preview_parsers(subparsers: argparse._SubParsersAction, registry: object) -> None:
    for spec in registry.all():
        action_parser = subparsers.add_parser(spec.name, help=f"preview a {spec.name} action without saving")
        action_parser.add_argument("campaign_dir")
        for option in spec.option_specs:
            add_action_option(action_parser, option)


def load_json_object_arg(value: str | None, *, label: str) -> dict[str, Any] | None:
    if not value:
        return None
    source = value.strip()
    if source.startswith("{"):
        data = json.loads(source)
    else:
        data = json.loads(Path(source).expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object")
    return data


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def refresh_cli_projections(
    campaign: Any,
    conn: Any,
    names: list[str],
    *,
    profile: str,
    dirty_only: bool = False,
    options: dict[str, dict[str, Any]] | None = None,
    commit_policy: str = "caller_committed_required",
) -> ProjectionReport:
    return ProjectionService(campaign, conn).refresh(
        names=names,
        dirty_only=dirty_only,
        profile=profile,
        options=options,
        commit_policy=commit_policy,
    )


def projection_artifact(report: ProjectionReport, name: str, index: int = 0) -> str | None:
    artifacts = report.artifacts_for(name)
    return artifacts[index] if len(artifacts) > index else None


def projection_count(report: ProjectionReport, name: str) -> int:
    item = report.item(name)
    if not item:
        return 0
    if "count" in item.metadata:
        return int(item.metadata["count"])
    return len(item.artifacts)


def strict_review_blockers(delta: dict[str, Any], warnings: list[str]) -> list[str]:
    meta = delta.get("meta", {})
    reviewed_by = isinstance(meta, dict) and bool(meta.get("reviewed_by"))
    review_required = isinstance(meta, dict) and bool(meta.get("review_required"))
    blockers = [warning for warning in warnings if "requires meta.review_required=true or meta.reviewed_by" in warning]
    if review_required and not reviewed_by:
        blockers.append("meta.review_required=true is present but meta.reviewed_by is not set")
    return [] if reviewed_by else list(dict.fromkeys(blockers))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rpg_engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    registered_actions = get_default_action_registry().names()
    add_v1_parsers(subparsers, registered_actions)

    init_parser = subparsers.add_parser("init", help="initialize campaign database")
    init_parser.add_argument("campaign_dir")
    init_parser.add_argument("--force", action="store_true", help="recreate database and event log")

    query_parser = subparsers.add_parser("query", help="query campaign state")
    query_sub = query_parser.add_subparsers(dest="query_type", required=True)
    entity_parser = query_sub.add_parser("entity", help="query one entity by id/name/alias")
    entity_parser.add_argument("campaign_dir")
    entity_parser.add_argument("name")
    entity_parser.add_argument(
        "--view",
        default="player",
        choices=["player", "gm", "maintenance"],
        help="visibility view for this query; player hides hidden facts",
    )
    scene_parser = query_sub.add_parser("scene", help="render current scene packet")
    scene_parser.add_argument("campaign_dir")
    scene_parser.add_argument(
        "--view",
        default="player",
        choices=["player", "gm", "maintenance"],
        help="visibility view for this query; player hides hidden facts",
    )

    context_parser = subparsers.add_parser("context", help="build a token-bounded AI context packet")
    context_sub = context_parser.add_subparsers(dest="context_type", required=True)
    context_build_parser = context_sub.add_parser("build", help="build context for one player request")
    context_build_parser.add_argument("campaign_dir")
    add_user_text_source_args(context_build_parser, required=True, help_text="current player request")
    context_build_parser.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "query", "action", "maintenance"],
        help="request mode; auto classifies from user text",
    )
    context_build_parser.add_argument(
        "--submode",
        choices=["entity", "scene", "context", *registered_actions, "maintenance"],
        help="optional request submode",
    )
    context_build_parser.add_argument("--budget", type=int, help="rough token budget; omitted uses dynamic policy")
    context_build_parser.add_argument("--max-events", type=int, default=6, help="recent events to include")
    context_build_parser.add_argument("--max-depth", type=int, default=1, help="related entity expansion depth")
    context_build_parser.add_argument(
        "--include-palettes",
        default="auto",
        choices=["auto", "always", "never"],
        help="whether to include generation palette candidates",
    )
    context_build_parser.add_argument(
        "--format",
        default="markdown",
        choices=["markdown", "json"],
        help="output format",
    )
    helper_backend_choices = [*AI_HELPER_BACKENDS, "hermes"]
    fallback_backend_choices = [*AI_HELPER_FALLBACK_BACKENDS, "hermes"]
    context_build_parser.add_argument(
        "--semantic-ai",
        default="off",
        choices=helper_backend_choices,
        help="optional semantic intent helper; off keeps context build pure rule/database based",
    )
    context_build_parser.add_argument(
        "--semantic-model",
        default=DEFAULT_AI_MODEL,
        help="model used when --semantic-ai=hermes",
    )
    context_build_parser.add_argument(
        "--semantic-provider",
        default=DEFAULT_AI_PROVIDER,
        help="provider used when --semantic-ai=hermes",
    )
    context_build_parser.add_argument(
        "--semantic-timeout",
        type=int,
        default=DEFAULT_SEMANTIC_TIMEOUT_SECONDS,
        help="semantic helper timeout in seconds",
    )
    context_build_parser.add_argument("--intent-ai", default="off", choices=["off", "consensus"])
    context_build_parser.add_argument("--intent-backend", default="direct", choices=helper_backend_choices)
    context_build_parser.add_argument("--intent-provider", default=DEFAULT_AI_PROVIDER)
    context_build_parser.add_argument("--intent-model", default=DEFAULT_AI_MODEL)
    context_build_parser.add_argument("--intent-timeout", type=int, default=DEFAULT_INTENT_TIMEOUT_SECONDS)
    context_build_parser.add_argument("--intent-base-url", default="")
    context_build_parser.add_argument("--intent-api-key-env", default="")
    context_build_parser.add_argument("--intent-fallback-backend", default="off", choices=fallback_backend_choices)
    context_build_parser.add_argument("--external-intent-candidate", help="JSON object or file path for the external AI intent candidate")
    context_build_parser.add_argument("--preflight-id", default="")
    context_build_parser.add_argument("--message-id", default="")
    context_build_parser.add_argument("--platform", default="")
    context_build_parser.add_argument("--session-key", default="")
    context_build_parser.add_argument("--source-user-text-hash", default="")
    context_build_parser.add_argument(
        "--audit-context",
        action="store_true",
        help="write this context build to context_runs/context_items; default remains pure read",
    )
    context_build_parser.add_argument(
        "--context-run-id",
        help="optional explicit id for --audit-context",
    )
    context_build_parser.add_argument("--debug", action="store_true", help="include debug budget details")

    memory_parser = subparsers.add_parser("memory", help="build or inspect long-term memory summaries")
    memory_sub = memory_parser.add_subparsers(dest="memory_type", required=True)
    memory_rebuild_parser = memory_sub.add_parser("rebuild", help="rebuild deterministic day/reflection summaries")
    memory_rebuild_parser.add_argument("campaign_dir")
    memory_suggest_parser = memory_sub.add_parser("suggest", help="draft advisory Archivist suggestions without writing facts")
    memory_suggest_parser.add_argument("campaign_dir")
    memory_suggest_parser.add_argument("--turn-id")
    memory_suggest_parser.add_argument("--ai", default="off", choices=helper_backend_choices)
    memory_suggest_parser.add_argument("--provider", default=DEFAULT_AI_PROVIDER)
    memory_suggest_parser.add_argument("--model", default=DEFAULT_AI_MODEL)
    memory_suggest_parser.add_argument("--timeout", type=int, default=DEFAULT_ARCHIVIST_TIMEOUT_SECONDS)
    memory_suggest_parser.add_argument("--store", action="store_true", help="store the suggestion in archivist_suggestions")
    memory_suggest_parser.add_argument("--enqueue", action="store_true", help="also enqueue memory/alias proposals for review")
    memory_suggest_parser.add_argument("--format", default="markdown", choices=["markdown", "json"])

    render_parser = subparsers.add_parser("render-current", help="write snapshots/current.md")
    render_parser.add_argument("campaign_dir")

    cards_parser = subparsers.add_parser("render-cards", help="write generated entity cards")
    cards_parser.add_argument("campaign_dir")
    cards_parser.add_argument("--no-clean", action="store_true", help="keep old generated cards")
    cards_parser.add_argument(
        "--index-view",
        default="player",
        choices=["player", "gm", "maintenance"],
        help="visibility view used for cards/INDEX.md; card files are still generated for all non-archived entities",
    )

    save_parser = subparsers.add_parser("save-turn", help="save one structured turn delta")
    save_parser.add_argument("campaign_dir")
    save_parser.add_argument("delta_json")

    validate_parser = subparsers.add_parser("validate", help="validate structured files without mutating state")
    validate_sub = validate_parser.add_subparsers(dest="validate_type", required=True)
    validate_delta_parser = validate_sub.add_parser("delta", help="validate a save-turn delta against engine schema and DB refs")
    validate_delta_parser.add_argument("campaign_dir")
    validate_delta_parser.add_argument("delta_json")
    validate_delta_parser.add_argument("--schema-only", action="store_true", help="only run legacy schema/DB reference checks")
    validate_sub.add_parser("schema", help="print the turn delta JSON schema")

    response_parser = subparsers.add_parser("response", help="lint AI GM responses")
    response_sub = response_parser.add_subparsers(dest="response_type", required=True)
    response_lint_parser = response_sub.add_parser("lint", help="check response structure")
    response_lint_parser.add_argument("campaign_dir")
    response_lint_parser.add_argument("--response-file")
    response_lint_parser.add_argument("--text")
    response_lint_parser.add_argument("--context-json", required=True)
    response_lint_parser.add_argument("--strict", action="store_true")

    proposal_parser = subparsers.add_parser("proposal", help="validate AI turn proposals before approval")
    proposal_sub = proposal_parser.add_subparsers(dest="proposal_type", required=True)
    proposal_validate_parser = proposal_sub.add_parser("validate", help="validate one TurnProposal JSON file")
    proposal_validate_parser.add_argument("campaign_dir")
    proposal_validate_parser.add_argument("proposal_json")
    proposal_validate_parser.add_argument("--response-file")
    proposal_validate_parser.add_argument("--text")
    proposal_create_parser = proposal_sub.add_parser("create", help="enqueue a structured proposal for review")
    proposal_create_parser.add_argument("campaign_dir")
    proposal_create_parser.add_argument("proposal_json")
    proposal_create_parser.add_argument("--kind", default="content_delta", choices=["content_delta", "turn_delta", "memory_update", "alias_suggestion"])
    proposal_create_parser.add_argument("--source-turn-id")
    proposal_create_parser.add_argument("--format", default="markdown", choices=["markdown", "json"])
    proposal_list_parser = proposal_sub.add_parser("list", help="list queued proposals")
    proposal_list_parser.add_argument("campaign_dir")
    proposal_list_parser.add_argument("--status")
    proposal_list_parser.add_argument("--kind")
    proposal_list_parser.add_argument("--risk-level")
    proposal_list_parser.add_argument("--limit", type=int, default=50)
    proposal_list_parser.add_argument("--format", default="markdown", choices=["markdown", "json"])
    proposal_report_parser = proposal_sub.add_parser("report", help="summarize proposal queue health")
    proposal_report_parser.add_argument("campaign_dir")
    proposal_report_parser.add_argument("--format", default="markdown", choices=["markdown", "json"])
    proposal_review_parser = proposal_sub.add_parser("review", help="approve or reject a queued proposal")
    proposal_review_parser.add_argument("campaign_dir")
    proposal_review_parser.add_argument("proposal_id")
    decision = proposal_review_parser.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    proposal_review_parser.add_argument("--reviewed-by", required=True)
    proposal_review_parser.add_argument("--reason")
    proposal_review_parser.add_argument("--format", default="markdown", choices=["markdown", "json"])
    proposal_batch_parser = proposal_sub.add_parser("batch-review", help="approve or reject multiple queued proposals")
    proposal_batch_parser.add_argument("campaign_dir")
    proposal_batch_parser.add_argument("--proposal-id", action="append", dest="proposal_ids")
    batch_decision = proposal_batch_parser.add_mutually_exclusive_group(required=True)
    batch_decision.add_argument("--approve", action="store_true")
    batch_decision.add_argument("--reject", action="store_true")
    proposal_batch_parser.add_argument("--reviewed-by", required=True)
    proposal_batch_parser.add_argument("--reason")
    proposal_batch_parser.add_argument("--status", default="needs_review")
    proposal_batch_parser.add_argument("--kind")
    proposal_batch_parser.add_argument("--risk-level")
    proposal_batch_parser.add_argument("--limit", type=int, default=50)
    proposal_batch_parser.add_argument("--format", default="markdown", choices=["markdown", "json"])
    proposal_apply_parser = proposal_sub.add_parser("apply", help="apply an approved queued content proposal")
    proposal_apply_parser.add_argument("campaign_dir")
    proposal_apply_parser.add_argument("proposal_id")
    proposal_apply_parser.add_argument("--format", default="markdown", choices=["markdown", "json"])
    proposal_rollback_parser = proposal_sub.add_parser("rollback-plan", help="show rollback guidance for a proposal")
    proposal_rollback_parser.add_argument("campaign_dir")
    proposal_rollback_parser.add_argument("proposal_id")
    proposal_rollback_parser.add_argument("--format", default="markdown", choices=["markdown", "json"])

    delta_parser = subparsers.add_parser("delta", help="draft, preview and check turn deltas")
    delta_sub = delta_parser.add_subparsers(dest="delta_type", required=True)
    delta_draft_parser = delta_sub.add_parser("draft", help="draft a conservative delta from an AI GM response")
    delta_draft_parser.add_argument("campaign_dir")
    add_user_text_source_args(delta_draft_parser, required=True)
    delta_draft_parser.add_argument("--response-file")
    delta_draft_parser.add_argument("--text")
    delta_draft_parser.add_argument("--intent", default="assistant_draft")
    delta_draft_parser.add_argument("--output", help="write raw delta JSON to this file")
    delta_diff_parser = delta_sub.add_parser("diff", help="preview what a delta would change")
    delta_diff_parser.add_argument("campaign_dir")
    delta_diff_parser.add_argument("delta_json")
    delta_check_parser = delta_sub.add_parser("check-response", help="check delta/response consistency")
    delta_check_parser.add_argument("campaign_dir")
    delta_check_parser.add_argument("delta_json")
    delta_check_parser.add_argument("--response-file")
    delta_check_parser.add_argument("--text")

    turn_parser = subparsers.add_parser("turn", help="orchestrate context, preview, lint, delta validation and optional save")
    turn_sub = turn_parser.add_subparsers(dest="turn_type", required=True)
    turn_assistant_parser = turn_sub.add_parser("assistant", help="run one conservative turn assistant pass")
    turn_assistant_parser.add_argument("campaign_dir")
    add_user_text_source_args(turn_assistant_parser, required=True)
    turn_assistant_parser.add_argument("--budget", type=int, default=2500)
    turn_assistant_parser.add_argument("--mode", default="auto", choices=["auto", "query", "action", "maintenance"])
    turn_assistant_parser.add_argument("--submode")
    turn_assistant_parser.add_argument("--target")
    turn_assistant_parser.add_argument("--project")
    turn_assistant_parser.add_argument("--output")
    turn_assistant_parser.add_argument("--weapon")
    turn_assistant_parser.add_argument("--ammo")
    turn_assistant_parser.add_argument("--distance")
    turn_assistant_parser.add_argument("--ready-state")
    turn_assistant_parser.add_argument("--destination")
    turn_assistant_parser.add_argument("--pace", default="normal")
    turn_assistant_parser.add_argument("--location")
    turn_assistant_parser.add_argument("--materials")
    turn_assistant_parser.add_argument("--time", dest="time_cost")
    turn_assistant_parser.add_argument("--npc")
    turn_assistant_parser.add_argument("--topic")
    turn_assistant_parser.add_argument("--approach")
    turn_assistant_parser.add_argument("--until")
    turn_assistant_parser.add_argument("--response-file")
    turn_assistant_parser.add_argument("--response-text")
    turn_assistant_parser.add_argument("--proposal-json")
    turn_assistant_parser.add_argument("--delta-json")
    turn_assistant_parser.add_argument("--save", action="store_true")
    turn_assistant_parser.add_argument("--rebuild-memory", action="store_true")
    turn_assistant_parser.add_argument("--audit-context", action="store_true")
    turn_assistant_parser.add_argument("--context-run-id")
    turn_accept_parser = turn_sub.add_parser("accept-response", help="draft, validate and optionally save an AI response")
    turn_accept_parser.add_argument("campaign_dir")
    add_user_text_source_args(turn_accept_parser, required=True)
    turn_accept_parser.add_argument("--response-file")
    turn_accept_parser.add_argument("--response-text")
    turn_accept_parser.add_argument("--mode", default="action", choices=["action", "query", "maintenance"])
    turn_accept_parser.add_argument("--submode")
    turn_accept_parser.add_argument("--intent", default="accepted_response")
    turn_accept_parser.add_argument("--output-delta")
    accept_save_group = turn_accept_parser.add_mutually_exclusive_group()
    accept_save_group.add_argument(
        "--save-if-safe",
        action="store_true",
        help="request auto-save only when validation has no warnings/blockers; response_draft still requires proposal guard approval",
    )
    accept_save_group.add_argument("--confirm-save", action="store_true", help="explicitly save after human/GM review")
    turn_accept_parser.add_argument("--rebuild-memory", action="store_true")

    reflection_parser = subparsers.add_parser("reflection", help="draft auditable long-term reflections")
    reflection_sub = reflection_parser.add_subparsers(dest="reflection_type", required=True)
    reflection_draft_parser = reflection_sub.add_parser("draft", help="draft a reflection for one entity")
    reflection_draft_parser.add_argument("campaign_dir")
    reflection_draft_parser.add_argument("--subject", required=True)
    reflection_draft_parser.add_argument("--ai", default="off", choices=helper_backend_choices)
    reflection_draft_parser.add_argument("--model", default=DEFAULT_AI_MODEL)
    reflection_draft_parser.add_argument("--provider", default=DEFAULT_AI_PROVIDER)
    reflection_draft_parser.add_argument("--timeout", type=int, default=DEFAULT_REFLECTION_TIMEOUT_SECONDS)
    reflection_draft_parser.add_argument("--output")

    ops_parser = subparsers.add_parser("ops", help="write operational reports")
    ops_sub = ops_parser.add_subparsers(dest="ops_type", required=True)
    ops_report_parser = ops_sub.add_parser("report", help="write current operations report")
    ops_report_parser.add_argument("campaign_dir")
    ops_report_parser.add_argument("--report")
    ops_report_parser.add_argument("--speed", action="store_true")

    backup_parser = subparsers.add_parser("backup", help="create, list and restore campaign backups")
    backup_sub = backup_parser.add_subparsers(dest="backup_type", required=True)
    backup_create_parser = backup_sub.add_parser("create", help="create a campaign backup")
    backup_create_parser.add_argument("campaign_dir")
    backup_create_parser.add_argument("--reason", default="manual")
    backup_list_parser = backup_sub.add_parser("list", help="list campaign backups")
    backup_list_parser.add_argument("campaign_dir")
    backup_restore_parser = backup_sub.add_parser("restore", help="restore a campaign backup")
    backup_restore_parser.add_argument("campaign_dir")
    backup_restore_parser.add_argument("backup_id")
    backup_restore_parser.add_argument("--yes", action="store_true", help="required confirmation for restore")
    backup_restore_parser.add_argument(
        "--no-pre-restore-backup",
        action="store_true",
        help="skip automatic backup before restore",
    )

    migrate_parser = subparsers.add_parser("migrate", help="inspect and apply database migrations")
    migrate_sub = migrate_parser.add_subparsers(dest="migrate_type", required=True)
    migrate_status_parser = migrate_sub.add_parser("status", help="show schema migration status")
    migrate_status_parser.add_argument("campaign_dir")
    migrate_apply_parser = migrate_sub.add_parser("apply", help="apply pending schema migrations")
    migrate_apply_parser.add_argument("campaign_dir")

    projection_parser = subparsers.add_parser("projection", help="inspect and repair derived projections")
    projection_sub = projection_parser.add_subparsers(dest="projection_type", required=True)
    projection_status_parser = projection_sub.add_parser("status", help="show projection and outbox status")
    projection_status_parser.add_argument("campaign_dir")
    projection_repair_parser = projection_sub.add_parser("repair", help="retry outbox and rebuild dirty projections")
    projection_repair_parser.add_argument("campaign_dir")
    projection_repair_parser.add_argument(
        "--name",
        action="append",
        choices=["events_jsonl", "search", "snapshots", "cards", "memory", "reports", "package_lock"],
        help="projection to repair; repeatable; defaults to all dirty projections",
    )
    projection_repair_parser.add_argument("--all", action="store_true", help="rebuild selected/all projections even if clean")

    package_parser = subparsers.add_parser("package", help="validate, install and safely upgrade campaign packages")
    package_sub = package_parser.add_subparsers(dest="package_type", required=True)
    package_build_parser = package_sub.add_parser("build", help="build a portable package archive")
    package_build_parser.add_argument("package_dir")
    package_build_parser.add_argument("--output")
    package_test_parser = package_sub.add_parser("test", help="validate a package and optionally diff it against a campaign")
    package_test_parser.add_argument("package_dir")
    package_test_parser.add_argument("--campaign-dir")
    package_validate_parser = package_sub.add_parser("validate", help="validate a package directory without mutating state")
    package_validate_parser.add_argument("package_dir")
    package_install_parser = package_sub.add_parser("install", help="install a package into a new campaign or adopt a legacy lock")
    package_install_parser.add_argument("campaign_dir")
    package_install_parser.add_argument("package_dir")
    package_install_parser.add_argument(
        "--adopt-existing",
        action="store_true",
        help="write package-lock.json for an already initialized legacy campaign only if reconcile is clean",
    )
    package_install_parser.add_argument("--force", action="store_true", help="replace an existing lock or non-empty install target")
    package_reconcile_parser = package_sub.add_parser("reconcile", help="check whether an initialized campaign can safely adopt a package lock")
    package_reconcile_parser.add_argument("campaign_dir")
    package_reconcile_parser.add_argument("package_dir")
    package_diff_parser = package_sub.add_parser("diff", help="diff a package directory against a campaign save")
    package_diff_parser.add_argument("campaign_dir")
    package_diff_parser.add_argument("package_dir")
    package_upgrade_parser = package_sub.add_parser("upgrade", help="apply or dry-run a package upgrade against a campaign save")
    package_upgrade_parser.add_argument("campaign_dir")
    package_upgrade_parser.add_argument("package_dir")
    package_upgrade_parser.add_argument("--dry-run", action="store_true", help="show package upgrade plan without mutating state")

    simulate_parser = subparsers.add_parser("simulate", help="run system-level simulations on a temp campaign copy")
    simulate_sub = simulate_parser.add_subparsers(dest="simulate_type", required=True)
    simulate_longrun_parser = simulate_sub.add_parser("longrun", help="run many context/save turns against a temp copy")
    simulate_longrun_parser.add_argument("campaign_dir")
    simulate_longrun_parser.add_argument("--turns", type=int, default=30)
    simulate_longrun_parser.add_argument("--budget", type=int, default=3000)
    simulate_longrun_parser.add_argument("--report")

    content_parser = subparsers.add_parser("content", help="generate and audit content maintenance data")
    content_sub = content_parser.add_subparsers(dest="content_type", required=True)
    content_sub.add_parser("list-types", help="list registered content types")
    content_inspect_type_parser = content_sub.add_parser("inspect-type", help="inspect one registered content type")
    content_inspect_type_parser.add_argument("name")
    content_sync_parser = content_sub.add_parser("sync", help="sync registered campaign content into the current database")
    content_sync_parser.add_argument("campaign_dir")
    content_sync_parser.add_argument(
        "--type",
        action="append",
        dest="sync_types",
        default=None,
        help="content type to sync; defaults to world_setting; repeatable",
    )
    content_sync_parser.add_argument(
        "--allow-unsafe",
        action="store_true",
        help="allow syncing content types not marked sync_safe",
    )
    content_sync_parser.add_argument("--expected-turn-id", help="reject sync if current turn changed")
    content_sync_parser.add_argument("--command-id", help="idempotency key for this sync")
    content_new_parser = content_sub.add_parser("new", help="create a content-delta draft from a template")
    content_new_parser.add_argument("kind", choices=["material", "location", "species", "faction", "recipe", "project", "npc"])
    content_new_parser.add_argument("campaign_dir")
    content_new_parser.add_argument("--id", required=True)
    content_new_parser.add_argument("--name", required=True)
    content_new_parser.add_argument("--summary", required=True)
    content_new_parser.add_argument("--location")
    content_new_parser.add_argument("--rarity")
    content_new_parser.add_argument("--uses")
    content_new_parser.add_argument("--risks")
    content_new_parser.add_argument("--aliases")
    content_new_parser.add_argument("--output")
    content_palette_parser = content_sub.add_parser("from-palette", help="create a content-delta draft from a palette candidate")
    content_palette_parser.add_argument("campaign_dir")
    content_palette_parser.add_argument("palette_id")
    content_palette_parser.add_argument("--visibility", default="hinted", choices=["known", "hinted", "hidden"])
    content_palette_parser.add_argument("--location")
    content_palette_parser.add_argument("--output")
    content_audit_parser = content_sub.add_parser("audit", help="audit content density and maintainability")
    content_audit_parser.add_argument("campaign_dir")
    content_audit_parser.add_argument("--report")
    content_validate_parser = content_sub.add_parser("validate-delta", help="preflight a content delta without writing")
    content_validate_parser.add_argument("campaign_dir")
    content_validate_parser.add_argument("delta_json")

    content_delta_parser = subparsers.add_parser(
        "apply-content-delta",
        help="apply a non-turn content maintenance delta",
    )
    content_delta_parser.add_argument("campaign_dir")
    content_delta_parser.add_argument("delta_json")
    content_delta_parser.add_argument(
        "--strict-review",
        action="store_true",
        help="block high-impact content deltas unless meta.reviewed_by is present",
    )

    action_parser = subparsers.add_parser("action", help="inspect registered action resolvers")
    action_sub = action_parser.add_subparsers(dest="action_type", required=True)
    action_sub.add_parser("list", help="list registered action resolvers")
    action_inspect_parser = action_sub.add_parser("inspect", help="inspect one action resolver")
    action_inspect_parser.add_argument("name")

    plugin_parser = subparsers.add_parser("plugin", help="inspect plugin manifests without loading code")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_type", required=True)
    plugin_list_parser = plugin_sub.add_parser("list", help="list campaign plugin manifests")
    plugin_list_parser.add_argument("campaign_dir")
    plugin_validate_parser = plugin_sub.add_parser("validate", help="validate campaign plugin manifests")
    plugin_validate_parser.add_argument("campaign_dir")

    check_parser = subparsers.add_parser("check", help="run consistency checks")
    check_parser.add_argument("campaign_dir")

    audit_parser = subparsers.add_parser("audit", help="write a non-blocking save-quality audit report")
    audit_parser.add_argument("campaign_dir")
    audit_parser.add_argument("--report", help="write markdown audit report to this path")

    preview_parser = subparsers.add_parser("preview", help="preview a structured action without saving")
    preview_sub = preview_parser.add_subparsers(dest="preview_type", required=True)
    add_preview_parsers(preview_sub, get_default_action_registry())

    palette_parser = subparsers.add_parser("palette", help="query campaign generation palettes")
    palette_sub = palette_parser.add_subparsers(dest="palette_type", required=True)
    palette_suggest_parser = palette_sub.add_parser("suggest", help="suggest legal palette entries for context")
    palette_suggest_parser.add_argument("campaign_dir")
    palette_suggest_parser.add_argument(
        "--kind",
        default="all",
        choices=["all", "biome", "material", "species", "faction", "encounter", "location"],
        help="palette kind to query",
    )
    palette_suggest_parser.add_argument("--location", help="location id/name/alias; defaults to current location")
    palette_suggest_parser.add_argument("--intent", help="action intent, such as gather/travel/social/craft")
    palette_suggest_parser.add_argument("--include-locked", action="store_true", help="include locked entries")
    palette_suggest_parser.add_argument("--limit", type=int, default=12, help="maximum candidates to print")

    import_parser = subparsers.add_parser("import-v1", help="import a campaign-specific v1 markdown save")
    import_parser.add_argument("campaign_dir")
    import_parser.add_argument("--source", help="source v1 directory; defaults to campaign/archive_v1")
    import_parser.add_argument("--apply", action="store_true", help="write parsed entities into the campaign database")
    import_parser.add_argument("--report", help="write markdown import report to this path")

    importer_parser = subparsers.add_parser("importer", help="inspect and run registered importers")
    importer_sub = importer_parser.add_subparsers(dest="importer_type", required=True)
    importer_sub.add_parser("list", help="list registered importers")
    importer_inspect_parser = importer_sub.add_parser("inspect", help="inspect one importer")
    importer_inspect_parser.add_argument("name")
    importer_run_parser = importer_sub.add_parser("run", help="run one importer")
    importer_run_parser.add_argument("campaign_dir")
    importer_run_parser.add_argument("name")
    importer_run_parser.add_argument("--source")
    importer_run_parser.add_argument("--apply", action="store_true")
    importer_run_parser.add_argument("--report")

    args = parser.parse_args(argv)

    v1_result = handle_v1_command(args)
    if v1_result is not None:
        return v1_result

    if args.command == "init":
        campaign = load_campaign(args.campaign_dir)
        init_database(campaign, force=args.force)
        with connect(campaign) as conn:
            projection_report = refresh_cli_projections(
                campaign,
                conn,
                ["events_jsonl", "search", "snapshots", "cards"],
                profile="init:maintenance_projection",
            )
        path = projection_artifact(projection_report, "snapshots", 0)
        json_path = projection_artifact(projection_report, "snapshots", 1)
        cards_count = projection_count(projection_report, "cards")
        print(f"initialized {campaign.name}")
        print(path)
        print(json_path)
        print(f"cards: {cards_count}")
        return 0 if projection_report.ok else 1

    if args.command == "query":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            if args.query_type == "entity":
                print(render_entity(conn, args.name, view=args.view))
            elif args.query_type == "scene":
                print(render_scene(conn, view=args.view))
        return 0

    if args.command == "context":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            if args.context_type == "build":
                packet = build_context(
                    campaign,
                    conn,
                    user_text=resolve_user_text_arg(args),
                    mode=args.mode,
                    submode=args.submode,
                    budget=args.budget,
                    output_format=args.format,
                    max_events=args.max_events,
                    max_depth=args.max_depth,
                    include_palettes=args.include_palettes,
                    debug=args.debug,
                    semantic_ai=args.semantic_ai,
                    semantic_model=args.semantic_model,
                    semantic_provider=args.semantic_provider,
                    semantic_timeout=args.semantic_timeout,
                    intent_ai=args.intent_ai,
                    intent_backend=args.intent_backend,
                    intent_provider=args.intent_provider,
                    intent_model=args.intent_model,
                    intent_timeout=args.intent_timeout,
                    intent_base_url=args.intent_base_url,
                    intent_api_key_env=args.intent_api_key_env,
                    intent_fallback_backend=args.intent_fallback_backend,
                    external_intent_candidate=load_json_object_arg(
                        args.external_intent_candidate,
                        label="--external-intent-candidate",
                    ),
                    preflight_id=args.preflight_id,
                    message_id=args.message_id,
                    platform=args.platform,
                    session_key=args.session_key,
                    source_user_text_hash=args.source_user_text_hash,
                    audit_context=args.audit_context,
                    audit_context_run_id=args.context_run_id,
                )
                if args.format == "json":
                    print(packet.to_json_text())
                else:
                    print(packet.markdown, end="")
        return 0

    if args.command == "memory":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            if args.memory_type == "rebuild":
                projection_report = refresh_cli_projections(
                    campaign,
                    conn,
                    ["memory"],
                    profile="memory_rebuild:maintenance_projection",
                )
                memory_item = projection_report.item("memory")
                by_kind = memory_item.metadata.get("by_kind", {}) if memory_item else {}
                print(f"memory summaries: {memory_item.metadata.get('summaries', 0) if memory_item else 0}")
                for kind, count in sorted(by_kind.items()):
                    print(f"{kind}: {count}")
                print(projection_artifact(projection_report, "memory", 0))
                return 0 if projection_report.ok else 1
            elif args.memory_type == "suggest":
                if args.store or args.enqueue:
                    result = run_archivist_workflow(
                        conn,
                        turn_id=args.turn_id,
                        ai=args.ai,
                        provider=args.provider,
                        model=args.model,
                        timeout=args.timeout,
                        enqueue=args.enqueue,
                    )
                    conn.commit()
                    if args.format == "json":
                        print_json(result.to_dict())
                    else:
                        print(result.render(), end="")
                    return 0 if not result.suggest_result.errors else 1
                result = suggest_archivist(
                    conn,
                    turn_id=args.turn_id,
                    ai=args.ai,
                    provider=args.provider,
                    model=args.model,
                    timeout=args.timeout,
                )
                if args.format == "json":
                    print_json(result.to_dict())
                else:
                    print(result.render(), end="")
                return 0 if not result.errors else 1
        return 0

    if args.command == "validate":
        if args.validate_type == "schema":
            print(load_schema_text())
            return 0
        campaign = load_campaign(args.campaign_dir)
        delta = load_delta(args.delta_json)
        if args.schema_only:
            with connect(campaign) as conn:
                errors = validate_delta_schema(delta, conn)
            print(render_delta_validation(errors))
            return 1 if errors else 0
        result = GMRuntime(campaign).validate_delta(delta)
        if result.ok and not result.warnings:
            print("OK")
        else:
            print("OK" if result.ok else "FAILED")
            for item in result.missing_required:
                print(f"- missing: {item}")
            for item in result.errors:
                print(f"- error: {item}")
            for item in result.warnings:
                print(f"- warning: {item}")
        return 0 if result.ok else 1

    if args.command == "response":
        campaign = load_campaign(args.campaign_dir)
        del campaign
        context_json = json.loads(Path(args.context_json).read_text(encoding="utf-8"))
        text = load_response_text(args.response_file, args.text)
        result = lint_response(
            text,
            turn_contract=load_turn_contract_from_context(context_json),
            strict=args.strict,
        )
        print(result.render(), end="")
        return 0 if result.ok else 1

    if args.command == "proposal":
        campaign = load_campaign(args.campaign_dir)
        if args.proposal_type == "validate":
            proposal = load_turn_proposal(args.proposal_json)
            response_text = load_response_text(args.response_file, args.text) if args.response_file or args.text else None
            with connect(campaign) as conn:
                result = validate_turn_proposal(campaign, conn, proposal, response_text=response_text)
            print(result.render(), end="")
            return 0 if result.ok else 1
        if args.proposal_type == "create":
            payload = load_json_payload(args.proposal_json)
            with connect(campaign) as conn:
                record = create_proposal(
                    conn,
                    kind=args.kind,
                    payload=payload,
                    source_turn_id=args.source_turn_id,
                )
                conn.commit()
            if args.format == "json":
                print_json(record.to_dict())
            else:
                print(f"created: {record.id}")
                print(f"status: {record.status}")
                print(f"risk_level: {record.risk_level}")
            return 0
        if args.proposal_type == "list":
            with connect(campaign) as conn:
                records = list_proposals(
                    conn,
                    status=args.status,
                    kind=args.kind,
                    risk_level=args.risk_level,
                    limit=args.limit,
                )
            if args.format == "json":
                print_json({"proposals": [record.to_dict() for record in records]})
            else:
                print(render_proposal_list(records), end="")
            return 0
        if args.proposal_type == "report":
            with connect(campaign) as conn:
                report = proposal_report(conn)
            if args.format == "json":
                print_json(report)
            else:
                print(render_proposal_report(report), end="")
            return 0
        if args.proposal_type == "review":
            with connect(campaign) as conn:
                record = review_proposal(
                    conn,
                    args.proposal_id,
                    approve=bool(args.approve),
                    reviewed_by=args.reviewed_by,
                    reason=args.reason,
                )
                conn.commit()
            if args.format == "json":
                print_json(record.to_dict())
            else:
                print(f"{record.id}: {record.status}")
            return 0
        if args.proposal_type == "batch-review":
            with connect(campaign) as conn:
                records = batch_review_proposals(
                    conn,
                    proposal_ids=args.proposal_ids,
                    status_filter=args.status,
                    kind=args.kind,
                    risk_level=args.risk_level,
                    approve=bool(args.approve),
                    reviewed_by=args.reviewed_by,
                    reason=args.reason,
                    limit=args.limit,
                )
                conn.commit()
            if args.format == "json":
                print_json({"reviewed": [record.to_dict() for record in records], "count": len(records)})
            else:
                print(f"reviewed: {len(records)}")
                for record in records:
                    print(f"- {record.id}: {record.status}")
            return 0
        if args.proposal_type == "apply":
            with connect(campaign) as conn:
                record = get_proposal(conn, args.proposal_id)
                if record.status != "approved":
                    print("FAILED")
                    print(f"- proposal status must be approved, got {record.status}")
                    return 1
                if record.kind != "content_delta":
                    print("FAILED")
                    print(f"- proposal apply currently supports content_delta, got {record.kind}")
                    return 1
            backup = create_backup(campaign, reason="pre_proposal_apply")
            with connect(campaign) as conn:
                counts = apply_content_delta(campaign, conn, record.payload)
                turn_row = conn.execute("select value from meta where key='current_turn_id'").fetchone()
                applied_turn_id = turn_row["value"] if turn_row else None
                rollback_hint = dict(record.rollback_hint)
                rollback_hint["backup_id"] = backup.id
                applied = mark_proposal_applied(
                    conn,
                    record.id,
                    applied_turn_id=applied_turn_id,
                    rollback_hint=rollback_hint,
                )
                conn.commit()
                projection_report = refresh_cli_projections(
                    campaign,
                    conn,
                    ["snapshots", "cards", "reports"],
                    profile="proposal_apply:maintenance_projection",
                )
            path = projection_artifact(projection_report, "snapshots", 0)
            json_path = projection_artifact(projection_report, "snapshots", 1)
            audit_path = projection_artifact(projection_report, "reports", 0)
            cards_count = projection_count(projection_report, "cards")
            if args.format == "json":
                print_json(
                    {
                        "proposal": applied.to_dict(),
                        "backup": backup.id,
                        "counts": counts,
                        "snapshot_path": path,
                        "snapshot_json_path": json_path,
                        "cards_count": cards_count,
                        "audit_path": audit_path,
                        "projection_report": projection_report.to_dict(),
                    }
                )
            else:
                print(f"applied: {applied.id}")
                print(f"backup: {backup.id}")
                print(f"entities: {counts['entities']}")
                print(path)
                print(json_path)
                print(f"cards: {cards_count}")
                print(audit_path)
            return 0 if projection_report.ok else 1
        if args.proposal_type == "rollback-plan":
            with connect(campaign) as conn:
                record = get_proposal(conn, args.proposal_id)
            if args.format == "json":
                print_json({"proposal": record.to_dict(), "rollback_hint": record.rollback_hint})
            else:
                print(render_rollback_plan(record), end="")
            return 0
        return 2

    if args.command == "delta":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            if args.delta_type == "draft":
                result = load_and_draft_delta(
                    conn,
                    user_text=resolve_user_text_arg(args),
                    response_file=args.response_file,
                    response_text=args.text,
                    intent=args.intent,
                )
                if args.output:
                    output_path = Path(args.output).expanduser()
                    if not output_path.is_absolute():
                        output_path = campaign.root / output_path
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(
                        json.dumps(result.delta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    print(output_path)
                print(result.render(), end="")
                return 0 if not result.errors else 1
            if args.delta_type == "diff":
                delta = load_delta(args.delta_json)
                print(render_delta_diff(conn, delta), end="")
                return 0
            if args.delta_type == "check-response":
                delta = load_delta(args.delta_json)
                text = load_response_text(args.response_file, args.text)
                warnings = check_delta_response_consistency(delta, text)
                print(render_consistency_report(warnings), end="")
                return 1 if warnings else 0
        return 2

    if args.command == "turn":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            if args.turn_type == "assistant":
                print(
                    run_turn_assistant(
                        campaign,
                        conn,
                        TurnAssistantOptions(
                            user_text=resolve_user_text_arg(args),
                            budget=args.budget,
                            mode=args.mode,
                            submode=args.submode,
                            target=args.target,
                            project=args.project,
                            output=args.output,
                            weapon=args.weapon,
                            ammo=args.ammo,
                            distance=args.distance,
                            ready_state=args.ready_state,
                            destination=args.destination,
                            pace=args.pace,
                            location=args.location,
                            materials=args.materials,
                            time_cost=args.time_cost,
                            npc=args.npc,
                            topic=args.topic,
                            approach=args.approach,
                            until=args.until,
                            response_file=args.response_file,
                            response_text=args.response_text,
                            proposal_json=args.proposal_json,
                            delta_json=args.delta_json,
                            save=args.save,
                            rebuild_memory=args.rebuild_memory,
                            audit_context=args.audit_context,
                            context_run_id=args.context_run_id,
                        ),
                    ),
                    end="",
                )
            elif args.turn_type == "accept-response":
                response_text = load_response_text(args.response_file, args.response_text)
                result = accept_response(
                    campaign,
                    conn,
                    user_text=resolve_user_text_arg(args),
                    response_text=response_text,
                    mode=args.mode,
                    submode=args.submode,
                    intent=args.intent,
                    save_if_safe=args.save_if_safe,
                    confirm_save=args.confirm_save,
                    rebuild_memory=args.rebuild_memory,
                )
                if args.output_delta:
                    output_path = Path(args.output_delta).expanduser()
                    if not output_path.is_absolute():
                        output_path = campaign.root / output_path
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(
                        json.dumps(result.delta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    print(output_path)
                print(result.render(), end="")
                if result.hard_blocked:
                    return 1
                if (args.save_if_safe or args.confirm_save) and not result.saved_turn_id:
                    return 1
        return 0

    if args.command == "reflection":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            draft = draft_reflection(
                campaign,
                conn,
                subject_id=args.subject,
                ai=args.ai,
                model=args.model,
                provider=args.provider,
                timeout=args.timeout,
            )
        output = draft.render()
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            print(args.output)
        else:
            print(output, end="")
        return 0 if not draft.errors else 1

    if args.command == "ops":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            path = write_ops_report(campaign, conn, args.report, run_speed=args.speed)
        print(path)
        return 0

    if args.command == "backup":
        campaign = load_campaign(args.campaign_dir)
        if args.backup_type == "create":
            backup = create_backup(campaign, reason=args.reason)
            print(backup.id)
            print(backup.path)
            return 0
        if args.backup_type == "list":
            print(render_backup_list(list_backups(campaign)), end="")
            return 0
        if args.backup_type == "restore":
            if not args.yes:
                print("FAILED\n- backup restore requires --yes")
                return 2
            pre_restore = restore_backup(
                campaign,
                args.backup_id,
                create_pre_restore_backup=not args.no_pre_restore_backup,
            )
            print("OK")
            print(f"restored: {args.backup_id}")
            if pre_restore:
                print(f"pre_restore_backup: {pre_restore.id}")
            return 0
        return 2

    if args.command == "migrate":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            if args.migrate_type == "status":
                print(render_migration_status(migration_status(conn)), end="")
                return 0
            if args.migrate_type == "apply":
                records = migration_status(conn)
                mismatched = [record for record in records if record.applied and record.checksum_ok is False]
                if mismatched:
                    print("FAILED")
                    for record in mismatched:
                        print(f"- applied migration checksum mismatch: {record.id}")
                    return 1
                pending = [record for record in records if not record.applied]
                backup = create_backup(campaign, reason="pre_migration") if pending else None
                applied = apply_pending_migrations(conn)
                conn.execute(
                    "insert into meta(key, value) values('engine_version', ?) on conflict(key) do update set value=excluded.value",
                    (campaign.engine_version,),
                )
                conn.execute(
                    "insert into meta(key, value) values('player_entity_id', ?) on conflict(key) do update set value=excluded.value",
                    (campaign.player_entity_id,),
                )
                conn.execute(
                    "insert into meta(key, value) values('package_version', ?) on conflict(key) do update set value=excluded.value",
                    (campaign.package_version,),
                )
                conn.execute(
                    "insert into meta(key, value) values('content_schema_version', ?) on conflict(key) do update set value=excluded.value",
                    (campaign.content_schema_version,),
                )
                for key in ("primary_energy_label", "primary_energy_detail_key", "primary_energy_full_value"):
                    if key not in campaign.defaults:
                        continue
                    conn.execute(
                        "insert into meta(key, value) values(?, ?) on conflict(key) do update set value=excluded.value",
                        (key, str(campaign.defaults[key])),
                    )
                conn.commit()
                if backup:
                    print(f"backup: {backup.id}")
                if applied:
                    print("applied:")
                    for record in applied:
                        print(f"- {record.id}")
                else:
                    print("no pending migrations")
                errors = run_checks(conn)
                if errors:
                    print("check: FAILED")
                    for error in errors:
                        print(f"- {error}")
                    return 1
                print("check: OK")
                return 0
        return 2

    if args.command == "projection":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            if args.projection_type == "status":
                print(render_projection_status(conn), end="")
                return 0
            if args.projection_type == "repair":
                result = ProjectionService(campaign, conn).refresh(
                    names=args.name,
                    dirty_only=not args.all,
                    profile="projection_repair:maintenance_projection",
                    commit_policy="caller_committed_required",
                )
                print("OK" if result.ok else "FAILED")
                print(f"profile: {result.profile}")
                print(f"status: {result.status}")
                print(f"global_status: {result.global_status}")
                print(f"requested: {', '.join(result.requested) if result.requested else '-'}")
                print(f"skipped: {', '.join(result.skipped) if result.skipped else '-'}")
                print(f"requested_dirty: {', '.join(result.requested_dirty) if result.requested_dirty else '-'}")
                print(f"requested_failed: {', '.join(result.requested_failed) if result.requested_failed else '-'}")
                print(f"requested_stale: {', '.join(result.requested_stale) if result.requested_stale else '-'}")
                print(f"global_dirty: {', '.join(result.global_dirty) if result.global_dirty else '-'}")
                print(f"global_failed: {', '.join(result.global_failed) if result.global_failed else '-'}")
                print(f"global_stale: {', '.join(result.global_stale) if result.global_stale else '-'}")
                print(f"outbox_status: {result.outbox_status}")
                if result.outbox_counts:
                    for status, count in result.outbox_counts.items():
                        print(f"outbox_count: {status}={count}")
                else:
                    print("outbox_count: empty=0")
                print(f"started_at: {result.started_at or '-'}")
                print(f"finished_at: {result.finished_at or '-'}")
                print(f"duration_ms: {result.duration_ms:.3f}" if result.duration_ms is not None else "duration_ms: -")
                for name in result.refreshed:
                    print(f"refreshed: {name}")
                for name in result.requested_failed:
                    print(f"failed: {name}")
                for row in result.outbox_non_done:
                    print(_format_outbox_report_row(row))
                for artifact in result.artifacts:
                    print(f"artifact: {artifact}")
                for error in result.errors:
                    print(f"error: {error}")
                return 0 if result.ok else 1
        return 2

    if args.command == "package":
        if args.package_type == "build":
            try:
                source = load_package_source(args.package_dir)
                result = build_package_archive(source, output_path=args.output)
            except Exception as exc:
                print("FAILED")
                print(f"- error: {exc}")
                return 1
            print(render_package_build(result), end="")
            return 0
        if args.package_type == "test":
            try:
                source = load_package_source(args.package_dir)
                if args.campaign_dir:
                    campaign = load_campaign(args.campaign_dir)
                    with connect(campaign) as conn:
                        result = test_package_source(source, campaign=campaign, conn=conn)
                else:
                    result = test_package_source(source)
            except Exception as exc:
                print("FAILED")
                print(f"- error: {exc}")
                return 1
            print(render_package_test(result), end="")
            return 0 if result.ok else 1
        if args.package_type == "validate":
            try:
                source = load_package_source(args.package_dir)
                result = validate_package_source(source)
            except Exception as exc:
                print("FAILED")
                print(f"- error: {exc}")
                return 1
            print(render_package_validation(result), end="")
            return 0 if result.ok else 1
        if args.package_type == "install":
            try:
                source = load_package_source(args.package_dir)
                if args.adopt_existing:
                    campaign = load_campaign(args.campaign_dir)
                    with connect(campaign) as conn:
                        result = adopt_existing_package_lock(campaign, conn, source, force=args.force)
                    print(render_package_adoption(result), end="")
                else:
                    result = install_package_to_new_campaign(source, args.campaign_dir, force=args.force)
                    print(render_package_install(result), end="")
            except Exception as exc:
                print("FAILED")
                print(f"- error: {exc}")
                return 1
            return 0
        if args.package_type == "reconcile":
            try:
                source = load_package_source(args.package_dir)
                campaign = load_campaign(args.campaign_dir)
                with connect(campaign) as conn:
                    result = reconcile_package_adoption(campaign, conn, source)
            except Exception as exc:
                print("FAILED")
                print(f"- error: {exc}")
                return 1
            print(render_package_adoption(result), end="")
            return 0 if result.ok else 1
        if args.package_type in {"diff", "upgrade"}:
            try:
                source = load_package_source(args.package_dir)
            except Exception as exc:
                print("FAILED")
                print(f"- error: {exc}")
                return 1
            campaign = load_campaign(args.campaign_dir)
            with connect(campaign) as conn:
                result = diff_package_against_campaign(
                    conn,
                    source,
                    target_name=campaign.name,
                    campaign=campaign,
                    require_lock=args.package_type == "upgrade" and not args.dry_run,
                )
                if args.package_type == "upgrade" and not args.dry_run:
                    if not result.ok:
                        print(render_package_diff(result), end="")
                        return 1
                    backup = create_backup(campaign, reason="pre_package_upgrade")
                    try:
                        apply_result = apply_package_upgrade(campaign, conn, source)
                    except Exception as exc:
                        print("FAILED")
                        print(f"- error: {exc}")
                        print(f"- backup: {backup.id}")
                        return 1
                    print(render_package_apply(apply_result, backup_id=backup.id), end="")
                    return 0
            print(render_package_diff(result), end="")
            return 0 if result.ok else 1
        return 2

    if args.command == "simulate":
        if args.simulate_type == "longrun":
            campaign = load_campaign(args.campaign_dir)
            output_path = None
            if args.report:
                output_path = Path(args.report).expanduser()
                if not output_path.is_absolute():
                    output_path = campaign.root / output_path
            path = write_simulation_report(campaign.root, output_path, turns=args.turns, budget=args.budget)
            print(path)
            return 0
        return 2

    if args.command == "content":
        if args.content_type == "list-types":
            print(render_content_type_list(), end="")
            return 0
        if args.content_type == "inspect-type":
            text, ok = render_content_type_detail(args.name)
            print(text, end="")
            return 0 if ok else 1
        campaign = load_campaign(args.campaign_dir)
        if args.content_type == "sync":
            try:
                specs = sync_specs_for_names(args.sync_types, allow_unsafe=args.allow_unsafe)
            except (KeyError, ValueError) as exc:
                print("FAILED")
                print(f"- {exc}")
                return 1
            with connect(campaign) as conn:
                validation = validate_content_sources(campaign, conn, specs)
            if not validation.ok:
                print(validation.render(), end="")
                return 1
            backup = create_backup(campaign, reason="pre_content_sync")
            with connect(campaign) as conn:
                counts = sync_campaign_content(
                    campaign,
                    conn,
                    type_names=args.sync_types,
                    allow_unsafe=args.allow_unsafe,
                    expected_turn_id=args.expected_turn_id,
                    command_id=args.command_id,
                )
                projection_report = refresh_cli_projections(
                    campaign,
                    conn,
                    ["snapshots", "cards", "reports"],
                    profile="content_sync:maintenance_projection",
                )
            path = projection_artifact(projection_report, "snapshots", 0)
            json_path = projection_artifact(projection_report, "snapshots", 1)
            audit_path = projection_artifact(projection_report, "reports", 0)
            cards_count = projection_count(projection_report, "cards")
            print(f"backup: {backup.id}")
            for key in sorted(counts):
                print(f"{key}: {counts[key]}")
            print(path)
            print(json_path)
            print(f"cards: {cards_count}")
            print(audit_path)
            return 0 if projection_report.ok else 1
        if args.content_type == "new":
            delta = make_content_delta(
                kind=args.kind,
                entity_id=args.id,
                name=args.name,
                summary=args.summary,
                location_id=args.location,
                rarity=args.rarity,
                uses=split_csv(args.uses),
                risks=split_csv(args.risks),
                aliases=split_csv(args.aliases) or None,
            )
            output = args.output
            if output:
                output_path = Path(output).expanduser()
                if not output_path.is_absolute():
                    output_path = campaign.root / output_path
                print(write_content_delta(delta, output_path))
            else:
                print(write_content_delta(delta, None))
            return 0
        if args.content_type == "from-palette":
            with connect(campaign) as conn:
                delta = make_content_delta_from_palette(
                    campaign,
                    conn,
                    palette_id=args.palette_id,
                    visibility=args.visibility,
                    location_id=args.location,
                )
            output = args.output
            if output:
                output_path = Path(output).expanduser()
                if not output_path.is_absolute():
                    output_path = campaign.root / output_path
                print(write_content_delta(delta, output_path))
            else:
                print(write_content_delta(delta, None))
            return 0
        if args.content_type == "audit":
            with connect(campaign) as conn:
                findings = audit_content_quality(conn)
            report = render_content_quality(findings)
            if args.report:
                report_path = Path(args.report).expanduser()
                if not report_path.is_absolute():
                    report_path = campaign.root / report_path
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(report, encoding="utf-8")
                print(report_path)
            else:
                print(report, end="")
            return 0
        if args.content_type == "validate-delta":
            delta = load_content_delta(args.delta_json)
            with connect(campaign) as conn:
                result = validate_content_delta(delta, conn)
            print(result.render(), end="")
            return 0 if result.ok else 1
        return 2

    if args.command == "render-current":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            projection_report = refresh_cli_projections(
                campaign,
                conn,
                ["snapshots"],
                profile="render_current:legacy_projection",
            )
        path = projection_artifact(projection_report, "snapshots", 0)
        json_path = projection_artifact(projection_report, "snapshots", 1)
        print(path)
        print(json_path)
        return 0 if projection_report.ok else 1

    if args.command == "action":
        if args.action_type == "list":
            print(render_action_resolver_list(), end="")
            return 0
        if args.action_type == "inspect":
            text, ok = render_action_resolver_detail(args.name)
            print(text, end="")
            return 0 if ok else 1
        return 2

    if args.command == "plugin":
        campaign = load_campaign(args.campaign_dir)
        manifests = discover_plugin_manifests(campaign)
        if args.plugin_type == "list":
            print(render_plugin_list(manifests), end="")
            return 0
        if args.plugin_type == "validate":
            print(render_plugin_validation(manifests), end="")
            return 0 if all(manifest.ok for manifest in manifests) else 1
        return 2

    if args.command == "render-cards":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            projection_report = refresh_cli_projections(
                campaign,
                conn,
                ["cards"],
                profile="render_cards:legacy_projection",
                options={"cards": {"clean": not args.no_clean, "index_view": args.index_view}},
            )
        print(f"wrote {projection_count(projection_report, 'cards')} card files")
        print(campaign.cards_path / "INDEX.md")
        return 0 if projection_report.ok else 1

    if args.command == "save-turn":
        campaign = load_campaign(args.campaign_dir)
        delta = load_delta(args.delta_json)
        with connect(campaign) as conn:
            validation = run_validation_pipeline(
                campaign,
                conn,
                profile="admin_or_legacy_save_turn",
                delta=delta,
                state_audit=True,
            )
            if not validation.ok:
                audit_stage = validation.stage("state_audit")
                if audit_stage and audit_stage.status == "blocked":
                    raise ValueError(
                        "State audit blocked turn delta:\n"
                        + "\n".join(f"- {message}" for message in audit_stage.issues)
                    )
                raise ValueError("Invalid turn delta:\n" + "\n".join(f"- {error}" for error in validation.errors))
            result = commit_turn_delta(
                campaign,
                conn,
                delta=delta,
                validation=validation,
                backup=True,
                backup_reason="pre_save_turn",
                run_post_check=True,
            )
        print(f"backup: {result.backup_id}")
        print(result.turn_id)
        print(result.snapshot_path)
        print(result.snapshot_json_path)
        print(f"cards: {result.cards_count}")
        print(f"profile: {result.profile}")
        print(f"write_status: {result.write_status}")
        print(f"projection_status: {result.projection_status}")
        if result.projection_report:
            if result.projection_report.requested_failed:
                print(f"projection_failed: {', '.join(result.projection_report.requested_failed)}")
            if result.projection_report.requested_dirty:
                print(f"projection_dirty: {', '.join(result.projection_report.requested_dirty)}")
            if result.projection_report.global_failed:
                print(f"projection_global_failed: {', '.join(result.projection_report.global_failed)}")
        if result.check_errors:
            print("check errors:")
            for error in result.check_errors:
                print(f"- {error}")
            return 1
        return 0 if result.ok else 1

    if args.command == "apply-content-delta":
        campaign = load_campaign(args.campaign_dir)
        delta = load_content_delta(args.delta_json)
        with connect(campaign) as conn:
            validation = validate_content_delta(delta, conn)
        if not validation.ok:
            print(validation.render(), end="")
            return 1
        if validation.warnings:
            print(validation.render(), end="")
        review_blockers = strict_review_blockers(delta, validation.warnings)
        if args.strict_review and review_blockers:
            with connect(campaign) as conn:
                record = create_proposal(
                    conn,
                    kind="content_delta",
                    payload=delta,
                    validation={"ok": validation.ok, "errors": validation.errors, "warnings": validation.warnings},
                    status="needs_review",
                    risk_level="high",
                )
                conn.commit()
            print("FAILED")
            for item in review_blockers:
                print(f"- review_required: {item}")
            print(f"- queued: {record.id}")
            return 1
        queued_record = None
        if review_blockers:
            with connect(campaign) as conn:
                queued_record = create_proposal(
                    conn,
                    kind="content_delta",
                    payload=delta,
                    validation={"ok": validation.ok, "errors": validation.errors, "warnings": validation.warnings},
                    status="needs_review",
                    risk_level="high",
                )
                conn.commit()
        backup = create_backup(campaign, reason="pre_apply_content_delta")
        with connect(campaign) as conn:
            counts = apply_content_delta(campaign, conn, delta)
            projection_report = refresh_cli_projections(
                campaign,
                conn,
                ["snapshots", "cards", "reports"],
                profile="content_delta:maintenance_projection",
            )
        path = projection_artifact(projection_report, "snapshots", 0)
        json_path = projection_artifact(projection_report, "snapshots", 1)
        audit_path = projection_artifact(projection_report, "reports", 0)
        cards_count = projection_count(projection_report, "cards")
        print(f"backup: {backup.id}")
        print(f"entities: {counts['entities']}")
        print(f"routes: {counts['routes']}")
        print(f"rules: {counts.get('rules', 0)}")
        for key in sorted(set(counts) - {"entities", "routes", "rules"}):
            if counts[key]:
                print(f"{key}: {counts[key]}")
        print(path)
        print(json_path)
        print(f"cards: {cards_count}")
        print(audit_path)
        if queued_record:
            print(f"proposal_queued: {queued_record.id}")
        return 0 if projection_report.ok else 1

    if args.command == "check":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            errors = run_checks(conn)
        if errors:
            print("FAILED")
            for error in errors:
                print(f"- {error}")
            return 1
        print("OK")
        return 0

    if args.command == "audit":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            findings = run_audit(conn)
            projection_report = refresh_cli_projections(
                campaign,
                conn,
                ["reports"],
                profile="audit:maintenance_projection",
                options={"reports": {"report_path": args.report}},
            )
            path = projection_artifact(projection_report, "reports", 0)
        print(f"findings: {len(findings)}")
        print(path)
        return 0 if projection_report.ok else 1

    if args.command == "preview":
        runtime = GMRuntime.from_path(args.campaign_dir)
        result = runtime.preview_action(args.preview_type, action_options_from_args(args))
        if result.markdown:
            print(result.markdown, end="" if result.markdown.endswith("\n") else "\n")
        else:
            print("OK" if result.ok else "FAILED")
            for item in result.missing_required:
                print(f"- missing: {item}")
            for item in result.errors:
                print(f"- error: {item}")
            for item in result.warnings:
                print(f"- warning: {item}")
        return 0 if result.ok else 1

    if args.command == "palette":
        campaign = load_campaign(args.campaign_dir)
        with connect(campaign) as conn:
            if args.palette_type == "suggest":
                print(
                    render_palette_suggestions(
                        campaign,
                        conn,
                        kind=args.kind,
                        location_query=args.location,
                        intent=args.intent,
                        include_locked=args.include_locked,
                        limit=args.limit,
                    )
                )
        return 0

    if args.command == "importer":
        if args.importer_type == "list":
            print(render_importer_list(), end="")
            return 0
        if args.importer_type == "inspect":
            text, ok = render_importer_detail(args.name)
            print(text, end="")
            return 0 if ok else 1
        if args.importer_type == "run":
            campaign = load_campaign(args.campaign_dir)
            try:
                report = run_importer(
                    campaign,
                    args.name,
                    source=args.source,
                    apply=args.apply,
                    registry=get_default_importer_registry(),
                )
            except Exception as exc:
                print("FAILED")
                print(f"- error: {exc}")
                return 1
            if args.apply:
                with connect(campaign) as conn:
                    projection_report = refresh_cli_projections(
                        campaign,
                        conn,
                        ["snapshots", "cards"],
                        profile="importer_run:import_projection",
                    )
                if not projection_report.ok:
                    print(projection_report.render(), end="")
                    return 1
            markdown = report.to_markdown()
            if args.report:
                report_path = Path(args.report).expanduser()
                if not report_path.is_absolute():
                    report_path = campaign.root / report_path
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(markdown + "\n", encoding="utf-8")
                print(report_path)
            else:
                print(markdown)
            return 0
        return 2

    if args.command == "import-v1":
        campaign = load_campaign(args.campaign_dir)
        report = run_importer(campaign, "isekai_farm_v1", source=args.source, apply=args.apply)
        if args.apply:
            with connect(campaign) as conn:
                projection_report = refresh_cli_projections(
                    campaign,
                    conn,
                    ["snapshots", "cards"],
                    profile="import_v1:import_projection",
                )
            if not projection_report.ok:
                print(projection_report.render(), end="")
                return 1
        markdown = report.to_markdown()
        if args.report:
            report_path = Path(args.report).expanduser()
            if not report_path.is_absolute():
                report_path = campaign.root / report_path
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(markdown + "\n", encoding="utf-8")
            print(report_path)
        else:
            print(markdown)
        return 0

    return 2
