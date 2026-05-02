import os
import requests
import json
from io import BytesIO
from PIL import Image
from supabase import create_client, Client
from datetime import datetime

# --- CONFIGURACIÓN ---
# Las variables se toman de los Secrets de GitHub
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# Inicializar Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_discord_log(message):
    if DISCORD_WEBHOOK_URL:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message})

def process_image(drive_id, sku):
    """Prueba múltiples fuentes y patrones para encontrar la imagen"""
    bucket_name = "fotos_demo"
    file_path = f"{sku}.webp"
    sku_clean = str(sku).strip()
    
    # Lista de fuentes potenciales
    source_urls = []
    
    # 1. Drive (si existe ID)
    if drive_id and drive_id.lower() != "prueba" and len(str(drive_id)) > 5:
        source_urls.extend([
            f"https://drive.google.com/thumbnail?id={drive_id}&sz=w1200",
            f"https://lh3.googleusercontent.com/d/{drive_id}=w1000"
        ])
    
    # 2. GitHub Repos (Beepexcuyo y Beepaw)
    repo_base = "https://raw.githubusercontent.com/fmz-mza/Beepexcuyo/main/images"
    patterns = [f"SKU_{sku_clean}", sku_clean]
    extensions = [".jpg", ".png", ".JPG", ".jpeg", ".webp"]

    for p in patterns:
        for ext in extensions:
            source_urls.append(f"{repo_base}/{p}{ext}")

    img_data = None
    used_url = None
    
    print(f"🔍 Buscando imagen para SKU {sku_clean}...")
    
    for url in source_urls:
        try:
            # Timeout corto para no ralentizar el proceso
            res = requests.get(url, timeout=5)
            if res.status_code == 200 and len(res.content) > 1000:
                img_data = res.content
                used_url = url
                break
        except:
            continue

    if not img_data:
        # Silencioso en consola para no inundar logs, pero reportamos el fallo
        return None

    try:
        print(f"✅ Encontrada: {used_url} | Procesando...")
        img = Image.open(BytesIO(img_data))
        
        # Optimización
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert("RGB")

        img.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="WEBP", quality=75)
        buffer.seek(0)

        # Intento de subida
        try:
            supabase.storage.from_(bucket_name).upload(
                path=file_path,
                file=buffer.read(),
                file_options={"content-type": "image/webp", "x-upsert": "true"}
            )
        except Exception as storage_err:
            # Si el error es que ya existe, no importa, recuperamos la URL
            if "already exists" not in str(storage_err).lower():
                print(f"❌ Error Storage en {sku}: {storage_err}")
                return None
        
        return supabase.storage.from_(bucket_name).get_public_url(file_path)
    except Exception as e:
        print(f"⚠️ Error general en {sku}: {e}")
        return None

def run_sync():
    stats = {"nuevos": 0, "actualizados": 0, "precios_cambiados": 0, "fotos_procesadas": 0}
    logs = []
    
    print("🚀 Iniciando Sincronización...")
    
    # Leer Google Sheets
    SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv"
    res = requests.get(SHEET_URL)
    if res.status_code != 200:
        send_discord_log("❌ Error: No se pudo acceder al Spreadsheet. Revisa el SPREADSHEET_ID.")
        return

    lines = res.text.splitlines()
    import csv
    reader = csv.reader(lines)
    header = next(reader) # Saltar cabecera

    for row in reader:
        if not row or len(row) < 5: continue
        
        sku = row[0].strip()
        nombre = row[1].strip()
        try:
            precio_pesos = float(row[4].replace(',', '').replace('$', ''))
        except:
            precio_pesos = 0
            
        foto_id = row[15] if len(row) > 15 else ""
        
        # 1. Verificar si ya existe para ver si procesamos foto
        existing = {}
        try:
            res_db = supabase.table("productos_demo").select("img_url", "precio_pesos").eq("codigo", sku).execute()
            if res_db.data:
                existing = res_db.data[0]
                stats["actualizados"] += 1
            else:
                stats["nuevos"] += 1
        except:
            pass

        product_data = {
            "codigo": sku,
            "nombre": nombre,
            "marca": row[2].strip(),
            "categoria": row[3].strip(),
            "precio_pesos": precio_pesos,
            "stock": row[5].strip() if len(row) > 5 else "S/D",
            "updated_at": datetime.now().isoformat()
        }

        # Solo procesamos la imagen si el producto NO tiene img_url ya guardada
        if not existing.get("img_url"):
            new_img_url = process_image(foto_id, sku)
            if new_img_url:
                product_data["img_url"] = new_img_url
                stats["fotos_procesadas"] += 1
        
        # Alertas de precio
        if existing and existing.get("precio_pesos") != precio_pesos:
            stats["precios_cambiados"] += 1
            logs.append(f"💰 {sku}: ${existing['precio_pesos']} -> ${precio_pesos}")

        # Upsert
        supabase.table("productos_demo").upsert(product_data).execute()

    # Resumen Final
    summary = (
        f"**Sincronización Finalizada** 🔄\n"
        f"✨ Nuevos: {stats['nuevos']}\n"
        f"🔄 Actualizados: {stats['actualizados']}\n"
        f"📈 Cambios precio: {stats['precios_cambiados']}\n"
        f"📸 Fotos procesadas: {stats['fotos_procesadas']}"
    )
    
    if logs:
        summary += "\n\n**Detalles:**\n" + "\n".join(logs[:10])
        if len(logs) > 10: summary += "\n*...y más*"

    send_discord_log(summary)
    print("✅ Proceso completado.")

if __name__ == "__main__":
    run_sync()
