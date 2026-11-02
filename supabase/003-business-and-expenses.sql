-- ─────────────────────────────────────────────────────────────
-- Roots · update 003: business sales and expenses
-- Run once in Supabase → SQL Editor, after 002-manual-orders.sql.
--
-- · Sales to businesses (stores) are orders with source = 'negocio'; the business
--   name goes in channel. Saving one takes the bags out of inventory.
-- · Expenses get their own table.
-- · The business list, expense categories and wholesale price live in settings,
--   so owners can edit them from the panel.
-- ─────────────────────────────────────────────────────────────

-- Change one key of the settings without touching the rest (stock moves can't be overwritten).
create or replace function public.set_setting(p_key text, p_value jsonb)
returns void language plpgsql volatile security definer set search_path = public as $$
begin
  if not is_owner() then raise exception 'not_allowed'; end if;
  if p_key not in ('businesses', 'expenseCats', 'wholesale') then raise exception 'invalid_key'; end if;
  update settings set data = jsonb_set(data, array[p_key], p_value, true), updated_at = now() where id = 1;
end $$;

-- A sale to a business: bags per flavor, total agreed with the business, and the date it was delivered.
create or replace function public.create_business_sale(p_sale jsonb)
returns text language plpgsql volatile security definer set search_path = public as $$
declare
  r text;
  biz text := left(btrim(coalesce(p_sale ->> 'business', '')), 80);
  d timestamptz := coalesce((p_sale ->> 'date')::date, current_date) + time '12:00';
  l jsonb; clean jsonb := '[]'::jsonb; bags int := 0; total int := coalesce((p_sale ->> 'total')::int, 0);
begin
  if not is_owner() then raise exception 'not_allowed'; end if;
  if biz = '' then raise exception 'invalid_business'; end if;
  for l in select * from jsonb_array_elements(coalesce(p_sale -> 'lines', '[]'::jsonb)) loop
    if coalesce(l ->> 'size', '') not in ('g','m') or coalesce(l ->> 'flavor', '') not in ('mango','fresa','pina')
       or coalesce((l ->> 'qty')::int, 0) < 1 then raise exception 'invalid_line'; end if;
    clean := clean || jsonb_build_array(jsonb_build_object('kind','single','size',l ->> 'size','flavor',l ->> 'flavor','qty',(l ->> 'qty')::int));
    bags := bags + (l ->> 'qty')::int;
  end loop;
  if bags = 0 then raise exception 'invalid_lines'; end if;
  -- spread the total over the lines so each line shows its amount
  select coalesce(jsonb_agg(e.line || jsonb_build_object('amount', round(total::numeric * (e.line ->> 'qty')::int / bags)) order by e.ord), '[]'::jsonb)
    into clean from jsonb_array_elements(clean) with ordinality as e(line, ord);

  r := reserve_order_ref();
  update order_refs set used = true where ref = r;
  insert into orders (id, created_at, customer, zone, lines, subtotal, saving, shipping, total, status, history, has_receipt, source, channel)
  values (r, d, jsonb_build_object('name', biz, 'notes', left(coalesce(p_sale ->> 'notes', ''), 400)), 'retiro', clean,
          total, 0, 0, total, 'por_verificar',
          jsonb_build_array(jsonb_build_object('status','por_verificar','at',now(),'note','Venta a negocio · ' || biz)),
          false, 'negocio', biz);
  perform set_order_status(r, 'entregado', 'Entregado al negocio');
  return r;
end $$;

create table if not exists public.expenses (
  id bigint generated always as identity primary key,
  spent_on date not null default current_date,
  category text not null,
  amount int not null check (amount > 0),
  note text not null default '',
  created_at timestamptz not null default now()
);
create index if not exists expenses_spent_on on public.expenses (spent_on desc);
alter table public.expenses enable row level security;
drop policy if exists owners_all on public.expenses;
create policy owners_all on public.expenses for all to authenticated using (public.is_owner()) with check (public.is_owner());

-- Starting lists (only if not set yet)
update public.settings set data = data
  || case when data ? 'businesses' then '{}'::jsonb else jsonb_build_object('businesses', jsonb_build_array(
       'Rganic Market','Green Center','23 Wellness','Green World','Mercadito Combai','Macrofit Tienda Orgánica',
       'Fresco by Salutem','Wellnest','Whole Foods Monteverde','Tramito al Granel (Escazú)','Tramito al Granel (Pinares)')) end
  || case when data ? 'expenseCats' then '{}'::jsonb else jsonb_build_object('expenseCats', jsonb_build_array(
       'Fruta','Hacienda','Paquetes','Mercadeo','Rent','Salario Lari','Others')) end
  || case when data ? 'wholesale' then '{}'::jsonb else jsonb_build_object('wholesale', 3051) end
where id = 1;

revoke execute on function public.set_setting(text, jsonb) from public, anon;
revoke execute on function public.create_business_sale(jsonb) from public, anon;
grant execute on function public.set_setting(text, jsonb) to authenticated;
grant execute on function public.create_business_sale(jsonb) to authenticated;

do $$ begin
  alter publication supabase_realtime add table public.expenses;
exception when duplicate_object then null; end $$;

-- ─────────── who did what ───────────
-- Owners can have a display name; history, stock moves and expenses record the email of whoever did them.
alter table public.owners add column if not exists name text not null default '';
alter table public.inventory_log add column if not exists by text not null default coalesce(auth.jwt() ->> 'email', '');
alter table public.expenses add column if not exists created_by text not null default coalesce(auth.jwt() ->> 'email', '');

create or replace function public.who()
returns text language sql stable as $$ select coalesce(auth.jwt() ->> 'email', '') $$;

create or replace function public.set_order_status(p_id text, p_to text, p_note text default '')
returns void language plpgsql volatile security definer set search_path = public as $$
declare o orders; paid text[] := array['pagado','preparando','enviado','entregado']; neg jsonb;
begin
  if not is_owner() then raise exception 'not_allowed'; end if;
  select * into o from orders where id = p_id for update;
  if not found then raise exception 'not_found'; end if;
  update orders
     set status = p_to, updated_at = now(),
         history = history || jsonb_build_array(jsonb_build_object('status', p_to, 'at', now(), 'note', coalesce(p_note, ''), 'by', who()))
   where id = p_id;
  if not (o.status = any(paid)) and p_to = any(paid) then
    select coalesce(jsonb_object_agg(key, -(value::int)), '{}'::jsonb) into neg from jsonb_each_text(order_bags(o.lines));
    perform move_stock(neg, 'Venta ' || p_id, p_id);
  elsif o.status = any(paid) and not (p_to = any(paid)) then
    perform move_stock(order_bags(o.lines), 'Devuelto al inventario · ' || p_id, p_id);
  end if;
end $$;

-- the first history entry of orders created in the panel says who created them
create or replace function public.stamp_creator()
returns trigger language plpgsql as $$
begin
  if new.source <> 'tienda' and jsonb_array_length(new.history) > 0 and who() <> '' then
    new.history := jsonb_set(new.history, '{0,by}', to_jsonb(who()));
  end if;
  return new;
end $$;
drop trigger if exists orders_stamp_creator on public.orders;
create trigger orders_stamp_creator before insert on public.orders for each row execute function public.stamp_creator();

-- Name the owners so the panel shows names instead of emails, e.g.:
-- update public.owners set name = 'Mariola' where email = 'mariola@...';
