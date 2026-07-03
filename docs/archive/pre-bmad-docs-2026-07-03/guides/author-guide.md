# AIGM Author Guide

This guide is for campaign authors. You do not need to write Python or understand SQLite, MCP, delta files, projections, or migrations to create a playable Campaign Package.

## Start A New Campaign

```bash
aigm campaign new ./campaigns/my-story --template small-cn
aigm campaign doctor ./campaigns/my-story
aigm campaign outline ./campaigns/my-story
aigm campaign test ./campaigns/my-story
```

Then create a playtest save:

```bash
aigm save init ./campaigns/my-story ./saves/my-story-test
aigm play query ./saves/my-story-test scene
```

## What To Edit

Author files:

```text
campaign.yaml
AUTHOR_NOTES.md
AUTHOR_AI_PROMPT.md
content/**
prompts/**
templates/**
tests/**
docs/**
```

Do not edit these as campaign content:

```text
data/**
cards/**
snapshots/**
memory/**
reports/**
backups/**
save.yaml
package-lock.json
```

Those are save, generated, or operational files.

## Campaign vs Save

Campaign Package defines the initial world, rules, NPCs, locations, random tables, GM style, and smoke tests.

Save Package stores one playthrough's current facts. Player progress belongs in a save, not in the campaign source files.

## Recommended Content Files

Small campaigns can use:

```text
content/locations.yaml
content/characters.yaml
content/items.yaml
content/projects.yaml
content/references.yaml
content/relationships.yaml
content/rules.yaml
content/clocks.yaml
content/routes.yaml
content/world_settings.yaml
content/random_tables.yaml
```

Each content file should stay easy to review. If one YAML file grows past hundreds of lines, split by region or type.

## Basic Records

Location:

```yaml
entities:
  - id: loc:camp
    type: location
    name: Camp
    visibility: known
    summary: A safe starting camp.
    aliases: [camp, start]
    location:
      safety_level: guarded
      description_short: A small camp beside the road.
      exits: [Old Bridge]
      resources: [clean water]
```

Character:

```yaml
entities:
  - id: npc:mira
    type: character
    name: Mira
    visibility: known
    location_id: loc:camp
    summary: A cautious guide.
    aliases: [guide]
    character:
      role: guide
      attitude: cautious
      health_state: healthy
```

Rule:

```yaml
rules:
  - id: rule:player-agency
    statement: Do not decide major player intent without confirmation.
```

Clock:

```yaml
clocks:
  - id: clock:storm
    name: Storm
    segments_total: 6
    segments_filled: 0
    visibility: visible
    trigger_when_full: Travel becomes dangerous.
```

Random table:

```yaml
random_tables:
  - id: table:road-detail
    name: Road Detail
    entries:
      - result: Wind moves through the broken sign.
        weight: 1
```

## Visibility

- `known`: player-visible fact.
- `hinted`: clue or partial fact.
- `hidden`: GM-only fact; do not put hidden spoilers in known summaries.

## Using AI

Copy [`../prompts/author-ai-prompt.md`](../../../prompts/author-ai-prompt.md) into your AI assistant together with campaign-local `AUTHOR_NOTES.md` and any doctor JSON output.

Use this repair loop:

```bash
aigm campaign doctor ./campaigns/my-story --format json
```

Give the JSON to your AI and ask it to fix errors first, then warnings.

## Before Sharing

Run:

```bash
aigm campaign doctor ./campaigns/my-story --strict
aigm campaign test ./campaigns/my-story
```

If both pass, the campaign is ready for playtesting or sharing.
