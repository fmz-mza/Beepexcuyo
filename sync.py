import os
import re
import requests
import pandas as pd
from PIL import Image
from io import BytesIO
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "16CTx8wJkiY45VDO9ft2r1VZZjsPyh5t_YGmhTOgQtrU")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

# URLs de origen
BEEPAW_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid=1686576198"
NETLIFY_SRC_URL = "https://beepawmayorista.netlify.app/ailen-l2.html"

# Inicializar Supabase
if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: SUPABASE_URL o SUPABASE_KEY no definidos.")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_discord_alert(message):
    if not DISCORD_WEBHOOK: return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message})
    except Exception as e:
        print(f"Error enviando alerta Discord: {e}")

def normalizar_iva(val):
    if pd.isna(val) or val is None: return ""
    s = str(val).replace(',', '.').replace('%', '').strip()
    try:
        f = float(s)
        if f == 0.21: return "21"
        if f == 0.105: return "10.5"
        return str(f)
    except:
        return s

def limpiar_precio(val):
    if pd.isna(val) or val is None: return 0
    s = str(val).replace('$', '').strip()
    if s.upper() == "SIN PVP": return 0
    s = re.sub(r'[^\d.,]', '', s)
    if not s: return 0
    try:
        s_clean = s.replace('.', '').replace(',', '.')
        if s_clean.count('.') > 1:
             s_clean = s_clean.replace('.', '', s_clean.count('.') - 1)
        return int(float(s_clean))
    except:
        return 0

def get_drive_ids_from_netlify():
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(NETLIFY_SRC_URL, headers=headers, timeout=10)
        html = res.text
        mapping = {}
        start_marker = 'DRIVE_IDS='
        start_idx = html.find(start_marker)
        if start_idx != -1:
            content_start = start_idx + len(start_marker)
            open_brace = html.find('{', content_start)
            close_brace = html.find('};', open_brace)
            if open_brace != -1 and close_brace != -1:
                obj_str = html[open_brace:close_brace+1]
                pairs = re.findall(r'["\']?(\w+)["\']?\s*:\s*["\']([\w\-]+)["\']', obj_str)
                for sku, drive_id in pairs:
                    mapping[sku] = drive_id
        return mapping
    except:
        return {}

def process_image(drive_id, sku):
    """Descarga, optimiza y sube la imagen a Supabase Storage"""
    bucket_name = "fotos_demo"
    file_path = f"{sku}.webp"
    
    # Fuentes de imagen (Priority: Drive -> Fallback GitHub Repositorio)
    source_urls = []
    if drive_id and drive_id.lower() != "prueba" and len(drive_id) > 5:
        source_urls.extend([
            f"https://drive.google.com/thumbnail?id={drive_id}&sz=w1200",
            f"https://lh3.googleusercontent.com/d/{drive_id}=w1000",
            f"https://drive.google.com/uc?id={drive_id}&export=download"
        ])
    
    # Fallback a tu repositorio Beepexcuyo (URL RAW)
    repo_base = "https://raw.githubusercontent.com/fmz-mza/Beepexcuyo/main/images"
    source_urls.append(f"{repo_base}/{sku}.jpg")
    source_urls.append(f"{repo_base}/{sku}.JPG")
    source_urls.append(f"{repo_base}/{sku}.png")
    source_urls.append(f"{repo_base}/{sku}.PNG")

    img_data = None
    used_url = ""
    for url in source_urls:
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200 and len(res.content) > 1000:
                img_data = res.content
                used_url = url
                break
        except:
            continue

    if not img_data:
        return None

    try:
        img = Image.open(BytesIO(img_data))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert("RGB")

        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="WEBP", quality=75)
        buffer.seek(0)

        # Upload (Upsert activado)
        supabase.storage.from_(bucket_name).upload(
            path=file_path,
            file=buffer.read(),
            file_options={"content-type": "image/webp", "x-upsert": "true"}
        )
        
        return supabase.storage.from_(bucket_name).get_public_url(file_path)
    except Exception as e:
        print(f"Error procesando {sku}: {e}")
        return None

def run_sync():
    print(f"Iniciando sincronización: {datetime.now()}")
    try:
        df = pd.read_csv(BEEPAW_CSV_URL)
        netlify_mapping = get_drive_ids_from_netlify()
    except Exception as e:
        send_discord_alert(f"❌ Error crítico: No se pudo leer el Spreadsheet: {e}")
        return

    stats = {"nuevos": 0, "actualizados": 0, "precios_cambiados": 0, "fotos_procesadas": 0}
    logs = []

    for _, row in df.iterrows():
        sku = str(row.get("CODIGO", "")).strip()
        if not sku or sku == "12333" or len(sku) < 2: continue
        
        nombre = str(row.get("NOMBRE", "")).replace('_', ' ').strip()
        descripcion = str(row.get("DESCRIPCION", "")).strip()
        iva = normalizar_iva(row.get("IVA"))
        precio_pvp = limpiar_precio(row.get("PVP"))
        precio_pesos = limpiar_precio(row.get("LISTA BASE"))
        
        if sku.isdigit() and int(sku) >= 11432 and precio_pvp > 0:
            precio_pesos = int(precio_pvp / 2)

        stock_fisico = 0
        try: stock_fisico = float(str(row.get("STOCK/INGRESO", "0")).replace(',', '.'))
        except: pass

        stock_ingresos = 0
        try: stock_ingresos = float(str(row.get("STOCK INGRESOS", "0")).replace(',', '.'))
        except: pass

        fecha_ingreso = str(row.get("INGRESOS", "")).strip()
        if fecha_ingreso.lower() == "none" or fecha_ingreso == "0": fecha_ingreso = ""

        if stock_fisico > 0: estado_stock = "STOCK"
        elif stock_ingresos > 0: estado_stock = f"PREVENTA ({fecha_ingreso})"
        else: estado_stock = "NOSTOCK"

        # Foto: Intentar ID de Drive, sino usar el SKU para buscar en el Repo de GitHub
        foto_id = str(row.get("FOTO", "")).strip()
        if not foto_id or foto_id.lower() == "prueba":
            foto_id = netlify_mapping.get(sku, "")
        
        # Forzar proceso de imagen (usará fallback de GitHub si no hay Drive ID)
        img_url = process_image(foto_id, sku)
        
        product_data = {
            "codigo": sku,
            "producto": nombre,
            "descripcion": descripcion,
            "iva": iva,
            "precio_pesos": precio_pesos,
            "precio_pvp": precio_pvp,
            "stock_estado": estado_stock,
            "stock_fisico": stock_fisico,
            "ean": str(row.get("EAN", "")).replace('/', '').strip(),
            "rubro": str(row.get("RUBRO", "")).strip(),
            "marca": str(row.get("MARCA", "")).strip(),
            "ingresos": fecha_ingreso,
            "stock_ingresos": stock_ingresos,
            "updated_at": datetime.now().isoformat()
        }

        if img_url:
            product_data["img_url"] = img_url
            stats["fotos_procesadas"] += 1

        try:
            existing = supabase.table("productos_demo").select("precio_pesos").eq("codigo", sku).execute()
            if existing.data:
                old_price = existing.data[0]["precio_pesos"]
                if old_price != precio_pesos:
                    stats["precios_cambiados"] += 1
                    logs.append(f"📈 {sku} - {nombre} (${old_price} -> ${precio_pesos})")
                stats["actualizados"] += 1
            else:
                stats["nuevos"] += 1
                logs.append(f"🆕 {sku} - {nombre}")

            supabase.table("productos_demo").upsert(product_data, on_conflict="codigo").execute()
        except:
            pass

    summary = f"🔄 **Sincronización Completada**\n"
    summary += f"- Nuevos: {stats['nuevos']} | Actualizados: {stats['actualizados']}\n"
    summary += f"- Cambios precio: {stats['precios_cambiados']}\n"
    summary += f"- **Fotos enviadas a Supabase: {stats['fotos_procesadas']}**\n"
    
    if logs:
        log_text = "\n".join(logs[:10])
        summary += f"\n**Movimientos:**\n{log_text}"

    send_discord_alert(summary)
    print(f"Finalizado. Fotos procesadas: {stats['fotos_procesadas']}")

if __name__ == "__main__":
    run_sync()
