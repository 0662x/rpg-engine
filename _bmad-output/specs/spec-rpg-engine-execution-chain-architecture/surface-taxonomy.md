# Surface Taxonomy

| Category | Intended callers | Allowed authority | Must not do |
| --- | --- | --- | --- |
| Player-safe | Ordinary CLI/MCP/platform player flows | Query, clarify, preview, create pending action, confirm existing pending action | Expose raw delta/proposal to players; commit without `player_confirm`; bypass session/platform identity |
| Trusted low-level | Developer, trusted GM, maintenance/admin profiles, Python API callers | Preflight, start/query/preview/validate, commit approved and validated proposal/delta | Be registered for ordinary player profile; become default gameplay UI; skip proposal/validation/write guards |
| Maintenance/admin | Operators running package, projection, migration, proposal, content, or repair commands | Maintenance writes, content/proposal workflows, repair and projection operations | Pretend to be ordinary play; write facts without backup/validation/approval/path/projection evidence where required |
| Platform sidecar | Platform message gateway | Gate platform/session/actor identity, forward to SaveManager, record metrics | Reimplement gameplay business logic; commit facts directly |
| Platform prewarm | Asynchronous platform prewarm worker | Create advisory `message_only` preflight records | Drive turns; become intent authority; cache permissions or proposals |
| Projection/outbox | Commit/post-commit services and repair tooling | Produce and repair read models, JSONL/event evidence, snapshots, cards, reports | Become fact authority; bypass SQLite validation; silently hide failed artifact state |

## Required Architecture Decision

Every future public command, MCP tool, platform endpoint, or runtime helper must declare one taxonomy category and name its write authority. If a surface spans categories, architecture must split the surface or document the gate that makes the category switch explicit.
