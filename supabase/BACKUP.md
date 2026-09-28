# Backup y restore de la base de datos

El plan gratuito de Supabase no incluye backups. El workflow
[`.github/workflows/backup-db.yml`](../.github/workflows/backup-db.yml) genera uno cifrado.

## Qué contiene

Un archivo `beepex-backup-<fecha>.tar.gpg` (AES-256) que, al descifrarlo, trae:

- `public.dump`: esquema y datos del esquema `public` (tablas, vistas, funciones, triggers y
  políticas RLS). Formato `pg_dump --format=custom`.
- `auth.dump`: solo datos de `auth.users` y `auth.identities` (cuentas de login).

No incluye Storage (fotos): se regeneran con `sync.py`. `productos` también se regenera solo.

## Configuración (una sola vez)

En GitHub → Settings → Secrets and variables → Actions:

| Secreto | Qué es |
|---|---|
| `SUPABASE_DB_URL` | Cadena de conexión a la base (panel de Supabase → Connect → Session pooler). Incluye la contraseña de la base. |
| `BACKUP_PASSPHRASE` | Contraseña larga para cifrar. **Guardarla también en un gestor de contraseñas: sin ella los backups no se pueden abrir.** |
| `DISCORD_WEBHOOK_URL` | Ya existe. Opcional: avisa si el backup salió bien o falló. |

## Seguridad

- El repo es **público** y los artefactos de un repo público los puede descargar cualquiera con
  cuenta de GitHub. Por eso todo se cifra antes de subirlo, y el workflow borra los volcados
  sin cifrar antes de terminar.
- Nunca commitear un volcado al repo ni subirlo sin cifrar.
- Los artefactos se conservan 90 días. Conviene bajar uno por mes y guardarlo fuera de GitHub.

## Ejecutar un backup

Corre solo los domingos a las 03:00 (Argentina). También se puede lanzar a mano: GitHub →
Actions → "Backup Supabase (cifrado)" → Run workflow. Al terminar, el archivo está en la
sección "Artifacts" de la corrida.

Estado (2026-09-28): se validó que el backup corre bien y que el archivo se descifra y contiene
`public.dump` y `auth.dump`. **Todavía falta hacer un restore de prueba** (ver abajo) para
confirmar que el contenido sirve para recuperar de verdad — se decidió activar igual la
programación semanal mientras tanto, en vez de esperar a ese restore.

## Restaurar

Nunca restaurar directo sobre producción sin pensarlo: primero probar en un proyecto de
Supabase nuevo y vacío.

```bash
# 1. Descifrar y extraer
gpg --output backup.tar --decrypt beepex-backup-AAAA-MM-DD_HHMM.tar.gpg
tar -xf backup.tar          # genera public.dump y auth.dump

# 2. Ver qué contiene (no modifica nada)
pg_restore --list public.dump | less

# 3. Restaurar el esquema public en una base NUEVA (usar pg_restore de versión >= 17)
pg_restore --dbname "<URL de la base nueva>" --no-owner --no-privileges --exit-on-error public.dump

# 4. (Opcional) cuentas de login
pg_restore --dbname "<URL de la base nueva>" --data-only --no-owner auth.dump
```

Para recuperar solo una tabla (por ejemplo tras un borrado accidental), restaurar a una base
temporal y copiar desde ahí:

```bash
pg_restore --dbname "<URL base temporal>" --no-owner --table=payments public.dump
```

## Limitaciones

- Es una foto de un momento dado: se pierde lo ocurrido desde la última corrida.
- No hay recuperación a un punto exacto en el tiempo (eso requiere plan Pro).
- Si `pg_dump` falla por permisos sobre `auth`, el workflow falla en voz alta (y avisa por
  Discord): no deja pasar backups incompletos.
