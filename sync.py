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
        if f == 21.0: return "21"
        if f == 10.5: return "10.5"
        return str(f)
    except:
        if "21" in s: return "21"
        if "10" in s and "5" in s: return "10.5"
        return s

def limpiar_precio(val):
    if pd.isna(val) or val is None: return 0
    s = str(val).replace('$', '').strip()
    if s.upper() == "SIN PVP": return 0
    # Limpieza agresiva de caracteres no numéricos
    s = re.sub(r'[^\d.,]', '', s)
    if not s: return 0
    try:
        # Manejar formatos como 11.899,00 o 11,899.00
        # Intentamos una conversión simple
        s_clean = s.replace('.', '').replace(',', '.')
        if s_clean.count('.') > 1: # caso 11.899.000
             s_clean = s_clean.replace('.', '', s_clean.count('.') - 1)
        return int(float(s_clean))
    except:
        return 0

def get_drive_ids_from_netlify():
    """Extrae el mapeo de IDs de Drive desde el HTML de Netlify"""
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
    except Exception as e:
        print(f"Error scraping Netlify: {e}")
        return {}

def process_image(drive_id, sku):
    """Descarga, optimiza y sube la imagen a Supabase Storage"""
    if not drive_id or drive_id.lower() == "prueba":
        return None

    bucket_name = "fotos_demo" # Usar fotos_demo para el piloto
    file_path = f"{sku}.webp"
    
    # Verificar si ya existe para ahorrar procesamiento
    try:
        # Intento rápido de ver si existe
        res = supabase.storage.from_(bucket_name).get_public_url(file_path)
        # Podríamos hacer un head request si quisiéramos ser seguros, 
        # pero para el piloto asumimos que si está en la tabla con URL, ya está.
    except:
        pass

    # Fallbacks de URLs de Drive
    drive_urls = [
        f"https://drive.google.com/thumbnail?id={drive_id}&sz=w1200",
        f"https://lh3.googleusercontent.com/d/{drive_id}=w1000",
        f"https://drive.google.com/uc?id={drive_id}&export=download"
    ]

    img_data = None
    for url in drive_urls:
        try:
            res = requests.get(url, timeout=15, stream=True)
            if res.status_code == 200 and len(res.content) > 2000:
                img_data = res.content
                break
        except:
            continue

    if not img_data:
        return None

    try:
        # Procesamiento con Pillow
        img = Image.open(BytesIO(img_data))
        
        # Convertir a RGB (manejar transparencias)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert("RGB")

        # Redimensionar (Max 1024px)
        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        
        # Guardar en buffer como WebP
        buffer = BytesIO()
        img.save(buffer, format="WEBP", quality=80)
        buffer.seek(0)

        # Subir a Supabase
        supabase.storage.from_(bucket_name).upload(
            path=file_path,
            file=buffer.read(),
            file_options={"content-type": "image/webp", "x-upsert": "true"}
        )
        
        return supabase.storage.from_(bucket_name).get_public_url(file_path)
    except Exception as e:
        print(f"Error procesando imagen para SKU {sku}: {e}")
        return None

def run_sync():
    print(f"Iniciando sincronización: {datetime.now()}")
    
    # 1. Obtener datos
    try:
        df = pd.read_csv(BEEPAW_CSV_URL)
        netlify_mapping = get_drive_ids_from_netlify()
    except Exception as e:
        print(f"Error obteniendo datos: {e}")
        return

    stats = {"nuevos": 0, "actualizados": 0, "precios_cambiados": 0, "fotos_procesadas": 0}
    logs = []

    for _, row in df.iterrows():
        sku = str(row.get("CODIGO", "")).strip()
        if not sku or sku == "12333": continue # Saltar prueba
        
        nombre = str(row.get("NOMBRE", "")).replace('_', ' ').strip()
        descripcion = str(row.get("DESCRIPCION", "")).strip()
        iva = normalizar_iva(row.get("IVA"))
        
        # Precios
        precio_pvp = limpiar_precio(row.get("PVP"))
        precio_pesos = limpiar_precio(row.get("LISTA BASE"))
        
        # Regla SKU >= 11432
        try:
            if int(sku) >= 11432 and precio_pvp > 0:
                precio_pesos = int(precio_pvp / 2)
        except: pass

        # Stock
        stock_fisico = 0
        try: stock_fisico = float(str(row.get("STOCK/INGRESO", "0")).replace(',', '.'))
        except: pass

        stock_ingresos = 0
        try: stock_ingresos = float(str(row.get("STOCK INGRESOS", "0")).replace(',', '.'))
        except: pass

        fecha_ingreso = str(row.get("INGRESOS", "")).strip()
        if fecha_ingreso.lower() == "none" or fecha_ingreso == "0": fecha_ingreso = ""

        if stock_fisico > 0:
            estado_stock = "STOCK"
        elif stock_ingresos > 0:
            estado_stock = f"PREVENTA ({fecha_ingreso})"
        else:
            estado_stock = "NOSTOCK"

        # Foto
        foto_id = str(row.get("FOTO", "")).strip()
        if not foto_id or foto_id.lower() == "prueba":
            foto_id = netlify_mapping.get(sku, "")
        
        # Upsert en Supabase (Tabla productos_demo para el piloto)
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

        # Verificar si hay que procesar foto
        if foto_id:
            # Solo procesar si no tenemos URL de imagen o queremos forzar refresh
            # Aquí podríamos consultar a Supabase primero, pero para el piloto 
            # procesaremos si detectamos un ID válido.
            img_url = process_image(foto_id, sku)
            if img_url:
                product_data["img_url"] = img_url
                stats["fotos_procesadas"] += 1

        try:
            # Consultar precio anterior para el log
            existing = supabase.table("productos_demo").select("precio_pesos").eq("codigo", sku).execute()
            if existing.data:
                old_price = existing.data[0]["precio_pesos"]
                if old_price != precio_pesos:
                    stats["precios_cambiados"] += 1
                    logs.append(f"📈 PRECIO: {sku} - {nombre} (${old_price} -> ${precio_pesos})")
                stats["actualizados"] += 1
            else:
                stats["nuevos"] += 1
                logs.append(f"🆕 NUEVO: {sku} - {nombre}")

            supabase.table("productos_demo").upsert(product_data, on_conflict="codigo").execute()
        except Exception as e:
            print(f"Error upserting SKU {sku}: {e}")

    # Alerta Discord
    summary = f"🔄 **Sincronización Completada**\n"
    summary += f"- Nuevos: {stats['nuevos']}\n"
    summary += f"- Actualizados: {stats['actualizados']}\n"
    summary += f"- Cambios precio: {stats['precios_cambiados']}\n"
    summary += f"- Fotos procesadas: {stats['fotos_procesadas']}\n"
    
    if logs:
        log_text = "\n".join(logs[:15]) # Top 15 cambios
        if len(logs) > 15: log_text += f"\n... y {len(logs)-15} cambios más."
        summary += f"\n**Detalle:**\n{log_text}"

    send_discord_alert(summary)
    print(f"Sincronización finalizada satisfactoriamente.")

if __name__ == "__main__":
    run_sync()
