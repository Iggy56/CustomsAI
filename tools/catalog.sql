-- CustomsAI – Catalog RPC functions
-- Deployare nel SQL Editor di Supabase prima di usare tools/scan_db.py.
--
-- Link: https://<tuo-progetto>.supabase.co/project/default/sql/new
-- Oppure via Supabase CLI: supabase db push
--
-- FUNZIONI:
--   list_public_tables()                         → tabelle pubbliche + stima righe
--   get_table_columns(p_table)                   → colonne con tipo e nullability
--   sample_column_values(p_table, p_col, p_limit) → valori distinti da una colonna
--
-- SICUREZZA:
--   - SECURITY DEFINER: le funzioni girano con i permessi del proprietario
--   - sample_column_values usa format() con %I (quote_ident) → no SQL injection
--   - sample_column_values valida il table_name contro pg_class prima di eseguire


-- ============================================================
-- 1. list_public_tables
--    Restituisce tutte le tabelle BASE nel schema public
--    con la stima del numero di righe da pg_class.
--    row_estimate = -1 se la tabella non è mai stata analizzata con ANALYZE.
-- ============================================================

drop function if exists list_public_tables();

create or replace function list_public_tables()
returns table(table_name text, row_estimate bigint)
language sql
security definer
stable
as $$
  select
    c.relname::text                 as table_name,
    greatest(c.reltuples, -1)::bigint as row_estimate
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public'
    and c.relkind = 'r'
  order by c.relname;
$$;


-- ============================================================
-- 2. get_table_columns
--    Restituisce le colonne di una tabella pubblica
--    con tipo PostgreSQL e flag nullable.
-- ============================================================

drop function if exists get_table_columns(text);

create or replace function get_table_columns(p_table text)
returns table(column_name text, data_type text, is_nullable bool)
language sql
security definer
stable
as $$
  select
    a.attname::text                                       as column_name,
    pg_catalog.format_type(a.atttypid, a.atttypmod)::text as data_type,
    not a.attnotnull                                      as is_nullable
  from pg_attribute a
  join pg_class     c on c.oid = a.attrelid
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname  = 'public'
    and c.relname  = p_table
    and a.attnum   > 0
    and not a.attisdropped
  order by a.attnum;
$$;


-- ============================================================
-- 3. sample_column_values
--    Restituisce p_limit valori distinti e non-null da una colonna.
--    Usa format() con %I (quote_ident) per prevenire SQL injection.
--    Valida table_name contro pg_class prima di eseguire la query.
-- ============================================================

drop function if exists sample_column_values(text, text, int);

create or replace function sample_column_values(
  p_table  text,
  p_column text,
  p_limit  int default 20
)
returns table(value text)
language plpgsql
security definer
stable
as $$
begin
  -- Validazione: la tabella deve esistere nello schema public
  if not exists (
    select 1
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = p_table
      and c.relkind = 'r'
  ) then
    raise exception 'Table % not found in public schema', p_table;
  end if;

  return query execute format(
    'select distinct %I::text from public.%I where %I is not null limit %s',
    p_column, p_table, p_column, p_limit
  );
end;
$$;
