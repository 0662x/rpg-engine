from __future__ import annotations

from typing import Any


def render_required_procedure(state: Any) -> str:
    lines = [
        "### 本轮流程",
        "",
        f"- 模式：`{state.mode}:{state.submode}`",
        f"- 查询不推进时间：{'否，本轮可能推进' if state.will_advance_time else '是'}",
        f"- 必须保存：{'是' if state.must_save else '否'}",
    ]
    if state.requires_preview:
        lines.append(f"- 正式结算前优先运行：`python3 -m rpg_engine play preview <save> {state.submode} ...`")
    if state.must_save:
        lines.append("- 行动结算后必须使用 `play validate-delta` 校验，再用 `play commit --proposal-json <turn_proposal.json>` 保存，并运行 `play health`。")
    else:
        lines.append("- 查询类回复只返回结构化信息，不写入存档。")
    if state.missing_required:
        lines.extend(["", "#### 缺失关键项"])
        for item in state.missing_required:
            lines.append(f"- {item}")
    if state.needs_user_confirmation:
        lines.extend(["", "#### 需要玩家确认"])
        for item in state.needs_user_confirmation:
            lines.append(f"- {item}")
    return "\n".join(lines)


def render_template_text(state: Any) -> str:
    path = state.campaign.root / "content" / "templates" / state.required_template
    if not path.exists():
        return ""
    return trim_text(path.read_text(encoding="utf-8"), 1000)


def trim_text(text: str, limit_chars: int) -> str:
    if len(text) <= limit_chars:
        return text
    return text[: max(0, limit_chars - 20)].rstrip() + "\n...（已按上下文预算截断）"
