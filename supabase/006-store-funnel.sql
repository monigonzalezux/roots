-- ─────────────────────────────────────────────────────────────
-- Roots · update 006: the store's funnel
-- Run once in Supabase → SQL Editor, after 004-activity-log.sql.
--
-- The store notes anonymous steps (visit, page viewed, added to cart, reached payment,
-- sent the order…) under a random id that lives only while the tab is open: no names,
-- phones, cookies or IP addresses. The public can only add steps; only owners read them,
-- and only as totals through store_funnel().
-- ─────────────────────────────────────────────────────────────

create table if not exists public.store_events (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  session text not null,
  event text not null,
  device text not null default '',
  detail jsonb not null default '{}'::jsonb
);
create index if not exists store_events_at on public.store_events (at desc);
create index if not exists store_events_session on public.store_events (session);
alter table public.store_events enable row level security;
drop policy if exists owners_read on public.store_events;
create policy owners_read on public.store_events for select to authenticated using (public.is_owner());

create or replace function public.track_event(p_session text, p_event text, p_device text default '', p_detail jsonb default '{}'::jsonb)
returns void language plpgsql volatile security definer set search_path = public as $$
begin
  if coalesce(p_session, '') !~ '^[a-z0-9]{8,32}$' then return; end if;
  if p_event not in ('visit','view','add_to_cart','open_cart','form_error','payment_step','receipt_added','order_placed','order_failed') then return; end if;
  if p_detail is null or jsonb_typeof(p_detail) <> 'object' or length(p_detail::text) > 500 then p_detail := '{}'::jsonb; end if;
  if (select count(*) from store_events where session = p_session) >= 200 then return; end if;  -- one tab can't flood the table
  insert into store_events (session, event, device, detail)
  values (p_session, p_event, case when p_device in ('mobile','desktop') then p_device else '' end, p_detail);
end $$;

-- Totals for a period, for the panel's "Embudo de la tienda" card.
create or replace function public.store_funnel(p_from timestamptz, p_to timestamptz)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare out jsonb;
begin
  if not is_owner() then raise exception 'not_allowed'; end if;
  with e as (select * from store_events where at >= p_from and at < p_to),
  s as (
    select session,
           bool_or(event = 'add_to_cart') as added,
           bool_or(event = 'view' and detail ->> 'page' = 'checkout') as checkout,
           bool_or(event = 'payment_step') as payment,
           bool_or(event = 'order_placed') as ordered,
           max(device) as device,
           min(at) filter (where event = 'view' and detail ->> 'page' = 'checkout') as t_checkout,
           min(at) filter (where event = 'order_placed') as t_order
      from e group by session)
  select jsonb_build_object(
    'sessions', count(*),
    'added', count(*) filter (where added),
    'checkout', count(*) filter (where checkout),
    'payment', count(*) filter (where payment),
    'ordered', count(*) filter (where ordered),
    'mobile', count(*) filter (where device = 'mobile'),
    'mobile_ordered', count(*) filter (where device = 'mobile' and ordered),
    'desktop_ordered', count(*) filter (where device = 'desktop' and ordered),
    'median_checkout_min', (select round((percentile_cont(0.5) within group (order by extract(epoch from (t_order - t_checkout)) / 60))::numeric, 1)
                              from s where t_order > t_checkout),
    'form_errors', (select coalesce(jsonb_object_agg(f, n), '{}'::jsonb) from (select detail ->> 'field' f, count(*) n from e where event = 'form_error' and detail ? 'field' group by 1) x),
    'referrers', (select coalesce(jsonb_object_agg(r, n), '{}'::jsonb) from (select coalesce(nullif(detail ->> 'ref', ''), 'directo') r, count(*) n from e where event = 'visit' group by 1 order by 2 desc limit 6) y),
    'first_event', (select min(at) from store_events)
  ) into out from s;
  return out;
end $$;

revoke execute on function public.track_event(text, text, text, jsonb) from public;
revoke execute on function public.store_funnel(timestamptz, timestamptz) from public, anon;
grant execute on function public.track_event(text, text, text, jsonb) to anon, authenticated;
grant execute on function public.store_funnel(timestamptz, timestamptz) to authenticated;
