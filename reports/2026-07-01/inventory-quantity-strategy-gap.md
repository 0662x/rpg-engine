# Inventory Quantity Strategy Gap

Status: confirmed design and implementation gap
Date: 2026-07-01

## Intended Policy

The engine should not force every item into exact accounting. It needs two storage
modes:

- High-risk or key inventory must be exact. This includes combat supplies, toxins,
  powders, potions, rare materials, special ammunition, critical quest materials,
  and anything whose loss or use can change safety, combat outcome, production
  outcome, or plot state. These records need exact quantity, unit, source,
  confidence, location, and enough provenance to block stale or unsafe spending.
- Low-risk common consumables may be fuzzy. Routine food, water, common herbs,
  ordinary fuel, and bulk low-value materials may use structured bands such as
  `充足`, `够用`, `少量`, `紧张`, `耗尽`, or `未盘点`.

Fuzzy storage does not mean free text only. A fuzzy quantity must still be
structured enough for query, rendering, spending, audit prompts, and later
conversion into an exact count.

## Current Implementation

The current item model has `quantity` and `unit` as first-class fields in the
`items` table. Fuzzy inventory usually appears in `details.quantity_text` or
other free-form properties. That makes fuzzy quantities visible in notes, but not
reliably usable by the core engine.

Current consequences:

- Query and rendering paths treat numeric `quantity` as the reliable amount.
  Items with only fuzzy text can be shown as remarks but are not consistently
  treated as spendable stock.
- Consumption and decrement paths expect numeric quantities. They do not have a
  shared representation for fuzzy bands, confidence, or "needs inventory audit".
- Minimal inventory upserts can overwrite metadata if the caller sends only a new
  quantity and unit.
- Validation can notice some bad inventory states after commit, but several risky
  cases need pre-commit blocking instead.
- Campaign rules already say exact and fuzzy inventory can coexist, but the
  engine does not yet expose that distinction as a first-class contract.

## Evidence

The current save contains examples of both styles:

- Some ordinary resources have fuzzy or mixed quantity text, such as `少量`,
  `若干株`, or `约小半竹杯`.
- Some dangerous or high-value resources carry stronger reliability metadata,
  such as `inventory_reliability` and quantity audit fields.

The consumption probe recorded the practical failures:

- Natural-language spend commands are often routed as generic queries instead of
  inventory actions.
- Exact structured deltas can decrement inventory correctly.
- Narrated consumption without a matching inventory upsert can still commit.
- Negative quantities, stale writes, unit mismatches, and metadata-loss upserts
  need stronger guardrails.

See `current-save-consumption-probe-2026-07-01.md` for the detailed case table.

## Required Direction

Add a first-class quantity strategy to the engine:

- `exact`: numeric amount plus unit, required for high-risk and key inventory.
- `fuzzy`: structured band plus optional estimated numeric range, allowed for
  low-risk common consumables.
- `unknown` or `needs_audit`: explicit state for items that exist but cannot be
  safely spent until checked.

The strategy should be visible to:

- intent recognition
- query results
- context rendering
- preview generation
- delta validation
- commit-time inventory guards
- AI state audit

## Acceptance Checks

Future fixes should pass these checks:

- A high-risk item cannot be spent from fuzzy-only inventory.
- A high-risk item cannot lose source, confidence, location, or audit metadata
  during a quantity update.
- A low-risk fuzzy consumable can be queried naturally and rendered as a
  structured band.
- A low-risk fuzzy consumable can be reduced by a routine use, with deterministic
  band transitions or an audit prompt when the spend is too large.
- `耗尽` and `未盘点` are distinct states.
- Unit mismatch is blocked before commit.
- Negative inventory is blocked before commit.
- Stale inventory writes require an expected turn or revision guard.
- A narrated consumption event without a matching state operation is blocked or
  converted into a pending confirmation.

## Non-Goals

- Do not require exact accounting for every ordinary resource.
- Do not rely on narrative text alone as inventory state.
- Do not silently invent exact quantities from fuzzy descriptions.
- Do not allow fuzzy storage for resources whose use changes combat, poison,
  explosive, rare-crafting, or major plot outcomes.
