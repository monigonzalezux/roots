# Builds store/index.html from the design canvas source (source/storefront.dc.html).
import os, re, sys
here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
dev = "--dev" in sys.argv
s = open(os.path.join(root, "source", "storefront.dc.html"), encoding="utf-8").read()

helmet = re.search(r"<helmet>(.*?)</helmet>", s, re.S).group(1)
tpl = re.search(r"</helmet>(.*?)</x-dc>", s, re.S).group(1)
js = re.search(r'<script type="text/x-dc" data-dc-script[^>]*>(.*?)</script>', s, re.S).group(1)
title = re.search(r"<title>(.*?)</title>", s).group(1)

# images: /_blob/<id> → img/<id>.<ext>
files = {f.split(".")[0]: f for f in os.listdir(os.path.join(root, "store", "img"))}
def img(m):
    return "img/" + files[m.group(1)]
helmet, tpl, js = (re.sub(r"/_blob/([0-9a-f]{32})", img, x) for x in (helmet, tpl, js))

def rep(text, old, new):
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)

# ── brand tokens come from roots-tokens.css (design-system/project/tokens.json) ──
ROOT_COLORS = ("--musgo:#515125;--musgo-2:#3E3E1B;--hueso:#EDE6D6;--hueso-2:#F5F0E5;--white:#FFFDF8;--ink:#222222;--mute:#5C5A43;"
               "--miel:#FCC14E;--coral:#F67A57;--lima:#C2C85E;--line:rgba(81,81,37,.18);--line-2:rgba(81,81,37,.34);")
helmet = rep(helmet, ROOT_COLORS, "--white:var(--card);")
helmet = rep(helmet, '--serif:"Newsreader","Iowan Old Style",Georgia,serif;--sans:"Hanken Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif;',
             "--serif:var(--font-serif);--sans:var(--font-sans);")

tpl = rep(tpl, 'style="font-family: var(--sans); color: #515125; background: #EDE6D6"', 'style="font-family: var(--sans); color: var(--musgo); background: var(--hueso)"')
tpl = rep(tpl, '<p class="lead" style="color: #515125">', '<p class="lead" style="color: var(--musgo)">')
# the order-receipt image is drawn on a canvas, which can't read CSS variables: look them up
js = rep(js, "var MUS = '#515125', HUE = '#EDE6D6', CARD = '#FFFDF8', MUTE = '#6B6950', CORAL = '#F67A57', MIEL = '#FCC14E';",
         "var tok = function (n, f) { try { return getComputedStyle(document.documentElement).getPropertyValue('--' + n).trim() || f; } catch (e) { return f; } };\n"
         "      var MUS = tok('musgo', '#515125'), HUE = tok('hueso', '#EDE6D6'), CARD = tok('card', '#FFFDF8'), MUTE = '#6B6950', CORAL = tok('coral', '#F67A57'), MIEL = tok('miel', '#FCC14E');")

# ── funnel steps (anonymous; see roots-store.js) ──
js = rep(js, "  go(view, extra) {\n", "  go(view, extra) {\n    ROOTS.track('view', { page: view });\n")
js = rep(js, "  addSingle(fid, size, n) {\n", "  addSingle(fid, size, n) {\n    ROOTS.track('add_to_cart', { item: size + '-' + fid, qty: n || 1 });\n")
js = rep(js, "  addPack(size, n, mix, label, absorb) {\n", "  addPack(size, n, mix, label, absorb) {\n    ROOTS.track('add_to_cart', { item: 'pack-' + size + '-' + n });\n")
js = rep(js, "  openCart() {\n", "  openCart() {\n    ROOTS.track('open_cart');\n")
js = rep(js, "this.setState({ tried: true, live: 'Revisá los campos marcados.' }", "ROOTS.track('form_error', { field: first }); this.setState({ tried: true, live: 'Revisá los campos marcados.' }")
js = rep(js, "reader.onload = function () { self.setState({ receipt:", "reader.onload = function () { ROOTS.track('receipt_added'); self.setState({ receipt:")

# ── template: real checkout, no prototype notes ──
tpl = rep(tpl, '<button type="button" class="btn btn-m" id="go-pay" onClick="{{submitStep1}}">Continuar al pago</button>',
          '<button type="button" class="btn btn-m" id="go-pay" onClick="{{submitStep1}}" disabled="{{submitting}}" aria-busy="{{submittingStr}}"><sc-if value="{{submitting}}" hint-placeholder-val="{{ false }}"><span class="spin"></span></sc-if>{{step1Label}}</button>')
tpl = rep(tpl, '<div class="co-actions">\n<button type="button" class="link" onClick="{{openCart}}">',
          '<sc-if value="{{hasNetErr}}" hint-placeholder-val="{{ false }}"><p class="err" role="alert">{{netErr}}</p></sc-if>\n<div class="co-actions">\n<button type="button" class="link" onClick="{{openCart}}">')
tpl = re.sub(r'<p class="proto-note">.*?</p>\n', "", tpl, count=1)
tpl = rep(tpl, "Tarifas de envío de ejemplo: {{rates}}.", "Tarifas de envío: {{rates}}.")
tpl = rep(tpl, "Envío de ejemplo: {{rates}}.", "Envío: {{rates}}.")
tpl = rep(tpl, "Esto es un prototipo: el número de pedido es solo una referencia de prueba. No se envió ningún pedido ni se procesó ningún pago.",
          "Te escribimos por WhatsApp cuando verifiquemos tu pago. Guardá tu número de pedido por si necesitás consultarnos.")
tpl = rep(tpl, "<span>Prototipo de tienda · envíos de ejemplo</span>", "")
tpl = re.sub(r'<p class="proto" aria-hidden="true">.*?</p>\n?', "", tpl, count=1)
assert "</script" not in tpl

# ── logic: reference and order go through Supabase ──
js = rep(js, """    var ref = this.state.orderRef || ('RTS-' + String(Math.floor(1000 + Math.random() * 9000)));
    this.setState({ step: 2, orderRef: ref }, function () { try { window.scrollTo(0, 0); } catch (err) {} });""",
"""    var self = this, toTop = function () { try { window.scrollTo(0, 0); } catch (err) {} };
    if (this.state.orderRef) { this.setState({ step: 2, netErr: '' }, toTop); return; }
    if (this.state.submitting) return;
    this.setState({ submitting: true, netErr: '' });
    ROOTS.reserveRef().then(function (ref) { ROOTS.track('payment_step'); self.setState({ step: 2, orderRef: ref, submitting: false }, toTop); },
      function () { self.setState({ submitting: false, netErr: 'No pudimos conectar con la tienda. Revisá tu conexión e intentá de nuevo.' }); });""")
js = rep(js, """    this.setState({ submitting: true });
    this.later('submit', function () {""",
"""    this.setState({ submitting: true, rErr: '' });
    ROOTS.placeOrder(this.state).then(function (srv) {
      t = ROOTS.applyTotals(t, srv);""")
js = rep(js, "    }, 1200);\n", """    }, function (err) {
      var m = String((err && err.message) || '');
      self.setState({ submitting: false, rErr: ROOTS.errorText(err), orderRef: m.indexOf('invalid_ref') >= 0 ? '' : self.state.orderRef });
    });
""")
js = rep(js, "isStep1: s.step === 1, ",
         "isStep1: s.step === 1, netErr: s.netErr || '', hasNetErr: !!s.netErr, step1Label: s.submitting ? 'Un momento…' : 'Continuar al pago', ")
js = rep(js, "componentDidMount() { this.runHero(); this.watchAnim(); }",
"""componentDidMount() {
    this.runHero(); this.watchAnim();
    var self = this;
    ROOTS.info().then(function (i) {
      if (i.sinpeNumber) CONFIG.sinpeNumber = i.sinpeNumber;
      if (i.sinpeName) CONFIG.sinpeName = i.sinpeName;
      if (i.ship) CONFIG.ship = { gam: +i.ship.gam || CONFIG.ship.gam, fuera: +i.ship.fuera || CONFIG.ship.fuera };
      self.forceUpdate();
    }, function () {});
  }""")

react = "development" if dev else "production.min"
page = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="icon" href="img/{files['5e85eacea9000037a164a8e22181911e']}">
<link rel="stylesheet" href="roots-tokens.css">
{helmet.strip()}
</head>
<body>
<div id="root"></div>
<script type="text/x-dc-template" id="dc-tpl">{tpl}</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.{react}.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.{react}.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js"></script>
<script src="config.js"></script>
<script src="dc-lite.js"></script>
<script src="roots-store.js"></script>
<script>
{js.strip()}

ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(Component, {{ startView: "inicio", heroMotion: true, testMode: false }}));
</script>
</body>
</html>
"""
open(os.path.join(root, "store", "index.html"), "w", encoding="utf-8").write(page)
print("ok", len(page))
