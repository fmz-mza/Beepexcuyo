-- APLICADA en producción el 2026-10-22 (migración "account_movements_privada").
--
-- Nota: el linter de Supabase marca `public.account_movements` como "Security Definer View".
-- Es a propósito: la vista corre con permisos de su dueño para poder leer el schema privado,
-- y el filtro por rol (is_admin / is_seller / cliente propio) está dentro de la vista.
--
-- Por qué: `account_movements` (ventas POS cerradas + pagos, la base de la cuenta corriente)
-- es una VISTA MATERIALIZADA, y a las vistas materializadas no se les aplica RLS. Tenía
-- GRANT SELECT para `authenticated`, así que cualquier usuario logueado —el registro es
-- abierto, ni siquiera hacía falta estar aprobado— podía leer los movimientos de todos los
-- clientes en /rest/v1/account_movements. Además `saldo_cliente(uuid)` (SECURITY DEFINER)
-- devolvía el saldo de cualquier cliente sin chequear quién preguntaba, y se podía
-- llamar hasta sin sesión (anon).
--
-- Qué hace:
--   * Mueve la vista materializada al schema `private` (no expuesto por la API).
--   * Crea en su lugar una vista normal `public.account_movements` con el mismo nombre y
--     columnas, filtrada: admin y vendedores ven todo (el POS necesita el saldo completo de
--     cualquier cliente), un cliente solo ve sus propios movimientos. Así admin, POS y
--     catálogo siguen funcionando sin cambios en el frontend.
--   * `refresh_account_movements()` (trigger de pos_orders/payments) pasa a SECURITY DEFINER
--     y refresca `private.account_movements`.
--   * `saldo_cliente` y `get_my_saldo` leen `private.account_movements`; `saldo_cliente`
--     ahora exige admin, vendedor o que el cliente sea del propio usuario.
--
-- Rollback:
--   drop view if exists public.account_movements;
--   alter materialized view private.account_movements set schema public;
--   grant select on public.account_movements to authenticated;
--   -- y recrear refresh_account_movements / saldo_cliente / get_my_saldo apuntando a
--   -- public.account_movements como estaban antes (sin el chequeo de rol en saldo_cliente).

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

alter materialized view public.account_movements set schema private;
revoke all on private.account_movements from public, anon, authenticated;

create view public.account_movements with (security_barrier = true) as
  select m.client_id, m.ref_id, m.tipo, m.monto, m.fecha, m.referencia
    from private.account_movements m
   where public.is_admin()
      or public.is_seller()
      or m.client_id in (select c.id from public.clients c where c.profile_id = auth.uid());

revoke all on public.account_movements from public, anon;
grant select on public.account_movements to authenticated;

create or replace function public.refresh_account_movements()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  refresh materialized view concurrently private.account_movements;
  return null;
end;
$$;

create or replace function public.saldo_cliente(p_client_id uuid)
returns numeric
language sql
stable security definer
set search_path = public, pg_temp
as $$
  select coalesce(sum(m.monto), 0)
    from private.account_movements m
   where m.client_id = p_client_id
     and (public.is_admin() or public.is_seller()
          or exists (select 1 from public.clients c where c.id = p_client_id and c.profile_id = auth.uid()));
$$;

create or replace function public.get_my_saldo()
returns numeric
language sql
stable security definer
set search_path = public, pg_temp
as $$
  select coalesce(sum(monto), 0)
    from private.account_movements
   where client_id = (select id from public.clients where profile_id = auth.uid() limit 1);
$$;

revoke execute on function public.saldo_cliente(uuid) from public, anon;
grant execute on function public.saldo_cliente(uuid) to authenticated;
revoke execute on function public.get_my_saldo() from public, anon;
grant execute on function public.get_my_saldo() to authenticated;
