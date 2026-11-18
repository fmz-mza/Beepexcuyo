"""Reemplaza fotos ya subidas por la foto actual del proveedor en Google Drive.

sync.py baja la foto de un SKU una sola vez (cuando img_url está vacío); si el proveedor
la cambia después, la nuestra queda vieja. Este script vuelve a bajar desde Drive
(productos.drive_id) los SKUs indicados en la variable SKUS (separados por espacio o coma)
y pisa fotos/<sku>.webp (1024px) y fotos/thumbs/<sku>.webp (400px).
Solo usa Drive: si Drive no responde, el SKU se saltea (no cae al fallback de GitHub,
que tiene las fotos viejas). Se corre desde .github/workflows/refresh-photos.yml."""
import os
import re
from io import BytesIO

import requests
from PIL import Image

from sync import supabase, FOTOS_BUCKET, PRODUCT_TABLE, upload_webp, make_thumb, thumb_path, THUMB_QUALITY

SKUS = [s for s in re.split(r"[\s,]+", os.getenv("SKUS", "")) if s]


def bajar(drive_id):
    for url in (f"https://drive.google.com/thumbnail?id={drive_id}&sz=w1200",
                f"https://lh3.googleusercontent.com/d/{drive_id}=w1024"):
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200 and len(r.content) > 1000:
                return r.content
        except Exception:
            pass
    return None


def a_rgb(img):
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        return bg
    return img.convert("RGB")


def main():
    if not SKUS:
        print("Sin SKUs (variable SKUS vacía).")
        return
    rows = supabase.table(PRODUCT_TABLE).select("codigo,drive_id").in_("codigo", SKUS).execute().data
    ids = {r["codigo"]: r.get("drive_id") for r in rows}
    ok, fallidos = 0, []
    for sku in SKUS:
        drive_id = ids.get(sku)
        data = bajar(drive_id) if drive_id else None
        if not data:
            fallidos.append(sku)
            print(f"❌ {sku}: sin drive_id o Drive no respondió")
            continue
        img = a_rgb(Image.open(BytesIO(data)))
        original = img.copy()
        original.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        upload_webp(FOTOS_BUCKET, f"{sku}.webp", original, 75, sku)
        upload_webp(FOTOS_BUCKET, thumb_path(sku), make_thumb(img), THUMB_QUALITY, sku)
        ok += 1
        print(f"📷 {sku}: {img.size[0]}x{img.size[1]} → {original.size[0]}x{original.size[1]}")
    print(f"Listo: {ok} reemplazadas, {len(fallidos)} fallidas {' '.join(fallidos)}")


if __name__ == "__main__":
    main()
