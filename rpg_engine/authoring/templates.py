from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..campaign import validate_campaign_config
from ..resource_paths import copy_packaged_example


CAMPAIGN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
TEMPLATE_ALIASES = {
    "blank": "blank_campaign",
    "blank-campaign": "blank_campaign",
    "blank_campaign": "blank_campaign",
    "small-cn": "small_cn_campaign",
    "small_cn": "small_cn_campaign",
    "small_cn_campaign": "small_cn_campaign",
    "v1-minimal-adventure": "v1_minimal_adventure",
    "v1_minimal_adventure": "v1_minimal_adventure",
}


@dataclass(frozen=True)
class AuthorTemplateResult:
    ok: bool
    template: str
    target_dir: str
    campaign_id: str = ""
    name: str = ""
    files_written: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "template": self.template,
            "target_dir": self.target_dir,
            "campaign_id": self.campaign_id,
            "name": self.name,
            "files_written": list(self.files_written),
            "next_steps": list(self.next_steps),
            "errors": list(self.errors),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def normalize_template_name(template: str) -> str:
    key = template.strip().lower().replace(" ", "-")
    return TEMPLATE_ALIASES.get(key, key.replace("-", "_"))


def infer_campaign_id(target: Path) -> str:
    candidate = target.name.strip().lower().replace(" ", "-")
    candidate = re.sub(r"[^a-z0-9_.-]+", "-", candidate).strip("-._")
    return candidate or "new-campaign"


def create_campaign_from_template(
    template: str,
    target: str | Path,
    *,
    campaign_id: str | None = None,
    name: str | None = None,
    force: bool = False,
) -> AuthorTemplateResult:
    template_name = normalize_template_name(template)
    target_path = Path(target).expanduser()
    effective_id = campaign_id or infer_campaign_id(target_path)
    if not CAMPAIGN_ID_PATTERN.match(effective_id):
        return AuthorTemplateResult(
            ok=False,
            template=template_name,
            target_dir=str(target_path),
            campaign_id=effective_id,
            errors=(f"invalid campaign id: {effective_id}",),
        )
    try:
        copied = copy_packaged_example(template_name, target_path, force=force)
        campaign_path = copied / "campaign.yaml"
        data = yaml.safe_load(campaign_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("campaign.yaml must be object")
        data["id"] = effective_id
        if name:
            data["name"] = name
        final_name = str(data.get("name") or effective_id)
        config_errors = validate_campaign_config(data)
        if config_errors:
            raise ValueError("Invalid generated campaign.yaml: " + "; ".join(config_errors))
        campaign_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        rewrite_author_notes(copied, effective_id, final_name)
        files = tuple(sorted(str(path.relative_to(copied)) for path in copied.rglob("*") if path.is_file()))
        return AuthorTemplateResult(
            ok=True,
            template=template_name,
            target_dir=str(copied),
            campaign_id=effective_id,
            name=final_name,
            files_written=files,
            next_steps=(
                f"Edit {copied / 'AUTHOR_NOTES.md'} with your world, protagonist and starting scene.",
                f"Run: aigm campaign doctor {copied}",
                f"Run: aigm campaign test {copied}",
                f"Then create a playtest save: aigm save init {copied} <save-dir>",
            ),
        )
    except Exception as exc:
        return AuthorTemplateResult(
            ok=False,
            template=template_name,
            target_dir=str(target_path),
            campaign_id=effective_id,
            errors=(str(exc),),
        )


def rewrite_author_notes(root: Path, campaign_id: str, name: str) -> None:
    replacements = {
        "{{CAMPAIGN_ID}}": campaign_id,
        "{{CAMPAIGN_NAME}}": name,
    }
    for relative in ("AUTHOR_NOTES.md", "prompts/gm.md"):
        path = root / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for source, replacement in replacements.items():
            text = text.replace(source, replacement)
        path.write_text(text, encoding="utf-8")


def render_template_result(result: AuthorTemplateResult) -> str:
    if not result.ok:
        lines = ["FAILED", f"- template: `{result.template}`", f"- target: `{result.target_dir}`"]
        lines.extend(f"- error: {item}" for item in result.errors)
        return "\n".join(lines).rstrip() + "\n"
    lines = [
        "# Campaign New",
        "",
        "- status: `OK`",
        f"- template: `{result.template}`",
        f"- campaign_id: `{result.campaign_id}`",
        f"- name: `{result.name}`",
        f"- target: `{result.target_dir}`",
        f"- files: `{len(result.files_written)}`",
        "",
        "## Next Steps",
        "",
    ]
    lines.extend(f"{index}. {step}" for index, step in enumerate(result.next_steps, start=1))
    return "\n".join(lines).rstrip() + "\n"
