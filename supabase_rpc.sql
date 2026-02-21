-- Run this in Supabase SQL Editor to enable vector search from the app.
-- Table public.chunks: text, metadata (jsonb), title, source_url, embedding (vector).
-- text-embedding-3-large = 3072 dimensions; adjust vector(N) if needed.

drop function if exists search_chunks(vector, integer);

create or replace function search_chunks(
  query_embedding vector(3072),
  match_count int
)
returns table (
  text text,
  metadata jsonb,
  title text,
  source_url text,
  similarity float
)
language sql stable
as $$
  select
    c.text,
    c.metadata,
    c.title,
    c.source_url,
    1 - (c.embedding <=> query_embedding) as similarity
  from public.chunks c
  where c.embedding is not null
  order by c.embedding <=> query_embedding
  limit match_count;
$$;
