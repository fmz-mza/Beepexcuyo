import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const RESEND_API_KEY = "re_DQmiqBMZ_KEPhiKyrvvtyV6uM19CDXeDa";
const ADMIN_EMAIL = "fernandozabosm@icloud.com";
const FROM_EMAIL = "onboarding@resend.dev";
const SUPABASE_URL = "https://mmerrzniuxbrjryhcsda.supabase.co";

serve(async (req) => {
  try {
    const body = await req.json();
    const record = body.record;

    if (!record) return new Response("No record", { status: 400 });

    // Si es aprobación via link
    const url = new URL(req.url);
    const approveId = url.searchParams.get("approve");
    if (approveId) {
      // Token secreto para verificar que el link es válido
      const token = url.searchParams.get("token");
      const expectedToken = btoa(approveId + "beepex_secret_2026").replace(/=/g, "");
      if (token !== expectedToken) {
        return new Response("Token inválido", { status: 403 });
      }

      const supabase = createClient(
        SUPABASE_URL,
        Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? ""
      );

      const { error } = await supabase
        .from("profiles")
        .update({ approved: true })
        .eq("id", approveId);

      if (error) throw error;

      // Buscar email del usuario para avisarle
      const { data: authUser } = await supabase.auth.admin.getUserById(approveId);
      const userEmail = authUser?.user?.email;
      const { data: profile } = await supabase
        .from("profiles")
        .select("nombre")
        .eq("id", approveId)
        .single();

      // Mandar email al usuario avisando que fue aprobado
      if (userEmail) {
        await fetch("https://api.resend.com/emails", {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${RESEND_API_KEY}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            from: FROM_EMAIL,
            to: userEmail,
            subject: "✅ Tu acceso al catálogo Beepex Cuyo fue aprobado",
            html: approvedEmailHtml(profile?.nombre || userEmail),
          }),
        });
      }

      // Respuesta HTML de confirmación
      return new Response(successHtml(profile?.nombre || "el usuario"), {
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    }

    // Nuevo registro — mandar email de aviso al admin
    const nombre = record.nombre || "Sin nombre";
    const userId = record.id;

    // Buscar email del usuario recién registrado
    const supabase = createClient(
      SUPABASE_URL,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? ""
    );
    const { data: authUser } = await supabase.auth.admin.getUserById(userId);
    const userEmail = authUser?.user?.email || "email no disponible";
    const createdAt = new Date(record.created_at).toLocaleString("es-AR", {
      timeZone: "America/Argentina/Mendoza",
    });

    // Generar token de aprobación
    const token = btoa(userId + "beepex_secret_2026").replace(/=/g, "");
    const approveUrl = `${SUPABASE_URL}/functions/v1/notify-new-user?approve=${userId}&token=${token}`;

    const emailRes = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: FROM_EMAIL,
        to: ADMIN_EMAIL,
        subject: `🐾 Nuevo registro en Beepex Cuyo — ${nombre}`,
        html: adminEmailHtml(nombre, userEmail, createdAt, approveUrl),
      }),
    });

    const emailData = await emailRes.json();
    return new Response(JSON.stringify({ ok: true, email: emailData }), {
      headers: { "Content-Type": "application/json" },
    });

  } catch (err) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});

// ── Email HTML para el admin ──────────────────────────────────────────────────
function adminEmailHtml(nombre: string, email: string, fecha: string, approveUrl: string) {
  return `<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:system-ui,-apple-system,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:40px 20px;">
    <tr><td align="center">
      <table width="100%" style="max-width:500px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
        <!-- Header -->
        <tr>
          <td style="background:#1a1b22;padding:28px 32px;text-align:center;">
            <div style="font-size:32px;margin-bottom:8px;">🐾</div>
            <div style="color:#ffffff;font-size:20px;font-weight:800;font-family:system-ui;">Beepex Cuyo</div>
            <div style="color:#6b7280;font-size:12px;margin-top:4px;">Catálogo Mayorista</div>
          </td>
        </tr>
        <!-- Badge -->
        <tr>
          <td style="padding:0 32px;">
            <div style="background:#fef3c7;border:1px solid #fbbf24;border-radius:8px;padding:10px 16px;margin:24px 0 0;text-align:center;">
              <span style="color:#92400e;font-size:13px;font-weight:700;">⏳ Nuevo registro pendiente de aprobación</span>
            </div>
          </td>
        </tr>
        <!-- Datos usuario -->
        <tr>
          <td style="padding:20px 32px;">
            <table width="100%" style="border-collapse:collapse;">
              <tr>
                <td style="padding:10px 0;border-bottom:1px solid #f3f4f6;">
                  <div style="font-size:11px;color:#9ca3af;font-weight:600;text-transform:uppercase;letter-spacing:.5px;">Nombre / Negocio</div>
                  <div style="font-size:16px;font-weight:700;color:#111827;margin-top:4px;">${nombre}</div>
                </td>
              </tr>
              <tr>
                <td style="padding:10px 0;border-bottom:1px solid #f3f4f6;">
                  <div style="font-size:11px;color:#9ca3af;font-weight:600;text-transform:uppercase;letter-spacing:.5px;">Email</div>
                  <div style="font-size:14px;color:#374151;margin-top:4px;">${email}</div>
                </td>
              </tr>
              <tr>
                <td style="padding:10px 0;">
                  <div style="font-size:11px;color:#9ca3af;font-weight:600;text-transform:uppercase;letter-spacing:.5px;">Fecha de registro</div>
                  <div style="font-size:14px;color:#374151;margin-top:4px;">${fecha}</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <!-- Botón aprobar -->
        <tr>
          <td style="padding:0 32px 32px;">
            <a href="${approveUrl}" style="display:block;background:#4a7cff;color:#ffffff;text-decoration:none;text-align:center;padding:14px;border-radius:10px;font-size:15px;font-weight:700;">
              ✅ Aprobar acceso al catálogo
            </a>
            <p style="font-size:11px;color:#9ca3af;text-align:center;margin-top:12px;">
              Este link aprueba el acceso de ${nombre} al catálogo mayorista.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`;
}

// ── Email HTML para el usuario aprobado ───────────────────────────────────────
function approvedEmailHtml(nombre: string) {
  return `<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:system-ui,-apple-system,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:40px 20px;">
    <tr><td align="center">
      <table width="100%" style="max-width:500px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
        <tr>
          <td style="background:#1a1b22;padding:28px 32px;text-align:center;">
            <div style="font-size:32px;margin-bottom:8px;">🐾</div>
            <div style="color:#ffffff;font-size:20px;font-weight:800;">Beepex Cuyo</div>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;text-align:center;">
            <div style="font-size:48px;margin-bottom:16px;">✅</div>
            <h2 style="color:#111827;font-size:22px;margin:0 0 12px;">¡Hola ${nombre}!</h2>
            <p style="color:#6b7280;font-size:15px;line-height:1.6;margin:0 0 24px;">
              Tu acceso al catálogo mayorista de Beepex Cuyo fue <strong style="color:#059669;">aprobado</strong>.<br>
              Ya podés ver precios, hacer pedidos y compartir productos.
            </p>
            <a href="https://fmz-mza.github.io/Beepexcuyo/beepex-cuyo.html" 
               style="display:inline-block;background:#4a7cff;color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:10px;font-size:15px;font-weight:700;">
              Ir al catálogo →
            </a>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`;
}

// ── Página de confirmación al aprobar ────────────────────────────────────────
function successHtml(nombre: string) {
  return `<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Usuario aprobado</title></head>
<body style="margin:0;padding:40px 20px;background:#f4f4f5;font-family:system-ui,sans-serif;text-align:center;">
  <div style="max-width:400px;margin:0 auto;background:#fff;border-radius:16px;padding:40px;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
    <div style="font-size:56px;margin-bottom:16px;">✅</div>
    <h2 style="color:#111827;margin:0 0 12px;">¡Acceso aprobado!</h2>
    <p style="color:#6b7280;margin:0;">${nombre} ya puede acceder al catálogo mayorista.<br>Se le envió un email de confirmación.</p>
  </div>
</body>
</html>`;
}
