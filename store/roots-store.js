// Roots storefront ↔ Supabase. Customers can only read the public store info,
// get an order reference and place an order; prices are recalculated in the database.
(function () {
  "use strict";
  var c = window.ROOTS_CONFIG || {};
  var sb = window.supabase && c.supabaseUrl && c.supabaseAnonKey
    ? window.supabase.createClient(c.supabaseUrl, c.supabaseAnonKey, { auth: { persistSession: false, autoRefreshToken: false } })
    : null;

  function call(fn, args) {
    if (!sb) return Promise.reject(new Error("not_configured"));
    return sb.rpc(fn, args || {}).then(function (r) { if (r.error) throw r.error; return r.data; });
  }

  // Phone screenshots can be several MB; shrink to a readable JPEG before sending.
  function shrink(dataUrl) {
    return new Promise(function (resolve) {
      var im = new Image();
      im.onload = function () {
        var max = 1600, s = Math.min(1, max / Math.max(im.width, im.height));
        var cv = document.createElement("canvas");
        cv.width = Math.round(im.width * s); cv.height = Math.round(im.height * s);
        var x = cv.getContext("2d"); x.fillStyle = "#fff"; x.fillRect(0, 0, cv.width, cv.height); x.drawImage(im, 0, 0, cv.width, cv.height);
        var out = cv.toDataURL("image/jpeg", 0.82);
        resolve(out.length < dataUrl.length ? out : dataUrl);
      };
      im.onerror = function () { resolve(dataUrl); };
      im.src = dataUrl;
    });
  }

  window.ROOTS = {
    info: function () { return call("store_info"); },
    reserveRef: function () { return call("reserve_order_ref"); },
    placeOrder: function (state) {
      var f = state.form;
      var customer = {
        name: (f.name || "").trim(), phone: f.phone, email: (f.email || "").trim(), prov: f.prov, canton: f.canton,
        distrito: (f.distrito || "").trim(), addr: (f.addr || "").trim(), waze: (f.waze || "").trim(), notes: (f.notes || "").trim()
      };
      var lines = state.cart.map(function (l) { var x = Object.assign({}, l); delete x.id; return x; });
      return shrink(state.receipt.url).then(function (img) {
        return call("place_order", { p_ref: state.orderRef, p_customer: customer, p_lines: lines, p_receipt: img });
      });
    },
    // The database's totals are the ones that count.
    applyTotals: function (t, srv) {
      if (!srv) return t;
      t.subtotal = srv.subtotal; t.saving = srv.saving; t.ship = srv.shipping; t.total = srv.total; t.zone = srv.zone;
      return t;
    },
    errorText: function (err) {
      var m = String((err && err.message) || "");
      if (m.indexOf("invalid_receipt") >= 0) return "No pudimos leer el comprobante. Probá con otra captura (JPG o PNG).";
      if (m.indexOf("invalid_customer") >= 0) return "Faltan datos de entrega. Volvé a “Datos de entrega” y revisalos.";
      if (m.indexOf("invalid_ref") >= 0) return "Tu número de pedido venció. Volvé a “Datos de entrega” y continuá de nuevo.";
      return "No pudimos enviar tu pedido. Revisá tu conexión e intentá de nuevo, o escribinos por WhatsApp.";
    }
  };
})();
