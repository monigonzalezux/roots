-- ─────────────────────────────────────────────────────────────
-- Roots · update 002: manual orders from the panel
-- Run once in Supabase → SQL Editor, after schema.sql.
-- Lets owners create orders that came by WhatsApp, Instagram, in person or at a fair,
-- including pick-up ("retiro") with no shipping.
-- ─────────────────────────────────────────────────────────────

alter table public.orders add column if not exists source text not null default 'tienda';
alter table public.orders add column if not exists channel text not null default '';
alter table public.orders drop constraint if exists orders_zone_check;
alter table public.orders add constraint orders_zone_check check (zone in ('gam','fuera','retiro'));

-- Takes the next order number, saves the order and, if it's already paid,
-- confirms it so the bags come out of inventory.
create or replace function public.create_manual_order(p_order jsonb)
returns text language plpgsql volatile security definer set search_path = public as $$
declare
  r text;
  st text := coalesce(p_order ->> 'status', 'por_verificar');
  z text := coalesce(p_order ->> 'zone', 'gam');
  ch text := left(coalesce(p_order ->> 'channel', ''), 40);
begin
  if not is_owner() then raise exception 'not_allowed'; end if;
  if st not in ('por_verificar','pagado') then raise exception 'invalid_status'; end if;
  if jsonb_typeof(p_order -> 'lines') <> 'array' or jsonb_array_length(p_order -> 'lines') < 1 then raise exception 'invalid_lines'; end if;
  r := reserve_order_ref();
  update order_refs set used = true where ref = r;
  insert into orders (id, customer, zone, lines, subtotal, saving, shipping, total, status, history, has_receipt, source, channel)
  values (r, coalesce(p_order -> 'customer', '{}'::jsonb), z, p_order -> 'lines',
          coalesce((p_order ->> 'subtotal')::int, 0), coalesce((p_order ->> 'saving')::int, 0),
          coalesce((p_order ->> 'shipping')::int, 0), coalesce((p_order ->> 'total')::int, 0),
          'por_verificar',
          jsonb_build_array(jsonb_build_object('status','por_verificar','at',now(),'note','Pedido manual · ' || ch)),
          false, 'manual', ch);
  if st = 'pagado' then perform set_order_status(r, 'pagado', 'Pago confirmado al crear'); end if;
  return r;
end $$;

revoke execute on function public.create_manual_order(jsonb) from public, anon;
grant execute on function public.create_manual_order(jsonb) to authenticated;
