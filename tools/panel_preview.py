# Builds a self-contained preview of the owners' panel that runs on example data,
# for design review in Claude (artifacts can't reach Supabase).
# Output: local/panel-preview/index.html (+ img/, roots-tokens.css). local/ is not in git.
import os, re, shutil
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.path.join(root, "panel")
out = os.path.join(root, "local", "panel-preview")
s = open(os.path.join(src, "index.html"), encoding="utf-8").read()

MOCK = r"""<script>
// ── Preview only: a fake Supabase client with example data. Nothing is saved. ──
(function(){
  var now=Date.now(), day=864e5, iso=function(d){return new Date(now-d*day).toISOString()};
  var T={
    settings:[{id:1,data:{v:2,sinpeNumber:"7112-6437",sinpeName:"Lara María Guardia",ship:{gam:2500,fuera:3500},cost:{g:1800,m:650},
      businesses:["Café Grano","Soda La Esquina","Mercado Orgánico"],
      stock:{"g-mango":{stock:34,low:8},"g-fresa":{stock:6,low:8},"g-pina":{stock:22,low:8},"m-mango":{stock:48,low:10},"m-fresa":{stock:0,low:10},"m-pina":{stock:31,low:10}}}}],
    orders:[], receipts:[], inventory_log:[
      {product:"g-mango",delta:40,reason:"Inventario inicial",order_id:"",at:iso(20)},
      {product:"g-fresa",delta:-2,reason:"Venta RTS-1004",order_id:"RTS-1004",at:iso(2)}],
    expenses:[
      {id:1,spent_on:iso(3).slice(0,10),category:"Fruta",amount:42000,note:"20 kg de mango",created_by:"lara@roots.cr"},
      {id:2,spent_on:iso(9).slice(0,10),category:"Empaque",amount:18500,note:"Bolsas kraft",created_by:"lara@roots.cr"},
      {id:3,spent_on:iso(15).slice(0,10),category:"Transporte",amount:9000,note:"",created_by:"moni@roots.cr"}],
    owners:[{email:"lara@roots.cr",name:"Lara"},{email:"moni@roots.cr",name:"Moni"}],
    activity_log:[
      {at:iso(0.1),by:"lara@roots.cr",action:"Cambio de estado",ref:"RTS-1004",details:"RTS-1004 → Enviado"},
      {at:iso(0.4),by:"",action:"Pedido de la tienda",ref:"RTS-1005",details:"RTS-1005 · ₡12,000"},
      {at:iso(3),by:"moni@roots.cr",action:"Gasto",ref:"",details:"Fruta · ₡42,000"}]
  };
  function Q(t){this.t=t; this.single=false; this.op="select"; this.f=[]}
  ["select","order","limit","range","neq","gte","lte","in"].forEach(function(m){Q.prototype[m]=function(){return this}});
  Q.prototype.eq=function(k,v){this.f.push([k,v]); return this};
  Q.prototype.maybeSingle=Q.prototype.single=function(){this.single=true; return this};
  Q.prototype.insert=function(r){this.op="insert"; this.rows=[].concat(r); return this};
  Q.prototype.update=function(r){this.op="update"; this.patch=r; return this};
  Q.prototype.delete=function(){this.op="delete"; return this};
  Q.prototype.then=function(ok,bad){
    var tb=T[this.t]||(T[this.t]=[]), f=this.f, hit=function(r){return f.every(function(x){return r[x[0]]==x[1]})}, self=this;
    if(this.op==="insert") this.rows.forEach(function(r){if(r.id==null&&self.t==="expenses") r.id=Date.now(); r.created_by=r.created_by||"moni@roots.cr"; tb.unshift(r)});
    if(this.op==="update") tb.forEach(function(r){if(hit(r)) Object.assign(r,self.patch)});
    if(this.op==="delete") T[this.t]=tb.filter(function(r){return !hit(r)});
    var rows=(T[this.t]||[]).filter(hit);
    return Promise.resolve({data:this.single?(rows[0]||null):rows.slice(),error:null}).then(ok,bad);
  };
  var session={user:{id:"preview",email:"moni@roots.cr"}};
  var client={
    from:function(t){return new Q(t)},
    rpc:function(n,a){
      if(n==="is_owner") return Promise.resolve({data:true,error:null});
      if(n==="set_setting"){T.settings[0].data[a.p_key]=a.p_value}
      if(n==="create_manual_order"||n==="create_business_sale") return Promise.resolve({data:"RTS-"+(2000+Math.floor(Math.random()*900)),error:null});
      return Promise.resolve({data:null,error:null});
    },
    auth:{onAuthStateChange:function(cb){setTimeout(function(){cb("SIGNED_IN",session)},0); return {data:{subscription:{unsubscribe:function(){}}}}},
      signOut:function(){return Promise.resolve({})},signInWithPassword:function(){return Promise.resolve({data:{session:session},error:null})},
      resetPasswordForEmail:function(){return Promise.resolve({})},updateUser:function(){return Promise.resolve({})},getSession:function(){return Promise.resolve({data:{session:session}})}},
    channel:function(){var c={on:function(){return c},subscribe:function(){return c}}; return c},
    removeChannel:function(){}
  };
  window.supabase={createClient:function(){return client}};
  window.ROOTS_CONFIG={supabaseUrl:"https://preview.local",supabaseAnonKey:"preview"};
})();
</script>"""

def rep(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:60])
    s = s.replace(old, new)

rep('<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js"></script>\n<script src="config.js"></script>', MOCK)
# example orders: the panel's own demo generator
rep("refreshAll(); startLive();", "refreshAll().then(function(){if(!S.demoOrders) S.demoOrders=makeDemo(); S.demo=true; render()}); startLive();")
s = s.replace("<title>", "<title>Vista previa · ", 1)

if os.path.exists(out): shutil.rmtree(out, ignore_errors=True)
os.makedirs(out, exist_ok=True)
open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(s)
for name in ("roots-tokens.css",):
    p = os.path.join(src, name)
    if os.path.exists(p): shutil.copy(p, out)
if os.path.isdir(os.path.join(src, "img")):
    shutil.copytree(os.path.join(src, "img"), os.path.join(out, "img"), dirs_exist_ok=True)
print("ok", len(s))
