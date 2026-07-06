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
SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE") or os.getenv("VITE_SUPABASE_ANON_KEY")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "16CTx8wJkiY45VDO9ft2r1VZZjsPyh5t_YGmhTOgQtrU")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

# Nombres de recursos (PRODUCCIÓN)
PRODUCT_TABLE = "productos"
FOTOS_BUCKET = "fotos"

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
    """
    Limpia y convierte a entero strings de precios.
    Detecta si los últimos dígitos son centavos (ej: .00 o ,50) para truncarlos,
    pero protege los miles (ej: 59.999).
    """
    if pd.isna(val) or val is None: return 0
    s = str(val).replace('$', '').strip()
    if s.upper() == "SIN PVP": return 0
    
    # Quitar todos los espacios
    s = s.replace(' ', '').replace('\xa0', '')
    
    # Encontrar el último separador
    last_sep_idx = -1
    for i, char in enumerate(s):
        if char in ',.':
            last_sep_idx = i
            
    if last_sep_idx != -1:
        # Analizar qué hay después del último separador
        decimals_part = s[last_sep_idx+1:]
        # Si hay exactamente 2 dígitos después del punto/coma, son centavos.
        # Si hay 3 o más, es herencia de separador de miles o error de formato.
        if len(decimals_part) == 2:
            s = s[:last_sep_idx]
        elif len(decimals_part) == 1:
            # Caso raro de un solo decimal, también truncamos
            s = s[:last_sep_idx]
    
    # Eliminar cualquier carácter no numérico restante
    s = re.sub(r'[^\d]', '', s)
    
    try:
        return int(s) if s else 0
    except Exception:
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

def limpiar_stock(val):
    if pd.isna(val) or val is None: return 0
    s = str(val).replace(',', '.').strip()
    try:
        # Intentar buscar el primer número que parezca un decimal o entero
        match = re.search(r'(\d+\.?\d*)', s)
        if match:
            return float(match.group(1))
    except:
        pass
    return 0

def process_image(drive_id, sku):
    """Descarga, optimiza y sube la imagen a Supabase Storage"""
    bucket_name = FOTOS_BUCKET
    file_path = f"{sku}.webp"
    
    # Fuentes de imagen (Priority: Direct URL -> Drive -> Fallback GitHub Repos)
    source_urls = []
    
    # 1. Si drive_id ya es una URL completa (desde Spreadsheet)
    if drive_id and (drive_id.startswith("http://") or drive_id.startswith("https://")):
        source_urls.append(drive_id)
    
    # 2. Si es un ID de Google Drive
    elif drive_id and drive_id.lower() != "prueba" and len(drive_id) > 5:
        source_urls.extend([
            f"https://drive.google.com/thumbnail?id={drive_id}&sz=w1200",
            f"https://lh3.googleusercontent.com/d/{drive_id}=w1000",
            f"https://drive.google.com/uc?id={drive_id}&export=download"
        ])
    
    # 3. Repositorios GitHub
    repos = [
        "https://raw.githubusercontent.com/fmz-mza/Beepexcuyo/main/images",
        "https://raw.githubusercontent.com/fmz-mza/beepaw/main/images"
    ]
    
    # Patrones de nombre: [Con prefijo (Beepexcuyo), Sin prefijo (Beepaw/Netlify/General)]
    naming_patterns = [f"SKU_{sku}", f"{sku}"]
    extensions = [".jpg", ".png", ".JPG", ".jpeg", ".PNG"]

    for repo in repos:
        for pattern in naming_patterns:
            for ext in extensions:
                source_urls.append(f"{repo}/{pattern}{ext}")

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
        print(f"❌ No se encontró imagen para SKU {sku} en ninguna fuente.")
        return None

    try:
        print(f"📷 Procesando {sku} desde {used_url[:50]}...")
        img = Image.open(BytesIO(img_data))
        
        # Convertir a RGB
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert("RGB")

        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        
        buffer = BytesIO()
        img.save(buffer, format="WEBP", quality=75) # Calidad 75 para máximo ahorro
        buffer.seek(0)

        # Upload
        try:
            supabase.storage.from_(bucket_name).upload(
                path=file_path,
                file=buffer.read(),
                file_options={"content-type": "image/webp", "x-upsert": "true"}
            )
        except Exception as upload_err:
            # Si ya existe y upsert falló por RLS, intentamos capturarlo suavemente
            if "already exists" in str(upload_err).lower():
                pass # Ignoramos si ya existe y no pudimos sobrescribir
            else:
                print(f"❌ Error Storage en {sku}: {upload_err}")
                # No retornamos None si el archivo ya existe (aunque no lo hayamos podido actualizar)
                # para que el link público siga funcionando en la DB.
        
        return supabase.storage.from_(bucket_name).get_public_url(file_path)
    except Exception as e:
        print(f"⚠️ Error procesando {sku}: {e}")
        return None

def get_variant_key(name):
    if not name or pd.isna(name):
        return ""
    # Reemplazar guiones bajos por espacios, colapsar espacios múltiples y dividir por /
    clean = str(name).replace('_', ' ')
    clean = re.sub(r'\s+', ' ', clean)
    if '/' in clean:
        clean = clean.split('/')[0]
    return clean.strip().upper()

def run_sync():
    print(f"Iniciando sincronización: {datetime.now()}")
    
    # 1. Obtener datos
    try:
        df = pd.read_csv(BEEPAW_CSV_URL)
        netlify_mapping = get_drive_ids_from_netlify()
    except Exception as e:
        print(f"Error obteniendo datos: {e}")
        return

    # Primer paso: Construir mapeo de precios base normales de variantes hermanas (SKU >= 11432)
    regular_prices_by_key = {}
    for _, row in df.iterrows():
        sku_raw = row.get("CODIGO", "")
        if pd.isna(sku_raw) or sku_raw == "":
            continue
        sku_str = str(sku_raw).strip()
        if sku_str.endswith(".0"):
            sku_str = sku_str[:-2]
        
        nombre = str(row.get("NOMBRE", "")).strip()
        marca = str(row.get("MARCA", "")).strip()
        
        try:
            val_sku = int(sku_str)
            if val_sku >= 11432 and "GENERICOS" in marca.upper():
                precio_liqui = limpiar_precio(row.get("LISTA LIQUIDACION"))
                precio_lista_base = limpiar_precio(row.get("LISTA BASE"))
                # Si NO está en liquidación y tiene precio base válido
                if precio_liqui <= 0 and precio_lista_base > 0:
                    key = get_variant_key(nombre)
                    if key:
                        existing = regular_prices_by_key.get(key, 0)
                        if precio_lista_base > existing:
                            regular_prices_by_key[key] = precio_lista_base
        except Exception:
            pass

    stats = {"nuevos": 0, "actualizados": 0, "precios_cambiados": 0, "fotos_procesadas": 0}
    logs = []

    for _, row in df.iterrows():
        sku_raw = row.get("CODIGO", "")
        if pd.isna(sku_raw) or sku_raw == "":
            continue
            
        # Limpieza de SKU para evitar decimales .0 (problema de float en Pandas)
        sku = str(sku_raw).strip()
        if sku.endswith(".0"):
            sku = sku[:-2]
        
        nombre = str(row.get("NOMBRE", "")).replace('_', ' ').strip()
        
        # Saltar si no hay SKU o es de prueba
        if not sku or sku == "0" or "PRUEBA" in nombre.upper() or "TEST" in nombre.upper():
            continue
        
        descripcion = str(row.get("DESCRIPCION", "")).strip()
        iva = normalizar_iva(row.get("IVA"))
        marca = str(row.get("MARCA", "")).strip()
        rubro = str(row.get("RUBRO", "")).strip()
        
        # PRECIOS: Lógica de Identidad entre listas
        precio_pvp = limpiar_precio(row.get("PVP"))
        precio_lista_base = limpiar_precio(row.get("LISTA BASE"))
        precio_14_20 = limpiar_precio(row.get("LISTA 14/20"))
        precio_20_30 = limpiar_precio(row.get("LISTA 20/30"))
        precio_liqui = limpiar_precio(row.get("LISTA LIQUIDACION"))
        
        precio_pesos = precio_lista_base
        regla_trigger = False
        motivo_regla = "Identidad"
        
        if precio_liqui > 0:
            # REGLA LIQUIDACIÓN: Sincronizar productos en liquidación calculando LISTA LIQUIDACION * 1.23
            # Aplica para todos los SKUs (incluyendo marca Beepaw < 11432) de manera puntual.
            precio_pesos = int(precio_liqui * 1.23)
            regla_trigger = True
            motivo_regla = "Liqui_1.23"
        else:
            if precio_lista_base > 0 and precio_lista_base == precio_14_20 == precio_20_30:
                if precio_pvp > 0:
                    calculado = int(precio_pvp / 2)
                    if precio_lista_base == precio_pvp or calculado > precio_lista_base:
                        precio_pesos = calculado
                        regla_trigger = True
                        motivo_regla = "PVP/2"
                else:
                    # NUEVA REGLA (04/05): Si no hay PVP y los precios de lista son idénticos, sumamos 21%
                    precio_pesos = int(precio_lista_base * 1.21)
                    regla_trigger = True
                    motivo_regla = "Base+21% (Iden)"

            # REGLA PROTECCIÓN GENÉRICOS (para productos NO en liquidación):
            # Si es Genérico >= 11432 y no hay PVP:
            try:
                val_sku = int(sku)
                if val_sku >= 11432 and "GENERICOS" in marca.upper() and precio_pvp <= 0:
                    precio_pesos = precio_lista_base
                    regla_trigger = True
                    motivo_regla = "Gen_Base_Directo"
            except:
                pass
            
            # Fallback histórico para SKUs nuevos sin lista base (>= 11432)
            if precio_pesos <= 0:
                try:
                    val_sku = int(sku)
                    if val_sku >= 11432 and precio_pvp > 0:
                        precio_pesos = int(precio_pvp / 2)
                        regla_trigger = True
                        motivo_regla = "PVP/2 (Fallback)"
                except:
                    pass
 
        # Mostrar en log si se aplicó alguna regla especial
        if regla_trigger:
            # Solo logueamos si el precio calculado es diferente al de LISTA BASE
            if precio_pesos != precio_lista_base:
                print(f"ℹ️ REGLA {motivo_regla}: SKU {sku} ({nombre}) -> Aplicado: ${precio_pesos} (Base era ${precio_lista_base})")

        # Stock
        stock_raw = str(row.get("STOCK/INGRESO", "0")).upper()
        stock_fisico = limpiar_stock(stock_raw)
        
        stock_ingresos = limpiar_stock(row.get("STOCK INGRESOS", "0"))

        fecha_val = row.get("INGRESOS")
        if pd.isna(fecha_val) or str(fecha_val).lower() in ["none", "0", "nan"]:
            fecha_ingreso = ""
        else:
            fecha_ingreso = str(fecha_val).strip()

        if stock_fisico > 0 or "STOCK" in stock_raw or "DISPONIBLE" in stock_raw:
            estado_stock = "STOCK"
        elif stock_ingresos > 0 or "PREVENTA" in stock_raw:
            if fecha_ingreso:
                estado_stock = f"PREVENTA ({fecha_ingreso})"
            else:
                estado_stock = "PREVENTA PROX."
        else:
            estado_stock = "NOSTOCK"

        # Foto
        foto_id = str(row.get("FOTO", "")).strip()
        if not foto_id or foto_id.lower() == "prueba":
            foto_id = netlify_mapping.get(sku, "")
        
        # 2. Verificar existencia y datos previos para evitar re-procesamiento innecesario
        existing = {}
        try:
            res_existing = supabase.table(PRODUCT_TABLE).select("precio_pesos", "img_url").eq("codigo", sku).execute()
            if res_existing.data:
                existing = res_existing.data[0]
        except:
            pass

        # Upsert en Supabase (Tabla productos operativa)
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

        # Lógica de Imagen: Si no tiene imagen en Supabase, intentamos buscarla
        if not existing.get("img_url"):
            img_url = process_image(foto_id, sku)
            if img_url:
                product_data["img_url"] = img_url
                stats["fotos_procesadas"] += 1
        else:
            # Mantener la que ya existe
            product_data["img_url"] = existing["img_url"]

        try:
            # Upsert usando 'codigo' como identificador único
            res = supabase.table(PRODUCT_TABLE).upsert(product_data, on_conflict="codigo").execute()
            
            if existing:
                old_price = existing.get("precio_pesos", 0)
                if old_price != precio_pesos:
                    stats["precios_cambiados"] += 1
                    logs.append(f"📈 PRECIO: {sku} - {nombre} (${old_price} -> ${precio_pesos})")
                stats["actualizados"] += 1
            else:
                stats["nuevos"] += 1
                logs.append(f"🆕 NUEVO: {sku} - {nombre}")
        except Exception as e:
            print(f"❌ Error guardando {sku}: {e}")
            # Si hay error, no incrementamos stats de éxito

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
