const puppeteer = require('puppeteer');
const { Resend } = require('resend');
const fs = require('fs');
const path = require('path');

const SUPABASE_URL    = process.env.SUPABASE_URL;
const SUPABASE_ANON   = process.env.SUPABASE_ANON_KEY || process.env.SUPABASE_KEY;
const RESEND_API_KEY  = process.env.RESEND_API_KEY;
const BUCKET_URL      = `${SUPABASE_URL}/storage/v1/object/public/fotos`;
const USED_FILE       = path.join(__dirname, 'used-products.json');
const PRODUCTS_PER_IMAGE = 4;
const TO_EMAIL        = 'fzabos@gmail.com';

// ── 1. Cargar historial de productos usados este mes ─────────────────────────
function loadUsed() {
  if (!fs.existsSync(USED_FILE)) return {};
  try { return JSON.parse(fs.readFileSync(USED_FILE, 'utf8')); }
  catch { return {}; }
}

function saveUsed(data) {
  fs.writeFileSync(USED_FILE, JSON.stringify(data, null, 2));
}

function getMonthKey() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

// ── 2. Traer productos de Supabase ───────────────────────────────────────────
async function fetchProducts() {
  const url = `${SUPABASE_URL}/rest/v1/productos?select=codigo,producto,marca,precio_pesos,stock_estado&order=marca.asc`;
  const res = await fetch(url, {
    headers: {
      'apikey': SUPABASE_ANON,
      'Authorization': `Bearer ${SUPABASE_ANON}`
    }
  });
  if (!res.ok) throw new Error(`Supabase error: ${res.status}`);
  return res.json();
}

// ── 3. Elegir 4 productos random sin repetir en el mes ───────────────────────
function pickProducts(all, usedThisMonth) {
  // Solo productos con stock
  const available = all.filter(p => {
    const s = (p.stock_estado || '').toUpperCase();
    return s === 'STOCK' || s.includes('PREVENTA');
  });

  // Excluir los ya usados este mes
  const fresh = available.filter(p => !usedThisMonth.includes(String(p.codigo)));

  // Si se agotaron los fresh, resetear (nuevo ciclo)
  const pool = fresh.length >= PRODUCTS_PER_IMAGE ? fresh : available;

  // Shuffle Fisher-Yates
  const shuffled = [...pool];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled.slice(0, PRODUCTS_PER_IMAGE);
}

// ── 4. Formatear precio ───────────────────────────────────────────────────────
function fmt(n) {
  return '$' + Number(n).toLocaleString('es-AR', { maximumFractionDigits: 0 });
}

// ── 5. Generar HTML del estado ────────────────────────────────────────────────
function buildHTML(products) {
  const today = new Date().toLocaleDateString('es-AR', {
    weekday: 'long', day: 'numeric', month: 'long'
  });

  const cards = products.map(p => {
    const imgUrl = `${BUCKET_URL}/${p.codigo}.webp`;
    const stock  = (p.stock_estado || '').toUpperCase().includes('PREVENTA') ? '🕐 Preventa' : '✅ En stock';
    const nombre = p.producto.length > 42 ? p.producto.slice(0, 42) + '…' : p.producto;
    return `
      <div class="card">
        <div class="img-wrap">
          <img src="${imgUrl}" alt="${nombre}" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22><rect width=%22200%22 height=%22200%22 fill=%22%23222%22/><text x=%2250%25%22 y=%2250%25%22 dominant-baseline=%22middle%22 text-anchor=%22middle%22 fill=%22%23555%22 font-size=%2240%22>🐾</text></svg>'"/>
        </div>
        <div class="info">
          <div class="brand">${p.marca}</div>
          <div class="name">${nombre}</div>
          <div class="price">${fmt(p.precio_pesos)}</div>
          <div class="stock">${stock}</div>
        </div>
      </div>`;
  }).join('');

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;600;700&display=swap');

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    width: 1080px;
    height: 1080px;
    background: #0e0f14;
    font-family: 'Inter', sans-serif;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  /* Fondo degradado sutil */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background:
      radial-gradient(ellipse 60% 40% at 20% 10%, rgba(58,108,240,.18) 0%, transparent 70%),
      radial-gradient(ellipse 50% 35% at 80% 90%, rgba(240,165,0,.12) 0%, transparent 70%);
    pointer-events: none;
  }

  .header {
    padding: 36px 48px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
  }

  .logo {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .logo-icon {
    width: 52px; height: 52px;
    background: #3a6cf0;
    border-radius: 14px;
    display: flex; align-items: center; justify-content: center;
    font-size: 28px;
  }

  .logo-text h1 {
    font-family: 'Syne', sans-serif;
    font-size: 22px; font-weight: 800;
    color: #fff; line-height: 1.1;
  }

  .logo-text p {
    font-size: 12px; color: #888; margin-top: 2px;
  }

  .date {
    font-size: 13px; color: #666;
    text-transform: capitalize;
  }

  .divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, #2a2d3e, transparent);
    margin: 0 48px;
    flex-shrink: 0;
  }

  .grid {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    gap: 20px;
    padding: 20px 48px;
  }

  .card {
    background: #16181f;
    border: 1px solid #2a2d3e;
    border-radius: 18px;
    overflow: hidden;
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0;
  }

  .img-wrap {
    width: 180px;
    height: 100%;
    flex-shrink: 0;
    background: #1e2028;
    display: flex; align-items: center; justify-content: center;
    overflow: hidden;
  }

  .img-wrap img {
    width: 100%; height: 100%;
    object-fit: cover;
  }

  .info {
    flex: 1;
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .brand {
    font-size: 10px; font-weight: 700;
    color: #3a6cf0; text-transform: uppercase;
    letter-spacing: 1px;
  }

  .name {
    font-size: 13px; font-weight: 600;
    color: #e8eaf0; line-height: 1.35;
  }

  .price {
    font-family: 'Syne', sans-serif;
    font-size: 20px; font-weight: 800;
    color: #f0a500; margin-top: 4px;
  }

  .stock {
    font-size: 10px; color: #666; margin-top: 2px;
  }

  .footer {
    padding: 16px 48px 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    gap: 8px;
  }

  .footer-text {
    font-size: 13px; color: #555;
  }

  .footer-cta {
    font-size: 13px; font-weight: 700;
    color: #3a6cf0;
  }
</style>
</head>
<body>
  <div class="header">
    <div class="logo">
      <div class="logo-icon">🐾</div>
      <div class="logo-text">
        <h1>BEEPEX CUYO</h1>
        <p>Distribuidora de mascotas</p>
      </div>
    </div>
    <div class="date">${today}</div>
  </div>

  <div class="divider"></div>

  <div class="grid">${cards}</div>

  <div class="footer">
    <span class="footer-text">Consultá disponibilidad y precios →</span>
    <span class="footer-cta">fmz-mza.github.io/Beepexcuyo</span>
  </div>
</body>
</html>`;
}

// ── 6. Capturar screenshot con Puppeteer ─────────────────────────────────────
async function screenshot(html) {
  const browser = await puppeteer.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1080, height: 1080, deviceScaleFactor: 1 });
  await page.setContent(html, { waitUntil: 'networkidle0', timeout: 30000 });
  // Esperar que las imágenes carguen
  await page.evaluate(() => {
    return Promise.all(
      [...document.images].map(img =>
        img.complete ? Promise.resolve() :
        new Promise(res => { img.onload = res; img.onerror = res; })
      )
    );
  });
  const buffer = await page.screenshot({ type: 'png' });
  await browser.close();
  return buffer;
}

// ── 7. Enviar por mail con Resend ─────────────────────────────────────────────
async function sendMail(imageBuffer, products) {
  const resend = new Resend(RESEND_API_KEY);
  const names = products.map(p => p.producto).join(', ');
  const today = new Date().toLocaleDateString('es-AR', {
    weekday: 'long', day: 'numeric', month: 'long'
  });

  await resend.emails.send({
    from: 'Beepex Cuyo <onboarding@resend.dev>',
    to: TO_EMAIL,
    subject: `📸 Estado WhatsApp del día — ${today}`,
    html: `
      <div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px;">
        <h2 style="color:#3a6cf0;">🐾 Beepex Cuyo — Estado del día</h2>
        <p style="color:#666;">${today}</p>
        <p style="margin:16px 0;">Productos de hoy: <strong>${names}</strong></p>
        <p style="color:#888;font-size:13px;">
          Guardá la imagen adjunta y subila a tu estado de WhatsApp.
        </p>
      </div>
    `,
    attachments: [{
      filename: `beepex-status-${new Date().toISOString().slice(0,10)}.png`,
      content: imageBuffer.toString('base64')
    }]
  });
}

// ── Main ──────────────────────────────────────────────────────────────────────
(async () => {
  console.log('🐾 Beepex Daily Status — iniciando...');

  // Cargar historial
  const used = loadUsed();
  const monthKey = getMonthKey();
  const usedThisMonth = used[monthKey] || [];
  console.log(`Mes: ${monthKey} | Productos usados este mes: ${usedThisMonth.length}`);

  // Traer productos
  const allProducts = await fetchProducts();
  console.log(`Productos en catálogo: ${allProducts.length}`);

  // Elegir 4
  const chosen = pickProducts(allProducts, usedThisMonth);
  console.log('Productos elegidos:', chosen.map(p => `${p.codigo} - ${p.producto}`).join(' | '));

  // Generar imagen
  const html = buildHTML(chosen);
  console.log('Generando imagen con Puppeteer...');
  const imgBuffer = await screenshot(html);
  console.log(`Imagen generada: ${imgBuffer.length} bytes`);

  // Enviar mail
  console.log(`Enviando a ${TO_EMAIL}...`);
  await sendMail(imgBuffer, chosen);
  console.log('✅ Mail enviado');

  // Actualizar historial
  const newUsed = [...usedThisMonth, ...chosen.map(p => String(p.codigo))];
  used[monthKey] = [...new Set(newUsed)]; // deduplicar por si acaso

  // Limpiar meses viejos (guardar solo los últimos 2)
  const keys = Object.keys(used).sort();
  if (keys.length > 2) keys.slice(0, -2).forEach(k => delete used[k]);

  saveUsed(used);
  console.log(`Historial actualizado: ${used[monthKey].length} productos usados en ${monthKey}`);
})().catch(err => {
  console.error('❌ Error:', err);
  process.exit(1);
});
