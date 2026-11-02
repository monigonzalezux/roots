# Turns the Claude-artifact version of the Roots panel into a standalone page backed by Supabase.
import re, sys
src, out = sys.argv[1], sys.argv[2]
s = open(src, encoding="utf-8").read()

def rep(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, (n, old[:80])
    s = s.replace(old, new)

def rep_re(pat, new, expand=False):
    global s
    m = list(re.finditer(pat, s, re.S))
    assert len(m) == 1, (len(m), pat[:80])
    s = s[:m[0].start()] + (new.replace('\\1', m[0].group(1)) if expand else new) + s[m[0].end():]

# ── libraries + config ──
rep('<script>\n(function(){\n"use strict";',
    '<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js"></script>\n'
    '<script src="config.js"></script>\n<script>\n(function(){\n"use strict";')
rep("// Data today: this artifact's shared db (orders/, receipts/, config/v2, inventory/log).\n"
    "// Production plan: same shapes in Supabase; the storefront writes orders directly.",
    "// Data: Supabase (tables orders, receipts, settings, inventory_log; see supabase/schema.sql).\n"
    "// The storefront writes orders through place_order(); owners log in with Supabase Auth.")

# ── logout button in the top bar ──
rep('    </nav>\n', '    </nav>\n    <button type="button" class="btn btn-o btn-sm" id="logout" hidden>Salir</button>\n')

# ── state ──
rep('var S={db:null,downloads:null,admin:false,ready:false,',
    'var S={sb:null,session:null,downloads:{save:saveFile},admin:false,ready:false,authView:"login",authMsg:"",authErr:"",chan:null,poll:null,')

# ── gates → login ──
rep_re(r"  if\(!S\.db\)\{app\.innerHTML=.*?return\}\n  if\(!S\.admin\)\{app\.innerHTML=.*?return\}\n",
'''  if(!S.sb){app.innerHTML=gate("Falta conectar la base de datos","Completá config.js con la URL y la llave pública (anon) de Supabase."); return}
  if(!S.session||S.authView==="setpw"){$("#tabs").hidden=true; $("#logout").hidden=!S.session; app.innerHTML=authView(); bindAuth(); return}
  if(!S.admin){$("#tabs").hidden=true; $("#logout").hidden=false; app.innerHTML=gate("Este panel es solo para el equipo de Roots","Entraste como "+esc(S.session.user.email)+". Si sos parte del equipo, pedile a la administradora que agregue tu correo."); return}
  $("#logout").hidden=false;
''')

# ── settings save ──
rep_re(r'      var p=isNew\?S\.db\.doc\(CFG_DOC\)\.set\(doc\):S\.db\.doc\(CFG_DOC\)\.update\(doc\);\n      p\.then\(function\(\)\{\n        if\(isNew\)\{var entries=(.*?); if\(entries\.length\) S\.db\.doc\("inventory/log"\)\.set\(\{entries:entries\}\)\}\n',
'''      var p=isNew?S.sb.from("settings").insert({id:1,data:doc}):S.sb.from("settings").update({data:doc,updated_at:doc.updatedAt}).eq("id",1);
      p.then(function(r){
        if(r.error) throw r.error;
        if(isNew){var entries=\\1; if(entries.length) S.sb.from("inventory_log").insert(entries.map(function(x){return {product:x.product,delta:x.delta,reason:x.reason,order_id:"",at:x.at}})).then(function(){loadLog()})}
        loadConfig().then(function(){if(!busy()) render()});
''', expand=True)

# ── stock moves ──
rep_re(r'function moveStock\(moves,reason,orderId\)\{.*?\n\}\nfunction orderMoves',
'''function moveStock(moves,reason,orderId){
  if(!S.config){toast("Primero creá la configuración en Ajustes."); return Promise.resolve()}
  return S.sb.rpc("move_stock",{p_moves:moves,p_reason:reason,p_order_id:orderId||""}).then(function(r){
    if(r.error) throw r.error; return refreshAll();
  }).catch(function(){toast("El inventario no se actualizó. Revisalo en Inventario.")});
}
function orderMoves''')

# ── receipts ──
rep_re(r'  S\.db\.doc\("receipts/"\+o\.id\)\.get\(\)\.then\(.*?\);\n',
'''  S.sb.from("receipts").select("data_url").eq("order_id",o.id).maybeSingle().then(function(r){S.receiptCache[o.id]=r.data?r.data.data_url:""; if(S.selected===o.id) renderDrawer()},function(){S.receiptCache[o.id]=""; if(S.selected===o.id) renderDrawer()});
''')

# ── status changes (stock moves happen in the database, in the same step) ──
rep_re(r'  S\.db\.doc\("orders/"\+o\.id\)\.update\(\{status:to,history:hist,updatedAt:now\}\)\.then\(function\(\)\{\n    S\.rejecting=false;.*?\n  \}\)\.catch\(',
'''  S.sb.rpc("set_order_status",{p_id:o.id,p_to:to,p_note:note||""}).then(function(r){
    if(r.error) throw r.error;
    S.rejecting=false; S.justChanged=o.id; o.status=to; o.history=hist;
    toast(o.id+": "+STATUS[to]); live(o.id+": "+STATUS[to]);
    return refreshAll();
  }).catch(''')

# ── manual orders: the database assigns the number and moves stock ──
if 'S.db.doc("orders/"+id).set(o)' in s:
    rep_re(r'  S\.db\.doc\("orders/"\+id\)\.set\(o\)\.then\(function\(\)\{.*?openOrder\(id\);\n  \}\)\.catch\(',
'''  S.sb.rpc("create_manual_order",{p_order:o}).then(function(r){
    if(r.error) throw r.error;
    var nid=r.data; toast("Pedido "+nid+" creado"); S.manual=null; S.justChanged=nid;
    return refreshAll().then(function(){openOrder(nid)});
  }).catch(''')

# ── boot ──
rep_re(r'// ═══════════ BOOT ═══════════\n.*?\n\}\)\(\);\n\}\)\(\);\n</script>',
r'''// ═══════════ LOGIN ═══════════
function saveFile(f){
  var b=f.data instanceof Blob?f.data:new Blob([f.data],{type:/\.csv$/.test(f.filename)?"text/csv;charset=utf-8":"application/octet-stream"});
  var a=document.createElement("a"); a.href=URL.createObjectURL(b); a.download=f.filename; document.body.appendChild(a); a.click();
  setTimeout(function(){URL.revokeObjectURL(a.href); a.remove()},1000); return Promise.resolve();
}
function gate(t,p){return '<div class="gate"><img src="'+IMG.frootPina+'" alt=""><h1 class="h1" style="font-size:32px">'+t+'</h1><p class="mute">'+p+'</p></div>'}
function authView(){
  var m=S.authView, title=m==="forgot"?"Recuperá tu contraseña":m==="setpw"?"Creá tu contraseña":"Entrá al panel";
  var sub=m==="forgot"?"Te mandamos un enlace a tu correo para crear una contraseña nueva.":m==="setpw"?"Usá al menos 8 caracteres. La vas a usar cada vez que entrés.":"Solo para el equipo de Roots.";
  var f='';
  if(m!=="setpw") f+='<div class="field"><label for="a-email">Correo</label><input class="inp" id="a-email" type="email" autocomplete="username" required></div>';
  if(m!=="forgot") f+='<div class="field"><label for="a-pw">'+(m==="setpw"?"Contraseña nueva":"Contraseña")+'</label><input class="inp" id="a-pw" type="password" autocomplete="'+(m==="setpw"?"new-password":"current-password")+'" required minlength="'+(m==="setpw"?8:1)+'"></div>';
  return '<div class="gate" style="justify-items:stretch;text-align:left;max-width:440px"><img src="'+IMG.frootPina+'" alt="" style="justify-self:center"><div style="text-align:center;display:grid;gap:6px"><h1 class="h1" style="font-size:34px">'+title+'</h1><p class="mute" style="margin:0">'+sub+'</p></div>'+
    '<form class="card" id="authf" style="display:grid;gap:14px" novalidate>'+f+
    (S.authErr?'<p class="alert alert-bad" role="alert" style="margin:0">'+esc(S.authErr)+'</p>':'')+
    (S.authMsg?'<p class="alert alert-warn" role="status" style="margin:0">'+esc(S.authMsg)+'</p>':'')+
    '<button type="submit" class="btn btn-m" id="a-go">'+(m==="forgot"?"Enviar enlace":m==="setpw"?"Guardar contraseña":"Entrar")+'</button>'+
    (m==="login"?'<button type="button" class="link" id="a-forgot" style="justify-self:center">¿Olvidaste tu contraseña?</button>':m==="forgot"?'<button type="button" class="link" id="a-back" style="justify-self:center">Volver a entrar</button>':'')+
    '</form></div>';
}
function bindAuth(){
  var f=$("#authf"); if(!f) return;
  var fg=$("#a-forgot"); if(fg) fg.onclick=function(){S.authView="forgot"; S.authErr=""; S.authMsg=""; render(); $("#a-email").focus()};
  var bk=$("#a-back"); if(bk) bk.onclick=function(){S.authView="login"; S.authErr=""; S.authMsg=""; render(); $("#a-email").focus()};
  f.onsubmit=function(e){e.preventDefault();
    var m=S.authView, em=$("#a-email")&&$("#a-email").value.trim(), pw=$("#a-pw")&&$("#a-pw").value, b=$("#a-go");
    S.authErr=""; S.authMsg="";
    if(m!=="setpw"&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em||"")){S.authErr="Escribí tu correo."; render(); $("#a-email").focus(); return}
    if(m==="login"&&!pw){S.authErr="Escribí tu contraseña."; render(); $("#a-email").value=em; $("#a-pw").focus(); return}
    if(m==="setpw"&&(pw||"").length<8){S.authErr="La contraseña necesita al menos 8 caracteres."; render(); $("#a-pw").focus(); return}
    b.disabled=true; b.textContent="Un momento…";
    var p=m==="login"?S.sb.auth.signInWithPassword({email:em,password:pw})
      :m==="forgot"?S.sb.auth.resetPasswordForEmail(em,{redirectTo:location.origin+location.pathname})
      :S.sb.auth.updateUser({password:pw});
    p.then(function(r){
      if(r.error){S.authErr=m==="login"?"Correo o contraseña incorrectos.":m==="setpw"?"No se pudo guardar la contraseña. Pedí un enlace nuevo.":"No se pudo enviar el enlace. Intentá de nuevo."; render(); if($("#a-email")&&em) $("#a-email").value=em; return}
      if(m==="forgot"){S.authMsg="Si el correo está registrado, te llegó un enlace. Revisá también la carpeta de spam."; render(); return}
      if(m==="setpw"){S.authView="login"; history.replaceState(null,"",location.pathname); toast("Contraseña guardada"); afterLogin()}
    });
  };
}

// ═══════════ DATA ═══════════
function busy(){var ae=document.activeElement; return ae&&ae.closest&&(ae.closest("form")||ae.closest(".drawer"))}
function rowToOrder(r){return {id:r.id,createdAt:r.created_at,updatedAt:r.updated_at,customer:r.customer||{},zone:r.zone,lines:r.lines||[],subtotal:r.subtotal,saving:r.saving,shipping:r.shipping,total:r.total,status:r.status,history:r.history||[],hasReceipt:r.has_receipt,source:r.source,channel:r.channel}}
function loadConfig(){return S.sb.from("settings").select("data").eq("id",1).maybeSingle().then(function(r){if(!r.error) S.config=r.data?r.data.data:null})}
function loadLog(){return S.sb.from("inventory_log").select("*").order("at",{ascending:false}).limit(300).then(function(r){if(!r.error) S.log=r.data.map(function(x){return {product:x.product,delta:x.delta,reason:x.reason,orderId:x.order_id,at:x.at}})})}
function loadOrders(){return S.sb.from("orders").select("*").order("created_at",{ascending:false}).limit(5000).then(function(r){
  if(r.error) return;
  var prev={}; S.orders.forEach(function(o){prev[o.id]=1});
  var list=r.data.map(rowToOrder), fresh=S.ordersLoaded?list.filter(function(o){return !prev[o.id]}):[];
  S.orders=list; S.ordersLoaded=true;
  if(fresh.length) toast("Nuevo pedido "+fresh[0].id+" · "+fmt(fresh[0].total));
})}
function repaint(){if(busy()){updateBadge(); if(S.selected) renderDrawer(); return} render()}
function refreshAll(){return Promise.all([loadConfig(),loadOrders(),loadLog()]).then(repaint)}
var liveT; function liveRefresh(){clearTimeout(liveT); liveT=setTimeout(refreshAll,400)}
function startLive(){
  stopLive();
  S.chan=S.sb.channel("roots-panel")
    .on("postgres_changes",{event:"*",schema:"public",table:"orders"},liveRefresh)
    .on("postgres_changes",{event:"*",schema:"public",table:"settings"},liveRefresh)
    .on("postgres_changes",{event:"*",schema:"public",table:"inventory_log"},liveRefresh)
    .subscribe();
  S.poll=setInterval(refreshAll,60000);
}
function stopLive(){if(S.chan){S.sb.removeChannel(S.chan); S.chan=null} clearInterval(S.poll)}
document.addEventListener("visibilitychange",function(){if(!document.hidden&&S.admin) refreshAll()});
function afterLogin(){
  S.sb.rpc("is_owner").then(function(r){
    S.admin=!!r.data; S.ready=true;
    if(!S.admin){render(); return}
    refreshAll(); startLive();
  });
}

// ═══════════ BOOT ═══════════
(function boot(){
  var c=window.ROOTS_CONFIG||{};
  if(!window.supabase||!c.supabaseUrl||!c.supabaseAnonKey){S.ready=true; render(); return}
  if(/type=(invite|recovery)/.test(location.hash)) S.authView="setpw";
  var sb=S.sb=window.supabase.createClient(c.supabaseUrl,c.supabaseAnonKey);
  $("#logout").onclick=function(){sb.auth.signOut()};
  sb.auth.onAuthStateChange(function(ev,session){
    if(ev==="PASSWORD_RECOVERY") S.authView="setpw";
    var same=S.session&&session&&S.session.user.id===session.user.id; S.session=session;
    if(!session){S.admin=false; S.orders=[]; S.ordersLoaded=false; S.config=null; stopLive(); if(S.authView==="setpw") S.authView="login"; S.ready=true; $("#layer").innerHTML=""; render(); return}
    if(same&&S.ready) return;
    setTimeout(afterLogin,0);
  });
})();
})();
</script>''')

open(out, "w", encoding="utf-8").write(s)
print("ok", len(s))
