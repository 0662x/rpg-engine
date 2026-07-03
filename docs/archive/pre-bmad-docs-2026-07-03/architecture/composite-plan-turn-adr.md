# ADR: Composite Plan Turn Contract

Status: accepted design direction
Date: 2026-07-02

## Context

Players often describe multi-step actions in one sentence:

```text
先去 Old Bridge，找 Scout Ren 问情况，然后回来整理物资
```

The current engine correctly refuses to compress that into a single committed action. `composite` is a clarification / `confirm_plan` boundary, not an executable transaction. This ADR defines the long-term execution model.

## Decision

Add a future `plan_turn` contract instead of executing `IntentCandidate.plan` directly.

`plan_turn` produces a `CompositeTurnPlan`:

```text
CompositeTurnPlan
  plan_id
  source_user_text
  steps[]
  status: draft | needs_confirmation | active | completed | cancelled
```

Each step is an ordinary single-action contract:

```text
PlanStep
  step_id
  action
  slots
  bound_options
  preconditions
  dependencies
  preview_status
  proposal_id
  commit_policy
```

Rules:

- Every step must pass the same path as a normal action: intent/binder -> resolver preview -> validate_delta -> commit_turn.
- A plan preview may summarize later steps, but it must not reveal or materialize hidden facts from future steps.
- Only the current executable step may generate a `TurnProposal`.
- A failed step pauses the plan. The player can revise, skip, retry, or cancel.
- Partial completion is explicit. Completed steps remain committed; future steps can be replanned.
- Multi-step commit as one atomic transaction is not the default. It requires a separate transaction profile and explicit human confirmation.

## Consequences

This keeps the safety invariant:

```text
AI plan != saved fact
plan step preview != committed state
committed step == validated single-action delta
```

It also keeps resolver ownership simple. Existing single-action resolvers do not need to understand long-horizon plans; `plan_turn` coordinates them.

## Non-Goals

- Do not make `composite` directly saveable.
- Do not let the external AI choose hidden future outcomes.
- Do not merge unrelated step deltas into one hand-written mega-delta.
- Do not treat a plan confirmation as confirmation for every later uncertain step.

## Eval Requirements

Before enabling executable composite plans:

- Add golden paths for `plan_turn -> current step preview -> validate_delta -> commit_turn`.
- Add negative paths for stale step proposals, skipped validation, hidden information leakage, and failed mid-plan replanning.
- Add state assertions after each committed step.
