-- APLICADA en producción el 2026-10-01 (migración "productos_variantes").
--
-- Por qué: la API de Beepaw (la misma que consume sync.py) ya manda por SKU
-- `agrupador`, `caracteristica`, `colorCol` y `categorizacion`, pero no los
-- guardábamos. Con ellos el catálogo agrupa los SKUs que son variantes de un
-- mismo producto (color / medida) en una sola tarjeta con un modal de variantes
-- (en la API: ~842 SKUs → 197 grupos, 132 con más de una variante).
--
--   agrupador       nombre del producto que agrupa a las variantes (ej. "CLEAN-E")
--   caracteristica  medida / modelo / talle de la variante (ej. "M", "50X80CM")
--   color           color de la variante
--   categorizacion  ruta de categoría en la API (ej. "COMEDEROS > FOOD-E"); hoy el
--                   catálogo no la usa, los ejes de variación se deducen de
--                   caracteristica / color de cada grupo
--
-- Son columnas nuevas, nullable y sin default: no cambian filas existentes ni
-- el trigger de historial de precios. sync.py las llena en cada corrida horaria
-- (upsert por `codigo`); hasta entonces quedan en NULL y el catálogo se
-- comporta como siempre (una tarjeta por SKU).
--
-- Rollback:
--   alter table public.productos
--     drop column if exists agrupador,
--     drop column if exists caracteristica,
--     drop column if exists color,
--     drop column if exists categorizacion;

alter table public.productos
  add column if not exists agrupador text,
  add column if not exists caracteristica text,
  add column if not exists color text,
  add column if not exists categorizacion text;
