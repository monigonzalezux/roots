-- ─────────────────────────────────────────────────────────────
-- Roots · update 004: activity log
-- Run once in Supabase → SQL Editor, after 003-business-and-expenses.sql.
-- Every change made in the panel (and every store order) leaves a line here,
-- with who did it. The panel shows it in Ajustes → Registro de actividad.
-- ─────────────────────────────────────────────────────────────

create table if not exists public.activity_log (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  by text not null default coalesce(auth.jwt() ->> 'email', ''),
  action text not null,
  details text not null default '',
  ref text not null default ''
);
create index if not exists activity_log_at on public.activity_log (at desc);
alter table public.activity_log enable row level security;
drop policy if exists owners_read on public.activity_log;
create policy owners_read on public.activity_log for select to authenticated using (public.is_owner());

-- Bulk loads set roots.importing = 'on' and write one summary line instead of one per row.
create or replace function public.log_activity(p_action text, p_details text, p_ref text default '')
returns void language plpgsql volatile security definer set search_path = public as $$
begin
  if coalesce(current_setting('roots.importing', true), '') = 'on' then return; end if;
  insert into activity_log (action, details, ref) values (p_action, coalesce(p_details, ''), coalesce(p_ref, ''));
end $$;

create or replace function public.crc(n int) returns text language sql immutable as $$ select '₡' || to_char(coalesce(n, 0), 'FM999,999,999') $$;

create or replace function public.log_orders()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    perform log_activity(
      case new.source when 'negocio' then 'Venta a negocio' when 'manual' then 'Pedido manual' else 'Pedido de la tienda' end,
      new.id || ' · ' || coalesce(new.customer ->> 'name', '') || ' · ' || crc(new.total), new.id);
  elsif new.status is distinct from old.status then
    perform log_activity('Cambio de estado', new.id || ' · ' || coalesce(new.customer ->> 'name', '') || ': ' || old.status || ' → ' || new.status, new.id);
  end if;
  return new;
end $$;
drop trigger if exists orders_activity on public.orders;
create trigger orders_activity after insert or update of status on public.orders for each row execute function public.log_orders();

create or replace function public.log_expenses()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    perform log_activity('Gasto agregado', new.category || ' · ' || crc(new.amount) || coalesce(nullif(' · ' || new.note, ' · '), ''), new.id::text);
    return new;
  end if;
  perform log_activity('Gasto borrado', old.category || ' · ' || crc(old.amount) || ' · del ' || to_char(old.spent_on, 'DD/MM/YYYY'), old.id::text);
  return old;
end $$;
drop trigger if exists expenses_activity on public.expenses;
create trigger expenses_activity after insert or delete on public.expenses for each row execute function public.log_expenses();

-- Settings: say which parts changed (stock is logged by the inventory moves themselves).
create or replace function public.log_settings()
returns trigger language plpgsql security definer set search_path = public as $$
declare changed text;
begin
  select string_agg(case k
           when 'sinpeNumber' then 'número SINPE' when 'sinpeName' then 'titular SINPE' when 'ship' then 'tarifas de envío'
           when 'cost' then 'costo por bolsa' when 'businesses' then 'lista de negocios' when 'expenseCats' then 'categorías de gastos'
           when 'wholesale' then 'precio a negocios' else k end, ', ')
    into changed
    from (select key k from jsonb_each(new.data) where key not in ('stock','updatedAt','v')
          and (old.data -> key) is distinct from (new.data -> key)) x;
  if changed is not null then perform log_activity('Ajustes cambiados', changed); end if;
  return new;
end $$;
drop trigger if exists settings_activity on public.settings;
create trigger settings_activity after update on public.settings for each row execute function public.log_settings();
create or replace function public.log_settings_created()
returns trigger language plpgsql security definer set search_path = public as $$
begin perform log_activity('Configuración creada', 'SINPE, envíos, costos e inventario inicial'); return new; end $$;
drop trigger if exists settings_created on public.settings;
create trigger settings_created after insert on public.settings for each row execute function public.log_settings_created();

-- Inventory: only hand-made moves (sales and returns already appear as status changes).
create or replace function public.log_inventory()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if new.order_id = '' then
    perform log_activity('Inventario', (case split_part(new.product, '-', 2) when 'pina' then 'Piña' when 'mango' then 'Mango' else 'Fresa' end)
      || ' ' || (case split_part(new.product, '-', 1) when 'g' then 'Grande' else 'Mini' end)
      || ' ' || case when new.delta > 0 then '+' else '' end || new.delta || ' · ' || new.reason);
  end if;
  return new;
end $$;
drop trigger if exists inventory_activity on public.inventory_log;
create trigger inventory_activity after insert on public.inventory_log for each row execute function public.log_inventory();

revoke execute on function public.log_activity(text, text, text) from public, anon, authenticated;

do $$ begin
  alter publication supabase_realtime add table public.activity_log;
exception when duplicate_object then null; end $$;
