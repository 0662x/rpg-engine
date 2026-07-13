from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .actions import ActionResolverRegistry
from .intent_router import TurnContract, template_for, turn_contract_from_dict

QUERY_HINTS = ["| 字段 |", "| 项目 |", "###", "##"]


@dataclass(frozen=True)
class ResponseLintResult:
    ok: bool
    errors: list[str]
    warnings: list[str]

    def render(self) -> str:
        lines = ["OK" if self.ok else "FAILED"]
        if self.errors:
            lines.append("")
            lines.append("## Errors")
            lines.extend(f"- {item}" for item in self.errors)
        if self.warnings:
            lines.append("")
            lines.append("## Warnings")
            lines.extend(f"- {item}" for item in self.warnings)
        return "\n".join(lines) + "\n"


def load_response_text(path: str | Path | None, text: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return text or ""


def lint_response(
    response_text: str,
    *,
    turn_contract: TurnContract,
    strict: bool = False,
    registry: ActionResolverRegistry | None = None,
) -> ResponseLintResult:
    errors: list[str] = []
    warnings: list[str] = []
    text = response_text.strip()
    if not text:
        return ResponseLintResult(False, ["response is empty"], [])

    required_headings = list(turn_contract.response_headings)
    if not required_headings:
        errors.append("turn contract response_headings is empty")
    if not turn_contract.required_template:
        errors.append("turn contract required_template is empty")
    if not turn_contract.validation_profile:
        errors.append("turn contract validation_profile is empty")
    expected_template = template_for(
        turn_contract.intent.mode,
        turn_contract.intent.submode,
        registry=registry,
    )
    if turn_contract.required_template != expected_template:
        errors.append(
            "turn contract required_template mismatch: "
            f"{turn_contract.required_template} != {expected_template}"
        )
    expected_profile = expected_validation_profile(turn_contract.intent.mode)
    if turn_contract.validation_profile != expected_profile:
        errors.append(
            "turn contract validation_profile mismatch: "
            f"{turn_contract.validation_profile} != {expected_profile}"
        )
    if turn_contract.must_save and "状态变化" not in text:
        errors.append("turn contract requires save, but response lacks 状态变化 section")

    headings = markdown_headings(text)
    mode = turn_contract.intent.mode
    submode = turn_contract.intent.submode
    if mode == "action":
        validate_action_response(
            errors,
            warnings,
            text,
            headings,
            submode=submode or "",
            strict=strict,
            required_headings=required_headings,
        )
    elif mode == "query":
        validate_query_response(errors, warnings, text, headings, strict=strict, required_headings=required_headings)
    else:
        validate_required_headings(errors, headings, required_headings)

    if "```json" in text and not json_blocks_parse(text):
        errors.append("response contains invalid fenced JSON")
    if contains_forbidden_save_claim(text):
        warnings.append("response claims saved/已保存; verify play commit with TurnProposal actually ran")
    return ResponseLintResult(not errors, errors, warnings)


def validate_action_response(
    errors: list[str],
    warnings: list[str],
    text: str,
    headings: list[str],
    *,
    submode: str,
    strict: bool,
    required_headings: list[str],
) -> None:
    validate_required_headings(errors, headings, required_headings)
    if "你的状态" in headings and "| 项目 |" not in text:
        errors.append("你的状态 section should contain a structured table")
    if "状态变化" in headings and "| 类型 |" not in text and "| 项目 |" not in text:
        errors.append("状态变化 section should contain a structured table")
    if ("可选行动" in headings or "后续行动" in headings) and "| # |" not in text:
        errors.append("follow-up action section should contain numbered options table")
    if submode == "combat" and not any(term in text for term in ["弹药", "距离", "目标", "遮蔽"]):
        warnings.append("combat response should mention ammo/distance/target context")
    if submode == "gather" and not any(term in text for term in ["收获", "采集", "容器", "工具"]):
        warnings.append("gather response should mention harvest/gather result and tools/container")
    if strict and "状态变化" in headings and "无" not in section_text(text, "状态变化") and "play commit" not in text:
        warnings.append("strict mode: state-changing response should mention that play validate-delta/play commit with TurnProposal was or must be run")


def validate_query_response(
    errors: list[str],
    warnings: list[str],
    text: str,
    headings: list[str],
    *,
    strict: bool,
    required_headings: list[str],
) -> None:
    if required_headings:
        validate_required_headings(errors, headings, required_headings)
    elif not headings:
        errors.append("query response should use markdown headings")
    if not any(hint in text for hint in QUERY_HINTS):
        errors.append("query response should be structured with a table or subsections")
    if strict and "ID" not in text:
        warnings.append("strict mode: entity query should include an ID when answering about a known entity")


def expected_validation_profile(mode: str) -> str:
    if mode == "query":
        return "preview_only"
    if mode == "maintenance":
        return "maintenance_commit"
    return "player_turn_commit"


def validate_required_headings(errors: list[str], headings: list[str], required_headings: list[str]) -> None:
    for heading in required_headings:
        if heading not in headings:
            errors.append(f"missing required heading: {heading}")


def load_turn_contract_from_context(context_json: dict[str, Any] | None) -> TurnContract:
    if not isinstance(context_json, dict):
        raise ValueError("context_json must be an object with request.turn_contract")
    top_level = context_json.get("turn_contract")
    if isinstance(top_level, dict):
        return turn_contract_from_dict(top_level)
    request = context_json.get("request")
    if isinstance(request, dict) and isinstance(request.get("turn_contract"), dict):
        return turn_contract_from_dict(request["turn_contract"])
    raise ValueError("context_json is missing request.turn_contract")


def markdown_headings(text: str) -> list[str]:
    result: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            result.append(match.group(1).strip())
    return result


def section_text(text: str, heading: str) -> str:
    pattern = re.compile(rf"^\s{{0,3}}#{{1,6}}\s+{re.escape(heading)}\s*$", re.M)
    match = pattern.search(text)
    if not match:
        return ""
    next_heading = re.search(r"^\s{0,3}#{1,6}\s+.+?$", text[match.end() :], re.M)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end() : end].strip()


def json_blocks_parse(text: str) -> bool:
    blocks = re.findall(r"```json\s*(.*?)\s*```", text, flags=re.S)
    for block in blocks:
        try:
            json.loads(block)
        except json.JSONDecodeError:
            return False
    return True


def contains_forbidden_save_claim(text: str) -> bool:
    return any(term in text for term in ["已保存", "保存完成", "已经写入存档"])
