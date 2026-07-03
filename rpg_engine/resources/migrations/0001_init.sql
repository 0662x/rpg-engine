pragma foreign_keys = on;

create table if not exists meta (
  key text primary key,
  value text not null
);

create table if not exists turns (
  id text primary key,
  session_id text,
  user_text text not null,
  intent text not null,
  game_time_before text,
  game_time_after text,
  location_before text,
  location_after text,
  summary text,
  changed integer not null default 0,
  created_at text not null
);

create table if not exists events (
  id text primary key,
  turn_id text not null,
  game_time text not null,
  type text not null,
  title text not null,
  summary text not null,
  payload_json text not null,
  source text not null,
  created_at text not null,
  foreign key(turn_id) references turns(id)
);

create table if not exists entities (
  id text primary key,
  type text not null,
  name text not null,
  status text not null default 'active',
  visibility text not null default 'known',
  location_id text,
  owner_id text,
  summary text not null default '',
  details_json text not null default '{}',
  updated_turn_id text not null,
  updated_at text not null,
  foreign key(location_id) references entities(id),
  foreign key(owner_id) references entities(id),
  foreign key(updated_turn_id) references turns(id)
);

create table if not exists aliases (
  alias text not null,
  entity_id text not null,
  kind text not null default 'name',
  primary key(alias, entity_id),
  foreign key(entity_id) references entities(id) on delete cascade
);

create table if not exists facts (
  id text primary key,
  subject_id text not null,
  predicate text not null,
  object_entity_id text,
  object_value text,
  value_type text not null,
  confidence real not null default 1.0,
  valid_from_turn text not null,
  valid_to_turn text,
  source_event_id text not null,
  note text,
  foreign key(subject_id) references entities(id) on delete cascade,
  foreign key(object_entity_id) references entities(id),
  foreign key(valid_from_turn) references turns(id),
  foreign key(valid_to_turn) references turns(id),
  foreign key(source_event_id) references events(id)
);

create table if not exists characters (
  entity_id text primary key,
  species_id text,
  role text,
  attitude text,
  trust integer default 0,
  health_state text,
  stress_json text not null default '{}',
  consequences_json text not null default '[]',
  goals_json text not null default '[]',
  knowledge_json text not null default '{}',
  foreign key(entity_id) references entities(id) on delete cascade,
  foreign key(species_id) references entities(id)
);

create table if not exists items (
  entity_id text primary key,
  category text not null,
  quantity real,
  unit text,
  quality text,
  durability_current integer,
  durability_max integer,
  stackable integer not null default 0,
  equipped_slot text,
  properties_json text not null default '{}',
  foreign key(entity_id) references entities(id) on delete cascade
);

create table if not exists locations (
  entity_id text primary key,
  parent_id text,
  coord_x real,
  coord_y real,
  coord_z real,
  biome text,
  safety_level text,
  discovered_turn_id text,
  travel_minutes_from_home integer,
  description_short text,
  exits_json text not null default '[]',
  resources_json text not null default '[]',
  foreign key(entity_id) references entities(id) on delete cascade,
  foreign key(parent_id) references entities(id),
  foreign key(discovered_turn_id) references turns(id)
);

create table if not exists routes (
  id text primary key,
  from_location_id text not null,
  to_location_id text not null,
  travel_minutes integer not null,
  difficulty text not null,
  hazards_json text not null default '[]',
  requirements_json text not null default '[]',
  last_verified_turn_id text,
  foreign key(from_location_id) references entities(id),
  foreign key(to_location_id) references entities(id),
  foreign key(last_verified_turn_id) references turns(id)
);

create table if not exists crop_plots (
  entity_id text primary key,
  plot_no integer not null,
  crop_entity_id text not null,
  area_sqm real,
  planted_day integer,
  growth_stage integer,
  growth_stage_max integer,
  harvest_day_min integer,
  harvest_day_max integer,
  harvest_status text,
  water_status text,
  soil_status text,
  expected_yield text,
  notes text,
  foreign key(entity_id) references entities(id) on delete cascade,
  foreign key(crop_entity_id) references entities(id)
);

create table if not exists clocks (
  entity_id text primary key,
  clock_type text not null,
  segments_total integer not null,
  segments_filled integer not null default 0,
  visibility text not null default 'visible',
  trigger_when_full text not null,
  tick_rules_json text not null default '{}',
  last_ticked_turn_id text,
  foreign key(entity_id) references entities(id) on delete cascade,
  foreign key(last_ticked_turn_id) references turns(id)
);

create table if not exists rules (
  entity_id text primary key,
  category text not null,
  scope text not null,
  statement text not null,
  examples_json text not null default '[]',
  exceptions_json text not null default '[]',
  source text not null,
  locked integer not null default 0,
  foreign key(entity_id) references entities(id) on delete cascade
);

create table if not exists memory_summaries (
  id text primary key,
  kind text not null,
  subject_id text,
  title text not null,
  summary text not null,
  key_points_json text not null default '[]',
  source_event_ids_json text not null default '[]',
  source_turn_ids_json text not null default '[]',
  valid_from_turn text,
  valid_to_turn text,
  updated_at text not null,
  foreign key(subject_id) references entities(id),
  foreign key(valid_from_turn) references turns(id),
  foreign key(valid_to_turn) references turns(id)
);

create table if not exists context_runs (
  id text primary key,
  created_at text not null,
  user_text text not null,
  mode text not null,
  submode text,
  budget_limit integer not null,
  estimated_tokens integer not null,
  allow_proceed integer not null,
  confidence text not null,
  missing_required_json text not null,
  needs_confirmation_json text not null,
  output_json text not null
);

create table if not exists context_items (
  context_run_id text not null,
  item_id text not null,
  item_kind text not null,
  source text not null,
  reason text not null,
  priority integer not null,
  estimated_tokens integer,
  included integer not null,
  omitted_reason text,
  depth integer,
  primary key (context_run_id, item_id, source),
  foreign key(context_run_id) references context_runs(id) on delete cascade
);

create virtual table if not exists fts_index using fts5(
  entity_id unindexed,
  type unindexed,
  title,
  body,
  tags
);

create index if not exists idx_entities_type_status on entities(type, status);
create index if not exists idx_entities_location on entities(location_id) where location_id is not null;
create index if not exists idx_entities_owner on entities(owner_id) where owner_id is not null;
create index if not exists idx_aliases_alias on aliases(alias);
create index if not exists idx_facts_subject_predicate on facts(subject_id, predicate) where valid_to_turn is null;
create index if not exists idx_items_category on items(category);
create index if not exists idx_clocks_active on clocks(visibility, segments_filled, segments_total);
create index if not exists idx_memory_kind_subject on memory_summaries(kind, subject_id);
create index if not exists idx_context_runs_created on context_runs(created_at);
