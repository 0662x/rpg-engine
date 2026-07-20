from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .actions import get_default_action_registry
from .authoring.doctor import render_doctor_result, run_campaign_doctor
from .authoring.explain import explain_author_topic, render_explanation
from .authoring.outline import build_campaign_outline, render_campaign_outline
from .authoring.split import build_split_plan, render_split_plan
from .authoring.templates import create_campaign_from_template, render_template_result
from .ai.defaults import (
    DEFAULT_AI_MODEL,
    DEFAULT_AI_PROVIDER,
    DEFAULT_ARCHIVIST_TIMEOUT_SECONDS,
    DEFAULT_INTENT_TIMEOUT_SECONDS,
    DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS,
)
from .ai.config import AI_HELPER_BACKENDS, AI_HELPER_FALLBACK_BACKENDS, AI_PROFILES
from .ai_intent import ExternalIntentContractError
from .ai_intent.safety_contract import external_intent_contract_error_dict
from .campaign import load_campaign
from .campaign_validation import render_campaign_test, render_campaign_validation, run_campaign_smoke_tests, validate_campaign_package
from .cli_text import add_user_text_external_source_args, add_user_text_source_args, resolve_user_text_arg
from .eval_suite import render_eval_report, run_eval_suite
from .resource_paths import copy_packaged_example
from .runtime import GMRuntime
from .save import load_delta
from .proposal import load_turn_proposal
from .save_archive import export_save, import_save_archive
from .save_patch import apply_save_patch, load_patch_file
from .save_service import init_v1_save, inspect_v1_save
from .save_manager import SaveManager
from .mcp_adapter import MCP_PROFILES, PLAYER_PROFILE


V1_COMMANDS = {"campaign", "save", "play", "mcp", "player", "platform", "eval"}


def add_format_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        default="markdown",
        choices=["markdown", "json"],
        help="output format for the V1 command",
    )


def add_play_preview_options(parser: argparse.ArgumentParser) -> None:
    seen: set[str] = set()
    for spec in get_default_action_registry().all():
        for option in spec.option_specs:
            if option.name in seen:
                continue
            seen.add(option.name)
            if option.name == "user_text":
                add_user_text_source_args(parser, required=False, help_text=option.help)
                continue
            flag = "--" + (option.dest or option.name).replace("_", "-")
            kwargs: dict[str, object] = {
                "dest": option.name,
                "help": option.help,
                "required": False,
            }
            if option.default is not None:
                kwargs["default"] = option.default
            parser.add_argument(flag, **kwargs)


def action_options_from_args(args: argparse.Namespace) -> dict[str, Any]:
    option_names = {
        option.name
        for spec in get_default_action_registry().all()
        for option in spec.option_specs
    }
    values = vars(args)
    options = {name: values[name] for name in sorted(option_names) if values.get(name) is not None}
    if "user_text" in option_names:
        user_text = resolve_user_text_arg(args, required=False)
        if user_text is not None:
            options["user_text"] = user_text
    return options


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


def intent_option_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "intent_ai": args.intent_ai,
        "intent_backend": args.intent_backend,
        "intent_provider": args.intent_provider,
        "intent_model": args.intent_model,
        "intent_timeout": args.intent_timeout,
        "intent_base_url": args.intent_base_url,
        "intent_api_key_env": args.intent_api_key_env,
        "intent_fallback_backend": args.intent_fallback_backend,
    }


def preflight_consume_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "preflight_id": args.preflight_id,
        "message_id": args.message_id,
        "platform": args.platform,
        "session_key": args.session_key,
        "source_user_text_hash": args.source_user_text_hash,
        "preflight_pending_wait_ms": args.preflight_pending_wait_ms,
    }


def intent_review_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "intent_backend": args.intent_backend,
        "intent_provider": args.intent_provider,
        "intent_model": args.intent_model,
        "intent_timeout": args.intent_timeout,
        "intent_base_url": args.intent_base_url,
        "intent_api_key_env": args.intent_api_key_env,
        "intent_fallback_backend": args.intent_fallback_backend,
    }


def preflight_identity_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "message_id": args.message_id,
        "platform": args.platform,
        "session_key": args.session_key,
        "source_user_text_hash": args.source_user_text_hash,
    }


def external_intent_candidate_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    return load_json_object_arg(
        args.external_intent_candidate,
        label="--external-intent-candidate",
    )


def intent_preview_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        **intent_option_kwargs_from_args(args),
        "external_intent_candidate": external_intent_candidate_from_args(args),
        **preflight_consume_kwargs_from_args(args),
    }


def intent_preflight_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        **intent_review_kwargs_from_args(args),
        "external_intent_candidate": external_intent_candidate_from_args(args),
        **preflight_identity_kwargs_from_args(args),
        "preflight_identity_profile": args.preflight_identity_profile,
        "ttl_seconds": args.ttl_seconds,
    }


def add_play_delta_validation_options(parser: argparse.ArgumentParser, registered_actions: list[str]) -> None:
    parser.add_argument("--action", choices=registered_actions, help="action resolver used for runtime delta validation")
    parser.add_argument("--options-json", help="JSON object or file path for action options")
    parser.add_argument("--context-json", help="JSON object or file path for runtime context")


def add_play_intent_options(parser: argparse.ArgumentParser) -> None:
    helper_backend_choices = [*AI_HELPER_BACKENDS, "hermes"]
    fallback_backend_choices = [*AI_HELPER_FALLBACK_BACKENDS, "hermes"]
    parser.add_argument("--intent-ai", default="off", choices=["off", "consensus"])
    parser.add_argument("--intent-backend", default="direct", choices=helper_backend_choices)
    parser.add_argument("--intent-provider", default=DEFAULT_AI_PROVIDER)
    parser.add_argument("--intent-model", default=DEFAULT_AI_MODEL)
    parser.add_argument("--intent-timeout", type=int, default=DEFAULT_INTENT_TIMEOUT_SECONDS)
    parser.add_argument("--intent-base-url", default="")
    parser.add_argument("--intent-api-key-env", default="")
    parser.add_argument("--intent-fallback-backend", default="off", choices=fallback_backend_choices)
    parser.add_argument("--external-intent-candidate", help="JSON object or file path for the external AI intent candidate")


def add_preflight_consume_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preflight-id", default="")
    parser.add_argument("--message-id", default="")
    parser.add_argument("--platform", default="")
    parser.add_argument("--session-key", default="")
    parser.add_argument("--source-user-text-hash", default="")
    parser.add_argument("--preflight-pending-wait-ms", type=int, default=0)


def add_player_internal_intent_options(parser: argparse.ArgumentParser) -> None:
    helper_backend_choices = [*AI_HELPER_BACKENDS, "hermes"]
    fallback_backend_choices = [*AI_HELPER_FALLBACK_BACKENDS, "hermes"]
    parser.add_argument("--intent-ai", default="off", choices=["off", "consensus"])
    parser.add_argument("--intent-backend", default="direct", choices=helper_backend_choices)
    parser.add_argument("--intent-provider", default=DEFAULT_AI_PROVIDER)
    parser.add_argument("--intent-model", default=DEFAULT_AI_MODEL)
    parser.add_argument("--intent-timeout", type=int, default=DEFAULT_INTENT_TIMEOUT_SECONDS)
    parser.add_argument("--intent-base-url", default="")
    parser.add_argument("--intent-api-key-env", default="")
    parser.add_argument("--intent-fallback-backend", default="off", choices=fallback_backend_choices)


def add_platform_message_options(parser: argparse.ArgumentParser, *, required_text: bool = True) -> None:
    parser.add_argument("--event-json", help="raw platform MessageEvent JSON object or file path")
    parser.add_argument("--platform")
    parser.add_argument("--session-key", default="")
    parser.add_argument("--message-id", default="")
    parser.add_argument("--actor-id", default="")
    parser.add_argument("--chat-type")
    parser.add_argument("--message-type")
    parser.add_argument("--actor-is-bot", action="store_true")
    parser.add_argument("--actor-is-self", action="store_true")
    parser.add_argument("--is-approval", action="store_true")
    add_user_text_source_args(parser, required=required_text)


def add_platform_sidecar_options(parser: argparse.ArgumentParser) -> None:
    helper_backend_choices = [*AI_HELPER_BACKENDS, "hermes"]
    fallback_backend_choices = [*AI_HELPER_FALLBACK_BACKENDS, "hermes"]
    parser.add_argument("--enable-prewarm", action="store_true", help="enable platform prewarm for this sidecar process")
    parser.add_argument("--prewarm-queue-size", type=int)
    parser.add_argument("--prewarm-workers", type=int)
    parser.add_argument("--active-ttl-seconds", type=int, default=1800)
    parser.add_argument("--preflight-pending-wait-ms", type=int, default=200)
    parser.add_argument("--intent-ai", default="consensus", choices=["off", "consensus"])
    parser.add_argument("--intent-backend", choices=helper_backend_choices)
    parser.add_argument("--intent-provider")
    parser.add_argument("--intent-model")
    parser.add_argument("--intent-timeout", type=int)
    parser.add_argument("--intent-base-url")
    parser.add_argument("--intent-api-key-env")
    parser.add_argument("--intent-fallback-backend", choices=fallback_backend_choices)


def add_v1_parsers(subparsers: argparse._SubParsersAction, registered_actions: list[str]) -> None:
    campaign_parser = subparsers.add_parser("campaign", help="V1 campaign package commands")
    campaign_sub = campaign_parser.add_subparsers(dest="campaign_type", required=True)
    campaign_validate_parser = campaign_sub.add_parser("validate", help="validate a V1 campaign package")
    campaign_validate_parser.add_argument("campaign_dir")
    add_format_option(campaign_validate_parser)
    campaign_test_parser = campaign_sub.add_parser("test", help="initialize a temp save and run V1 smoke checks")
    campaign_test_parser.add_argument("campaign_dir")
    add_format_option(campaign_test_parser)
    campaign_copy_parser = campaign_sub.add_parser("copy-example", help="copy a packaged example campaign")
    campaign_copy_parser.add_argument("target_dir")
    campaign_copy_parser.add_argument("--name", default="v1_minimal_adventure", help="packaged example name")
    campaign_copy_parser.add_argument("--force", action="store_true", help="overwrite a non-empty target directory")
    add_format_option(campaign_copy_parser)
    campaign_new_parser = campaign_sub.add_parser("new", help="create a new author-friendly campaign from a template")
    campaign_new_parser.add_argument("target_dir")
    campaign_new_parser.add_argument("--template", default="small-cn", help="template name: blank or small-cn")
    campaign_new_parser.add_argument("--id", dest="campaign_id", help="campaign id to write into campaign.yaml")
    campaign_new_parser.add_argument("--name", help="campaign display name")
    campaign_new_parser.add_argument("--force", action="store_true", help="overwrite a non-empty target directory")
    add_format_option(campaign_new_parser)
    campaign_doctor_parser = campaign_sub.add_parser("doctor", help="run author-facing campaign diagnostics")
    campaign_doctor_parser.add_argument("campaign_dir")
    campaign_doctor_parser.add_argument("--strict", action="store_true", help="treat warnings as failing")
    add_format_option(campaign_doctor_parser)
    campaign_outline_parser = campaign_sub.add_parser("outline", help="render an author-facing campaign outline")
    campaign_outline_parser.add_argument("campaign_dir")
    campaign_outline_parser.add_argument("--view", default="author", choices=["author", "debug"])
    add_format_option(campaign_outline_parser)
    campaign_explain_parser = campaign_sub.add_parser("explain", help="explain an authoring field, capability, or error")
    campaign_explain_parser.add_argument("topic")
    add_format_option(campaign_explain_parser)
    campaign_check_ai_parser = campaign_sub.add_parser("check-ai", help="check common AI-assisted authoring issues")
    campaign_check_ai_parser.add_argument("campaign_dir")
    campaign_check_ai_parser.add_argument("--strict", action="store_true", help="treat warnings as failing")
    add_format_option(campaign_check_ai_parser)
    campaign_split_parser = campaign_sub.add_parser("split", help="suggest a campaign content split plan")
    campaign_split_parser.add_argument("campaign_dir")
    campaign_split_parser.add_argument("--by", default="type", choices=["type"])
    split_mode = campaign_split_parser.add_mutually_exclusive_group()
    split_mode.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    split_mode.add_argument("--apply", dest="dry_run", action="store_false")
    add_format_option(campaign_split_parser)

    save_parser = subparsers.add_parser("save", help="V1 save commands")
    save_sub = save_parser.add_subparsers(dest="save_type", required=True)
    save_init_parser = save_sub.add_parser("init", help="initialize a save directory from a campaign package")
    save_init_parser.add_argument("campaign_dir")
    save_init_parser.add_argument("save_dir")
    save_init_parser.add_argument("--force", action="store_true", help="replace an existing save directory")
    add_format_option(save_init_parser)
    save_inspect_parser = save_sub.add_parser("inspect", help="inspect a save directory")
    save_inspect_parser.add_argument("save_dir")
    add_format_option(save_inspect_parser)
    save_validate_parser = save_sub.add_parser("validate", help="validate a save directory")
    save_validate_parser.add_argument("save_dir")
    add_format_option(save_validate_parser)
    save_export_parser = save_sub.add_parser("export", help="export a campaign save archive")
    save_export_parser.add_argument("campaign_dir")
    save_export_parser.add_argument("--output")
    add_format_option(save_export_parser)
    save_import_parser = save_sub.add_parser("import", help="import a save archive into a target directory")
    save_import_parser.add_argument("archive")
    save_import_parser.add_argument("target_dir")
    save_import_parser.add_argument("--force", action="store_true", help="allow importing into a non-empty target")
    save_import_parser.add_argument("--yes", action="store_true", help="required confirmation for import")
    add_format_option(save_import_parser)
    save_patch_parser = save_sub.add_parser("patch", help="apply a safe maintenance patch to a save")
    save_patch_parser.add_argument("save_dir")
    save_patch_parser.add_argument("patch_file")
    save_patch_parser.add_argument("--no-backup", action="store_true", help="skip pre-patch backup")
    add_format_option(save_patch_parser)

    play_parser = subparsers.add_parser("play", help="developer/trusted low-level runtime commands")
    play_sub = play_parser.add_subparsers(dest="play_type", required=True)
    play_preflight_parser = play_sub.add_parser(
        "preflight",
        help="developer/trusted low-level advisory intent preflight",
    )
    play_preflight_parser.add_argument("campaign_dir")
    add_user_text_source_args(play_preflight_parser, required=True)
    add_play_intent_options(play_preflight_parser)
    play_preflight_parser.add_argument("--message-id", default="")
    play_preflight_parser.add_argument("--platform", default="")
    play_preflight_parser.add_argument("--session-key", default="")
    play_preflight_parser.add_argument("--source-user-text-hash", default="")
    play_preflight_parser.add_argument(
        "--preflight-identity-profile",
        default="candidate_bound",
        choices=["candidate_bound", "message_only"],
    )
    play_preflight_parser.add_argument("--ttl-seconds", type=int, default=300)
    add_format_option(play_preflight_parser)

    play_start_parser = play_sub.add_parser(
        "start-turn",
        help="developer/trusted low-level turn classification",
    )
    play_start_parser.add_argument("campaign_dir")
    add_user_text_source_args(play_start_parser, required=True)
    play_start_parser.add_argument("--mode", default="auto", choices=["auto", "query", "action", "maintenance"])
    play_start_parser.add_argument("--submode", choices=["entity", "scene", "context", *registered_actions, "maintenance"])
    play_start_parser.add_argument("--budget", type=int)
    play_start_parser.add_argument("--max-events", type=int, default=6)
    play_start_parser.add_argument("--max-depth", type=int, default=1)
    add_play_intent_options(play_start_parser)
    add_preflight_consume_options(play_start_parser)
    add_format_option(play_start_parser)

    play_query_parser = play_sub.add_parser(
        "query",
        help="developer/trusted low-level read-only runtime query",
    )
    play_query_parser.add_argument("campaign_dir")
    play_query_parser.add_argument("kind", choices=["scene", "entity", "context"])
    play_query_parser.add_argument("query_text", nargs="?")
    play_query_parser.add_argument("--view", default="player", choices=["player", "gm", "maintenance"])
    play_query_parser.add_argument("--budget", type=int)
    add_format_option(play_query_parser)

    play_act_parser = play_sub.add_parser(
        "act",
        help="developer/trusted low-level natural-language action preview",
    )
    play_act_parser.add_argument("campaign_dir")
    play_act_parser.add_argument("user_text", nargs="?")
    add_user_text_external_source_args(play_act_parser)
    play_act_parser.add_argument("--view", default="player", choices=["player", "gm", "debug"])
    play_act_parser.add_argument("--auto-confirm-low-risk", action="store_true")
    add_play_intent_options(play_act_parser)
    add_preflight_consume_options(play_act_parser)
    add_format_option(play_act_parser)

    play_preview_parser = play_sub.add_parser(
        "preview",
        help="developer/trusted low-level action preview without saving",
    )
    play_preview_parser.add_argument("campaign_dir")
    play_preview_parser.add_argument("action", choices=registered_actions)
    play_preview_parser.add_argument("--view", default="player", choices=["player", "gm", "debug"])
    play_preview_parser.add_argument("--source-user-text", help="original player text used to guard action/text mismatches")
    add_play_preview_options(play_preview_parser)
    add_format_option(play_preview_parser)

    play_validate_parser = play_sub.add_parser(
        "validate-delta",
        help="developer/trusted low-level delta validation through GMRuntime",
    )
    play_validate_parser.add_argument("campaign_dir")
    play_validate_parser.add_argument("delta_json")
    add_play_delta_validation_options(play_validate_parser, registered_actions)
    add_format_option(play_validate_parser)

    play_commit_parser = play_sub.add_parser(
        "commit",
        help="developer/trusted low-level commit of approved TurnProposal delta",
    )
    play_commit_parser.add_argument("campaign_dir")
    play_commit_parser.add_argument("delta_json")
    play_commit_parser.add_argument("--proposal-json", help="TurnProposal JSON produced by preview and approved for commit")
    add_play_delta_validation_options(play_commit_parser, registered_actions)
    play_commit_parser.add_argument("--no-backup", action="store_true", help="skip pre-commit backup")
    play_commit_parser.add_argument("--archivist-suggest", action="store_true", help="store advisory Archivist suggestions after commit")
    helper_backend_choices = [*AI_HELPER_BACKENDS, "hermes"]
    play_commit_parser.add_argument("--archivist-ai", default="off", choices=helper_backend_choices)
    play_commit_parser.add_argument("--archivist-provider", default=DEFAULT_AI_PROVIDER)
    play_commit_parser.add_argument("--archivist-model", default=DEFAULT_AI_MODEL)
    play_commit_parser.add_argument("--archivist-timeout", type=int, default=DEFAULT_ARCHIVIST_TIMEOUT_SECONDS)
    play_commit_parser.add_argument(
        "--no-archivist-enqueue",
        action="store_true",
        help="store Archivist suggestion without enqueuing memory/alias proposals",
    )
    play_commit_parser.add_argument(
        "--state-audit",
        action="store_true",
        help="run advisory State Auditor before writing; enabled by default for deterministic checks",
    )
    play_commit_parser.add_argument(
        "--no-state-audit",
        action="store_true",
        help="skip deterministic State Auditor checks before writing",
    )
    play_commit_parser.add_argument("--state-audit-ai", default="off", choices=helper_backend_choices)
    play_commit_parser.add_argument("--state-audit-provider", default=DEFAULT_AI_PROVIDER)
    play_commit_parser.add_argument("--state-audit-model", default=DEFAULT_AI_MODEL)
    play_commit_parser.add_argument("--state-audit-timeout", type=int, default=DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS)
    play_commit_parser.add_argument(
        "--no-state-audit-block",
        action="store_true",
        help="report State Auditor high-risk findings but do not block commit",
    )
    add_format_option(play_commit_parser)

    play_health_parser = play_sub.add_parser(
        "health",
        help="developer/trusted low-level read-only runtime health check",
    )
    play_health_parser.add_argument("campaign_dir")
    add_format_option(play_health_parser)
    play_ux_metrics_parser = play_sub.add_parser(
        "ux-metrics",
        help="developer/trusted low-level read-only runtime UX metrics",
    )
    play_ux_metrics_parser.add_argument("campaign_dir")
    add_format_option(play_ux_metrics_parser)

    mcp_parser = subparsers.add_parser("mcp", help="MCP adapter host/profile commands")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_type", required=True)
    mcp_serve_parser = mcp_sub.add_parser("serve", help="serve the V1 MCP adapter over stdio")
    mcp_serve_parser.add_argument("--root", required=True, help="root containing allowed campaign/save directories")
    mcp_serve_parser.add_argument("--default-campaign", help="default campaign path relative to --root")
    mcp_serve_parser.add_argument("--default-save", help="default save path relative to --root")
    mcp_serve_parser.add_argument("--default-starter-save", help="default starter save path relative to --root")
    mcp_serve_parser.add_argument("--registry-active", action="store_true", help="resolve omitted save from registry active save")
    mcp_serve_parser.add_argument("--mcp-profile", default=PLAYER_PROFILE, choices=sorted(MCP_PROFILES))
    mcp_serve_parser.add_argument("--ai-profile", default="off", choices=AI_PROFILES)
    mcp_serve_parser.add_argument("--ai-provider", help="default provider for all AI helpers")
    mcp_serve_parser.add_argument("--ai-model", help="default model for all AI helpers")
    mcp_serve_parser.add_argument("--ai-timeout", type=int, help="default timeout for all AI helpers")
    fallback_backend_choices = [*AI_HELPER_FALLBACK_BACKENDS, "hermes"]
    mcp_serve_parser.add_argument("--semantic-ai", choices=helper_backend_choices)
    mcp_serve_parser.add_argument("--semantic-provider")
    mcp_serve_parser.add_argument("--semantic-model")
    mcp_serve_parser.add_argument("--semantic-timeout", type=int)
    mcp_serve_parser.add_argument("--intent-ai", choices=["off", "consensus"])
    mcp_serve_parser.add_argument("--intent-backend", choices=helper_backend_choices)
    mcp_serve_parser.add_argument("--intent-provider")
    mcp_serve_parser.add_argument("--intent-model")
    mcp_serve_parser.add_argument("--intent-timeout", type=int)
    mcp_serve_parser.add_argument("--intent-base-url")
    mcp_serve_parser.add_argument("--intent-api-key-env")
    mcp_serve_parser.add_argument("--intent-fallback-backend", choices=fallback_backend_choices)
    mcp_serve_parser.add_argument("--state-audit-ai", choices=helper_backend_choices)
    mcp_serve_parser.add_argument("--state-audit-provider")
    mcp_serve_parser.add_argument("--state-audit-model")
    mcp_serve_parser.add_argument("--state-audit-timeout", type=int)
    mcp_serve_parser.add_argument("--archivist-suggest", action="store_true", default=None)
    mcp_serve_parser.add_argument("--archivist-ai", choices=helper_backend_choices)
    mcp_serve_parser.add_argument("--archivist-provider")
    mcp_serve_parser.add_argument("--archivist-model")
    mcp_serve_parser.add_argument("--archivist-timeout", type=int)
    mcp_serve_parser.add_argument("--no-archivist-enqueue", action="store_true")
    mcp_serve_parser.add_argument("--transport", default="stdio", choices=["stdio"])
    mcp_config_parser = mcp_sub.add_parser("print-config", help="print AI client MCP JSON config")
    mcp_config_parser.add_argument("root", help="root containing allowed campaign/save directories")
    mcp_config_parser.add_argument("--default-campaign", help="default campaign path relative to root")
    mcp_config_parser.add_argument("--default-save", help="default save path relative to root")
    mcp_config_parser.add_argument("--default-starter-save", help="default starter save path relative to root")
    mcp_config_parser.add_argument("--registry-active", action="store_true", help="use registry active save when save is omitted")
    mcp_config_parser.add_argument("--mcp-profile", default=PLAYER_PROFILE, choices=sorted(MCP_PROFILES))
    mcp_config_parser.add_argument("--command", dest="client_command", default="aigm", help="command used by the AI client")
    mcp_config_parser.add_argument("--server-name", default="aigm-kernel", help="MCP server name in client config")

    player_parser = subparsers.add_parser("player", help="player-safe save registry and turn commands")
    player_sub = player_parser.add_subparsers(dest="player_type", required=True)

    player_inspect_parser = player_sub.add_parser("inspect", help="inspect a player workspace registry")
    player_inspect_parser.add_argument("root")
    add_format_option(player_inspect_parser)

    player_campaigns_parser = player_sub.add_parser("campaigns", help="list registered campaigns")
    player_campaigns_parser.add_argument("root")
    player_campaigns_parser.add_argument("--refresh", action="store_true")
    add_format_option(player_campaigns_parser)

    player_saves_parser = player_sub.add_parser("saves", help="list registered saves")
    player_saves_parser.add_argument("root")
    player_saves_parser.add_argument("--campaign-id")
    player_saves_parser.add_argument("--include-archived", action="store_true")
    player_saves_parser.add_argument("--refresh", action="store_true")
    add_format_option(player_saves_parser)

    player_current_parser = player_sub.add_parser("current", help="show the active save")
    player_current_parser.add_argument("root")
    player_current_parser.add_argument("--refresh", action="store_true")
    add_format_option(player_current_parser)

    player_start_parser = player_sub.add_parser("start", help="continue active save or create one if missing")
    player_start_parser.add_argument("root")
    player_start_parser.add_argument("--campaign")
    player_start_parser.add_argument("--starter-save")
    player_start_parser.add_argument("--label")
    add_user_text_source_args(player_start_parser, required=False)
    player_start_parser.add_argument("--no-create", action="store_true")
    add_format_option(player_start_parser)

    player_query_parser = player_sub.add_parser("query", help="ask a player-facing question about the active save")
    player_query_parser.add_argument("root")
    player_query_parser.add_argument("kind", nargs="?", default="scene", choices=["scene", "entity", "context"])
    player_query_parser.add_argument("query_text", nargs="?")
    player_query_parser.add_argument("--budget", type=int)
    add_format_option(player_query_parser)

    player_turn_parser = player_sub.add_parser("turn", help="standard natural-language player turn for query/action/clarify/block")
    player_turn_parser.add_argument("root")
    player_turn_parser.add_argument("user_text", nargs="?")
    add_user_text_external_source_args(player_turn_parser)
    add_player_internal_intent_options(player_turn_parser)
    player_turn_parser.add_argument("--external-intent-candidate", help="JSON object or file path for the external AI intent candidate")
    add_preflight_consume_options(player_turn_parser)
    player_turn_parser.add_argument("--actor-id", default="")
    player_turn_parser.add_argument("--expected-pending-id", default="")
    player_turn_parser.add_argument("--clarification-id", default="")
    add_format_option(player_turn_parser)

    player_act_parser = player_sub.add_parser("act", help="compatibility wrapper for natural-language player turns")
    player_act_parser.add_argument("root")
    player_act_parser.add_argument("user_text", nargs="?")
    add_user_text_external_source_args(player_act_parser)
    add_player_internal_intent_options(player_act_parser)
    add_preflight_consume_options(player_act_parser)
    player_act_parser.add_argument("--actor-id", default="")
    player_act_parser.add_argument("--expected-pending-id", default="")
    player_act_parser.add_argument("--clarification-id", default="")
    add_format_option(player_act_parser)

    player_cancel_parser = player_sub.add_parser("cancel", help="cancel the exact pending player session")
    player_cancel_parser.add_argument("root")
    player_cancel_parser.add_argument("--expected-pending-id", required=True)
    player_cancel_parser.add_argument("--save-path", default="")
    player_cancel_parser.add_argument("--platform", default="")
    player_cancel_parser.add_argument("--session-key", default="")
    player_cancel_parser.add_argument("--actor-id", default="")
    add_format_option(player_cancel_parser)

    player_confirm_parser = player_sub.add_parser("confirm", help="confirm and save the pending player action")
    player_confirm_parser.add_argument("root")
    player_confirm_parser.add_argument("--session-id", required=True, help="pending action session_id returned by player turn")
    player_confirm_parser.add_argument("--save-path", default="")
    player_confirm_parser.add_argument("--platform", default="")
    player_confirm_parser.add_argument("--session-key", default="")
    player_confirm_parser.add_argument("--actor-id", default="")
    add_format_option(player_confirm_parser)

    player_new_parser = player_sub.add_parser("new", help="create and activate a new save")
    player_new_parser.add_argument("root")
    player_new_parser.add_argument("--campaign", required=True)
    player_new_parser.add_argument("--starter-save")
    player_new_parser.add_argument("--label")
    add_format_option(player_new_parser)

    player_switch_parser = player_sub.add_parser("switch", help="switch active save")
    player_switch_parser.add_argument("root")
    player_switch_parser.add_argument("save_id")
    add_format_option(player_switch_parser)

    player_duplicate_parser = player_sub.add_parser("duplicate", help="duplicate an existing save and activate the copy")
    player_duplicate_parser.add_argument("root")
    player_duplicate_parser.add_argument("save_id")
    player_duplicate_parser.add_argument("--label")
    add_format_option(player_duplicate_parser)

    platform_parser = subparsers.add_parser("platform", help="platform sidecar prewarm and player entry commands")
    platform_sub = platform_parser.add_subparsers(dest="platform_type", required=True)

    platform_message_parser = platform_sub.add_parser("message", help="handle one platform message event for prewarm")
    platform_message_parser.add_argument("root")
    add_platform_message_options(platform_message_parser, required_text=True)
    add_platform_sidecar_options(platform_message_parser)
    platform_message_parser.add_argument("--drain", action="store_true", help="run queued prewarm synchronously for diagnostics")
    add_format_option(platform_message_parser)

    platform_start_parser = platform_sub.add_parser("start", help="start or continue a game from a platform message")
    platform_start_parser.add_argument("root")
    platform_start_parser.add_argument("--campaign")
    platform_start_parser.add_argument("--starter-save")
    platform_start_parser.add_argument("--label")
    platform_start_parser.add_argument("--no-create", action="store_true")
    add_platform_message_options(platform_start_parser, required_text=False)
    add_platform_sidecar_options(platform_start_parser)
    add_format_option(platform_start_parser)

    platform_act_parser = platform_sub.add_parser("act", help="run player_act from a platform message with passive preflight identifiers")
    platform_act_parser.add_argument("root")
    add_platform_message_options(platform_act_parser, required_text=True)
    add_platform_sidecar_options(platform_act_parser)
    platform_act_parser.add_argument("--drain-before-act", action="store_true", help="run queued prewarm before player_act for diagnostics")
    add_format_option(platform_act_parser)

    platform_confirm_parser = platform_sub.add_parser("confirm", help="confirm a pending player action from a platform message")
    platform_confirm_parser.add_argument("root")
    platform_confirm_parser.add_argument("--session-id", required=True)
    add_platform_message_options(platform_confirm_parser, required_text=False)
    add_platform_sidecar_options(platform_confirm_parser)
    add_format_option(platform_confirm_parser)

    platform_cancel_parser = platform_sub.add_parser("cancel", help="cancel the exact pending platform player session")
    platform_cancel_parser.add_argument("root")
    platform_cancel_parser.add_argument("--expected-pending-id", required=True)
    add_platform_message_options(platform_cancel_parser, required_text=False)
    add_platform_sidecar_options(platform_cancel_parser)
    add_format_option(platform_cancel_parser)

    platform_metrics_parser = platform_sub.add_parser("metrics", help="print platform sidecar canary metrics")
    platform_metrics_parser.add_argument("root")
    add_platform_sidecar_options(platform_metrics_parser)
    add_format_option(platform_metrics_parser)

    platform_expire_parser = platform_sub.add_parser("expire", help="expire stale platform game-session bindings")
    platform_expire_parser.add_argument("root")
    add_platform_sidecar_options(platform_expire_parser)
    add_format_option(platform_expire_parser)

    platform_deactivate_parser = platform_sub.add_parser("deactivate", help="deactivate one platform game-session binding")
    platform_deactivate_parser.add_argument("root")
    add_platform_message_options(platform_deactivate_parser, required_text=False)
    add_platform_sidecar_options(platform_deactivate_parser)
    add_format_option(platform_deactivate_parser)

    eval_parser = subparsers.add_parser("eval", help="run deterministic engine eval suites")
    eval_sub = eval_parser.add_subparsers(dest="eval_type", required=True)
    eval_run_parser = eval_sub.add_parser("run", help="run deterministic intent and MCP transcript evals")
    eval_run_parser.add_argument(
        "--suite",
        default="all",
        choices=[
            "all",
            "intent",
            "intent-consensus",
            "intent-consensus-commit",
            "intent-real-canary",
            "intent-clarification-loop",
            "mcp",
        ],
    )
    eval_run_parser.add_argument("--intent-gold", help="path to intent-router gold-set YAML")
    eval_run_parser.add_argument("--intent-consensus-gold", help="path to fake-consensus intent gold-set YAML")
    eval_run_parser.add_argument("--intent-consensus-commit", help="path to consensus-to-commit gold-set YAML")
    eval_run_parser.add_argument("--intent-real-canary", help="path to real-model intent canary YAML")
    eval_run_parser.add_argument("--intent-clarification-loops", help="path to clarification-loop gold-set YAML")
    eval_run_parser.add_argument("--mcp-transcripts", help="path to MCP transcript fixture YAML")
    eval_run_parser.add_argument("--campaign-dir", help="campaign/save package to copy for intent eval")
    add_format_option(eval_run_parser)


def handle_v1_command(args: argparse.Namespace) -> int | None:
    if args.command == "campaign":
        return handle_campaign(args)
    if args.command == "save":
        return handle_save(args)
    if args.command == "play":
        return handle_play(args)
    if args.command == "mcp":
        return handle_mcp(args)
    if args.command == "player":
        return handle_player(args)
    if args.command == "platform":
        return handle_platform(args)
    if args.command == "eval":
        return handle_eval(args)
    return None


def handle_eval(args: argparse.Namespace) -> int:
    if args.eval_type == "run":
        try:
            result = run_eval_suite(
                suite=args.suite,
                intent_gold_path=args.intent_gold,
                intent_consensus_gold_path=args.intent_consensus_gold,
                intent_consensus_commit_path=args.intent_consensus_commit,
                intent_real_canary_path=args.intent_real_canary,
                intent_clarification_loops_path=args.intent_clarification_loops,
                mcp_transcripts_path=args.mcp_transcripts,
                campaign_dir=args.campaign_dir,
            )
        except Exception as exc:
            return print_failure(exc, args.format)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(render_eval_report(result), end="")
        return 0 if result.ok else 1
    return 2


def handle_campaign(args: argparse.Namespace) -> int:
    if args.campaign_type == "validate":
        result = validate_campaign_package(args.campaign_dir)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(render_campaign_validation(result), end="")
        return 0 if result.ok else 1
    if args.campaign_type == "test":
        result = run_campaign_smoke_tests(args.campaign_dir)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(render_campaign_test(result), end="")
        return 0 if result.ok else 1
    if args.campaign_type == "copy-example":
        try:
            target_dir = copy_packaged_example(args.name, args.target_dir, force=args.force)
        except Exception as exc:
            result = {
                "ok": False,
                "example": args.name,
                "target_dir": str(Path(args.target_dir)),
                "errors": [str(exc)],
            }
            if args.format == "json":
                print_json(result)
            else:
                print(f"FAILED\n- error: {exc}")
            return 1

        result = {
            "ok": True,
            "example": args.name,
            "target_dir": str(target_dir),
        }
        if args.format == "json":
            print_json(result)
        else:
            print(f"OK\nCopied {args.name} to {target_dir}")
        return 0
    if args.campaign_type == "new":
        result = create_campaign_from_template(
            args.template,
            args.target_dir,
            campaign_id=args.campaign_id,
            name=args.name,
            force=args.force,
        )
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(render_template_result(result), end="")
        return 0 if result.ok else 1
    if args.campaign_type == "doctor":
        result = run_campaign_doctor(args.campaign_dir, strict=args.strict)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(render_doctor_result(result), end="")
        return 0 if result.ok else 1
    if args.campaign_type == "outline":
        try:
            result = build_campaign_outline(args.campaign_dir, view=args.view)
        except Exception as exc:
            return print_failure(exc, args.format)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(render_campaign_outline(result), end="")
        return 0
    if args.campaign_type == "explain":
        result = explain_author_topic(args.topic)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(render_explanation(result), end="")
        return 0 if result.ok else 1
    if args.campaign_type == "check-ai":
        result = run_campaign_doctor(args.campaign_dir, strict=args.strict, ai_checks=True)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(render_doctor_result(result), end="")
        return 0 if result.ok else 1
    if args.campaign_type == "split":
        try:
            result = build_split_plan(args.campaign_dir, by=args.by, dry_run=args.dry_run)
        except Exception as exc:
            return print_failure(exc, args.format)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(render_split_plan(result), end="")
        return 0 if result.ok else 1
    return 2


def handle_save(args: argparse.Namespace) -> int:
    if args.save_type == "init":
        try:
            result = init_v1_save(args.campaign_dir, args.save_dir, force=args.force)
        except Exception as exc:
            return print_failure(exc, args.format)
        if args.format == "json":
            print_json(result)
        else:
            print(render_v1_save_init(result), end="")
        return 0
    if args.save_type == "inspect":
        result = inspect_save_or_error(args.save_dir)
        if args.format == "json":
            print_json(result)
        else:
            print(render_v1_save_inspect(result), end="")
        return 0 if result["ok"] else 1
    if args.save_type == "validate":
        result = inspect_save_or_error(args.save_dir)
        if args.format == "json":
            print_json(result)
        else:
            print(render_v1_save_validate(result), end="")
        return 0 if result["ok"] else 1
    if args.save_type == "export":
        campaign = load_campaign(args.campaign_dir)
        result = export_save(campaign, output_path=args.output)
        if args.format == "json":
            print_json(save_archive_to_dict(result))
        else:
            print(result.render_export(), end="")
        return 0
    if args.save_type == "import":
        if not args.yes:
            if args.format == "json":
                print_json({"ok": False, "errors": ["save import requires --yes"]})
            else:
                print("FAILED")
                print("- save import requires --yes")
            return 2
        try:
            result = import_save_archive(args.archive, args.target_dir, force=args.force)
        except Exception as exc:
            return print_failure(exc, args.format)
        if args.format == "json":
            data = save_archive_to_dict(result)
            data["ok"] = True
            print_json(data)
        else:
            print(result.render_import(), end="")
        return 0
    if args.save_type == "patch":
        try:
            campaign = load_campaign(args.save_dir)
            patch = load_patch_file(args.patch_file)
            result = apply_save_patch(campaign, patch, backup=not args.no_backup)
        except Exception as exc:
            return print_failure(exc, args.format)
        if args.format == "json":
            print_json(result.to_dict())
        else:
            print(result.render(), end="")
        return 0 if result.ok else 1
    return 2


def handle_play(args: argparse.Namespace) -> int:
    runtime = GMRuntime.from_path(args.campaign_dir)
    if args.play_type == "start-turn":
        try:
            user_text = resolve_user_text_arg(args)
            result = runtime.start_turn(
                user_text,
                mode=args.mode,
                submode=args.submode,
                budget=args.budget,
                max_events=args.max_events,
                max_depth=args.max_depth,
                **intent_preview_kwargs_from_args(args),
            )
        except (ExternalIntentContractError, ValueError) as exc:
            return print_failure(exc, args.format)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(result.markdown, end="")
        return 0 if result.can_proceed else 1
    if args.play_type == "preflight":
        try:
            user_text = resolve_user_text_arg(args)
            result = runtime.preflight_intent(
                user_text,
                **intent_preflight_kwargs_from_args(args),
            )
        except (ExternalIntentContractError, ValueError) as exc:
            return print_failure(exc, args.format)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(f"preflight {result.status}: {result.preflight_id}")
            if result.message_id:
                print(f"message_id: {result.message_id}")
            print(f"source_user_text_hash: {result.source_user_text_hash}")
            print(f"identity_profile: {result.identity_profile}")
            if result.expires_at:
                print(f"expires_at: {result.expires_at}")
        return 0 if result.ok else 1
    if args.play_type == "query":
        result = runtime.query(args.kind, args.query_text, view=args.view, budget=args.budget)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print(result.text, end="" if result.text.endswith("\n") else "\n")
        return 0
    if args.play_type == "act":
        try:
            user_text = resolve_user_text_arg(args)
            result = runtime.act(
                user_text,
                view=args.view,
                auto_confirm_low_risk=args.auto_confirm_low_risk,
                **intent_preview_kwargs_from_args(args),
            )
        except (ExternalIntentContractError, ValueError) as exc:
            return print_failure(exc, args.format)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            if result.markdown:
                print(result.markdown, end="" if result.markdown.endswith("\n") else "\n")
            else:
                print(result.player_message)
                if result.repair_options:
                    print("")
                    print("## 选择")
                    for option in result.repair_options:
                        print(f"- {option.label}: {option.effect or option.description}")
        return 0 if result.ok else 1
    if args.play_type == "preview":
        result = runtime.preview_action(
            args.action,
            action_options_from_args(args),
            context={"view": args.view},
            source_user_text=args.source_user_text,
        )
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
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
    if args.play_type == "ux-metrics":
        result = runtime.ux_metrics()
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print("# UX Metrics")
            print("")
            print(f"- campaign: `{result.campaign_id}`")
            print(f"- current_turn_id: `{result.current_turn_id}`")
            print(f"- current_location_id: `{result.current_location_id}`")
            print(f"- total_turns: `{result.total_turns}`")
            print(f"- scene_affordance_count: `{result.scene_affordance_count}`")
            if result.turns_by_intent:
                print("")
                print("## Turns By Intent")
                for intent, count in result.turns_by_intent.items():
                    print(f"- {intent}: {count}")
            if result.notes:
                print("")
                print("## Notes")
                for note in result.notes:
                    print(f"- {note}")
        return 0
    if args.play_type == "validate-delta":
        delta = load_delta(args.delta_json)
        try:
            result = runtime.validate_delta(
                delta,
                action=args.action,
                action_options=load_json_object_arg(args.options_json, label="--options-json"),
                context=load_json_object_arg(args.context_json, label="--context-json"),
            )
        except Exception as exc:
            return print_failure(exc, args.format)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print("OK" if result.ok else "FAILED")
            for item in result.missing_required:
                print(f"- missing: {item}")
            for item in result.errors:
                print(f"- error: {item}")
            for item in result.warnings:
                print(f"- warning: {item}")
        return 0 if result.ok else 1
    if args.play_type == "commit":
        delta = load_delta(args.delta_json)
        turn_proposal = load_turn_proposal(args.proposal_json) if args.proposal_json else None
        try:
            result = runtime.commit_turn(
                delta,
                turn_proposal=turn_proposal,
                backup=not args.no_backup,
                action=args.action,
                action_options=load_json_object_arg(args.options_json, label="--options-json"),
                context=load_json_object_arg(args.context_json, label="--context-json"),
                archivist_suggest=args.archivist_suggest,
                archivist_ai=args.archivist_ai,
                archivist_provider=args.archivist_provider,
                archivist_model=args.archivist_model,
                archivist_timeout=args.archivist_timeout,
                archivist_enqueue=not args.no_archivist_enqueue,
                state_audit=(not args.no_state_audit) or args.state_audit or args.state_audit_ai != "off",
                state_audit_ai=args.state_audit_ai,
                state_audit_provider=args.state_audit_provider,
                state_audit_model=args.state_audit_model,
                state_audit_timeout=args.state_audit_timeout,
                state_audit_block=not args.no_state_audit_block,
            )
        except Exception as exc:
            return print_failure(exc, args.format)
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print("# Play Commit")
            print("")
            print(f"- status: `{'OK' if result.ok else 'FAILED'}`")
            print(f"- campaign: `{result.campaign_id}`")
            print(f"- turn_id: `{result.turn_id}`")
            print(f"- write_status: `{result.write_status}`")
            print(f"- projection_status: `{result.projection_status}`")
            if result.backup_id:
                print(f"- backup: `{result.backup_id}`")
            if result.snapshot_path:
                print(f"- snapshot: `{result.snapshot_path}`")
            print(f"- cards: `{result.cards_count}`")
            if result.projection_report:
                failed = result.projection_report.get("requested_failed") or result.projection_report.get("failed") or []
                dirty = result.projection_report.get("requested_dirty") or result.projection_report.get("dirty") or []
                global_failed = result.projection_report.get("global_failed") or []
                if failed:
                    print(f"- projection_failed: `{', '.join(failed)}`")
                if dirty:
                    print(f"- projection_dirty: `{', '.join(dirty)}`")
                if global_failed:
                    print(f"- projection_global_failed: `{', '.join(global_failed)}`")
            if result.archivist_suggestion_id:
                print(f"- archivist_suggestion: `{result.archivist_suggestion_id}`")
                print(f"- archivist_ai_status: `{result.archivist_ai_status}`")
                print(f"- archivist_proposals: `{len(result.archivist_proposal_ids)}`")
            if result.state_audit:
                audit = result.state_audit
                print(f"- state_audit: `{audit.get('risk', 'low')}`")
                print(f"- state_audit_findings: `{len(audit.get('findings', []))}`")
        return 0 if result.ok else 1
    if args.play_type == "health":
        result = runtime.health()
        if args.format == "json":
            print(result.to_json_text(), end="")
        else:
            print("# Play Health")
            print("")
            print(f"- status: `{'OK' if result.ok else 'FAILED'}`")
            print(f"- campaign: `{result.campaign_id}`")
            if result.errors:
                print("")
                print("## Errors")
                for item in result.errors:
                    print(f"- {item}")
        return 0 if result.ok else 1
    return 2


def handle_player(args: argparse.Namespace) -> int:
    manager = SaveManager(args.root)
    try:
        if args.player_type == "inspect":
            result = manager.inspect_workspace()
        elif args.player_type == "campaigns":
            result = manager.list_campaigns(refresh=args.refresh)
        elif args.player_type == "saves":
            result = manager.list_saves(
                campaign_id=args.campaign_id,
                include_archived=args.include_archived,
                refresh=args.refresh,
            )
        elif args.player_type == "current":
            result = manager.current_save(refresh=args.refresh)
        elif args.player_type == "start":
            result = manager.start_or_continue(
                campaign=args.campaign,
                starter_save=args.starter_save,
                label=args.label,
                user_text=resolve_user_text_arg(args, default="开始游戏"),
                create_if_missing=not args.no_create,
            )
        elif args.player_type == "query":
            result = manager.player_query(kind=args.kind, query_text=args.query_text, budget=args.budget)
        elif args.player_type == "turn":
            result = manager.player_turn(
                user_text=resolve_user_text_arg(args),
                **intent_preview_kwargs_from_args(args),
                actor_id=args.actor_id,
                expected_pending_id=args.expected_pending_id,
                clarification_id=args.clarification_id,
            )
        elif args.player_type == "act":
            result = manager.player_act(
                user_text=resolve_user_text_arg(args),
                **intent_option_kwargs_from_args(args),
                **preflight_consume_kwargs_from_args(args),
                actor_id=args.actor_id,
                expected_pending_id=args.expected_pending_id,
                clarification_id=args.clarification_id,
            )
        elif args.player_type == "cancel":
            result = manager.player_cancel(
                args.expected_pending_id,
                save_path=args.save_path,
                platform=args.platform,
                session_key=args.session_key,
                actor_id=args.actor_id,
            )
        elif args.player_type == "confirm":
            result = manager.player_confirm(
                session_id=args.session_id,
                save_path=args.save_path,
                platform=args.platform,
                session_key=args.session_key,
                actor_id=args.actor_id,
            )
        elif args.player_type == "new":
            result = manager.create_save(
                campaign=args.campaign,
                starter_save=args.starter_save,
                label=args.label,
                activate=True,
            )
        elif args.player_type == "switch":
            result = manager.switch_save(args.save_id)
        elif args.player_type == "duplicate":
            result = manager.duplicate_save(args.save_id, label=args.label, activate=True)
        else:
            return 2
    except Exception as exc:
        return print_failure(exc, args.format)

    if args.format == "json":
        print_json(result)
    else:
        print(render_player_result(args.player_type, result), end="")
    return 0 if result.get("ok") else 1


def handle_platform(args: argparse.Namespace) -> int:
    try:
        sidecar = build_platform_sidecar(args)
        if args.platform_type == "message":
            result = sidecar.handle_message_event(platform_event_from_args(args)).to_dict()
            worker_results = sidecar.drain_prewarm() if args.drain else []
            data = {
                "ok": True,
                "platform_prewarm": result,
                "worker_results": [item.to_dict() for item in worker_results],
                "platform_metrics": sidecar.metrics_snapshot(),
            }
        elif args.platform_type == "start":
            data = sidecar.start_or_continue_from_message(
                platform_event_from_args(args),
                campaign=args.campaign,
                starter_save=args.starter_save,
                label=args.label,
                create_if_missing=not args.no_create,
            ).to_dict()
        elif args.platform_type == "act":
            if args.drain_before_act:
                sidecar.handle_message_event(platform_event_from_args(args))
                sidecar.drain_prewarm()
            data = sidecar.player_act_from_message(platform_event_from_args(args)).to_dict()
        elif args.platform_type == "confirm":
            data = sidecar.player_confirm_from_message(
                platform_event_from_args(args),
                session_id=args.session_id,
            ).to_dict()
        elif args.platform_type == "cancel":
            data = sidecar.player_cancel_from_message(
                platform_event_from_args(args),
                expected_pending_id=args.expected_pending_id,
            ).to_dict()
        elif args.platform_type == "metrics":
            sidecar.expire_stale_bindings()
            data = {"ok": True, "platform_metrics": sidecar.metrics_snapshot()}
        elif args.platform_type == "expire":
            expired = sidecar.expire_stale_bindings()
            data = {"ok": True, "expired_count": expired, "platform_metrics": sidecar.metrics_snapshot()}
        elif args.platform_type == "deactivate":
            binding = sidecar.deactivate_from_message(platform_event_from_args(args))
            data = {"ok": True, "platform_binding": binding, "platform_metrics": sidecar.metrics_snapshot()}
        else:
            return 2
    except Exception as exc:
        return print_failure(exc, args.format)

    if args.format == "json":
        print_json(data)
    else:
        print(render_platform_result(args.platform_type, data), end="")
    return 0 if data.get("ok") else 1


def build_platform_sidecar(args: argparse.Namespace) -> Any:
    from .platform_prewarm import PlatformPrewarmConfig
    from .platform_sidecar import PlatformSidecar, PlatformSidecarConfig

    env_config = PlatformPrewarmConfig.from_env()
    prewarm = PlatformPrewarmConfig(
        enabled=bool(args.enable_prewarm or env_config.enabled),
        max_queue_size=args.prewarm_queue_size or env_config.max_queue_size,
        worker_count=args.prewarm_workers or env_config.worker_count,
        intent_backend=args.intent_backend or env_config.intent_backend,
        intent_provider=args.intent_provider or env_config.intent_provider,
        intent_model=args.intent_model or env_config.intent_model,
        intent_timeout=args.intent_timeout if args.intent_timeout is not None else env_config.intent_timeout,
        intent_base_url=args.intent_base_url if args.intent_base_url is not None else env_config.intent_base_url,
        intent_api_key_env=args.intent_api_key_env if args.intent_api_key_env is not None else env_config.intent_api_key_env,
        intent_fallback_backend=args.intent_fallback_backend or env_config.intent_fallback_backend,
        ttl_seconds=env_config.ttl_seconds,
    )
    config = PlatformSidecarConfig.from_prewarm_config(
        prewarm,
        player_intent_ai=args.intent_ai,
        player_intent_timeout=(
            args.intent_timeout if args.intent_timeout is not None else DEFAULT_INTENT_TIMEOUT_SECONDS
        ),
        active_ttl_seconds=args.active_ttl_seconds,
        preflight_pending_wait_ms=args.preflight_pending_wait_ms,
    )
    return PlatformSidecar(args.root, config=config)


def platform_event_from_args(args: argparse.Namespace) -> dict[str, Any]:
    event = load_json_object_arg(args.event_json, label="--event-json") if args.event_json else {}
    text = resolve_user_text_arg(args, required=False)
    if text is not None:
        event["text"] = text
    for key in ("platform", "session_key", "message_id", "actor_id", "chat_type", "message_type"):
        value = getattr(args, key, "")
        if value:
            event[key] = value
    if args.actor_is_bot:
        event["actor_is_bot"] = True
    if args.actor_is_self:
        event["actor_is_self"] = True
    if args.is_approval:
        event["is_approval"] = True
    return event


def render_platform_result(kind: str, data: dict[str, Any]) -> str:
    if kind == "message":
        prewarm = data.get("platform_prewarm") if isinstance(data.get("platform_prewarm"), dict) else {}
        reason = prewarm.get("reason") or "unknown"
        state = "enqueued" if prewarm.get("enqueued") else f"dropped:{reason}" if prewarm.get("dropped") else reason
        return f"platform prewarm {state}\n"
    if kind in {"metrics", "expire"}:
        return json.dumps(data.get("platform_metrics", {}), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if kind == "deactivate":
        return "platform binding deactivated\n" if data.get("platform_binding") else "platform binding not found\n"
    message = str(data.get("message") or "").strip()
    if message:
        return message if message.endswith("\n") else message + "\n"
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def handle_mcp(args: argparse.Namespace) -> int:
    from .mcp_adapter import MCPAdapterConfig, build_client_config, render_client_config, serve_mcp

    try:
        if args.mcp_type == "print-config":
            data = build_client_config(
                args.root,
                default_campaign=args.default_campaign,
                default_save=args.default_save,
                default_starter_save=args.default_starter_save,
                registry_active=args.registry_active,
                mcp_profile=args.mcp_profile,
                command=args.client_command,
                server_name=args.server_name,
            )
            print(render_client_config(data), end="")
            return 0
        if args.mcp_type == "serve":
            config = MCPAdapterConfig.from_values(
                args.root,
                default_campaign=args.default_campaign,
                default_save=args.default_save,
                default_starter_save=args.default_starter_save,
                registry_active=args.registry_active,
                mcp_profile=args.mcp_profile,
                ai_profile=args.ai_profile,
                ai_provider=args.ai_provider,
                ai_model=args.ai_model,
                ai_timeout=args.ai_timeout,
                semantic_ai=args.semantic_ai,
                semantic_provider=args.semantic_provider,
                semantic_model=args.semantic_model,
                semantic_timeout=args.semantic_timeout,
                intent_ai=args.intent_ai,
                intent_backend=args.intent_backend,
                intent_provider=args.intent_provider,
                intent_model=args.intent_model,
                intent_timeout=args.intent_timeout,
                intent_base_url=args.intent_base_url,
                intent_api_key_env=args.intent_api_key_env,
                intent_fallback_backend=args.intent_fallback_backend,
                state_audit_ai=args.state_audit_ai,
                state_audit_provider=args.state_audit_provider,
                state_audit_model=args.state_audit_model,
                state_audit_timeout=args.state_audit_timeout,
                archivist_suggest=args.archivist_suggest,
                archivist_ai=args.archivist_ai,
                archivist_provider=args.archivist_provider,
                archivist_model=args.archivist_model,
                archivist_timeout=args.archivist_timeout,
                archivist_enqueue=not args.no_archivist_enqueue,
            )
            serve_mcp(config, transport=args.transport)
            return 0
    except Exception as exc:
        print("FAILED")
        print(f"- error: {exc}")
        return 1
    return 2


def render_player_result(kind: str, result: dict[str, Any]) -> str:
    if kind == "start" and result.get("onboarding_text"):
        return str(result["onboarding_text"])
    if kind == "query":
        return str(result.get("text") or "").rstrip() + "\n"
    if kind in {"turn", "act"}:
        lines = [str(result.get("message") or "").rstrip()]
        if result.get("ready_to_confirm"):
            lines.extend(["", "下一步：确认后保存这个行动。"])
        if result.get("errors"):
            lines.extend(["", "## 问题", ""])
            lines.extend(f"- {item}" for item in result["errors"])
        return "\n".join(line for line in lines if line is not None).rstrip() + "\n"
    if kind == "confirm":
        lines = [str(result.get("message") or "").rstrip()]
        if result.get("errors"):
            lines.extend(["", "## 问题", ""])
            lines.extend(f"- {item}" for item in result["errors"])
        return "\n".join(line for line in lines if line is not None).rstrip() + "\n"
    lines = ["# Player", "", f"- status: `{'OK' if result.get('ok') else 'FAILED'}`"]
    if result.get("active_save_id"):
        lines.append(f"- active_save_id: `{result['active_save_id']}`")
    if result.get("root"):
        lines.append(f"- root: `{result['root']}`")
    save = result.get("save")
    if isinstance(save, dict):
        lines.extend(["", "## Save", ""])
        lines.append(f"- id: `{save.get('id')}`")
        lines.append(f"- label: {save.get('label')}")
        lines.append(f"- campaign: {save.get('campaign_name') or save.get('campaign_id')}")
        lines.append(f"- summary: {save.get('summary')}")
        lines.append(f"- health: `{save.get('health')}`")
    if result.get("saves"):
        lines.extend(["", "## Saves", ""])
        for index, item in enumerate(result["saves"], start=1):
            lines.append(
                f"{index}. `{item.get('id')}` {item.get('label') or item.get('campaign_name')} - "
                f"{item.get('summary') or item.get('current_location_id')} ({item.get('health')})"
            )
    if result.get("campaigns"):
        lines.extend(["", "## Campaigns", ""])
        for item in result["campaigns"]:
            lines.append(f"- `{item.get('id')}` {item.get('name')} - {item.get('path')} ({item.get('status')})")
    if result.get("errors"):
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {item}" for item in result["errors"])
    return "\n".join(lines).rstrip() + "\n"


def inspect_save_or_error(save_dir: str | Path) -> dict[str, Any]:
    try:
        return inspect_v1_save(save_dir)
    except Exception as exc:
        return {
            "ok": False,
            "errors": [str(exc)],
            "missing_files": [],
            "counts": {},
            "campaign_id": "",
            "save_dir": str(save_dir),
        }


def save_archive_to_dict(result: Any) -> dict[str, Any]:
    return {
        "archive_path": str(result.archive_path),
        "files": [
            {"path": item.path, "bytes": item.bytes, "sha256": item.sha256}
            for item in result.files
        ],
        "manifest": result.manifest,
    }


def render_v1_save_init(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Save Init",
            "",
            "- status: `OK`",
            f"- campaign: `{result['campaign_id']}`",
            f"- save_dir: `{result['save_dir']}`",
            f"- database: `{result['database']}`",
            f"- snapshot: `{result['snapshot_path']}`",
            f"- cards: `{result['cards_count']}`",
        ]
    ) + "\n"


def render_v1_save_inspect(result: dict[str, Any]) -> str:
    lines = [
        "# Save Inspect",
        "",
        f"- status: `{'OK' if result['ok'] else 'FAILED'}`",
        f"- campaign: `{result['campaign_id']}`",
        f"- save_dir: `{result['save_dir']}`",
        f"- current_turn_id: `{result.get('current_turn_id')}`",
        f"- current_location_id: `{result.get('current_location_id')}`",
        "",
        "| Table | Count |",
        "|-------|-------|",
    ]
    for name, count in sorted(result["counts"].items()):
        lines.append(f"| `{name}` | {count} |")
    if result["missing_files"]:
        lines.extend(["", "## Missing Files", ""])
        lines.extend(f"- {item}" for item in result["missing_files"])
    if result["errors"]:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {item}" for item in result["errors"])
    return "\n".join(lines).rstrip() + "\n"


def render_v1_save_validate(result: dict[str, Any]) -> str:
    if result["ok"]:
        return "OK\n"
    lines = ["FAILED"]
    lines.extend(f"- missing: {item}" for item in result["missing_files"])
    lines.extend(f"- error: {item}" for item in result["errors"])
    return "\n".join(lines).rstrip() + "\n"


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def print_failure(exc: Exception, output_format: str) -> int:
    if isinstance(exc, ExternalIntentContractError):
        if output_format == "json":
            print_json(external_intent_contract_error_dict(exc))
        else:
            print("FAILED")
            print(f"- error: {exc.message}")
            print(f"- action: {exc.action}")
        return 1
    if output_format == "json":
        print_json({"ok": False, "errors": [str(exc)]})
    else:
        print("FAILED")
        print(f"- error: {exc}")
    return 1
