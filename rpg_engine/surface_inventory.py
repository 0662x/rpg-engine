from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SurfaceEntry:
    name: str
    surface: str
    category: str
    profile: str
    write_mode: str
    default_exposed: bool
    normal_play: bool
    description: str
    notes: tuple[str, ...] = ()
    related_tools: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FORBIDDEN_DEFAULT_MCP_TOKENS = (
    "admin",
    "repair",
    "migration",
    "migrate",
    "plugin",
    "upgrade",
    "reconcile",
    "install",
    "import",
    "export",
    "patch",
    "backup",
    "restore",
    "arbitrary_file",
)

MCP_SURFACE_INVENTORY = (
    SurfaceEntry(
        name="workspace_inspect",
        surface="mcp",
        category="workspace_registry",
        profile="player_read",
        write_mode="read_only",
        default_exposed=True,
        normal_play=True,
        description="Inspect the configured player workspace registry.",
    ),
    SurfaceEntry(
        name="campaign_list",
        surface="mcp",
        category="campaign_package",
        profile="player_read",
        write_mode="read_only",
        default_exposed=True,
        normal_play=True,
        description="List player-facing campaign packages registered under the MCP root.",
    ),
    SurfaceEntry(
        name="save_list",
        surface="mcp",
        category="save_package",
        profile="player_read",
        write_mode="read_only",
        default_exposed=True,
        normal_play=True,
        description="List player-facing saves registered under the MCP root.",
    ),
    SurfaceEntry(
        name="save_current",
        surface="mcp",
        category="save_package",
        profile="player_read",
        write_mode="read_only",
        default_exposed=True,
        normal_play=True,
        description="Return the active player-facing save.",
    ),
    SurfaceEntry(
        name="save_create",
        surface="mcp",
        category="save_package",
        profile="player_controlled_create",
        write_mode="controlled_create",
        default_exposed=True,
        normal_play=True,
        description="Create a new save package from a campaign or starter save.",
        notes=("May create save files, but must not advance story facts or mutate gameplay state.",),
    ),
    SurfaceEntry(
        name="save_switch",
        surface="mcp",
        category="save_package",
        profile="player_controlled_selection",
        write_mode="controlled_selection",
        default_exposed=True,
        normal_play=True,
        description="Switch the active player-facing save.",
        notes=("Selects a save registry entry; does not change story facts.",),
    ),
    SurfaceEntry(
        name="start_or_continue",
        surface="mcp",
        category="player_entry",
        profile="player_controlled_create",
        write_mode="controlled_create",
        default_exposed=True,
        normal_play=True,
        description="Continue an active save, or create one and return onboarding context.",
        notes=("May create a save package for onboarding; gameplay facts still require player_turn/player_confirm.",),
    ),
    SurfaceEntry(
        name="intent_manifest",
        surface="mcp",
        category="player_contract",
        profile="player_read",
        write_mode="read_only",
        default_exposed=True,
        normal_play=True,
        description="Read-only kernel-generated action/query manifest for external candidate construction.",
        notes=("Contract source only; natural-language play still enters player_turn.",),
        related_tools=("player_turn",),
    ),
    SurfaceEntry(
        name="player_query",
        surface="mcp",
        category="player_workflow",
        profile="player_read",
        write_mode="read_only",
        default_exposed=False,
        normal_play=False,
        description="Structured compatibility query against the active save; normal natural language enters player_turn.",
    ),
    SurfaceEntry(
        name="player_turn",
        surface="mcp",
        category="player_workflow",
        profile="player_turn_preview",
        write_mode="preview_only",
        default_exposed=True,
        normal_play=True,
        description="Standard player turn entry for natural-language query/action/clarify/block without exposing delta or TurnProposal JSON.",
        related_tools=("player_confirm",),
    ),
    SurfaceEntry(
        name="player_act",
        surface="mcp",
        category="player_workflow",
        profile="player_turn_preview",
        write_mode="preview_only",
        default_exposed=False,
        normal_play=False,
        description="Compatibility player action preview; new normal play uses player_turn.",
        related_tools=("player_confirm",),
    ),
    SurfaceEntry(
        name="player_confirm",
        surface="mcp",
        category="player_workflow",
        profile="player_turn_commit",
        write_mode="validated_commit",
        default_exposed=True,
        normal_play=True,
        description="Confirm and save the pending player action using the player_turn session_id without exposing delta or TurnProposal JSON.",
        related_tools=("player_turn", "player_act"),
    ),
    SurfaceEntry(
        name="campaign_validate",
        surface="mcp",
        category="campaign_package",
        profile="player_read",
        write_mode="read_only",
        default_exposed=True,
        normal_play=True,
        description="Validate a configured campaign package without mutating it.",
    ),
    SurfaceEntry(
        name="save_inspect",
        surface="mcp",
        category="save_package",
        profile="player_read",
        write_mode="read_only",
        default_exposed=True,
        normal_play=True,
        description="Inspect a configured save package without mutating it.",
    ),
    SurfaceEntry(
        name="start_turn",
        surface="mcp",
        category="turn_workflow",
        profile="player_turn_read",
        write_mode="read_only",
        default_exposed=False,
        normal_play=False,
        description="Low-level context packet and turn contract builder for one player request.",
    ),
    SurfaceEntry(
        name="intent_preflight",
        surface="mcp",
        category="turn_workflow",
        profile="developer_or_trusted_gm_advisory_cache",
        write_mode="advisory_only",
        default_exposed=False,
        normal_play=False,
        description="Precompute an advisory internal intent review for later same-context reuse.",
        notes=("Does not preview, commit, or change gameplay facts; stores only advisory cache state.",),
        related_tools=("preview_from_text",),
    ),
    SurfaceEntry(
        name="query",
        surface="mcp",
        category="turn_workflow",
        profile="player_turn_read",
        write_mode="read_only",
        default_exposed=False,
        normal_play=False,
        description="Low-level read of current player-visible state without advancing time or saving facts.",
    ),
    SurfaceEntry(
        name="preview_from_text",
        surface="mcp",
        category="turn_workflow",
        profile="player_turn_preview",
        write_mode="preview_only",
        default_exposed=False,
        normal_play=False,
        description="Low-level natural-language preview primitive; player_turn is the normal play entry.",
        related_tools=("start_turn", "validate_delta", "commit_turn"),
    ),
    SurfaceEntry(
        name="preview_action",
        surface="mcp",
        category="turn_low_level",
        profile="developer_or_trusted_gm_low_level",
        write_mode="preview_only",
        default_exposed=False,
        normal_play=False,
        description="Low-level preview for an already-selected action contract.",
        notes=("Default player profile is code-gated from this tool; use player_turn for normal play.",),
        related_tools=("preview_from_text",),
    ),
    SurfaceEntry(
        name="validate_delta",
        surface="mcp",
        category="turn_low_level",
        profile="developer_or_trusted_gm_validation",
        write_mode="validation_only",
        default_exposed=False,
        normal_play=False,
        description="Validate a structured turn delta without saving it.",
    ),
    SurfaceEntry(
        name="commit_turn",
        surface="mcp",
        category="turn_low_level",
        profile="developer_or_trusted_gm_commit",
        write_mode="validated_commit",
        default_exposed=False,
        normal_play=False,
        description="Commit one validated and accepted TurnProposal delta to a configured save.",
        notes=("Default player profile is code-gated from this tool; use player_confirm for normal play.",),
    ),
    SurfaceEntry(
        name="health",
        surface="mcp",
        category="runtime_health",
        profile="player_read",
        write_mode="read_only",
        default_exposed=True,
        normal_play=True,
        description="Run a read-only health check for a configured save.",
        notes=("Does not run repair or projection rebuild.",),
    ),
)

AI_PROMPT_SURFACE_INVENTORY = (
    SurfaceEntry(
        name="docs/prompts/ai-client-prompt.md",
        surface="ai_prompt",
        category="external_ai_gm",
        profile="external_agent_low_trust",
        write_mode="workflow_guidance_only",
        default_exposed=True,
        normal_play=True,
        description="Generic external AI client prompt for MCP/CLI play.",
        notes=("Prompt guidance is not a permission grant.",),
        related_tools=("player_turn", "player_confirm", "start_turn", "preview_from_text", "validate_delta", "commit_turn"),
    ),
    SurfaceEntry(
        name="docs/prompts/author-ai-prompt.md",
        surface="ai_prompt",
        category="campaign_authoring",
        profile="authoring_low_trust",
        write_mode="author_files_only",
        default_exposed=False,
        normal_play=False,
        description="External AI prompt for campaign package authoring and doctor fixes.",
        notes=("Must not edit save packages, runtime databases, plugins, scripts or executable rules.",),
    ),
    SurfaceEntry(
        name="campaign-local AUTHOR_AI_PROMPT.md",
        surface="ai_prompt",
        category="campaign_authoring",
        profile="authoring_low_trust",
        write_mode="author_files_only",
        default_exposed=False,
        normal_play=False,
        description="Template-copied authoring prompt inside campaign packages.",
        notes=("Applies to campaign package source files, not save package state.",),
    ),
)

PACKAGE_SURFACE_INVENTORY = (
    SurfaceEntry(
        name="aigm campaign validate",
        surface="cli_v1",
        category="campaign_package",
        profile="authoring_or_player_read",
        write_mode="read_only",
        default_exposed=False,
        normal_play=False,
        description="Validate a V1 campaign package.",
    ),
    SurfaceEntry(
        name="aigm campaign test",
        surface="cli_v1",
        category="campaign_package",
        profile="authoring_or_maintenance",
        write_mode="temp_save_only",
        default_exposed=False,
        normal_play=False,
        description="Initialize a temporary save and run V1 smoke checks.",
    ),
    SurfaceEntry(
        name="aigm campaign new",
        surface="cli_v1",
        category="campaign_package",
        profile="authoring",
        write_mode="controlled_create",
        default_exposed=False,
        normal_play=False,
        description="Create an author-friendly campaign from a template.",
    ),
    SurfaceEntry(
        name="aigm campaign doctor",
        surface="cli_v1",
        category="campaign_package",
        profile="authoring_or_maintenance",
        write_mode="read_only",
        default_exposed=False,
        normal_play=False,
        description="Run author-facing campaign diagnostics.",
    ),
    SurfaceEntry(
        name="aigm save init",
        surface="cli_v1",
        category="save_package",
        profile="player_or_maintenance_create",
        write_mode="controlled_create",
        default_exposed=False,
        normal_play=False,
        description="Initialize a save directory from a campaign package.",
        notes=("Creates save package structure; does not commit player turn facts.",),
    ),
    SurfaceEntry(
        name="aigm save inspect",
        surface="cli_v1",
        category="save_package",
        profile="player_read",
        write_mode="read_only",
        default_exposed=False,
        normal_play=True,
        description="Inspect a save directory.",
    ),
    SurfaceEntry(
        name="aigm save validate",
        surface="cli_v1",
        category="save_package",
        profile="player_read",
        write_mode="read_only",
        default_exposed=False,
        normal_play=True,
        description="Validate a save directory.",
    ),
    SurfaceEntry(
        name="aigm save export",
        surface="cli_v1",
        category="save_package",
        profile="maintenance_export",
        write_mode="export_only",
        default_exposed=False,
        normal_play=False,
        description="Export a campaign save archive.",
    ),
    SurfaceEntry(
        name="aigm save import",
        surface="cli_v1",
        category="save_package",
        profile="maintenance_import",
        write_mode="controlled_import",
        default_exposed=False,
        normal_play=False,
        description="Import a save archive into a target directory.",
    ),
    SurfaceEntry(
        name="aigm save patch",
        surface="cli_v1",
        category="save_package",
        profile="maintenance_repair",
        write_mode="maintenance_write",
        default_exposed=False,
        normal_play=False,
        description="Apply a safe maintenance patch to a save.",
    ),
    SurfaceEntry(
        name="aigm package upgrade",
        surface="cli_admin",
        category="campaign_package",
        profile="admin_maintenance",
        write_mode="admin_write",
        default_exposed=False,
        normal_play=False,
        description="Apply or dry-run a package upgrade against a campaign save.",
    ),
    SurfaceEntry(
        name="aigm migration apply",
        surface="cli_admin",
        category="database_migration",
        profile="admin_maintenance",
        write_mode="admin_write",
        default_exposed=False,
        normal_play=False,
        description="Apply pending schema migrations.",
    ),
    SurfaceEntry(
        name="aigm projection repair",
        surface="cli_admin",
        category="projection",
        profile="admin_maintenance",
        write_mode="maintenance_write",
        default_exposed=False,
        normal_play=False,
        description="Retry outbox and rebuild dirty projections.",
    ),
    SurfaceEntry(
        name="aigm plugin validate",
        surface="cli_admin",
        category="plugin",
        profile="admin_read",
        write_mode="read_only",
        default_exposed=False,
        normal_play=False,
        description="Inspect and validate plugin manifests without loading code.",
    ),
)


def mcp_default_tool_names() -> tuple[str, ...]:
    return tuple(entry.name for entry in MCP_SURFACE_INVENTORY if entry.default_exposed)


def all_surface_entries() -> tuple[SurfaceEntry, ...]:
    return MCP_SURFACE_INVENTORY + AI_PROMPT_SURFACE_INVENTORY + PACKAGE_SURFACE_INVENTORY


def entries_by_surface(surface: str) -> tuple[SurfaceEntry, ...]:
    return tuple(entry for entry in all_surface_entries() if entry.surface == surface)


def default_mcp_violations(tool_names: tuple[str, ...] | None = None) -> tuple[str, ...]:
    names = tool_names or mcp_default_tool_names()
    violations: list[str] = []
    for name in names:
        lower = name.lower()
        if any(token in lower for token in FORBIDDEN_DEFAULT_MCP_TOKENS):
            violations.append(name)
    return tuple(violations)


def render_surface_inventory_markdown() -> str:
    lines = [
        "# Phase 0 Surface Inventory",
        "",
        "This inventory is generated from `rpg_engine.surface_inventory`.",
        "",
        "## Default MCP Tools",
        "",
        "| Tool | Category | Profile | Write mode | Normal play |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in MCP_SURFACE_INVENTORY:
        lines.append(
            f"| `{entry.name}` | {entry.category} | {entry.profile} | {entry.write_mode} | {entry.normal_play} |"
        )
    lines.extend(
        [
            "",
            "## AI Prompt Surfaces",
            "",
            "| File | Category | Profile | Write mode |",
            "| --- | --- | --- | --- |",
        ]
    )
    for entry in AI_PROMPT_SURFACE_INVENTORY:
        lines.append(f"| `{entry.name}` | {entry.category} | {entry.profile} | {entry.write_mode} |")
    lines.extend(
        [
            "",
            "## Package Management Surfaces",
            "",
            "| Entry | Surface | Category | Profile | Write mode | Default exposed |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for entry in PACKAGE_SURFACE_INVENTORY:
        lines.append(
            f"| `{entry.name}` | {entry.surface} | {entry.category} | {entry.profile} | "
            f"{entry.write_mode} | {entry.default_exposed} |"
        )
    return "\n".join(lines) + "\n"
