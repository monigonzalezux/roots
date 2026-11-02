// Roots · copies store orders into the owners' Google Sheet.
// Supabase sends every new order and every status change here; one row per order.
// The row is updated in place, so the sheet always shows each order's latest status.
// Edits made in the sheet do NOT go back to the panel: change statuses in the panel.

const SHEET_ID = '14fg0fDN6CY4_ycJ_AMPWlR_e58mDux_GP83bV8gobIs';
const TAB = 'Pedidos tienda';
const TOKEN = 'PASTE_SYNC_TOKEN_HERE'; // must match supabase/sheet-sync.sql

const HEAD = ['Pedido', 'Fecha', 'Estado', 'Cliente', 'Teléfono', 'Correo', 'Provincia', 'Cantón', 'Distrito', 'Señas',
  'Indicaciones', 'Zona', 'Productos', 'Bolsas', 'Subtotal', 'Descuento volumen', 'Envío', 'Total', 'Última actualización'];
const STATUS = { por_verificar: 'Pago por verificar', pagado: 'Pago confirmado', preparando: 'En preparación', enviado: 'Enviado',
  entregado: 'Entregado', rechazado: 'Pago rechazado', cancelado: 'Cancelado' };
const FLAV = { mango: 'Mango', fresa: 'Fresa', pina: 'Piña' };
const SIZE = { g: ['Grande', 'Grandes'], m: ['Mini', 'Minis'] };

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return reply({ ok: false, error: 'bad_json' }); }
  if (body.token !== TOKEN || !body.order || !body.order.id) return reply({ ok: false, error: 'not_allowed' });
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const sh = sheet();
    const row = toRow(body.order);
    const last = sh.getLastRow();
    const ids = last > 1 ? sh.getRange(2, 1, last - 1, 1).getValues().map(r => r[0]) : [];
    const i = ids.indexOf(row[0]);
    if (i >= 0) sh.getRange(i + 2, 1, 1, row.length).setValues([row]);
    else sh.appendRow(row);
  } finally {
    lock.releaseLock();
  }
  return reply({ ok: true });
}

function sheet() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  let sh = ss.getSheetByName(TAB);
  if (!sh) {
    sh = ss.insertSheet(TAB);
    sh.appendRow(HEAD);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, HEAD.length).setFontWeight('bold');
    sh.getRange('B:B').setNumberFormat('d/m/yyyy h:mm');
    sh.getRange('S:S').setNumberFormat('d/m/yyyy h:mm');
    sh.getRange('O:R').setNumberFormat('"₡"#,##0');
  }
  return sh;
}

function toRow(o) {
  const c = o.customer || {};
  const lines = o.lines || [];
  const products = lines.map(l => {
    if (l.kind === 'pack') {
      const mix = Object.keys(FLAV).filter(f => l.mix && l.mix[f]).map(f => l.mix[f] + ' ' + FLAV[f]).join(', ');
      return l.qty + '× ' + (l.label || 'Pack de ' + l.n + ' ' + SIZE[l.size][1]) + ' (' + mix + ')';
    }
    return l.qty + '× ' + FLAV[l.flavor] + ' ' + SIZE[l.size][0];
  }).join(' · ');
  const bags = lines.reduce((n, l) => n + (l.kind === 'pack' ? l.n * l.qty : l.qty), 0);
  return [
    o.id, new Date(o.created_at), STATUS[o.status] || o.status,
    c.name || '', c.phone || '', c.email || '', c.prov || '', c.canton || '', c.distrito || '', c.addr || '', c.notes || '',
    o.zone === 'gam' ? 'GAM' : o.zone === 'retiro' ? 'Retiro' : 'Fuera de GAM', products, bags,
    o.subtotal, o.saving || 0, o.shipping, o.total, new Date(o.updated_at || o.created_at)
  ];
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// Run once from the editor (select "authorize" → Run) to grant access to the sheet and create the tab.
function authorize() {
  sheet();
}
