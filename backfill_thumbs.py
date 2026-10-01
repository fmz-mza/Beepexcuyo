"""Backfill único: genera fotos/thumbs/<sku>.webp (400px) a partir de las originales
ya subidas en fotos/<sku>.webp. No modifica ni toca las originales (1024px).
Es idempotente: si la miniatura ya existe, se saltea (FORCE=1 para regenerarlas)."""
import os
from io import BytesIO

import requests
from PIL import Image
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET = "fotos"
THUMB_SIZE = 400
THUMB_QUALITY = 72
FORCE = os.getenv("FORCE") == "1"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
PUBLIC = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}"


def listar(prefix=""):
    """Lista todos los objetos de un prefijo (paginado)."""
    nombres, offset = [], 0
    while True:
        page = supabase.storage.from_(BUCKET).list(prefix, {"limit": 1000, "offset": offset})
        if not page:
            break
        nombres += [o["name"] for o in page if o.get("id")]  # id=None => carpeta
        if len(page) < 1000:
            break
        offset += 1000
    return nombres


def main():
    originales = [n for n in listar() if n.endswith(".webp")]
    existentes = set() if FORCE else set(listar("thumbs"))
    print(f"Originales: {len(originales)} · miniaturas existentes: {len(existentes)}")

    ok = saltadas = errores = 0
    for nombre in originales:
        if nombre in existentes:
            saltadas += 1
            continue
        try:
            res = requests.get(f"{PUBLIC}/{nombre}", timeout=20)
            res.raise_for_status()
            img = Image.open(BytesIO(res.content)).convert("RGB")
            img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="WEBP", quality=THUMB_QUALITY)
            supabase.storage.from_(BUCKET).upload(
                path=f"thumbs/{nombre}",
                file=buf.getvalue(),
                file_options={"content-type": "image/webp", "x-upsert": "true"},
            )
            ok += 1
        except Exception as e:
            errores += 1
            print(f"❌ {nombre}: {e}")

    print(f"✅ creadas: {ok} · ya existían: {saltadas} · errores: {errores}")
    if errores:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
