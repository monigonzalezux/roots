// dc-lite: renders the storefront's design template ({{holes}}, <sc-if>, <sc-for>, events) with React.
// The template lives in <script type="text/x-dc-template" id="dc-tpl">; the page's
// `class Component extends DCLogic` supplies renderVals().
(function () {
  "use strict";
  var h = React.createElement, Fragment = React.Fragment;
  var VOID = { area: 1, base: 1, br: 1, col: 1, embed: 1, hr: 1, img: 1, input: 1, link: 1, meta: 1, source: 1, track: 1, wbr: 1 };
  var RAW = { script: 1, style: 1, textarea: 1 };
  var NO_WS = { table: 1, thead: 1, tbody: 1, tfoot: 1, tr: 1, colgroup: 1, select: 1 };
  var RENAME = {
    "class": "className", "for": "htmlFor", tabindex: "tabIndex", readonly: "readOnly", maxlength: "maxLength", minlength: "minLength",
    colspan: "colSpan", rowspan: "rowSpan", autocomplete: "autoComplete", inputmode: "inputMode", crossorigin: "crossOrigin",
    srcset: "srcSet", spellcheck: "spellCheck", autofocus: "autoFocus", novalidate: "noValidate", enterkeyhint: "enterKeyHint",
    contenteditable: "contentEditable", viewbox: "viewBox", preserveaspectratio: "preserveAspectRatio", fetchpriority: "fetchPriority",
    referrerpolicy: "referrerPolicy", accesskey: "accessKey", datetime: "dateTime", "accept-charset": "acceptCharset", "http-equiv": "httpEquiv",
    "xlink:href": "xlinkHref", "xml:space": "xmlSpace"
  };
  var BOOL = { disabled: 1, checked: 1, readOnly: 1, required: 1, open: 1, hidden: 1, multiple: 1, autoFocus: 1, noValidate: 1, selected: 1, controls: 1, loop: 1, muted: 1 };

  var decoder = document.createElement("textarea");
  function decode(s) { if (s.indexOf("&") < 0) return s; decoder.innerHTML = s; return decoder.value; }

  // ─────────── parse: a small, forgiving HTML tokenizer (keeps attribute case, no foster-parenting) ───────────
  function parse(src) {
    var root = { tag: "#root", attrs: [], kids: [] }, stack = [root], i = 0, n = src.length;
    function text(t) { if (t) stack[stack.length - 1].kids.push(t); }
    while (i < n) {
      var lt = src.indexOf("<", i);
      if (lt < 0) { text(src.slice(i)); break; }
      text(src.slice(i, lt));
      if (src.startsWith("<!--", lt)) { var ce = src.indexOf("-->", lt); i = ce < 0 ? n : ce + 3; continue; }
      if (src[lt + 1] === "/") {
        var gt = src.indexOf(">", lt), name = src.slice(lt + 2, gt).trim().toLowerCase();
        for (var k = stack.length - 1; k > 0; k--) { if (stack[k].tag === name) { stack.length = k; break; } }
        i = gt + 1; continue;
      }
      if (!/[a-zA-Z]/.test(src[lt + 1] || "")) { text("<"); i = lt + 1; continue; }
      var j = lt + 1;
      while (j < n && !/[\s\/>]/.test(src[j])) j++;
      var tag = src.slice(lt + 1, j).toLowerCase(), attrs = [], self = false;
      while (j < n) {
        while (j < n && /\s/.test(src[j])) j++;
        if (src[j] === ">") { j++; break; }
        if (src[j] === "/" && src[j + 1] === ">") { self = true; j += 2; break; }
        if (src[j] === "/") { j++; continue; }
        var a = j;
        while (j < n && !/[\s=\/>]/.test(src[j])) j++;
        var an = src.slice(a, j), av = null, save = j;
        while (j < n && /\s/.test(src[j])) j++;
        if (src[j] === "=") {
          j++;
          while (j < n && /\s/.test(src[j])) j++;
          var q = src[j];
          if (q === '"' || q === "'") { var qe = src.indexOf(q, j + 1); av = src.slice(j + 1, qe); j = qe + 1; }
          else { var b = j; while (j < n && !/[\s>]/.test(src[j])) j++; av = src.slice(b, j); }
        } else j = save;
        if (an) attrs.push([an, av]);
      }
      var node = { tag: tag, attrs: attrs, kids: [] };
      stack[stack.length - 1].kids.push(node);
      if (RAW[tag] && !self) {
        var close = src.indexOf("</" + tag, j);
        if (close < 0) close = n;
        if (close > j) node.kids.push(src.slice(j, close));
        i = src.indexOf(">", close) + 1 || n; continue;
      }
      if (!self && !VOID[tag]) stack.push(node);
      i = j;
    }
    return root;
  }

  // ─────────── holes ───────────
  var WHOLE = /^\{\{\s*([^}]*?)\s*\}\}$/, HOLE = /\{\{\s*([^}]*?)\s*\}\}/g;
  function lookup(expr, scope) {
    if (expr === "true") return true;
    if (expr === "false") return false;
    if (expr === "null") return null;
    if (expr === "undefined" || expr === "") return undefined;
    if (/^-?\d+(\.\d+)?$/.test(expr)) return +expr;
    if (/^'[^']*'$|^"[^"]*"$/.test(expr)) return expr.slice(1, -1);
    var parts = expr.split("."), v = scope[parts[0]];
    for (var i = 1; i < parts.length; i++) { if (v == null) return undefined; v = v[parts[i]]; }
    return v;
  }
  function value(raw, scope) {
    if (raw == null) return "";
    var m = WHOLE.exec(raw);
    if (m) return lookup(m[1], scope);
    raw = decode(raw);
    if (raw.indexOf("{{") < 0) return raw;
    return raw.replace(HOLE, function (_, e) { var v = lookup(e, scope); return v == null ? "" : String(v); });
  }
  function attr(node, name) { for (var i = 0; i < node.attrs.length; i++) if (node.attrs[i][0] === name) return node.attrs[i][1]; return null; }

  // ─────────── props ───────────
  function camel(s) { return s.replace(/-([a-z])/g, function (_, c) { return c.toUpperCase(); }); }
  function propName(n) {
    var l = n.toLowerCase();
    if (RENAME[l]) return RENAME[l];
    if (/^(aria|data)-/.test(l)) return l;
    if (/^on[A-Z]/.test(n)) return n;
    if (n.indexOf("-") > 0) return camel(l);
    return n;
  }
  function styleObj(s) {
    var o = {}, decls = [], depth = 0, start = 0;
    for (var i = 0; i < s.length; i++) {
      var c = s[i];
      if (c === "(") depth++; else if (c === ")") depth--;
      else if (c === ";" && depth === 0) { decls.push(s.slice(start, i)); start = i + 1; }
    }
    decls.push(s.slice(start));
    decls.forEach(function (d) {
      var k = d.indexOf(":"); if (k < 0) return;
      var p = d.slice(0, k).trim(), v = d.slice(k + 1).trim();
      if (!p) return;
      if (p.indexOf("--") !== 0) p = camel(p.replace(/^-ms-/, "ms-"));
      o[p] = v;
    });
    return o;
  }
  function props(node, scope, key) {
    var p = key == null ? {} : { key: key }, hasChange = false;
    node.attrs.forEach(function (a) {
      var n = a[0];
      if (/^hint-/.test(n)) return;
      var name = propName(n), v = a[1] == null ? "" : value(a[1], scope);
      if (name === "onChange" || name === "onInput") hasChange = true;
      if (name === "style") { p.style = typeof v === "string" ? styleObj(v) : v; return; }
      if (BOOL[name]) { p[name] = v === "" || v === true || v === n || v === "true" ? true : v === "false" ? false : !!v; return; }
      if (/^(aria|data)-/.test(name) && typeof v === "boolean") v = String(v);
      p[name] = v;
    });
    var t = node.tag;
    if ((t === "input" || t === "select" || t === "textarea") && "value" in p) {
      if (p.value == null) p.value = "";
      if (!hasChange) { p.defaultValue = p.value; delete p.value; }
    }
    if (t === "input" && "checked" in p && !hasChange) { p.defaultChecked = p.checked; delete p.checked; }
    return p;
  }

  // ─────────── render ───────────
  function kids(node, scope) {
    var out = [];
    node.kids.forEach(function (k) {
      if (typeof k === "string") {
        if (NO_WS[node.tag] && !k.trim()) return;
        out.push(value(k, scope));
        return;
      }
      var r = build(k, scope);
      if (r !== null && r !== undefined) out.push(r);
    });
    return out;
  }
  function build(node, scope, key) {
    var t = node.tag;
    if (t === "helmet") return null;
    if (t === "sc-if") return lookupAttr(node, "value", scope) ? h.apply(null, [Fragment, key == null ? null : { key: key }].concat(kids(node, scope))) : null;
    if (t === "sc-for") {
      var list = lookupAttr(node, "list", scope) || [], as = attr(node, "as") || "item";
      return list.map(function (it, i) {
        var s = Object.create(scope); s[as] = it; s.$index = i;
        return h.apply(null, [Fragment, { key: i }].concat(kids(node, s)));
      });
    }
    var p = props(node, scope, key);
    if (t === "style" || t === "script") { p.dangerouslySetInnerHTML = { __html: node.kids.join("") }; return h(t, p); }
    if (t === "textarea") {
      if (!("value" in p) && !("defaultValue" in p)) p.defaultValue = value(node.kids.join(""), scope);
      return h(t, p);
    }
    return h.apply(null, [t, p].concat(kids(node, scope)));
  }
  function lookupAttr(node, name, scope) { var raw = attr(node, name); return raw == null ? undefined : value(raw, scope); }

  var TPL = null;
  function template() {
    if (!TPL) TPL = parse(document.getElementById("dc-tpl").textContent);
    return TPL;
  }

  window.DCLogic = class DCLogic extends React.Component {
    render() { return h.apply(null, [Fragment, null].concat(kids(template(), this.renderVals() || {}))); }
  };
})();
