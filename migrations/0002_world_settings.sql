create table if not exists world_settings (
  entity_id text primary key,
  category text not null,
  scope text not null default 'world',
  visibility text not null default 'known',
  priority integer not null default 50,
  summary text not null default '',
  content_json text not null default '{}',
  linked_rules_json text not null default '[]',
  linked_clocks_json text not null default '[]',
  linked_entities_json text not null default '[]',
  applies_when_json text not null default '{}',
  source text not null default 'content',
  foreign key(entity_id) references entities(id) on delete cascade
);

create index if not exists idx_world_settings_category
on world_settings(category, visibility, priority);
