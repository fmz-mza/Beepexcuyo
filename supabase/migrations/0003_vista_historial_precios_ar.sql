-- APLICADA en producción el 2026-09-30 (migración "vista_historial_precios_ar").
-- Probada antes con una transacción revertida (rollback): se insertó una fila
-- de prueba con changed_at = 2026-09-30 20:19:04+00 y la vista devolvió
-- changed_at_ar = 2026-09-30 17:19:04 (3 horas menos, correcto para GMT-3).
--
-- Por qué: productos_historial_precios.changed_at es timestamptz (guarda un
-- instante preciso, independiente de huso horario — es la forma correcta de
-- almacenarlo, y la misma que usan el resto de las tablas del proyecto:
-- orders, payments, pos_orders, etc.). Cambiar el huso horario de la BASE
-- afectaría a todas esas tablas a la vez, no solo a esta. En cambio, esta
-- vista no toca el storage: solo agrega una columna ya convertida a hora de
-- Buenos Aires (changed_at_ar) para leerla cómodo, sin tener que convertir
-- a mano cada vez.

create view public.productos_historial_precios_ar
with (security_invoker = true)  -- respeta la RLS de la tabla de base (solo admins)
as
select
  id, codigo, campo, valor_anterior, valor_nuevo,
  changed_at,                                                             -- UTC, el dato preciso
  changed_at at time zone 'America/Argentina/Buenos_Aires' as changed_at_ar -- hora de Buenos Aires, para leer
from public.productos_historial_precios;

-- Rollback:
--   drop view if exists public.productos_historial_precios_ar;

-- Ejemplo de consulta, ya en hora de Buenos Aires:
--   select campo, valor_anterior, valor_nuevo, changed_at_ar
--   from public.productos_historial_precios_ar
--   where codigo = '11307'
--   order by changed_at_ar desc;
