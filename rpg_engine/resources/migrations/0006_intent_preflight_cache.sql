create table if not exists intent_preflight_cache (
  id text primary key,
  status text not null check(status in ('pending', 'ready', 'failed', 'expired', 'used', 'rejected')),
  platform text not null default '',
  session_key text not null default '',
  message_id text not null default '',
  save_id text not null,
  user_text text not null,
  source_user_text_hash text not null,
  base_turn_id text not null,
  context_hash text not null,
  intent_context_id text not null,
  provider text not null,
  model text not null,
  backend text not null,
  model_version text not null,
  schema_version text not null,
  task_version text not null,
  external_candidate_json text not null default '{}',
  rule_candidate_json text not null default '{}',
  internal_review_json text not null default '{}',
  helper_audit_json text not null default '{}',
  error text,
  created_at text not null,
  updated_at text not null,
  expires_at text not null,
  used_at text,
  rejected_reason text
);

create index if not exists idx_intent_preflight_cache_status_expires
  on intent_preflight_cache(status, expires_at);

create index if not exists idx_intent_preflight_cache_message
  on intent_preflight_cache(message_id, source_user_text_hash);
