-- APLICADA en producción el 2026-09-26 (migración "proteger_columnas_privilegiadas_profiles").
-- Probada antes y después con transacciones revertidas (rollback).
--
-- Problema (auditoría del 2026-09-26):
--   La política "Admin edita perfiles" en public.profiles tiene
--   USING (auth.uid() = id OR is_admin()) y NO tiene WITH_CHECK, y el rol
--   `authenticated` tiene UPDATE sobre todas las columnas. Resultado: cualquier
--   usuario logueado (incluso sin aprobar) puede hacer
--     PATCH /rest/v1/profiles?id=eq.<su_id>  {"is_admin": true}   o   {"approved": true}
--   y auto-aprobarse o convertirse en admin (ve clientes, pagos, precios y puede borrar).
--
-- Solución: un trigger BEFORE UPDATE que solo deja cambiar is_admin / approved
--   a un admin. Se mantiene la política actual, así el panel admin (que aprueba
--   usuarios como admin autenticado) y la edge function notify-new-user (service
--   role, auth.uid() es null) siguen funcionando sin cambios.
--
-- Probar primero en una rama de Supabase (create_branch), no directo en producción.

create or replace function public.protect_profile_privileged_columns()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  if (new.is_admin is distinct from old.is_admin
      or new.approved is distinct from old.approved)
     and auth.uid() is not null          -- service role / SQL editor: auth.uid() es null, se permite
     and not public.is_admin() then
    raise exception 'No autorizado para modificar is_admin ni approved';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_protect_profile_privileged_columns on public.profiles;
create trigger trg_protect_profile_privileged_columns
  before update on public.profiles
  for each row
  execute function public.protect_profile_privileged_columns();

-- Rollback:
--   drop trigger if exists trg_protect_profile_privileged_columns on public.profiles;
--   drop function if exists public.protect_profile_privileged_columns();
