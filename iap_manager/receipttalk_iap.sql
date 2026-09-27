-- =====================================================================
-- ReceiptTalk Apple IAP + 语音分钟包
-- 在 Supabase SQL Editor 执行（整段一次执行，带事务）
-- 只新增表/列/函数，不修改、不删除任何现有数据
-- =====================================================================
begin;

-- ---------------------------------------------------------------------
-- 1. Apple 交易流水：幂等 + 对账 + 退款回滚依据
-- ---------------------------------------------------------------------
create table if not exists public.iap_transactions (
  transaction_id          text primary key,              -- Apple transactionId（每次购买/续费都不同）
  original_transaction_id text not null,                 -- 同一订阅链不变
  user_id                 uuid not null,
  product_id              text not null,
  product_type            varchar(20) not null,          -- subscription / receipt_pack / voice_pack
  bundle_id               text,
  environment             varchar(20),                   -- Sandbox / Production
  purchased_at            timestamptz,
  expires_at              timestamptz,                   -- 仅订阅有
  revoked_at              timestamptz,                   -- 退款/撤销时间
  receipts_added          integer not null default 0,    -- 实际加到 raw_limit 的张数（退款按此回滚）
  voice_seconds_added     integer not null default 0,    -- 实际加到语音余额的秒数（退款按此回滚）
  created_at              timestamptz not null default now()
);

create index if not exists iap_transactions_user_idx
  on public.iap_transactions (user_id);
create index if not exists iap_transactions_original_idx
  on public.iap_transactions (original_transaction_id);
create index if not exists iap_transactions_active_sub_idx
  on public.iap_transactions (user_id, expires_at)
  where product_type = 'subscription' and revoked_at is null;

alter table public.iap_transactions enable row level security;
-- 不建 policy：只有后端（数据库直连）和 service_role 能读写

-- ---------------------------------------------------------------------
-- 2. 语音永久余额（分钟包充值进这里，不随月份清零）
-- ---------------------------------------------------------------------
create table if not exists public.aivoice_balance (
  user_id      uuid primary key,
  pack_seconds integer not null default 0 check (pack_seconds >= 0),
  updated_at   timestamptz not null default now()
);

alter table public.aivoice_balance enable row level security;

-- ---------------------------------------------------------------------
-- 3. 月度用量表加一列：本月有多少秒是从永久余额里扣的
--    本月“套餐内已用” = quick_voice_seconds + journey_voice_seconds - pack_seconds_used
-- ---------------------------------------------------------------------
alter table public.aivoice_usage_monthly
  add column if not exists pack_seconds_used integer not null default 0;

-- ---------------------------------------------------------------------
-- 4. 预扣：先扣当月套餐额度，不够再扣永久余额
--    quick_note 和 journey 共用一个月度秒数池
-- ---------------------------------------------------------------------
create or replace function public.reserve_aivoice_usage_v2(
  p_user_id uuid,
  p_usage_type text,
  p_seconds integer,
  p_month_seconds_limit integer
)
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  v_month      date := date_trunc('month', now() at time zone 'utc')::date;
  v_row        public.aivoice_usage_monthly%rowtype;
  v_pack       integer;
  v_month_used integer;
  v_month_left integer;
  v_from_month integer;
  v_from_pack  integer;
begin
  if p_usage_type not in ('quick_note', 'journey') or p_seconds < 1 then
    raise exception 'invalid voice usage reservation';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || v_month::text, 0));

  insert into public.aivoice_usage_monthly (user_id, month_start)
  values (p_user_id, v_month)
  on conflict (user_id, month_start) do nothing;

  select * into v_row
  from public.aivoice_usage_monthly
  where user_id = p_user_id and month_start = v_month
  for update;

  select pack_seconds into v_pack
  from public.aivoice_balance
  where user_id = p_user_id
  for update;
  v_pack := coalesce(v_pack, 0);

  v_month_used := greatest(
    v_row.quick_voice_seconds + v_row.journey_voice_seconds - v_row.pack_seconds_used, 0);
  v_month_left := greatest(p_month_seconds_limit - v_month_used, 0);
  v_from_month := least(p_seconds, v_month_left);
  v_from_pack  := p_seconds - v_from_month;

  if v_from_pack > v_pack then
    return jsonb_build_object(
      'allowed', false,
      'month_start', v_month,
      'month_used_seconds', v_month_used,
      'month_limit_seconds', p_month_seconds_limit,
      'pack_seconds', v_pack
    );
  end if;

  if p_usage_type = 'quick_note' then
    update public.aivoice_usage_monthly
    set quick_voice_count   = quick_voice_count + 1,
        quick_voice_seconds = quick_voice_seconds + p_seconds,
        pack_seconds_used   = pack_seconds_used + v_from_pack,
        updated_at          = now()
    where user_id = p_user_id and month_start = v_month;
  else
    update public.aivoice_usage_monthly
    set journey_voice_count   = journey_voice_count + 1,
        journey_voice_seconds = journey_voice_seconds + p_seconds,
        pack_seconds_used     = pack_seconds_used + v_from_pack,
        updated_at            = now()
    where user_id = p_user_id and month_start = v_month;
  end if;

  if v_from_pack > 0 then
    update public.aivoice_balance
    set pack_seconds = pack_seconds - v_from_pack,
        updated_at   = now()
    where user_id = p_user_id;
  end if;

  return jsonb_build_object(
    'allowed', true,
    'month_start', v_month,
    'from_month', v_from_month,
    'from_pack', v_from_pack,
    'month_used_seconds', v_month_used + v_from_month,
    'month_limit_seconds', p_month_seconds_limit,
    'pack_seconds', v_pack - v_from_pack
  );
end;
$function$;

-- ---------------------------------------------------------------------
-- 5. 退还：按预扣时的拆分精确退回（套餐部分退回当月，余额部分退回永久池）
--    p_month_start 用预扣返回的 month_start，跨月失败也能退对
-- ---------------------------------------------------------------------
create or replace function public.refund_aivoice_usage_v2(
  p_user_id uuid,
  p_usage_type text,
  p_seconds integer,
  p_from_pack integer,
  p_month_start date
)
returns void
language plpgsql
security definer
set search_path to 'public'
as $function$
begin
  if p_usage_type = 'quick_note' then
    update public.aivoice_usage_monthly
    set quick_voice_count   = greatest(quick_voice_count - 1, 0),
        quick_voice_seconds = greatest(quick_voice_seconds - p_seconds, 0),
        pack_seconds_used   = greatest(pack_seconds_used - coalesce(p_from_pack, 0), 0),
        updated_at          = now()
    where user_id = p_user_id and month_start = p_month_start;
  elsif p_usage_type = 'journey' then
    update public.aivoice_usage_monthly
    set journey_voice_count   = greatest(journey_voice_count - 1, 0),
        journey_voice_seconds = greatest(journey_voice_seconds - p_seconds, 0),
        pack_seconds_used     = greatest(pack_seconds_used - coalesce(p_from_pack, 0), 0),
        updated_at            = now()
    where user_id = p_user_id and month_start = p_month_start;
  end if;

  if coalesce(p_from_pack, 0) > 0 then
    insert into public.aivoice_balance (user_id, pack_seconds)
    values (p_user_id, p_from_pack)
    on conflict (user_id) do update
      set pack_seconds = public.aivoice_balance.pack_seconds + excluded.pack_seconds,
          updated_at   = now();
  end if;
end;
$function$;

-- ---------------------------------------------------------------------
-- 6. 查询当前语音额度（给 App 展示用）
-- ---------------------------------------------------------------------
create or replace function public.get_aivoice_status(
  p_user_id uuid,
  p_month_seconds_limit integer
)
returns jsonb
language plpgsql
stable
security definer
set search_path to 'public'
as $function$
declare
  v_month      date := date_trunc('month', now() at time zone 'utc')::date;
  v_row        public.aivoice_usage_monthly%rowtype;
  v_pack       integer;
  v_month_used integer;
begin
  select * into v_row
  from public.aivoice_usage_monthly
  where user_id = p_user_id and month_start = v_month;

  select pack_seconds into v_pack
  from public.aivoice_balance where user_id = p_user_id;
  v_pack := coalesce(v_pack, 0);

  v_month_used := greatest(
    coalesce(v_row.quick_voice_seconds, 0) + coalesce(v_row.journey_voice_seconds, 0)
    - coalesce(v_row.pack_seconds_used, 0), 0);

  return jsonb_build_object(
    'month_start', v_month,
    'quick_voice_count',     coalesce(v_row.quick_voice_count, 0),
    'quick_voice_seconds',   coalesce(v_row.quick_voice_seconds, 0),
    'journey_voice_count',   coalesce(v_row.journey_voice_count, 0),
    'journey_voice_seconds', coalesce(v_row.journey_voice_seconds, 0),
    'month_used_seconds',    v_month_used,
    'month_limit_seconds',   p_month_seconds_limit,
    'month_remaining_seconds', greatest(p_month_seconds_limit - v_month_used, 0),
    'pack_seconds',          v_pack,
    'total_remaining_seconds', greatest(p_month_seconds_limit - v_month_used, 0) + v_pack
  );
end;
$function$;

-- 只允许服务端调用（Edge Function 用 service_role key）
revoke all on function public.reserve_aivoice_usage_v2(uuid, text, integer, integer) from public, anon, authenticated;
revoke all on function public.refund_aivoice_usage_v2(uuid, text, integer, integer, date) from public, anon, authenticated;
revoke all on function public.get_aivoice_status(uuid, integer) from public, anon, authenticated;
grant execute on function public.reserve_aivoice_usage_v2(uuid, text, integer, integer) to service_role;
grant execute on function public.refund_aivoice_usage_v2(uuid, text, integer, integer, date) to service_role;
grant execute on function public.get_aivoice_status(uuid, integer) to service_role;

commit;

-- =====================================================================
-- 可选：把现有那 1 个 Apple 用户的 'Pro' 统一成小写 'pro'（和 Stripe 一致）
-- update public.user_level_en set subscription_status = 'pro' where subscription_status = 'Pro';
-- =====================================================================
