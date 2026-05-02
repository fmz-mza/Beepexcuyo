import os
import requests
from io import BytesIO
from PIL import Image
from supabase import create_client
from datetime import datetime

# Configuración desde Secrets de GitHub
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def process_image(drive_id, sku):
    """Descarga, optimiza y sube la imagen a Supabase Storage"""
    bucket_name = "fotos_demo"
    file_path = f"{sku}.webp"
    
    # Fuentes de imagen (Priority: Drive -> Fallback GitHub Repos)
    source_urls = []
    if drive_id and drive_id.lower() != "prueba" and len(drive_id) > 5:
        source_urls.extend([
            f"https://drive.google.com/thumbnail?id={drive_id}&sz=w1200",
            f"https://lh3.googleusercontent.com/d/{drive_id}=w1000",
            f"https://drive.google.com/uc?id={drive_id}&export=download"
        ])
    
    # Repositorios GitHub (Beepexcuyo y Beepaw/Netlify Style)
    repo_base = "https://raw.githubusercontent.com/fmz-mza/Beepexcuyo/main/images"
    naming_patterns = [f"SKU_{sku}", f"{sku}"]
    extensions = [".jpg", ".png", ".JPG", ".jpeg"]

    for pattern in naming_patterns:
        for ext in extensions:
            source_urls.append(f"{repo_base}/{pattern}{ext}")

    img_data = None
    used_url = ""
    for url in source_urls:
        try:
            res = requests.get(url, timeout=10, stream=True)
            if res.status_code == 200 and len(res.content) > 1000:
                img_data = res.content
                used_url = url
                break
        except:
            continue

    if not img_data:
        return None

    try:
        print(f"📷 Procesando {sku} desde {used_url[:50]}...")
        img = Image.open(BytesIO(img_data))
        
        # Convertir a RGB
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, (0,0), img)
            img = bg
        else:
            img = img.convert("RGB")

        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        
        buffer = BytesIO()
        img.save(buffer, format="WEBP", quality=75)
        buffer.seek(0)

        # Subida con manejo de error 403
        try:
            supabase.storage.from_(bucket_name).upload(
                path=file_path,
                file=buffer.read(),
                file_options={"content-type": "image/webp", "x-upsert": "true"}
            )
        except Exception as storage_err:
            if "already exists" in str(storage_err):
                pass # Si ya existe, no importa
            else:
                print(f"❌ Error Storage en {sku}: {storage_err}")
                return None
        
        return supabase.storage.from_(bucket_name).get_public_url(file_path)
    except Exception as e:
        print(f"⚠️ Error procesando {sku}: {e}")
        return None

def run_sync():
    print("🚀 Iniciando Sincronización...")
    stats = {"nuevos": 0, "actualizados": 0, "fotos_procesadas": 0}
    
    # Leer Spreadsheet (vía export CSV para simplicidad sin API compleja)
    csv_url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv"
    response = requests.get(csv_url)
    lines = response.text.splitlines()
    
    import csv
    reader = csv.DictReader(lines)
    
    for row in reader:
        sku = row.get("CODIGO") or row.get("sku")
        nombre = row.get("NOMBRE") or row.get("nombre")
        precio_pesos = float(row.get("PRECIO") or 0)
        stock = int(row.get("STOCK") or 0)
        foto_id = row.get("FOTO") or ""
        categoria = row.get("CATEGORIA") or "General"

        if not sku: continue

        # Datos base
        product_data = {
            "codigo": sku,
            "nombre": nombre,
            "precio_pesos": precio_pesos,
            "stock": stock,
            "categoria": categoria,
            "updated_at": datetime.now().isoformat()
        }

        # Lógica de Imagen (Solo si no tiene ya una URL válida en BD)
        try:
            existing = supabase.table("productos_demo").select("img_url").eq("codigo", sku).execute()
            if not existing.data or not existing.data[0].get("img_url"):
                img_url = process_image(foto_id, sku)
                if img_url:
                    product_data["img_url"] = img_url
                    stats["fotos_procesadas"] += 1
        except:
            pass

        # Upsert
        try:
            supabase.table("productos_demo").upsert(product_data).execute()
            stats["actualizados"] += 1
        except Exception as e:
            print(f"❌ Error guardando {sku}: {e}")

    # Notificación Discord
    msg = (
        "✅ **Sincronización Piloto Finalizada**\n"
        f"📦 Productos procesados: {stats['actualizados']}\n"
        f"🖼️ Fotos nuevas en Supabase: {stats['fotos_procesadas']}\n"
        "---"
    )
    if DISCORD_WEBHOOK_URL:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    print("Terminado.")

if __name__ == "__main__":
    run_sync()
