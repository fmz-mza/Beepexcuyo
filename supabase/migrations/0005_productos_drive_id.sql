-- APLICADA en producción el 2026-10-07 (migración "productos_drive_id").
--
-- Por qué: la API de Beepaw manda por SKU el ID del archivo de la foto en Google Drive
-- (`driveMap`), y sync.py ya lo usa para armar nuestras fotos en Storage (webp 1024px +
-- thumbs 400px). Guardarlo permite que el catálogo ofrezca "Descargar foto" en JPG
-- directo desde Drive (lh3.googleusercontent.com/d/<id>=w1024-rj) sin convertir ni subir
-- nada a Storage. Si el enlace de Drive falla, el catálogo cae a nuestra foto webp y la
-- convierte a JPG en el navegador.
--
-- Columna nueva, nullable y sin default: no cambia filas existentes ni el trigger de
-- historial de precios. sync.py la llena en cada corrida horaria (solo la escribe si la
-- API trae un ID válido, así un faltante transitorio no pisa uno bueno).
--
-- Rollback:
--   alter table public.productos drop column if exists drive_id;

alter table public.productos add column if not exists drive_id text;
