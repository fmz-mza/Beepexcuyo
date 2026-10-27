-- APLICADA en producción el 2026-10-26 (migración "orders_precios_desactualizados").
--
-- Por qué: una pestaña del catálogo abierta desde antes de una publicación sigue corriendo el
-- código viejo, que no actualiza precios ni puede forzarse a recargar. Si el cliente envía el
-- pedido desde ahí, va con los precios del día en que abrió la página. El mensaje de WhatsApp
-- no se puede corregir, pero el pedido igual se guarda en `orders`: este trigger compara cada
-- ítem con el precio actual de `productos` al momento de guardarlo y deja la diferencia en
-- `orders.precios_desactualizados`, que el admin muestra como ⚠️ en "Todos los pedidos".
-- Funciona con cualquier versión del catálogo, vieja o nueva.
--
-- Formato: null si todo coincide; si no, un array de
--   { sku, nombre, enviado, actual }  (precios SIN IVA; actual = null si el SKU ya no existe)
--
-- Nota: el catálogo fija el SKU 11573 en $59.999 aunque `productos` diga otra cosa (override en
-- loadProducts/fetchCatalog de beepex-cuyo.html); acá se replica para no marcar esos pedidos.
--
-- Rollback:
--   drop trigger if exists trg_orders_precios_desactualizados on public.orders;
--   drop function if exists public.marcar_precios_desactualizados();
--   alter table public.orders drop column if exists precios_desactualizados;

alter table public.orders add column if not exists precios_desactualizados jsonb;

create or replace function public.marcar_precios_desactualizados()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  dif jsonb;
begin
  select jsonb_agg(jsonb_build_object(
           'sku', x.sku, 'nombre', x.nombre, 'enviado', x.enviado, 'actual', x.actual))
    into dif
    from (
      select it->>'sku' as sku,
             it->>'name' as nombre,
             round(coalesce(
               (it->>'precio_sin_iva')::numeric,
               case when coalesce((it->>'include_iva')::boolean, false)
                    then (it->>'price')::numeric / (1 + coalesce((it->>'iva_percent')::numeric, 0) / 100)
                    else (it->>'price')::numeric end)) as enviado,
             case when it->>'sku' = '11573' then 59999 else p.precio_pesos::numeric end as actual
        from jsonb_array_elements(coalesce(new.items, '[]'::jsonb)) it
        left join public.productos p on p.codigo = it->>'sku'
    ) x
   where x.actual is null or abs(x.enviado - x.actual) >= 1;
  new.precios_desactualizados := dif;
  return new;
exception when others then
  -- Nunca bloquear un pedido por este control
  new.precios_desactualizados := null;
  return new;
end;
$$;

revoke execute on function public.marcar_precios_desactualizados() from public, anon, authenticated;

drop trigger if exists trg_orders_precios_desactualizados on public.orders;
create trigger trg_orders_precios_desactualizados
  before insert on public.orders
  for each row execute function public.marcar_precios_desactualizados();
