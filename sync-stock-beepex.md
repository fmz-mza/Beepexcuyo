# Sync de stock Beepex

Contrato para el `sync.py` de Fernando: cómo subir la disponibilidad de Beepex
al ERP. El stock cargado se ve en el módulo **/stock** (columna "Stock Beepex").

## RPC

`public.actualizar_stock_beepex(p_items jsonb)` — creada en la migración
`app/supabase/migrations/0026_origen_stock_dropship_y_stock_beepex.sql`.

- **Entrada**: `p_items` es un array JSON de items `{"sku": "...", "stock": N}`.
- **Efecto**: por cada item actualiza `products.stock_beepex` y
  `products.stock_beepex_updated_at = now()` matcheando por **SKU exacto**
  (se aplica `trim()` al SKU recibido; no es case-insensitive ni parcial).
- **Devuelve**: `{"actualizados": n, "sin_match": [...], "invalidos": [...]}`.
- Si `p_items` no es un array no vacío, falla con error
  `Se espera un array de items {sku, stock}`.
- Items con `sku` vacío o null se ignoran (no cuentan ni como actualizados
  ni como sin_match).
- Items con `stock` null, no numérico o negativo se reportan en `invalidos`
  y NO pisan el dato anterior — loguearlos igual que `sin_match`.

## Ejemplo con curl

```bash
curl -X POST "${SUPABASE_URL}/rest/v1/rpc/actualizar_stock_beepex" \
  -H "apikey: ${SUPABASE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "p_items": [
      {"sku": "1100", "stock": 25},
      {"sku": "1205", "stock": 0}
    ]
  }'
```

`SUPABASE_KEY` puede ser la **service role key** (recomendado para un script
de sync server-side; nunca exponerla en un cliente) o el access token de un
usuario autenticado del ERP.

Respuesta esperada (HTTP 200):

```json
{"actualizados": 2, "sin_match": []}
```

## Ejemplo en Python (para sync.py)

```python
import requests

SUPABASE_URL = "https://<proyecto>.supabase.co"
SUPABASE_KEY = "<service-role-key>"  # leerla de env/secret, no hardcodear

def subir_stock_beepex(items: list[dict]) -> dict:
    """items: [{"sku": "1100", "stock": 25}, ...]"""
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/actualizar_stock_beepex",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        },
        json={"p_items": items},
        timeout=30,
    )
    resp.raise_for_status()
    resultado = resp.json()
    if resultado["sin_match"]:
        print(f"AVISO: {len(resultado['sin_match'])} SKUs sin match: {resultado['sin_match']}")
    print(f"Stock Beepex actualizado: {resultado['actualizados']} productos")
    return resultado
```

## Notas

- El match es por **SKU exacto** (con trim). Si Beepex usa otros códigos,
  mapearlos a los SKUs del ERP antes de llamar a la RPC.
- **Loguear siempre `sin_match`**: son SKUs que Beepex informó pero no
  existen en `products` (típicamente productos nuevos del proveedor o
  códigos mal mapeados).
- Se puede mandar todo el catálogo en una sola llamada (~200 SKUs no es
  problema); no hace falta batchear.
- `stock_beepex = null` en la base significa "sin dato de sync" — la UI lo
  muestra como "—". Mandar `stock: 0` cuando Beepex informa explícitamente
  que no hay disponibilidad.
- La pantalla /stock muestra "Stock Beepex actualizado: {fecha}" con el
  máximo `stock_beepex_updated_at`, así que conviene correr el sync completo
  cada vez (no incremental) para que esa fecha refleje la última corrida.
