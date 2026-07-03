from __future__ import annotations

from .base import ActionResolverRegistry
from .combat import COMBAT_RESOLVER
from .craft import CRAFT_RESOLVER
from .explore import EXPLORE_RESOLVER
from .gather import GATHER_RESOLVER
from .random_table import RANDOM_TABLE_RESOLVER
from .rest import REST_RESOLVER
from .routine import ROUTINE_RESOLVER
from .social import SOCIAL_RESOLVER
from .travel import TRAVEL_RESOLVER


def get_default_action_registry() -> ActionResolverRegistry:
    registry = ActionResolverRegistry()
    for spec in [
        COMBAT_RESOLVER,
        REST_RESOLVER,
        ROUTINE_RESOLVER,
        SOCIAL_RESOLVER,
        CRAFT_RESOLVER,
        GATHER_RESOLVER,
        EXPLORE_RESOLVER,
        TRAVEL_RESOLVER,
        RANDOM_TABLE_RESOLVER,
    ]:
        registry.register(spec)
    return registry


def render_action_resolver_list() -> str:
    lines = [
        "# Action Resolvers",
        "",
        "| Name | Template | Required Options | Options | Contract |",
        "|------|----------|------------------|---------|----------|",
    ]
    for spec in get_default_action_registry().all():
        contract = [
            "request",
            "preview",
            "resolve",
            "delta",
        ]
        lines.append(
            f"| `{spec.name}` | `{spec.response_template}` | {', '.join(spec.required_options)} | "
            f"{', '.join(option.name for option in spec.option_specs)} | {', '.join(contract)} |"
        )
    return "\n".join(lines) + "\n"


def render_action_resolver_detail(name: str) -> tuple[str, bool]:
    spec = get_default_action_registry().get(name)
    if not spec:
        return f"FAILED\n- unknown action resolver: {name}\n", False
    lines = [
        f"# Action Resolver: {spec.name}",
        "",
        f"- response_template: `{spec.response_template}`",
        f"- required_options: `{', '.join(spec.required_options)}`",
        f"- option_specs: `{', '.join(option.name for option in spec.option_specs)}`",
        f"- keywords: `{', '.join(spec.keywords)}`",
        f"- semantic_labels: `{', '.join(spec.semantic_labels)}`",
        f"- inference_priority: `{spec.inference_priority}`",
        f"- request_model: `{spec.request_model.__name__}`",
        f"- proposal_model: `{spec.proposal_model.__name__}`",
        f"- has_preview: `{'yes' if spec.preview else 'no'}`",
        f"- has_request_contract: `yes`",
        f"- has_resolve_contract: `yes`",
        f"- has_delta_contract: `yes`",
    ]
    return "\n".join(lines) + "\n", True
