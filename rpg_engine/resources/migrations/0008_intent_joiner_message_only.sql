alter table intent_preflight_cache
  add column identity_profile text not null default 'candidate_bound';

alter table intent_preflight_cache
  add column bypassed_at text;

alter table intent_preflight_cache
  add column late_ready_unused_at text;

create index if not exists idx_intent_preflight_cache_message_join
  on intent_preflight_cache(identity_profile, save_id, base_turn_id, platform, session_key, message_id, source_user_text_hash, status, expires_at);
