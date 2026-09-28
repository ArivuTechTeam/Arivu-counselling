-- Release A1 read-only database capacity report.
-- Run against staging after the seed/load test and save the result with the
-- API JSON report. This transaction cannot write application data.

begin transaction read only;

select
  current_database() as database_name,
  now() as observed_at,
  pg_size_pretty(pg_database_size(current_database())) as database_size,
  (select count(*) from pg_stat_activity where datname = current_database()) as open_connections,
  (select count(*) from pg_stat_activity where datname = current_database() and state = 'active') as active_connections;

select
  relname as table_name,
  n_live_tup as estimated_live_rows,
  n_dead_tup as estimated_dead_rows,
  last_analyze,
  last_autoanalyze,
  last_vacuum,
  last_autovacuum
from pg_stat_user_tables
order by n_live_tup desc, relname;

select
  table_name,
  pg_size_pretty(table_bytes) as table_size,
  pg_size_pretty(index_bytes) as index_size,
  pg_size_pretty(total_bytes) as total_size
from (
  select
    relname as table_name,
    pg_relation_size(relid) as table_bytes,
    pg_indexes_size(relid) as index_bytes,
    pg_total_relation_size(relid) as total_bytes
  from pg_catalog.pg_statio_user_tables
) sizes
order by total_bytes desc, table_name;

select
  schemaname,
  relname as table_name,
  indexrelname as index_name,
  idx_scan,
  pg_size_pretty(pg_relation_size(indexrelid)) as index_size
from pg_stat_user_indexes
order by pg_relation_size(indexrelid) desc, indexrelname;

select
  status,
  count(*) as jobs,
  min(created_at) as oldest_created_at,
  max(extract(epoch from (now() - created_at))) filter (where status = 'queued') as oldest_queue_age_seconds
from public.faculty_jobs
group by status
order by status;

commit;
