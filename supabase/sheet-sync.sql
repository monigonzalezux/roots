-- ─────────────────────────────────────────────────────────────
-- Roots · copy orders to the owners' Google Sheet
-- Run AFTER schema.sql, once the Apps Script in sheets/Code.gs is deployed as a web app.
-- Before running: replace PASTE_WEB_APP_URL_HERE below with the web app URL (…/exec).
--
-- Every new order, and every change to an order's status, is sent to the sheet.
-- Receipt images are not sent. The panel stays the source of truth: edits made
-- in the sheet don't come back.
-- ─────────────────────────────────────────────────────────────

create extension if not exists pg_net;

-- Where to send orders. No policies on purpose: neither the store nor the panel can read it.
create table if not exists public.sheet_sync (
  id int primary key default 1 check (id = 1),
  url text not null,
  token text not null
);
alter table public.sheet_sync enable row level security;

create or replace function public.sheet_post(o public.orders)
returns void language plpgsql security definer set search_path = public as $$
declare s public.sheet_sync;
begin
  select * into s from public.sheet_sync where id = 1;
  if s.url is null or s.url not like 'https://script.google.com/%' then return; end if;
  perform net.http_post(
    url := s.url,
    body := jsonb_build_object('token', s.token, 'order', to_jsonb(o) - 'history'),
    headers := '{"Content-Type": "application/json"}'::jsonb,
    timeout_milliseconds := 10000
  );
end $$;

create or replace function public.orders_to_sheet()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  perform public.sheet_post(new);
  return new;
end $$;

revoke execute on function public.sheet_post(public.orders) from public, anon, authenticated;
revoke execute on function public.orders_to_sheet() from public, anon, authenticated;

drop trigger if exists orders_to_sheet on public.orders;
create trigger orders_to_sheet
  after insert or update of status, customer, lines, total on public.orders
  for each row execute function public.orders_to_sheet();

insert into public.sheet_sync (id, url, token)
values (1, 'PASTE_WEB_APP_URL_HERE', 'PASTE_SYNC_TOKEN_HERE')
on conflict (id) do update set url = excluded.url, token = excluded.token;

-- Send the orders that already exist (safe to run again: rows are matched by order number).
select public.sheet_post(o) from public.orders o order by o.created_at;

-- To stop syncing later:  drop trigger orders_to_sheet on public.orders;
