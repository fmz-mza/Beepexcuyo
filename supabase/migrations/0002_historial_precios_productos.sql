-- APLICADA en producción el 2026-09-30 (migración "historial_precios_productos").
-- Probada antes con una transacción revertida (rollback): 4 casos (sin cambios,
-- solo cambia pvp, cambian los dos, cambia una columna no relacionada) dieron el
-- resultado esperado antes de aplicarla.
--
-- Por qué: sync.py solo loguea (print/Discord) cuando cambia `precio_pesos`, y
-- para varios SKUs (los que no entran en ninguna regla especial de precio,
-- ver README de sync.py en CLAUDE.md) `precio_pesos` se calcula directo desde
-- `precioBase` de la API, sin mirar `pvp` en ningún momento. Un cambio de PVP
-- del proveedor que no toque `precioBase` se pisaba en silencio cada hora sin
-- dejar rastro de cuándo pasó ni por qué (caso real: SKU 11307, sep/2026).
--
-- Esta migración agrega un historial a nivel de base de datos, que registra
-- CUALQUIER cambio real de precio_pesos o precio_pvp en productos, sin
-- depender de que sync.py (o cualquier otro script futuro) se acuerde de
-- loguearlo. Se dispara con cualquier UPDATE real (vía service_role, como
-- hace sync.py), no solo desde el script actual.

create table public.productos_historial_precios (
  id bigint generated always as identity primary key,
  codigo text not null references public.productos(codigo) on delete cascade,
  campo text not null check (campo in ('precio_pesos','precio_pvp')),
  valor_anterior numeric,
  valor_nuevo numeric,
  changed_at timestamptz not null default now()
);

create index productos_historial_precios_codigo_idx
  on public.productos_historial_precios (codigo, changed_at desc);

alter table public.productos_historial_precios enable row level security;

-- Los precios en sí son públicos (tabla productos), pero el historial de
-- cambios queda restringido a admins.
create policy "Admin ve historial de precios"
  on public.productos_historial_precios
  for select
  using (is_admin());

create or replace function public.log_cambio_precio_producto()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $f$
begin
  if new.precio_pesos is distinct from old.precio_pesos then
    insert into public.productos_historial_precios (codigo, campo, valor_anterior, valor_nuevo)
    values (new.codigo, 'precio_pesos', old.precio_pesos, new.precio_pesos);
  end if;
  if new.precio_pvp is distinct from old.precio_pvp then
    insert into public.productos_historial_precios (codigo, campo, valor_anterior, valor_nuevo)
    values (new.codigo, 'precio_pvp', old.precio_pvp, new.precio_pvp);
  end if;
  return new;
end;
$f$;

create trigger trg_log_cambio_precio_producto
  after update on public.productos
  for each row
  execute function public.log_cambio_precio_producto();

-- Rollback:
--   drop trigger if exists trg_log_cambio_precio_producto on public.productos;
--   drop function if exists public.log_cambio_precio_producto();
--   drop table if exists public.productos_historial_precios;

-- Ejemplo de consulta para responder "¿cuándo cambió el precio del SKU X y a qué?":
--   select campo, valor_anterior, valor_nuevo, changed_at
--   from public.productos_historial_precios
--   where codigo = '11307'
--   order by changed_at desc;
