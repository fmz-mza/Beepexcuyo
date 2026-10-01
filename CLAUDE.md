# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Beepex Cuyo: a wholesale pet-product catalog (Argentina, Spanish-language UI/comments). There is **no build step, bundler, test suite, or linter**. The frontend is three standalone HTML files served as-is; the backend is a Supabase project (`mmerrzniuxbrjryhcsda`) plus scheduled GitHub Actions scripts.

## Architecture

```
Beepaw API (beepex.dev/api/landings/products)
   └─ sync.py (hourly) ──► Supabase table `productos` + Storage bucket `fotos` (<sku>.webp 1024px, thumbs/<sku>.webp 400px)
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
  - Images: only fetched if `img_url` is empty; tries Drive/direct URLs, then `images/SKU_<sku>.jpg` from the GitHub repos, converts to WEBP ≤1024px and uploads to the `fotos` bucket. Each new photo also gets a 400px copy at `fotos/thumbs/<sku>.webp` (see "Catalog frontend"). The committed `images/` folder is a fallback source for this.
  - Variants: the API already sends `agrupador`, `caracteristica`, `colorCol`, `categorizacion` per SKU; they are stored in `productos.agrupador/caracteristica/color/categorizacion` (migration 0004) on every run. `get_variant_key` is unrelated — it only feeds the price rules. `categorizacion` is a category path (e.g. `COMEDEROS > FOOD-E`), **not** a variation axis; the catalog deduces axes from `caracteristica`/`color`.
  - Upserts on `codigo`, notifies Discord.
- **`backfill_thumbs.py`** + `.github/workflows/backfill-thumbs.yml` (manual `workflow_dispatch`): generates `fotos/thumbs/<sku>.webp` from the existing originals (idempotent; `force=1` regenerates). Needed only to rebuild thumbnails; `sync.py` makes them for new photos. There is no Python on the dev machine, so scripts run through GitHub Actions (`gh workflow run sync.yml` triggers an extra sync; a full run takes ~6 min).
- **Catalog frontend (`beepex-cuyo.html`) — how the grid works**:
  - **Tabs** (`CAT_TABS`, state in `activeStock`: `'DISP'|'LIQUIDACION'|'PREVENTA'`): Disponible = `STOCK` + `STOCK LIQUIDACION`, Oportunidades = any liquidation, Preventa = `PREVENTA*`. `tabMatch()` + `baseVisible()` (admin-disabled SKUs and the admin `catalog_show_nostock` setting; NOSTOCK items still go to the end under "Sin stock") are the single source for the grid, tab counters and rubro chips. Sale mode ignores tabs. Tab/brand/rubro persist in `sessionStorage` (`beepex_filters`); view mode in `localStorage` (`beepex_view`). Rubro chips re-render on every tap: `renderRubros()` preserves `scrollLeft` on purpose.
  - **Images**: cards load `fotos/thumbs/<sku>.webp` (`loadCardImg`, falls back to the 1024px original if the thumb is missing); lightbox, info modal, PDF and sharing use the original (`imgCache[sku]` holds the original URL). A 1024×1024 bitmap is ~4 MB decoded vs ~0.6 MB for a thumb — this was the main iOS crash driver. `imgObserver` watches `.card-img` (not the `<img>`: it is `display:none` until loaded and hidden elements never intersect) in both directions: far cards (>1200px) release their `src` so decoded bitmaps stay bounded.
  - **Infinite scroll**: `#grid-sentinel` must keep `order:10000` — cards have `order:9999`, without it the sentinel sits at the top of the grid and every scroll loads another page (hundreds of cards in the DOM).
  - **Variants**: in card view (not sale mode, not list view) `buildDisplayItems()` merges SKUs with the same `agrupador` (≥2 visible in the current tab/filters) into one group card (`createGroupCard`, id `card-g_<slug>`, registry `_groupMap`); the grid pages those items, not SKUs. The modal (`openGroup`, `_grp`) selects a variant on tap (photo, code, EAN, PVP, stock) **without** touching quantities; qty only via −/+/typing; "Agregar" calls `chg()` per SKU, so the cart stays per SKU. "Compartir producto" there builds one PNG per selected variant with `buildProductShareFile()` (same generator as the single-product info modal).
  - **List view** (`toggleView`, `renderList`): per-SKU rows without photos, grouped by rubro, rendered in chunks; uses the same `chg()` cart. Cart-change hooks: `updateCount()` → `listRefresh()` / `refreshGroupCards()`; `patchPrices()` re-renders.
  - No per-card entrance/filter animations on purpose (each card with inline `opacity`/`transform` becomes its own compositing layer; hundreds of them crash iOS Safari).
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
- Security is entirely RLS (the HTML files use the public anon key). The schema/policies are not versioned in the repo: only a handful of migrations exist in Supabase (`list_migrations`). Migrations applied since 2026-09-27 are mirrored in `supabase/migrations/` (0001–0004). Since 2026-09-26 a BEFORE UPDATE trigger on `profiles` only lets admins (or service role, where `auth.uid()` is null) change `is_admin`/`approved`; before that, any logged-in user could promote themselves. To test DB changes without risk, run them in a DO block that ends with a deliberate `RAISE EXCEPTION` (auto-rollback), then verify the DB is unchanged.
- `sync.py` only logs/alerts when `precio_pesos` changes — never compares old vs. new `pvp` directly, and for SKUs where none of the special pricing rules trigger (identical base/lista14/lista20, SKU < 11432, no liquidación), `precio_pesos` is set straight from `precioBase`, never reading `pvp` at all. A supplier PVP change with the same `precioBase` silently overwrites every hour with zero trace (real case: SKU 11307, sep/2026 — checked `list_migrations`/triggers, found none, then searched the last 15 `sync.yml` run logs for the SKU and found nothing, consistent with this code path). Since 2026-09-30, `productos_historial_precios` (trigger `trg_log_cambio_precio_producto`, see migration 0002) logs every real change to `precio_pesos`/`precio_pvp` regardless of which script makes it — query it by `codigo` to answer "when did this price change and to what" instead of re-deriving the above from scratch. `changed_at` is `timestamptz` (UTC instant, consistent with every other timestamp column in this schema); read `productos_historial_precios_ar` (migration 0003) instead for the same rows with a ready-made `changed_at_ar` column already converted to `America/Argentina/Buenos_Aires` — don't change the database's timezone setting to "fix" this, that would shift every other timestamptz column in the project at once.
- `irm`, `scoop`, and `~scoopapps7zip26.00` at the root are stray files from shell mishaps, not part of the project.
- `beepex-cuyo.html`'s Supabase client must keep `detectSessionInUrl: false`. `initAuth()` (the app's own hand-rolled parser for the `#access_token=...&type=recovery` hash from password-reset/email-confirmation links) only runs after the product catalog finishes loading. With `detectSessionInUrl: true`, the SDK silently consumes and strips that hash on its own during `createClient()`, long before `initAuth()` gets a chance to read it — the reset-password modal then never appears, with no error. This was "fixed" several times by patching `initAuth()`'s parsing logic without touching this setting, which never addressed the actual race. A `.claude/launch.json` (`npx http-server`) is included for reproducing this locally: load `#access_token=x&type=recovery` and check `window.location.hash` isn't already empty by the time the page settles.
- **iOS crash / reload when scrolling and tapping filter chips** (reported by the owner on a real iPhone; "Ocurrió un problema varias veces en …" is Safari killing the tab, i.e. memory/GPU pressure). It took three rounds and is confirmed fixed on device; the causes, in order of impact: (1) every card loaded the full 1024×1024 photo (~4 MB decoded each) → thumbnails; (2) decoded images were never released → bidirectional `imgObserver`; (3) the sentinel of the infinite scroll had no `order`, so every scroll loaded another page and the DOM grew to 600+ cards; (4) per-card flip/entrance animations (removed). `overscroll-behavior-y: contain` on `html`/`body` is only defensive and was never the cause. If it ever recurs, check these four before guessing; the next step would be windowing the DOM (removing far-away cards), which is not implemented.
- Testing the catalog locally: `.claude/launch.json` serves the repo with `npx http-server` on 8123. The in-app browser pane does not fire real `scroll` events while hidden — dispatch `window.dispatchEvent(new Event('scroll'))` after `scrollTo` to exercise infinite scroll, and pass a cache-buster (`?v=N`) when reloading. Setting `userApproved = true` in the console is enough to exercise cart/price flows without logging in.
- Commit messages in this repo follow `Fix:`/`Feat:` + Spanish description + emoji.
