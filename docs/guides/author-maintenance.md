# AIGM Author Maintenance

Use this checklist when updating an existing Campaign Package.

## Safe Campaign Edits

- Fix typos in names and summaries.
- Add aliases.
- Add new locations, NPCs, items, rules, clocks, routes, random tables.
- Add smoke tests for newly declared capabilities.
- Improve prompts and response templates.

Run after edits:

```bash
aigm campaign doctor ./campaigns/my-story
aigm campaign test ./campaigns/my-story
```

## Be Careful With Existing Saves

Changing campaign source files does not automatically update existing Save Packages.

Be careful when changing:

- Entity IDs.
- Starting location.
- Player entity ID.
- Fields that may change during play, such as `location_id`, `owner_id`, inventory quantities, clock filled segments, or relationship trust.

If a player save already exists, use a controlled package upgrade, save patch, or gameplay commit path rather than hand-editing save files.

## Versioning

When publishing a revised campaign:

1. Update `package_version`.
2. Run `campaign doctor --strict`.
3. Run `campaign test`.
4. Generate an outline for review:

```bash
aigm campaign outline ./campaigns/my-story > RELEASE_OUTLINE.md
```
