alter table memory_summaries add column summary_type text not null default 'deterministic';
alter table memory_summaries add column visibility_mode text not null default 'player';
alter table memory_summaries add column freshness_status text not null default 'fresh';
alter table memory_summaries add column freshness_turn_id text;
alter table memory_summaries add column stale_reason text not null default '';
alter table memory_summaries add column freshness_evidence_json text not null default '{}';
alter table memory_summaries add column derived_authority_json text not null default '{"authority":"derived_context","fact_authority":false}';
