# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Beepex Cuyo: a wholesale pet-product catalog (Argentina, Spanish-language UI/comments). There is **no build step, bundler, test suite, or linter**. The frontend is three standalone HTML files served as-is; the backend is a Supabase project (`mmerrzniuxbrjryhcsda`) plus scheduled GitHub Actions scripts.

## Architecture

```
Beepaw API (beepex.dev/api/landings/products)
   └─ sync.py (hourly) ──► Supabase table `productos` + Storage bucket `fotos` (<sku>.webp)
                                   │
        ┌──────────────────────────┼───────────────────────────┐
  beepex-cuyo.html          beepex-admin.html            beepex-pos.html
  (public catalog/cart)     (admin panel)                (POS / accounts)
                                   │
        generate_excel.py (daily → Beepex.xlsx in Storage)   daily-status/generate.js (daily WhatsApp status image via Puppeteer → email via Resend)
```

- **Frontend** (`beepex-cuyo.html` ~6-8k lines, `beepex-admin.html`, `beepex-pos.html`): each is a self-contained single file with inline CSS/JS, using `@supabase/supabase-js` from a CDN and talking to Supabase directly (both supabase-js and raw `/rest/v1/...` fetches). The Supabase URL and the publishable anon key are hardcoded in each file (that is expected; security relies on RLS). Auth tokens are kept in `localStorage` (`sb_access_token`, `admin_token`, ...). Tables used: `productos`, `profiles` (has `approved` flag gating catalog access), `orders`/`order_items`, `pos_orders`, `clients`, `payments`/`payment_allocations`/`account_movements`, `user_prices`, `settings`, `presence`, `debt_alerts`, `seller_profiles`, `stock_movements`. Changes to settings use PATCH because of RLS policies. The catalog hides SKUs disabled in admin even for admin users.
- **PWA / deploy**: `manifest.json` + `sw.js` (network-first cache of only `beepex-cuyo.html` and `beepex-pos.html`; bump `CACHE` in `sw.js` when changing the cached asset list). Every push to `main` deploys the **whole repo root** to GitHub Pages (`.github/workflows/deploy.yml`) at `fmz-mza.github.io/Beepexcuyo/`, so anything committed here is public.
- **`sync.py`** — the core business logic; pricing rules live here and are easy to break:
  - Source is the Beepaw API; `SKUS_SIN_REPOSICION` is a hardcoded set with no transit/preorder.
  - `precio_pesos` rules, in priority: liquidation (`liquidacion * 1.23`) → if base/lista14/lista20 are identical: `pvp/2` (when pvp exists) or `base * 1.21` (no pvp) → for GENERICOS with SKU >= 11432 and no PVP, use base directly → fallback `pvp/2` for new SKUs with no base.
  - Stock under 10 units counts as 0; transit under 10 is ignored. `stock_estado` is one of `STOCK`, `STOCK LIQUIDACION`, `PREVENTA (<eta>)`, `PREVENTA PROX.`, `NOSTOCK`, `NOSTOCK LIQUIDACION`; the frontend and `daily-status` filter on these strings.
  - Images: only fetched if `img_url` is empty; tries Drive/direct URLs, then `images/SKU_<sku>.jpg` from the GitHub repos, converts to WEBP ≤1024px and uploads to the `fotos` bucket. The committed `images/` folder is a fallback source for this.
  - Upserts on `codigo`, notifies Discord.
- **`generate_excel.py`**: reads `productos`, builds the price-list workbook with embedded photos, uploads it to Storage.
- **`daily-status/`**: own `package.json` (puppeteer, resend). Picks 4 random in-stock products per day without repeating within a month; the history is `used-products.json`, which the workflow commits back to `main` (hence the frequent `chore: update used products [skip ci]` commits — pull/rebase before pushing).
- **`supabase/functions/notify-new-user/index.ts`**: Deno edge function; emails the admin on new signup with an approve link (sets `profiles.approved`), and emails the user on approval. Reads `RESEND_API_KEY`, `APPROVAL_TOKEN_SECRET`, `SERVICE_ROLE_KEY` (and optional `ADMIN_EMAIL`, `FROM_EMAIL`) from env; `verify_jwt` is off because the approve link is opened from an email. The repo copy mirrors deployed v11 (synced 2026-09-26); the stale root-level `index.ts` with hardcoded secrets was deleted. Deployed via Supabase, not by any workflow here — re-check with `get_edge_function` before assuming the repo matches.
- **`sync-stock-beepex.md`**: contract for the ERP RPC `actualizar_stock_beepex` (lives in a separate ERP repo's migrations, not here).

## Commands

Run scripts locally (needs `SUPABASE_URL` and `SUPABASE_KEY`, service-role for writes; a `.env` is loaded via python-dotenv; `sync.py` also uses `DISCORD_WEBHOOK_URL`, `SPREADSHEET_ID`):

```bash
pip install -r requirements.txt
python sync.py
python generate_excel.py            # Discord webhook is only used in the workflow
npm install --prefix daily-status && node daily-status/generate.js   # needs RESEND_API_KEY
```

To preview the frontend, serve the repo root statically (e.g. `python -m http.server`) and open `beepex-cuyo.html`. Workflows can also be triggered manually via `workflow_dispatch`.

## Gotchas

- Old versions of the edge function with a hardcoded Resend API key and the secret `beepex_secret_2026` are still in git history (public repo). Production now uses env vars, but the old key and secret must be considered leaked until rotated (the approval token is `btoa(userId + secret)`).
- `images/` (~75 MB) and `.git` (~60 MB) are committed and published with the site.
- Security is entirely RLS (the HTML files use the public anon key). The schema/policies are not versioned in the repo: only 4 migrations exist in Supabase (`list_migrations`). Applied migrations are mirrored in `supabase/migrations/`. Since 2026-09-26 a BEFORE UPDATE trigger on `profiles` only lets admins (or service role, where `auth.uid()` is null) change `is_admin`/`approved`; before that, any logged-in user could promote themselves. To test DB changes without risk, run them in a DO block that ends with a deliberate `RAISE EXCEPTION` (auto-rollback), then verify the DB is unchanged.
- `irm`, `scoop`, and `~scoopapps7zip26.00` at the root are stray files from shell mishaps, not part of the project.
- `beepex-cuyo.html`'s Supabase client must keep `detectSessionInUrl: false`. `initAuth()` (the app's own hand-rolled parser for the `#access_token=...&type=recovery` hash from password-reset/email-confirmation links) only runs after the product catalog finishes loading. With `detectSessionInUrl: true`, the SDK silently consumes and strips that hash on its own during `createClient()`, long before `initAuth()` gets a chance to read it — the reset-password modal then never appears, with no error. This was "fixed" several times by patching `initAuth()`'s parsing logic without touching this setting, which never addressed the actual race. A `.claude/launch.json` (`npx http-server`) is included for reproducing this locally: load `#access_token=x&type=recovery` and check `window.location.hash` isn't already empty by the time the page settles.
- The filter chips (`#brandFilters`, `#rubroChips`) sit right at the top of the catalog, at scroll position 0. `html`/`body` set `overscroll-behavior-y: contain` to stop a touch drag there from being interpreted as mobile Chrome/Safari's native pull-to-refresh (which froze the UI then reloaded the whole page — a recurring complaint before this was identified). Keep this when touching the top-of-page layout.
- Commit messages in this repo follow `Fix:`/`Feat:` + Spanish description + emoji.
