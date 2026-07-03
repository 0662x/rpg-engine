from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable


ContextStepFn = Callable[[Any], None]
RenderResultFn = Callable[[Any], Any]
AuditResultFn = Callable[[Any, Any, str | None], str]


@dataclass(frozen=True)
class ContextPipelineStep:
    name: str
    run: ContextStepFn


@dataclass(frozen=True)
class ContextPipeline:
    steps: Iterable[ContextPipelineStep]
    render_result: RenderResultFn
    audit_result: AuditResultFn | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))

    def run(
        self,
        state: Any,
        *,
        audit_context: bool = False,
        audit_context_run_id: str | None = None,
    ) -> Any:
        for step in self.steps:
            step.run(state)

        result = self.render_result(state)
        if not audit_context:
            return result

        if self.audit_result is None:
            raise RuntimeError("context pipeline audit requested without an audit_result hook")

        request = getattr(result, "request", None)
        if not isinstance(request, dict):
            raise TypeError("context pipeline result must expose a request dict for audit metadata")

        audit_id = self.audit_result(state, result, audit_context_run_id)
        request["context_audit_run_id"] = audit_id
        return result

