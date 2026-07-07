from __future__ import annotations

from .base import ContentTypeSpec


class ContentRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, ContentTypeSpec] = {}
        self._by_campaign_key: dict[str, ContentTypeSpec] = {}
        self._by_delta_key: dict[str, ContentTypeSpec] = {}
        self._by_entity_type: dict[str, ContentTypeSpec] = {}

    def register(self, spec: ContentTypeSpec) -> None:
        if spec.name in self._by_name:
            raise ValueError(f"Duplicate content type name: {spec.name}")
        if spec.campaign_key and spec.campaign_key in self._by_campaign_key:
            raise ValueError(f"Duplicate campaign content key: {spec.campaign_key}")
        if spec.delta_key and spec.delta_key in self._by_delta_key:
            raise ValueError(f"Duplicate delta key: {spec.delta_key}")
        if spec.entity_type and spec.entity_type in self._by_entity_type:
            raise ValueError(f"Duplicate entity type: {spec.entity_type}")
        self._by_name[spec.name] = spec
        if spec.campaign_key:
            self._by_campaign_key[spec.campaign_key] = spec
        if spec.delta_key:
            self._by_delta_key[spec.delta_key] = spec
        if spec.entity_type:
            self._by_entity_type[spec.entity_type] = spec

    def get(self, name: str) -> ContentTypeSpec:
        return self._by_name[name]

    def by_campaign_key(self, key: str) -> ContentTypeSpec | None:
        return self._by_campaign_key.get(key)

    def by_delta_key(self, key: str) -> ContentTypeSpec | None:
        return self._by_delta_key.get(key)

    def by_entity_type(self, entity_type: str) -> ContentTypeSpec | None:
        return self._by_entity_type.get(entity_type)

    def all(self) -> list[ContentTypeSpec]:
        return list(self._by_name.values())

    def seed_specs(self) -> list[ContentTypeSpec]:
        return [
            spec
            for spec in self.all()
            if spec.campaign_key and spec.yaml_key and spec.seed_handler
        ]

    def delta_specs(self) -> list[ContentTypeSpec]:
        return [
            spec
            for spec in self.all()
            if spec.delta_key and spec.upsert
        ]

    def sync_specs(self) -> list[ContentTypeSpec]:
        return [
            spec
            for spec in self.seed_specs()
            if spec.sync_safe
        ]


def get_default_registry() -> ContentRegistry:
    registry = ContentRegistry()
    from .core import register_core_content_types
    from .world_setting import register_world_setting

    register_core_content_types(registry)
    register_world_setting(registry)
    return registry


def render_content_type_list(registry: ContentRegistry | None = None) -> str:
    registry = registry or get_default_registry()
    lines = [
        "# Content Types",
        "",
        "| Name | Campaign Key | YAML Key | Delta Key | Entity Type | Table | Sync Safe |",
        "|------|--------------|----------|-----------|-------------|-------|-----------|",
    ]
    for spec in registry.all():
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{spec.name}`",
                    f"`{spec.campaign_key}`" if spec.campaign_key else "",
                    f"`{spec.yaml_key}`" if spec.yaml_key else "",
                    f"`{spec.delta_key}`" if spec.delta_key else "",
                    f"`{spec.entity_type}`" if spec.entity_type else "",
                    f"`{spec.table}`" if spec.table else "",
                    "yes" if spec.sync_safe else "no",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _format_contract_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"`{value}`" for value in values)


def render_content_type_detail(name: str, registry: ContentRegistry | None = None) -> tuple[str, bool]:
    registry = registry or get_default_registry()
    try:
        spec = registry.get(name)
    except KeyError:
        return f"FAILED\n- unknown content type: {name}\n", False
    metadata = spec.contract_metadata()
    merge_policy = metadata["merge_policy"]
    presentation_spec = None
    if spec.entity_type:
        from ..card_registry import get_default_card_registry

        presentation_spec = get_default_card_registry().by_entity_type(spec.entity_type)
    lines = [
        f"# Content Type: {spec.name}",
        "",
        "## Content Lifecycle",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Campaign Key | `{spec.campaign_key}` |" if spec.campaign_key else "| Campaign Key |  |",
        f"| YAML Key | `{spec.yaml_key}` |" if spec.yaml_key else "| YAML Key |  |",
        f"| Delta Key | `{spec.delta_key}` |" if spec.delta_key else "| Delta Key |  |",
        f"| Entity Type | `{spec.entity_type}` |" if spec.entity_type else "| Entity Type |  |",
        f"| Table | `{spec.table}` |" if spec.table else "| Table |  |",
        f"| Count Key | `{spec.result_key}` |",
        f"| Payload Key | `{spec.event_payload_key}` |",
        f"| Sync Safe | {'yes' if spec.sync_safe else 'no'} |",
        f"| Has Seed | {'yes' if spec.seed_handler else 'no'} |",
        f"| Has Delta Upsert | {'yes' if spec.upsert and spec.delta_key else 'no'} |",
        f"| Has Record Preflight | {'yes' if spec.validate_record else 'no'} |",
        f"| Has Database Check | {'yes' if spec.validate_database else 'no'} |",
        f"| Record Validation | {'yes' if metadata['has_record_validation'] else 'no'} |",
        f"| Database Validation | {'yes' if metadata['has_database_validation'] else 'no'} |",
        "",
        "## Merge Policy",
        "",
        "| Field Group | Fields |",
        "|-------------|--------|",
        f"| Author Owned | {_format_contract_values(merge_policy['author_owned'])} |",
        f"| Runtime Owned | {_format_contract_values(merge_policy['runtime_owned'])} |",
        f"| Mergeable | {_format_contract_values(merge_policy['mergeable'])} |",
        f"| Conflict Only | {_format_contract_values(merge_policy['conflict_only'])} |",
        f"| Unlisted Fields | `{merge_policy['default_ownership'][0]}` |",
        "",
        "## Presentation",
        "",
        "| Field | Value |",
        "|-------|-------|",
        (
            f"| Presentation Entity Type | `{presentation_spec.entity_type}` |"
            if presentation_spec
            else "| Presentation Entity Type |  |"
        ),
        f"| Presentation Card Dir | `{presentation_spec.card_dir}` |" if presentation_spec else "| Presentation Card Dir |  |",
        f"| Presentation Sort Order | {presentation_spec.sort_order} |" if presentation_spec else "| Presentation Sort Order |  |",
        (
            f"| Presentation ID Prefixes | `{', '.join(presentation_spec.id_prefixes)}` |"
            if presentation_spec and presentation_spec.id_prefixes
            else "| Presentation ID Prefixes |  |"
        ),
        f"| Has Presentation Sections | {'yes' if presentation_spec and presentation_spec.append_sections else 'no'} |",
        f"| Has Query Renderer | {'yes' if presentation_spec and presentation_spec.render_query else 'no'} |",
    ]
    return "\n".join(lines) + "\n", True
