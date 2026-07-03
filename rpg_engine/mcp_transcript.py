from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .mcp_adapter import MCP_TOOL_NAMES, PLAYER_MCP_TOOL_NAMES


FORBIDDEN_NORMAL_PLAY_TOOL_TOKENS = (
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
)

MESSAGE_ROLES = {"assistant", "player", "system"}


@dataclass(frozen=True)
class TranscriptFinding:
    code: str
    message: str
    step_index: int | None = None
    tool: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_mcp_tool_name(name: str) -> str:
    normalized = str(name).strip()
    prefix = "mcp_aigm_kernel_"
    if normalized.startswith(prefix):
        return normalized[len(prefix) :]
    return normalized


def validate_external_agent_transcript(transcript: dict[str, Any]) -> tuple[TranscriptFinding, ...]:
    """Validate a low-trust external AI transcript against the default play workflow."""
    kind = str(transcript.get("kind") or "normal_play")
    steps = transcript.get("steps") or ()
    if not isinstance(steps, list):
        return (
            TranscriptFinding(
                code="invalid_transcript",
                message="transcript steps must be a list",
            ),
        )

    findings: list[TranscriptFinding] = []
    normalized_steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(steps):
        step = raw_step if isinstance(raw_step, dict) else {"tool": raw_step}
        role = normalize_transcript_role(step.get("role"))
        tool = normalize_mcp_tool_name(str(step.get("tool") or "")) if ("tool" in step or not role) else ""
        normalized_steps.append({**step, "tool": tool, "role": role})
        if tool:
            findings.extend(validate_tool_name(tool, index=index, kind=kind))
        elif not role:
            findings.append(
                TranscriptFinding(
                    code="invalid_transcript_step",
                    message="transcript step must contain either a tool call or a message role",
                    step_index=index,
                )
            )

    tool_history: list[str] = []
    pending_clarification: dict[str, Any] | None = None
    awaiting_repreview: dict[str, Any] | None = None
    for index, step in enumerate(normalized_steps):
        tool = str(step["tool"])
        role = str(step.get("role") or "")
        if role == "assistant":
            if pending_clarification is not None and assistant_self_selected_clarification(
                step,
                pending_clarification.get("clarification"),
            ):
                findings.append(
                    TranscriptFinding(
                        code="clarification_self_selected",
                        message="external AI cannot select a clarification choice before the player answers",
                        step_index=index,
                    )
                )
                pending_clarification = None
                continue
            if pending_clarification is not None and assistant_asks_clarification(
                step,
                pending_clarification.get("clarification"),
            ):
                pending_clarification["asked"] = True
            continue
        if role == "player":
            if pending_clarification is not None:
                if pending_clarification.get("asked"):
                    awaiting_repreview = {
                        "player_message": str(step.get("message") or step.get("content") or ""),
                        "original_request": pending_clarification.get("request") or {},
                    }
                    pending_clarification = None
                else:
                    findings.append(
                        TranscriptFinding(
                            code="clarification_not_asked",
                            message="external AI must ask the structured clarification before accepting a player answer",
                            step_index=index,
                        )
                    )
                    pending_clarification = None
            continue
        if tool and awaiting_repreview is not None:
            if tool not in {"player_turn", "start_turn", "preview_from_text"}:
                code = (
                    "commit_after_clarification_answer_without_repreview"
                    if tool == "commit_turn"
                    else "tool_after_clarification_answer_without_repreview"
                )
                findings.append(
                    TranscriptFinding(
                        code=code,
                        message="external AI must re-run player_turn or a low-level fresh preview from the player clarification answer",
                        step_index=index,
                        tool=tool,
                    )
                )
                awaiting_repreview = None
            elif not repreview_is_fresh(step, awaiting_repreview):
                findings.append(
                    TranscriptFinding(
                        code="clarification_stale_repreview",
                        message="clarification answer must produce fresh user_text or a fresh external_intent_candidate",
                        step_index=index,
                        tool=tool,
                    )
                )
                awaiting_repreview = None
            else:
                awaiting_repreview = None
        if tool and pending_clarification is not None:
            if pending_clarification.get("asked"):
                code = "commit_after_clarification_without_player_answer" if tool == "commit_turn" else "tool_after_clarification_without_player_answer"
                message = (
                    "commit_turn cannot run after clarification until the player answers"
                    if tool == "commit_turn"
                    else "external AI cannot continue tool workflow after clarification until the player answers"
                )
            else:
                code = "clarification_not_asked"
                message = "external AI must ask the structured clarification before continuing tool workflow"
            findings.append(
                TranscriptFinding(
                    code=code,
                    message=message,
                    step_index=index,
                    tool=tool,
                )
            )
            pending_clarification = None
        if kind == "natural_language_player_action" and tool == "preview_action":
            if "player_turn" not in tool_history and "preview_from_text" not in tool_history and not bool(step.get("allow_low_level_preview")):
                findings.append(
                    TranscriptFinding(
                        code="natural_language_preview_action_first",
                        message="natural-language player action must route through player_turn before preview_action",
                        step_index=index,
                        tool=tool,
                    )
                )
        if tool == "commit_turn":
            findings.extend(validate_commit_prerequisites(normalized_steps, index))
        clarification = extract_step_clarification(step)
        if clarification is not None:
            pending_clarification = {
                "step_index": index,
                "tool": tool,
                "clarification": clarification,
                "request": step.get("request") if isinstance(step.get("request"), dict) else {},
                "asked": False,
            }
        if tool:
            tool_history.append(tool)

    if pending_clarification is not None and not pending_clarification.get("asked"):
        findings.append(
            TranscriptFinding(
                code="clarification_not_asked",
                message="external AI must ask the structured clarification returned by the kernel",
                step_index=int(pending_clarification.get("step_index") or 0),
                tool=str(pending_clarification.get("tool") or "") or None,
            )
        )
    if awaiting_repreview is not None:
        findings.append(
            TranscriptFinding(
                code="clarification_answer_without_repreview",
                message="external AI received a clarification answer but did not re-run player_turn or a low-level fresh preview",
            )
        )

    return tuple(findings)


def normalize_transcript_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    return role if role in MESSAGE_ROLES else ""


def validate_tool_name(tool: str, *, index: int, kind: str) -> tuple[TranscriptFinding, ...]:
    findings: list[TranscriptFinding] = []
    if kind in {"normal_play", "natural_language_player_action"}:
        lowered = tool.lower()
        forbidden_reported = False
        if any(token in lowered for token in FORBIDDEN_NORMAL_PLAY_TOOL_TOKENS):
            findings.append(
                TranscriptFinding(
                    code="forbidden_normal_play_tool",
                    message=f"{tool} is not allowed in normal external-agent play",
                    step_index=index,
                    tool=tool,
                )
            )
            forbidden_reported = True
        if tool not in PLAYER_MCP_TOOL_NAMES and not forbidden_reported:
            findings.append(
                TranscriptFinding(
                    code="forbidden_normal_play_tool",
                    message=f"{tool} is not exposed in the default player MCP surface",
                    step_index=index,
                    tool=tool,
                )
            )
    if tool not in MCP_TOOL_NAMES:
        findings.append(
            TranscriptFinding(
                code="unknown_default_mcp_tool",
                message=f"{tool} is not part of the default MCP tool surface",
                step_index=index,
                tool=tool,
            )
        )
    return tuple(findings)


def extract_step_clarification(step: dict[str, Any]) -> dict[str, Any] | None:
    result = step.get("result")
    if not isinstance(result, dict):
        return None
    direct = result.get("clarification")
    if is_clarification_object(direct):
        return direct
    interpretation = result.get("interpretation")
    if isinstance(interpretation, dict):
        nested = interpretation.get("clarification")
        if is_clarification_object(nested):
            return nested
        intent = interpretation.get("intent")
        if isinstance(intent, dict) and is_clarification_object(intent.get("clarification")):
            return intent["clarification"]
    intent = result.get("intent")
    if isinstance(intent, dict) and is_clarification_object(intent.get("clarification")):
        return intent["clarification"]
    return None


def is_clarification_object(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(value.get(key) for key in ("question", "choices", "reason", "missing_slots"))


def assistant_asks_clarification(step: dict[str, Any], clarification: Any) -> bool:
    if bool(step.get("asks_clarification")):
        return True
    if not isinstance(clarification, dict):
        return False
    question = str(clarification.get("question") or "").strip()
    message = str(step.get("message") or step.get("content") or "").strip()
    return bool(question and message and question in message)


def assistant_self_selected_clarification(step: dict[str, Any], clarification: Any = None) -> bool:
    if bool(step.get("self_selected_clarification")):
        return True
    if any(step.get(key) for key in ("selected_choice_id", "clarification_response", "selected_clarification_choice")):
        return True
    message = str(step.get("message") or step.get("content") or "").strip().lower()
    if not message:
        return False
    selection_markers = ("我选择", "我选", "替你选", "按外部判断", "按内部复核", "i choose", "i'll choose", "selecting")
    if not any(marker in message for marker in selection_markers):
        return False
    if not isinstance(clarification, dict):
        return True
    choices = clarification.get("choices") if isinstance(clarification.get("choices"), list) else []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        for key in ("id", "label"):
            value = str(choice.get(key) or "").strip().lower()
            if value and value in message:
                return True
    return False


def repreview_is_fresh(step: dict[str, Any], awaiting: dict[str, Any]) -> bool:
    request = step.get("request")
    if not isinstance(request, dict):
        return False
    original = awaiting.get("original_request") if isinstance(awaiting.get("original_request"), dict) else {}
    original_text = str(original.get("user_text") or "").strip()
    user_text = str(request.get("user_text") or "").strip()
    player_message = str(awaiting.get("player_message") or "").strip()
    original_candidate = original.get("external_intent_candidate")
    candidate = request.get("external_intent_candidate")
    if isinstance(candidate, dict) and candidate != original_candidate:
        return True
    if user_text and user_text != original_text:
        return text_overlaps(user_text, player_message)
    return False


def text_overlaps(candidate: str, answer: str) -> bool:
    if not answer:
        return True
    candidate_norm = normalize_compact_text(candidate)
    answer_norm = normalize_compact_text(answer)
    if not candidate_norm or not answer_norm:
        return False
    return candidate_norm in answer_norm or answer_norm in candidate_norm


def normalize_compact_text(value: str) -> str:
    return "".join(str(value or "").lower().split()).strip("。！？!?,，")


def validate_commit_prerequisites(steps: list[dict[str, Any]], commit_index: int) -> tuple[TranscriptFinding, ...]:
    commit_step = steps[commit_index]
    previous_tools = [str(step.get("tool") or "") for step in steps[:commit_index]]
    findings: list[TranscriptFinding] = []
    if "validate_delta" not in previous_tools:
        findings.append(
            TranscriptFinding(
                code="commit_without_validation",
                message="commit_turn requires validate_delta earlier in the transcript",
                step_index=commit_index,
                tool="commit_turn",
            )
        )
    if not any(tool in previous_tools for tool in ("preview_from_text", "preview_action")):
        findings.append(
            TranscriptFinding(
                code="commit_without_preview",
                message="commit_turn requires a preview step earlier in the transcript",
                step_index=commit_index,
                tool="commit_turn",
            )
        )

    last_preview = latest_previous_step(steps, commit_index, ("preview_from_text", "preview_action"))
    if last_preview and isinstance(last_preview.get("result"), dict):
        result = last_preview["result"]
        if result.get("ready_to_save") is False:
            findings.append(
                TranscriptFinding(
                    code="commit_after_unready_preview",
                    message="commit_turn cannot follow a preview with ready_to_save=false",
                    step_index=commit_index,
                    tool="commit_turn",
                )
            )

    last_validation = latest_previous_step(steps, commit_index, ("validate_delta",))
    if last_validation and isinstance(last_validation.get("result"), dict):
        result = last_validation["result"]
        if result.get("ok") is False:
            findings.append(
                TranscriptFinding(
                    code="commit_after_failed_validation",
                    message="commit_turn cannot follow validate_delta.ok=false",
                    step_index=commit_index,
                    tool="commit_turn",
                )
            )
    request = commit_step.get("request")
    if not isinstance(request, dict) or not isinstance(request.get("turn_proposal"), dict):
        findings.append(
            TranscriptFinding(
                code="commit_without_turn_proposal",
                message="commit_turn requires the approved TurnProposal returned by preview",
                step_index=commit_index,
                tool="commit_turn",
            )
        )
    return tuple(findings)


def latest_previous_step(
    steps: list[dict[str, Any]],
    end_index: int,
    tools: tuple[str, ...],
) -> dict[str, Any] | None:
    for step in reversed(steps[:end_index]):
        if step.get("tool") in tools:
            return step
    return None
