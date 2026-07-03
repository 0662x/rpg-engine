alter table intent_preflight_cache
  add column fallback_backend text not null default '';

alter table intent_preflight_cache
  add column external_candidate_hash text not null default '';

alter table intent_preflight_cache
  add column rule_candidate_hash text not null default '';

create index if not exists idx_intent_preflight_cache_context
  on intent_preflight_cache(save_id, base_turn_id, source_user_text_hash, intent_context_id);
