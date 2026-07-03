alter table turns add column command_id text;
alter table turns add column command_hash text;
alter table turns add column expected_turn_id text;
alter table schema_migrations add column checksum text;

create unique index if not exists idx_turns_command_id
on turns(command_id)
where command_id is not null;

create table if not exists outbox (
  id text primary key,
  topic text not null,
  payload_json text not null,
  status text not null default 'pending',
  attempts integer not null default 0,
  created_at text not null,
  processed_at text,
  last_error text
);

create index if not exists idx_outbox_status_created
on outbox(status, created_at);

create table if not exists projection_state (
  name text primary key,
  version integer not null default 1,
  last_turn_id text,
  status text not null default 'clean',
  updated_at text not null,
  last_error text,
  foreign key(last_turn_id) references turns(id)
);

insert into meta(key, value) values('save_schema_version', '0.3')
on conflict(key) do update set value=excluded.value;

insert into meta(key, value) values('content_schema_version', '1')
on conflict(key) do update set value=excluded.value;

insert into meta(key, value) values('projection_schema_version', '1')
on conflict(key) do update set value=excluded.value;

insert into meta(key, value) values('schema_version', '0.3')
on conflict(key) do update set value=excluded.value;
