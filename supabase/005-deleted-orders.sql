-- ─────────────────────────────────────────────────────────────
-- Roots · update 005: delete orders (e.g. tests)
-- Run once in Supabase → SQL Editor, after 004-activity-log.sql.
-- "Eliminar" hides an order from Pedidos, Ventas, Resumen and Finanzas; if it was paid,
-- its bags go back to inventory. Deleted orders live in Ajustes → Pedidos eliminados,
-- where they can be restored or erased for good.
-- ─────────────────────────────────────────────────────────────

alter table public.orders add column if not exists deleted_at timestamptz;
alter table public.orders add column if not exists deleted_by text not null default '';

create or replace function public.delete_order(p_id text, p_reason text default '')
returns void language plpgsql volatile security definer set search_path = public as $$
declare o orders; paid text[] := array['pagado','preparando','enviado','entregado'];
begin
  if not is_owner() then raise exception 'not_allowed'; end if;
  select * into o from orders where id = p_id for update;
  if not found then raise exception 'not_found'; end if;
  if o.deleted_at is not null then return; end if;
  if o.status = any(paid) then
    perform move_stock(order_bags(o.lines), 'Pedido eliminado · ' || p_id, p_id);
  end if;
  update orders set deleted_at = now(), deleted_by = who(), updated_at = now() where id = p_id;
  perform log_activity('Pedido eliminado',
    p_id || ' · ' || coalesce(o.customer ->> 'name', '') || ' · ' || crc(o.total) || coalesce(nullif(' · ' || p_reason, ' · '), ''), p_id);
end $$;

create or replace function public.restore_order(p_id text)
returns void language plpgsql volatile security definer set search_path = public as $$
declare o orders; paid text[] := array['pagado','preparando','enviado','entregado']; neg jsonb;
begin
  if not is_owner() then raise exception 'not_allowed'; end if;
  select * into o from orders where id = p_id for update;
  if not found then raise exception 'not_found'; end if;
  if o.deleted_at is null then return; end if;
  if o.status = any(paid) then
    select coalesce(jsonb_object_agg(key, -(value::int)), '{}'::jsonb) into neg from jsonb_each_text(order_bags(o.lines));
    perform move_stock(neg, 'Pedido recuperado · ' || p_id, p_id);
  end if;
  update orders set deleted_at = null, deleted_by = '', updated_at = now() where id = p_id;
  perform log_activity('Pedido recuperado', p_id || ' · ' || coalesce(o.customer ->> 'name', ''), p_id);
end $$;

-- Erases a deleted order and its receipt for good. Only works on orders already in "Pedidos eliminados".
create or replace function public.purge_order(p_id text)
returns void language plpgsql volatile security definer set search_path = public as $$
declare o orders;
begin
  if not is_owner() then raise exception 'not_allowed'; end if;
  select * into o from orders where id = p_id for update;
  if not found then return; end if;
  if o.deleted_at is null then raise exception 'not_deleted'; end if;
  delete from orders where id = p_id;
  perform log_activity('Pedido borrado definitivamente', p_id || ' · ' || coalesce(o.customer ->> 'name', '') || ' · ' || crc(o.total), p_id);
end $$;

revoke execute on function public.delete_order(text, text), public.restore_order(text), public.purge_order(text) from public, anon;
grant execute on function public.delete_order(text, text), public.restore_order(text), public.purge_order(text) to authenticated;
