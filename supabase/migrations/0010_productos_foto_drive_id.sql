-- APLICADA en producción el 2026-11-17 (migración "productos_foto_drive_id").
--
-- Por qué: sync.py bajaba la foto de un SKU una sola vez (cuando img_url estaba vacío).
-- Si el proveedor cambiaba la foto en Drive, `drive_id` se actualizaba pero nuestra foto
-- en Storage quedaba la vieja (en nov/2026 había 162 fotos de baja resolución con una
-- mejor en Drive; se reemplazaron con refresh_photos.py).
--
-- `foto_drive_id` guarda de qué archivo de Drive salió la foto que tenemos en Storage.
-- sync.py la vuelve a bajar cuando `drive_id` (lo que manda la API) es distinto.
--
-- Backfill: se iguala a `drive_id` para TODAS las filas, a propósito. Hay ~420 fotos que
-- difieren de la de Drive con resolución parecida (muchas de ambiente vs. producto solo)
-- y el dueño decidió no reemplazarlas; con el backfill solo se rebajan cuando el
-- proveedor cambie la foto de ahora en adelante.
--
-- Rollback:
--   alter table public.productos drop column if exists foto_drive_id;

alter table public.productos add column if not exists foto_drive_id text;

update public.productos set foto_drive_id = drive_id
where foto_drive_id is null and drive_id is not null and coalesce(img_url, '') <> '';
