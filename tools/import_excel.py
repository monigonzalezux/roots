# Turns the owners' spreadsheet ("CONTROL GASTOS - INGRESOS ROOTS.xlsx") into one SQL file
# that loads its sales and expenses into Supabase. Run with:
#   python3 tools/import_excel.py "<path to .xlsx>" local/005-import-excel.sql
# The output holds customer names, so it goes in local/ (kept out of git).
#
# Rules
# · DIRECTAS → orders with source 'manual' (channel 'Histórico (Excel)'); NEGOCIOS → source 'negocio'.
# · A row's month column decides its month. A date that is missing, unreadable or in another
#   month is replaced by the 15th of that month (or today, for the current month).
# · Status: paid and delivered → entregado; paid → pagado; otherwise por_verificar.
# · Business sales count the "Total Estimado +IVA" (that's what the SUMMARY sheet adds up).
# · Imported orders don't move inventory: the stock in Ajustes is already today's count.
import re, sys, json, zipfile, datetime, xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
          "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
YEAR = 2026
TODAY = datetime.date.today()
OUTSIDE_GAM = ["guanacaste", "puntarenas", "limón", "limon", "san carlos", "jacó", "jaco", "tamarindo", "nicoya", "upala",
               "fortuna", "san vito", "coto brus", "zeldón", "zeledón", "orotina", "san ramón", "san ramon", "grecia", "naranjo",
               "palmares", "monteverde", "quesada", "liberia", "pérez", "perez", "limonal"]


def read_xlsx(path):
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            ss.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sheets = {}
    for sh in wb.find("m:sheets", NS):
        target = rels[sh.get("{%s}id" % NS["r"])]
        root = ET.fromstring(z.read("xl/" + target.lstrip("/").replace("xl/", "")))
        rows = []
        for row in root.iter("{%s}row" % NS["m"]):
            cells = {}
            for c in row.findall("m:c", NS):
                v = c.find("m:v", NS)
                if v is None:
                    continue
                col = 0
                for ch in re.match(r"[A-Z]+", c.get("r")).group(0):
                    col = col * 26 + ord(ch) - 64
                cells[col] = ss[int(v.text)] if c.get("t") == "s" else v.text
            if cells:
                rows.append(cells)
        sheets[sh.get("name")] = rows
    return sheets


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def month_of(v):
    return MONTHS.get(str(v or "").strip().lower())


def pick_date(raw, month):
    """The row's own date if it is real and in the row's month, else a stand-in in that month."""
    d = None
    try:
        f = float(raw)
        if 40000 < f < 60000:
            d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(f))
    except (TypeError, ValueError):
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})$", str(raw or "").strip())
        if m:
            try:
                d = datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                d = None
    if d and d.year == YEAR and d.month == month and d <= TODAY:
        return d, False
    stand_in = datetime.date(YEAR, month, 15)
    if stand_in > TODAY:
        stand_in = max(datetime.date(YEAR, month, 1), TODAY)
    return stand_in, True


def zone_of(place):
    p = (place or "").lower()
    return "fuera" if any(k in p for k in OUTSIDE_GAM) else "gam"


def lines_from(cells, cols):
    out = []
    for col, size, flavor in cols:
        q = int(num(cells.get(col)))
        if q > 0:
            out.append({"kind": "single", "size": size, "flavor": flavor, "qty": q})
    return out


def sql_str(s):
    return "'" + str(s).replace("'", "''") + "'"


def main(src, dst):
    sh = read_xlsx(src)
    report = {"direct": 0, "direct_total": 0, "biz": 0, "biz_total": 0, "skipped": [], "no_amount": [], "fixed_dates": 0,
              "by_month_direct": {}, "by_month_biz": {}, "bags_direct": {}, "expenses": 0}
    orders = []

    # DIRECTAS: B name, C month, D date, E amount, F-H grandes, I-K minis, L place, M estado, N pago
    dcols = [(6, "g", "pina"), (7, "g", "mango"), (8, "g", "fresa"), (9, "m", "pina"), (10, "m", "mango"), (11, "m", "fresa")]
    for c in sh["DIRECTAS"]:
        name, month = str(c.get(2, "")).strip(), month_of(c.get(3))
        if not name or not month:
            continue
        amount, lines = int(round(num(c.get(5)))), lines_from(c, dcols)
        if not amount and not lines:
            report["skipped"].append(name)
            continue
        if not amount:
            report["no_amount"].append(name)
        d, fixed = pick_date(c.get(4), month)
        report["fixed_dates"] += fixed
        paid, delivered = bool(str(c.get(14, "")).strip()), str(c.get(13, "")).strip().lower().startswith("entregado")
        status = "entregado" if paid and delivered else "pagado" if paid else "por_verificar"
        place = str(c.get(12, "")).strip()
        orders.append({"date": d, "source": "manual", "channel": "Histórico (Excel)", "status": status, "zone": zone_of(place),
                       "customer": {"name": re.sub(r"\s*\(mini\)\s*$", "", name, flags=re.I).strip(), "addr": place,
                                    "notes": "Importado del Excel" + (" · fecha aproximada" if fixed else "")},
                       "lines": lines, "total": amount})
        report["direct"] += 1
        report["direct_total"] += amount
        report["by_month_direct"][month] = report["by_month_direct"].get(month, 0) + amount
        for l in lines:
            k = l["flavor"] + "-" + l["size"]
            report["bags_direct"][k] = report["bags_direct"].get(k, 0) + l["qty"]

    # NEGOCIOS: A business, B month, C-E grandes, F-H minis, I estimado, J pagado, K método, L crédito, M entrega, N pago
    bcols = [(3, "g", "pina"), (4, "g", "mango"), (5, "g", "fresa"), (6, "m", "pina"), (7, "m", "mango"), (8, "m", "fresa")]
    businesses = []
    for c in sh["NEGOCIOS"]:
        name, month = str(c.get(1, "")).strip(), month_of(c.get(2))
        if not name or not month or name.lower() == "empresa":
            continue
        est, paid_amt, lines = int(round(num(c.get(9)))), int(round(num(c.get(10)))), lines_from(c, bcols)
        if not est and not lines:
            report["skipped"].append(name)
            continue
        d, fixed = pick_date(c.get(13), month)
        report["fixed_dates"] += fixed
        pay_date, _ = pick_date(c.get(14), month) if c.get(14) else (None, None)
        notes = [str(c.get(11, "")).strip() or "", ("Crédito " + str(int(num(c.get(12)))) + " días") if c.get(12) else "",
                 ("Pagado " + "₡{:,}".format(paid_amt)) if paid_amt else "Pago pendiente o sin registrar",
                 "Importado del Excel" + (" · fecha aproximada" if fixed else "")]
        if name not in businesses:
            businesses.append(name)
        bags = sum(l["qty"] for l in lines) or 1
        for l in lines:
            l["amount"] = round(est * l["qty"] / bags)
        orders.append({"date": d, "source": "negocio", "channel": name, "status": "entregado", "zone": "retiro",
                       "customer": {"name": name, "notes": " · ".join(x for x in notes if x)}, "lines": lines, "total": est})
        report["biz"] += 1
        report["biz_total"] += est
        report["by_month_biz"][month] = report["by_month_biz"].get(month, 0) + est

    # GASTOS: A tipo, B mes, C fecha, D descripción, E monto
    expenses = []
    for c in sh.get("GASTOS", []):
        cat, month, amount = str(c.get(1, "")).strip(), month_of(c.get(2)), int(round(num(c.get(5))))
        if not cat or not month or amount <= 0:
            continue
        d, _ = pick_date(c.get(3), month)
        expenses.append((d, cat.capitalize(), amount, str(c.get(4, "")).strip()))
    report["expenses"] = len(expenses)

    # Check against the owners' own SUMMARY sheet
    summary = {}
    for c in sh.get("SUMMARY", []):
        label = str(c.get(2, "")).strip().lower()
        if label in ("ventas directas", "ventas negocios"):
            summary[label] = {m: int(round(num(c.get(m + 2)))) for m in range(1, 13)}

    orders.sort(key=lambda o: (o["date"], o["source"]))
    out = ["-- Carga inicial desde el Excel. Generado por tools/import_excel.py el " + TODAY.isoformat() + ".",
           "-- Correr UNA vez en Supabase → SQL Editor, después de 003 y 004.",
           "begin;",
           "select set_config('roots.importing', 'on', true);  -- no anotar cada fila en el registro de actividad",
           "do $$ begin if exists (select 1 from public.orders where source in ('manual','negocio') and customer ->> 'notes' like 'Importado del Excel%') then",
           "  raise exception 'Este Excel ya se cargó antes. No se cargó nada de nuevo.'; end if; end $$;"]
    for o in orders:
        ts = o["date"].isoformat() + " 12:00:00-06"
        hist = [{"status": "por_verificar", "at": ts, "note": "Importado del Excel"}]
        if o["status"] != "por_verificar":
            hist.append({"status": o["status"], "at": ts, "note": "Importado del Excel"})
        out.append("insert into public.orders (id, created_at, updated_at, customer, zone, lines, subtotal, saving, shipping, total, status, history, has_receipt, source, channel) values "
                   "(public.reserve_order_ref(), {ts}, {ts}, {cu}::jsonb, {z}, {li}::jsonb, {t}, 0, 0, {t}, {st}, {hi}::jsonb, false, {so}, {ch});".format(
                       ts=sql_str(ts), cu=sql_str(json.dumps(o["customer"], ensure_ascii=False)), z=sql_str(o["zone"]),
                       li=sql_str(json.dumps(o["lines"], ensure_ascii=False)), t=o["total"], st=sql_str(o["status"]),
                       hi=sql_str(json.dumps(hist, ensure_ascii=False)), so=sql_str(o["source"]), ch=sql_str(o["channel"])))
    out.append("update public.order_refs set used = true where ref in (select id from public.orders);")
    for d, cat, amount, note in expenses:
        out.append("insert into public.expenses (spent_on, category, amount, note, created_by) values ({}, {}, {}, {}, 'Excel');".format(
            sql_str(d.isoformat()), sql_str(cat), amount, sql_str(note)))
    out.append("update public.settings set data = jsonb_set(data, '{businesses}', "
               "(select coalesce(jsonb_agg(distinct x), '[]'::jsonb) from (select jsonb_array_elements_text(coalesce(data -> 'businesses', '[]'::jsonb)) x "
               "union select unnest(array[" + ",".join(sql_str(b) for b in businesses) + "])) s), true) where id = 1;")
    detail = ("{} ventas directas (₡{:,}) y {} ventas a negocios (₡{:,}), marzo a noviembre {}. {} gastos. "
              "{} filas sin monto ni bolsas omitidas{}. {} fechas faltantes o mal escritas se pusieron a mitad del mes de la fila. "
              "Los pedidos importados no movieron el inventario.").format(
        report["direct"], report["direct_total"], report["biz"], report["biz_total"], YEAR, report["expenses"],
        len(report["skipped"]), (" (" + ", ".join(report["skipped"]) + ")") if report["skipped"] else "", report["fixed_dates"])
    if report["no_amount"]:
        detail += " Sin monto (revisar): " + ", ".join(report["no_amount"]) + "."
    out.append("insert into public.activity_log (by, action, details) values ('Excel', 'Carga inicial de datos', " + sql_str(detail) + ");")
    out.append("commit;")
    open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")

    # Report
    print(detail)
    print("\nMes  | Directas: Excel vs carga        | Negocios: Excel vs carga")
    for m in range(1, 13):
        a, b = summary.get("ventas directas", {}).get(m, 0), report["by_month_direct"].get(m, 0)
        c, d = summary.get("ventas negocios", {}).get(m, 0), report["by_month_biz"].get(m, 0)
        if a or b or c or d:
            print("{:>4} | {:>12,} {:>12,} {} | {:>12,} {:>12,} {}".format(m, a, b, "✓" if a == b else "✗", c, d, "✓" if c == d else "✗"))
    print("\nBolsas directas:", report["bags_direct"])
    print("Negocios:", businesses)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
