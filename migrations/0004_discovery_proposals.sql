create table if not exists discovery_states (
  id text primary key,
  subject_id text,
  palette_id text,
  kind text not null,
  stage text not null,
  visibility text not null,
  evidence_count integer not null default 0,
  confirmation_methods_json text not null default '[]',
  source_event_ids_json text not null default '[]',
  created_turn_id text,
  updated_turn_id text,
  notes text,
  created_at text not null,
  updated_at text not null
);

create index if not exists idx_discovery_palette on discovery_states(palette_id);
create index if not exists idx_discovery_subject on discovery_states(subject_id);
create index if not exists idx_discovery_stage on discovery_states(stage, visibility);

create table if not exists proposal_queue (
  id text primary key,
  kind text not null,
  status text not null,
  risk_level text not null,
  source_turn_id text,
  payload_json text not null,
  validation_json text not null default '{}',
  reviewed_by text,
  created_at text not null,
  updated_at text not null
);

create index if not exists idx_proposal_status on proposal_queue(status, risk_level, created_at);
