# Roots: store + owners' panel

Two static sites that share one Supabase database.

| Folder | What it is | Who uses it |
|---|---|---|
| `store/` | The storefront. Checkout saves the order and the SINPE receipt to Supabase. | Customers |
| `panel/` | Roots Pedidos. Orders show up live; owners log in with email and password. | Owners only |
| `supabase/schema.sql` | Tables, access rules and the functions both sites call. | Run once |
| `source/` | The original design-canvas storefront and Claude-artifact panel these were built from. | Reference |
| `tools/` | `build_store.py` rebuilds `store/index.html` from `source/storefront.dc.html`. | Developers |

## How orders flow

1. At **Continuar al pago**, the store asks the database for the next order number (`RTS-1001`, `RTS-1002`, ...), so the customer can write it in the SINPE detail.
2. At **Enviar pedido**, the store sends the customer's details, cart and receipt image to `place_order()`. The database recalculates prices, volume discounts, the GAM zone and shipping itself, so a customer can't change the total.
3. The order appears in the panel as **Pago por verificar** within seconds.
4. When an owner confirms the payment, the database takes the bags out of inventory in the same step. Cancelling or rejecting a paid order puts them back.

## One-time setup

### 1. Supabase
1. Create a project at supabase.com (the Free plan is enough to start).
2. **SQL Editor → New query**: paste all of `supabase/schema.sql`, then **Run**. Then do the same with `supabase/002-manual-orders.sql` (manual orders) and `supabase/003-business-and-expenses.sql` (business sales, expenses, and who changed what).
3. **Authentication → Sign In / Providers**: turn **off** "Allow new users to sign up". Owners are invited instead.
4. **Authentication → URL Configuration**: set **Site URL** to the panel's address, for example `https://roots-panel.netlify.app`.
5. For each owner:
   - **Authentication → Users → Invite user**: their email. They'll get a link that opens the panel to create their password.
   - **SQL Editor**: `insert into public.owners (email) values ('their@email.com');`
6. **Project Settings → API**: copy `config.example.js` to `config.js` in both `store/` and `panel/`, then fill in the **Project URL** and the **anon / publishable** key. Never use the `service_role` or secret key in these files. `config.js` is kept out of git; deploy from a folder that has it.

### 2. Netlify
Deploy `store/` and `panel/` as two separate sites. Each folder is ready to deploy as-is, with no build step.

### 3. First login
An owner opens the panel, logs in, and goes to **Ajustes** to set the SINPE number and name, shipping rates, costs and starting stock. The store reads the SINPE details and shipping rates from there.

### 4. Google Sheet copy (optional)
Orders are also written to the tab **Pedidos tienda** in the owners' sheet: one row per order, updated when its status changes in the panel. Edits in the sheet don't go back to the panel.
1. Go to script.google.com → **New project**, paste `sheets/Code.gs`, and save.
2. Select `authorize` → **Run** and allow access. This creates the tab.
3. **Deploy → New deployment → Web app**: Execute as **Me**, Who has access **Anyone**. Copy the `…/exec` URL.
4. In `supabase/sheet-sync.sql`, replace `PASTE_WEB_APP_URL_HERE` with that URL, then run it in the Supabase SQL Editor.

## Removing an owner
Delete their row: `delete from public.owners where email = '...';`, and remove the user under **Authentication → Users**.

## Known limits
- The GAM canton list is an approximation. Update it in both `zone_of()` in the schema and `GAM` in the store to match the courier's zones.
- Prices are set in two places: `tier_price()` in the schema, and `SIZES` in the store and panel. Change all of them together.
- Stock isn't checked at checkout. A sold-out flavor can still be ordered; owners see it when confirming.
