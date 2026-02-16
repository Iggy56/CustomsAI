-- Run this in Supabase SQL Editor to enable vector search from the app.
-- Table public.chunks: text, article_ref, title, source_url, embedding (vector).
-- text-embedding-3-large = 3072 dimensions; adjust vector(N) if needed.

create or replace function search_chunks(
  query_embedding vector(3072),
  match_count int
)
returns table (
  text text,
  article_ref text,
  title text,
  source_url text
)
language sql stable
as $$
  select
    c.text,
    c.article_ref,
    c.title,
    c.source_url
  from public.chunks c
  where c.embedding is not null
  order by c.embedding <=> query_embedding
  limit match_count;
$$;
