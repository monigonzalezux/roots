-- ─────────────────────────────────────────────────────────────
-- Roots · Supabase setup
-- Run once: Supabase dashboard → SQL Editor → New query → paste all → Run.
--
-- Who can do what:
--   · Customers (the public store, not logged in) can only call
--     store_info(), reserve_order_ref() and place_order(). They can't read
--     or change any table.
--   · Owners (logged in AND listed in public.owners) can read and change
--     everything through the panel.
-- ─────────────────────────────────────────────────────────────

-- ─────────── tables ───────────
create table if not exists public.owners (
  email text primary key
);

-- One row (id = 1) holding the panel's settings: SINPE, shipping, costs, stock.
create table if not exists public.settings (
  id int primary key default 1 check (id = 1),
  data jsonb not null,
  updated_at timestamptz not null default now()
);

-- Order references are handed out at step 1 of checkout, so the customer
-- can write the reference in the SINPE detail before paying.
create sequence if not exists public.order_ref_seq start 1001;
create table if not exists public.order_refs (
  ref text primary key,
  created_at timestamptz not null default now(),
  used boolean not null default false
);

create table if not exists public.orders (
  id text primary key references public.order_refs(ref),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  status text not null default 'por_verificar'
    check (status in ('por_verificar','pagado','preparando','enviado','entregado','rechazado','cancelado')),
  customer jsonb not null,
  zone text not null check (zone in ('gam','fuera')),
  lines jsonb not null,
  subtotal int not null,
  saving int not null default 0,
  shipping int not null,
  total int not null,
  history jsonb not null default '[]'::jsonb,
  has_receipt boolean not null default false
);
create index if not exists orders_created_at on public.orders (created_at desc);

-- SINPE receipt images, kept apart so the order list loads fast.
create table if not exists public.receipts (
  order_id text primary key references public.orders(id) on delete cascade,
  data_url text not null
);

create table if not exists public.inventory_log (
  id bigint generated always as identity primary key,
  product text not null,
  delta int not null,
  reason text not null default '',
  order_id text not null default '',
  at timestamptz not null default now()
);
create index if not exists inventory_log_at on public.inventory_log (at desc);

-- ─────────── who is an owner ───────────
create or replace function public.is_owner()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from owners
    where lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

-- ─────────── row level security ───────────
alter table public.owners        enable row level security;
alter table public.settings      enable row level security;
alter table public.order_refs    enable row level security;
alter table public.orders        enable row level security;
alter table public.receipts      enable row level security;
alter table public.inventory_log enable row level security;

drop policy if exists owners_read on public.owners;
create policy owners_read on public.owners for select to authenticated using (public.is_owner());

drop policy if exists owners_all on public.settings;
create policy owners_all on public.settings for all to authenticated using (public.is_owner()) with check (public.is_owner());
drop policy if exists owners_all on public.order_refs;
create policy owners_all on public.order_refs for all to authenticated using (public.is_owner()) with check (public.is_owner());
drop policy if exists owners_all on public.orders;
create policy owners_all on public.orders for all to authenticated using (public.is_owner()) with check (public.is_owner());
drop policy if exists owners_all on public.receipts;
create policy owners_all on public.receipts for all to authenticated using (public.is_owner()) with check (public.is_owner());
drop policy if exists owners_all on public.inventory_log;
create policy owners_all on public.inventory_log for all to authenticated using (public.is_owner()) with check (public.is_owner());

-- ─────────── store: public info ───────────
create or replace function public.store_info()
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'sinpeNumber', coalesce((select data ->> 'sinpeNumber' from settings where id = 1), ''),
    'sinpeName',   coalesce((select data ->> 'sinpeName'   from settings where id = 1), ''),
    'ship',        coalesce((select data -> 'ship'         from settings where id = 1), '{"gam":2500,"fuera":3500}'::jsonb)
  );
$$;

-- ─────────── store: step 1 hands out the order reference ───────────
create or replace function public.reserve_order_ref()
returns text language plpgsql volatile security definer set search_path = public as $$
declare r text;
begin
  r := 'RTS-' || nextval('order_ref_seq');
  insert into order_refs (ref) values (r);
  return r;
end $$;

-- ─────────── shared helpers ───────────
create or replace function public.tier_price(p_size text, p_units int)
returns int language sql immutable as $$
  select case p_size
    when 'g' then case when p_units >= 10 then 3200 when p_units >= 5 then 3500 else 4000 end
    when 'm' then case when p_units >= 12 then 1250 when p_units >= 6 then 1350 else 1500 end
  end;
$$;

-- GAM cantons, same list as the store (an approximation: match it to the courier's zones).
create or replace function public.zone_of(p_prov text, p_canton text)
returns text language sql immutable as $$
  select case
    when p_prov in ('San José','Alajuela','Cartago','Heredia')
     and p_canton in ('San José','Escazú','Desamparados','Aserrí','Mora','Goicoechea','Santa Ana','Alajuelita',
                      'Vázquez de Coronado','Tibás','Moravia','Montes de Oca','Curridabat',
                      'Alajuela','Atenas','Poás',
                      'Cartago','Paraíso','La Unión','Alvarado','Oreamuno','El Guarco',
                      'Heredia','Barva','Santo Domingo','Santa Bárbara','San Rafael','San Isidro','Belén','Flores','San Pablo')
    then 'gam' else 'fuera' end;
$$;

-- Bags per product an order uses, e.g. {"g-mango": 3, "m-pina": 2}.
create or replace function public.order_bags(p_lines jsonb)
returns jsonb language sql immutable as $$
  select coalesce(jsonb_object_agg(k, n), '{}'::jsonb) from (
    select k, sum(n)::int as n from (
      select (l ->> 'size') || '-' || f as k, coalesce((l -> 'mix' ->> f)::int, 0) * (l ->> 'qty')::int as n
        from jsonb_array_elements(p_lines) l, unnest(array['mango','fresa','pina']) f
       where l ->> 'kind' = 'pack'
      union all
      select (l ->> 'size') || '-' || (l ->> 'flavor'), (l ->> 'qty')::int
        from jsonb_array_elements(p_lines) l
       where l ->> 'kind' = 'single'
    ) x group by k
  ) y where n <> 0;
$$;

-- ─────────── store: step 2 saves the order ───────────
-- Prices, shipping and zone are worked out here, never trusted from the browser.
create or replace function public.place_order(p_ref text, p_customer jsonb, p_lines jsonb, p_receipt text)
returns jsonb language plpgsql volatile security definer set search_path = public as $$
declare
  l jsonb; clean jsonb := '[]'::jsonb; units_g int := 0; units_m int := 0;
  u int; amt int; sub int := 0; base int := 0; ship int; z text; c jsonb; mixsum int; ok_packs int[];
  s jsonb;
begin
  -- reference
  if not exists (select 1 from order_refs where ref = p_ref and not used and created_at > now() - interval '2 days') then
    raise exception 'invalid_ref';
  end if;

  -- customer
  c := jsonb_build_object(
    'name',     left(btrim(coalesce(p_customer ->> 'name', '')), 120),
    'phone',    left(btrim(coalesce(p_customer ->> 'phone', '')), 20),
    'email',    left(btrim(coalesce(p_customer ->> 'email', '')), 160),
    'prov',     left(btrim(coalesce(p_customer ->> 'prov', '')), 40),
    'canton',   left(btrim(coalesce(p_customer ->> 'canton', '')), 60),
    'distrito', left(btrim(coalesce(p_customer ->> 'distrito', '')), 80),
    'addr',     left(btrim(coalesce(p_customer ->> 'addr', '')), 400),
    'waze',     left(btrim(coalesce(p_customer ->> 'waze', '')), 400),
    'notes',    left(btrim(coalesce(p_customer ->> 'notes', '')), 400));
  if c ->> 'name' = '' or length(regexp_replace(c ->> 'phone', '\D', '', 'g')) <> 8
     or c ->> 'prov' = '' or c ->> 'canton' = '' or c ->> 'addr' = '' then
    raise exception 'invalid_customer';
  end if;

  -- lines
  if jsonb_typeof(p_lines) <> 'array' or jsonb_array_length(p_lines) < 1 or jsonb_array_length(p_lines) > 30 then
    raise exception 'invalid_lines';
  end if;
  for l in select * from jsonb_array_elements(p_lines) loop
    if coalesce(l ->> 'size', '') not in ('g','m') or coalesce((l ->> 'qty')::int, 0) not between 1 and 20 then
      raise exception 'invalid_line';
    end if;
    if l ->> 'kind' = 'single' then
      if coalesce(l ->> 'flavor', '') not in ('mango','fresa','pina') then raise exception 'invalid_line'; end if;
      u := (l ->> 'qty')::int;
      clean := clean || jsonb_build_array(jsonb_build_object('kind','single','size',l ->> 'size','flavor',l ->> 'flavor','qty',u));
    elsif l ->> 'kind' = 'pack' then
      ok_packs := case l ->> 'size' when 'g' then array[3,5,10] else array[6,12] end;
      if not ((l ->> 'n')::int = any(ok_packs)) then raise exception 'invalid_line'; end if;
      mixsum := coalesce((l -> 'mix' ->> 'mango')::int,0) + coalesce((l -> 'mix' ->> 'fresa')::int,0) + coalesce((l -> 'mix' ->> 'pina')::int,0);
      if mixsum <> (l ->> 'n')::int or least(coalesce((l -> 'mix' ->> 'mango')::int,0), coalesce((l -> 'mix' ->> 'fresa')::int,0), coalesce((l -> 'mix' ->> 'pina')::int,0)) < 0 then
        raise exception 'invalid_line';
      end if;
      u := (l ->> 'n')::int * (l ->> 'qty')::int;
      clean := clean || jsonb_build_array(jsonb_build_object('kind','pack','size',l ->> 'size','n',(l ->> 'n')::int,
        'mix', jsonb_build_object('mango',coalesce((l -> 'mix' ->> 'mango')::int,0),'fresa',coalesce((l -> 'mix' ->> 'fresa')::int,0),'pina',coalesce((l -> 'mix' ->> 'pina')::int,0)),
        'label', case when l ->> 'label' = 'El Trío' then 'El Trío' else '' end,
        'qty', (l ->> 'qty')::int));
    else
      raise exception 'invalid_line';
    end if;
    if l ->> 'size' = 'g' then units_g := units_g + u; else units_m := units_m + u; end if;
  end loop;

  -- volume pricing across flavors, same rule as the store
  select coalesce(jsonb_agg(x.line || jsonb_build_object('amount', x.amt) order by x.ord), '[]'::jsonb),
         coalesce(sum(x.amt), 0), coalesce(sum(x.base), 0)
    into clean, sub, base
    from (
      select e.line, e.ord,
             (case when e.line ->> 'kind' = 'pack' then (e.line ->> 'n')::int * (e.line ->> 'qty')::int else (e.line ->> 'qty')::int end)
               * tier_price(e.line ->> 'size', case when e.line ->> 'size' = 'g' then units_g else units_m end) as amt,
             (case when e.line ->> 'kind' = 'pack' then (e.line ->> 'n')::int * (e.line ->> 'qty')::int else (e.line ->> 'qty')::int end)
               * tier_price(e.line ->> 'size', 1) as base
        from jsonb_array_elements(clean) with ordinality as e(line, ord)
    ) x;

  z := zone_of(c ->> 'prov', c ->> 'canton');
  select data into s from settings where id = 1;
  ship := coalesce((s -> 'ship' ->> z)::int, case z when 'gam' then 2500 else 3500 end);

  -- receipt
  if p_receipt is null or p_receipt !~ '^data:image/(jpeg|png|webp);base64,' or length(p_receipt) > 4000000 then
    raise exception 'invalid_receipt';
  end if;

  insert into orders (id, customer, zone, lines, subtotal, saving, shipping, total, status, history, has_receipt)
  values (p_ref, c, z, clean, sub, base - sub, ship, sub + ship, 'por_verificar',
          jsonb_build_array(jsonb_build_object('status','por_verificar','at',now(),'note','Pedido desde la tienda')), true);
  insert into receipts (order_id, data_url) values (p_ref, p_receipt);
  update order_refs set used = true where ref = p_ref;

  return jsonb_build_object('id', p_ref, 'zone', z, 'subtotal', sub, 'saving', base - sub, 'shipping', ship, 'total', sub + ship);
end $$;

-- ─────────── panel: stock moves and status changes (owners only) ───────────
create or replace function public.move_stock(p_moves jsonb, p_reason text, p_order_id text default '')
returns void language plpgsql volatile security definer set search_path = public as $$
declare k text; d int; cur int; nxt int; s jsonb;
begin
  if not is_owner() then raise exception 'not_allowed'; end if;
  select data into s from settings where id = 1 for update;
  if s is null then return; end if;
  if s -> 'stock' is null then s := jsonb_set(s, '{stock}', '{}'::jsonb); end if;
  for k, d in select key, value::int from jsonb_each_text(p_moves) loop
    cur := coalesce((s -> 'stock' -> k ->> 'stock')::int, 0);
    nxt := greatest(0, cur + d);
    s := jsonb_set(s, array['stock', k], jsonb_build_object('stock', nxt, 'low', coalesce((s -> 'stock' -> k ->> 'low')::int, 0)), true);
    if nxt <> cur then
      insert into inventory_log (product, delta, reason, order_id) values (k, nxt - cur, coalesce(p_reason, ''), coalesce(p_order_id, ''));
    end if;
  end loop;
  update settings set data = s, updated_at = now() where id = 1;
end $$;

-- Changes an order's status and moves stock when it crosses paid / not paid.
create or replace function public.set_order_status(p_id text, p_to text, p_note text default '')
returns void language plpgsql volatile security definer set search_path = public as $$
declare o orders; paid text[] := array['pagado','preparando','enviado','entregado']; neg jsonb;
begin
  if not is_owner() then raise exception 'not_allowed'; end if;
  select * into o from orders where id = p_id for update;
  if not found then raise exception 'not_found'; end if;
  update orders
     set status = p_to, updated_at = now(),
         history = history || jsonb_build_array(jsonb_build_object('status', p_to, 'at', now(), 'note', coalesce(p_note, '')))
   where id = p_id;
  if not (o.status = any(paid)) and p_to = any(paid) then
    select coalesce(jsonb_object_agg(key, -(value::int)), '{}'::jsonb) into neg from jsonb_each_text(order_bags(o.lines));
    perform move_stock(neg, 'Venta ' || p_id, p_id);
  elsif o.status = any(paid) and not (p_to = any(paid)) then
    perform move_stock(order_bags(o.lines), 'Devuelto al inventario · ' || p_id, p_id);
  end if;
end $$;

-- ─────────── who may call what ───────────
revoke execute on all functions in schema public from public, anon;
grant execute on function public.store_info()                         to anon, authenticated;
grant execute on function public.reserve_order_ref()                  to anon, authenticated;
grant execute on function public.place_order(text, jsonb, jsonb, text) to anon, authenticated;
grant execute on function public.is_owner()                           to authenticated;
grant execute on function public.move_stock(jsonb, text, text)        to authenticated;
grant execute on function public.set_order_status(text, text, text)   to authenticated;
grant execute on function public.tier_price(text, int), public.zone_of(text, text), public.order_bags(jsonb) to authenticated;

-- ─────────── live updates for the panel ───────────
do $$ begin
  alter publication supabase_realtime add table public.orders, public.settings, public.inventory_log;
exception when duplicate_object then null; end $$;

-- ─────────── owners ───────────
-- Add each owner's email here AND invite them in Authentication → Users → Invite user.
-- insert into public.owners (email) values ('owner1@example.com'), ('owner2@example.com');
