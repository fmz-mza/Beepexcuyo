-- APLICADA en producción el 2026-10-26 (migración "quitar_precio_fijo_11573").
--
-- Por qué: catálogo, POS y generate_excel.py fijaban el SKU 11573 (lanzapelotas Shoot-E 2.0
-- verde lima) en $59.999 desde mayo/2026, sin explicación, mientras el precio real en
-- `productos` subió a $81.162. Ese precio fijo se quitó de los tres lugares; acá se quita la
-- misma excepción del trigger de la migración 0008, así ese SKU se compara con `productos`
-- como cualquier otro.
--
-- Rollback: volver a crear la función con la línea de la 0008
--   case when it->>'sku' = '11573' then 59999 else p.precio_pesos::numeric end as actual

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
             p.precio_pesos::numeric as actual
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
