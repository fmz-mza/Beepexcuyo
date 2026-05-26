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
  const mustReset = fresh.length < PRODUCTS_PER_IMAGE;
  const pool = mustReset ? available : fresh;

  // Shuffle Fisher-Yates
  const shuffled = [...pool];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return {
    chosen: shuffled.slice(0, PRODUCTS_PER_IMAGE),
    resetHistory: mustReset
  };
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
    const isPreventa = (p.stock_estado || '').toUpperCase().includes('PREVENTA');
    const stockClass = isPreventa ? 'preventa' : 'in-stock';
    const stockText = isPreventa ? '🕐 Preventa' : '✅ En Stock';
    const nombre = p.producto.length > 55 ? p.producto.slice(0, 52) + '…' : p.producto;
    const marca = (p.marca || 'Genéricos').toUpperCase();
    return `
      <div class="card">
        <div class="img-wrap">
          <img src="${imgUrl}" alt="${nombre}" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22><rect width=%22200%22 height=%22200%22 fill=%22%23f5f5f7%22/><text x=%2250%25%22 y=%2250%25%22 dominant-baseline=%22middle%22 text-anchor=%22middle%22 fill=%22%23999%22 font-size=%2240%22>🐾</text></svg>'"/>
        </div>
        <div class="info">
          <div class="brand">${marca}</div>
          <div class="name">${nombre}</div>
          <div class="price-stock-row">
            <div class="price">${fmt(p.precio_pesos)}</div>
            <div class="stock-badge ${stockClass}">${stockText}</div>
          </div>
        </div>
      </div>`;
  }).join('');

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    width: 1080px;
    height: 1920px;
    background: #0B0D17;
    font-family: 'Plus Jakarta Sans', sans-serif;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  /* Fondo degradado moderno */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background:
      radial-gradient(circle at 10% 15%, rgba(90, 120, 250, 0.16) 0%, transparent 60%),
      radial-gradient(circle at 90% 85%, rgba(180, 80, 250, 0.14) 0%, transparent 60%),
      radial-gradient(circle at 50% 50%, rgba(58, 108, 240, 0.04) 0%, transparent 70%);
    pointer-events: none;
  }

  .header {
    padding: 70px 64px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
  }

  .logo {
    display: flex;
    align-items: center;
    gap: 18px;
  }

  .logo-icon {
    width: 68px; height: 68px;
    background: linear-gradient(135deg, #3a6cf0 0%, #5f86f7 100%);
    border-radius: 20px;
    display: flex; align-items: center; justify-content: center;
    font-size: 36px;
    box-shadow: 0 8px 24px rgba(58, 108, 240, 0.3);
  }

  .logo-text h1 {
    font-family: 'Outfit', sans-serif;
    font-size: 32px; font-weight: 800;
    color: #ffffff; line-height: 1.1;
    letter-spacing: 0.5px;
  }

  .logo-text p {
    font-size: 15px; color: #8a92b2; margin-top: 3px;
    font-weight: 500;
  }

  .date {
    font-size: 16px; color: #7c8ba1;
    text-transform: capitalize;
    font-weight: 600;
    background: rgba(255, 255, 255, 0.05);
    padding: 8px 18px;
    border-radius: 30px;
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  .title-sec {
    padding: 20px 64px 10px;
    text-align: center;
    flex-shrink: 0;
  }

  .title-sec h2 {
    font-family: 'Outfit', sans-serif;
    font-size: 36px;
    font-weight: 800;
    color: #ffffff;
    text-transform: uppercase;
    letter-spacing: 2px;
    background: linear-gradient(135deg, #ffffff 30%, #a5b4fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }

  .title-sec p {
    font-size: 16px;
    color: #7c8ba1;
    margin-top: 6px;
  }

  .grid {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    gap: 32px;
    padding: 30px 64px;
  }

  .card {
    background: rgba(22, 26, 41, 0.65);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 32px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 18px;
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.3);
    backdrop-filter: blur(12px);
  }

  .img-wrap {
    width: 100%;
    height: 400px;
    background: #ffffff;
    border-radius: 22px;
    display: flex; align-items: center; justify-content: center;
    padding: 24px;
    overflow: hidden;
    box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.05);
  }

  .img-wrap img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
  }

  .info {
    padding: 16px 6px 4px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .brand {
    font-size: 11px; font-weight: 700;
    color: #7096ff; text-transform: uppercase;
    letter-spacing: 1.5px;
  }

  .name {
    font-size: 15px; font-weight: 600;
    color: #e2e8f0; line-height: 1.4;
    height: 42px;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  .price-stock-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 8px;
  }

  .price {
    font-family: 'Outfit', sans-serif;
    font-size: 26px; font-weight: 800;
    color: #ff9f0a;
  }

  .stock-badge {
    font-size: 11px; font-weight: 700;
    padding: 4px 10px;
    border-radius: 12px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .stock-badge.in-stock {
    background: rgba(48, 209, 88, 0.15);
    color: #30d158;
    border: 1px solid rgba(48, 209, 88, 0.25);
  }

  .stock-badge.preventa {
    background: rgba(255, 159, 10, 0.15);
    color: #ff9f0a;
    border: 1px solid rgba(255, 159, 10, 0.25);
  }

  .footer {
    padding: 20px 64px 70px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    gap: 8px;
  }

  .footer-text {
    font-size: 15px; color: #7c8ba1;
    font-weight: 500;
  }

  .footer-cta {
    font-family: 'Outfit', sans-serif;
    font-size: 18px; font-weight: 700;
    color: #3a6cf0;
    background: rgba(58, 108, 240, 0.1);
    padding: 8px 24px;
    border-radius: 20px;
    border: 1px solid rgba(58, 108, 240, 0.2);
    letter-spacing: 0.5px;
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

  <div class="title-sec">
    <h2>Recomendados de hoy</h2>
    <p>Los mejores productos seleccionados para tu mascota</p>
  </div>

  <div class="grid">${cards}</div>

  <div class="footer">
    <span class="footer-text">Consultá disponibilidad y precios en la web</span>
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
  await page.setViewport({ width: 1080, height: 1920, deviceScaleFactor: 2 });
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
  const { chosen, resetHistory } = pickProducts(allProducts, usedThisMonth);
  if (resetHistory) {
    console.log('🔄 Se agotaron los productos sin usar. Reseteando ciclo del mes.');
  }
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
  const baseUsed = resetHistory ? [] : usedThisMonth;
  const newUsed = [...baseUsed, ...chosen.map(p => String(p.codigo))];
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
