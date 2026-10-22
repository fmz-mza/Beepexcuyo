-- APLICADA en producción el 2026-10-22 (migración "user_sessions").
--
-- Por qué: `presence` guarda una sola fila por usuario (last_seen, se pisa en cada
-- heartbeat), así que no hay forma de saber cuánto tiempo estuvo alguien en el catálogo.
-- El admin mostraba "2 min" para casi todos porque lo estimaba como interacciones × 2.
--
-- `user_sessions` guarda una fila por visita. El catálogo llama a `touch_session()` en
-- cada heartbeat (cada 2 min, solo con la pestaña visible): si la última sesión del
-- usuario tuvo actividad hace menos de 5 min, la extiende; si no, abre una nueva.
-- Duración de una sesión = last_seen - started_at.
--
-- Rollback:
--   drop function if exists public.touch_session();
--   drop table if exists public.user_sessions;

create table if not exists public.user_sessions (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  started_at timestamptz not null default now(),
  last_seen timestamptz not null default now()
);

create index if not exists user_sessions_user_last_seen_idx
  on public.user_sessions (user_id, last_seen desc);
create index if not exists user_sessions_started_at_idx
  on public.user_sessions (started_at desc);

alter table public.user_sessions enable row level security;

drop policy if exists "Admin ve sesiones" on public.user_sessions;
create policy "Admin ve sesiones" on public.user_sessions
  for select using (auth.uid() = user_id or public.is_admin());

-- Sin políticas de insert/update: solo se escribe a través de touch_session().

create or replace function public.touch_session()
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  uid uuid := auth.uid();
  sid bigint;
begin
  if uid is null then return; end if;
  select id into sid from public.user_sessions
   where user_id = uid and last_seen > now() - interval '5 minutes'
   order by last_seen desc limit 1;
  if sid is null then
    insert into public.user_sessions (user_id) values (uid);
  else
    update public.user_sessions set last_seen = now() where id = sid;
  end if;
end;
$$;

revoke all on function public.touch_session() from public, anon;
grant execute on function public.touch_session() to authenticated;
