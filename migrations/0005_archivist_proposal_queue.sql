create table if not exists archivist_suggestions (
  id text primary key,
  turn_id text,
  ai_status text not null,
  suggestion_json text not null,
  audit_json text not null default '{}',
  status text not null default 'suggested',
  created_at text not null,
  updated_at text not null
);

create index if not exists idx_archivist_suggestions_turn on archivist_suggestions(turn_id, status, created_at);
