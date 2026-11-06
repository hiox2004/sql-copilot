-- Data consistency checks. Each query counts VIOLATIONS and must return 0.
-- Run at the end of database initialisation (a failure aborts the build) or on demand:
--   docker exec t2sql-postgres psql -U admin -d saas -v ref_now="'2026-11-05 12:00:00+00'" -f /schema/99_checks.sql
-- Rule of thumb: golden answers are only trustworthy if the data underneath obeys these.
\ir ref_include.inc

DO $chk$
DECLARE
  r record;
  n bigint;
  failures text := '';
  total int := 0;
BEGIN
  FOR r IN SELECT * FROM (VALUES
    -- ===== subscriptions =====
    ('sub canceled in future or before start',
     'SELECT count(*) FROM subscriptions WHERE canceled_at > pg_temp.ref() OR canceled_at < started_at'),
    ('sub started in future or before its org existed',
     'SELECT count(*) FROM subscriptions s JOIN organizations o ON o.id = s.org_id WHERE s.started_at > pg_temp.ref() OR s.started_at < o.created_at'),
    ('past_due sub without an open invoice',
     'SELECT count(*) FROM subscriptions s WHERE s.status = ''past_due'' AND NOT EXISTS (SELECT 1 FROM invoices i WHERE i.subscription_id = s.id AND i.status = ''open'')'),
    ('open invoice on a sub that is not past_due',
     'SELECT count(*) FROM invoices i JOIN subscriptions s ON s.id = i.subscription_id WHERE i.status = ''open'' AND s.status <> ''past_due'''),
    -- ===== invoices =====
    ('invoice outside subscription lifetime',
     'SELECT count(*) FROM invoices i JOIN subscriptions s ON s.id = i.subscription_id WHERE i.issued_at < s.started_at OR i.issued_at > COALESCE(s.canceled_at, pg_temp.ref())'),
    ('invoice for a free or trialing subscription',
     'SELECT count(*) FROM invoices i JOIN subscriptions s ON s.id = i.subscription_id WHERE s.status = ''trialing'' OR s.plan_tier = ''free'' AND NOT EXISTS (SELECT 1 FROM subscription_events e WHERE e.subscription_id = s.id AND e.event_type = ''upgraded'')'),
    ('invoice paid in the future or before issue',
     'SELECT count(*) FROM invoices WHERE paid_at > pg_temp.ref() OR paid_at < issued_at'),
    -- ===== subscription history =====
    ('subscription whose first event is not created',
     'SELECT count(*) FROM subscriptions s WHERE (SELECT event_type FROM subscription_events e WHERE e.subscription_id = s.id ORDER BY occurred_at, id LIMIT 1) IS DISTINCT FROM ''created'''),
    ('history ends in a different tier than the subscription',
     'SELECT count(*) FROM subscriptions s WHERE (SELECT to_tier FROM subscription_events e WHERE e.subscription_id = s.id AND e.event_type IN (''created'',''upgraded'',''downgraded'') ORDER BY occurred_at DESC, id DESC LIMIT 1) IS DISTINCT FROM s.plan_tier'),
    ('events after cancellation or in the future',
     'SELECT count(*) FROM subscription_events e JOIN subscriptions s ON s.id = e.subscription_id WHERE e.occurred_at > pg_temp.ref() OR (s.canceled_at IS NOT NULL AND e.occurred_at > s.canceled_at)'),
    ('canceled subscription without a canceled event',
     'SELECT count(*) FROM subscriptions s WHERE s.status = ''canceled'' AND NOT EXISTS (SELECT 1 FROM subscription_events e WHERE e.subscription_id = s.id AND e.event_type = ''canceled'')'),
    -- ===== orders and payments =====
    ('order total differs from its items, or order has no items',
     'SELECT count(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.id) OR o.total_cents <> (SELECT sum(quantity * unit_price_cents) FROM order_items i WHERE i.order_id = o.id)'),
    ('order before its org existed or in the future',
     'SELECT count(*) FROM orders o JOIN organizations g ON g.id = o.org_id WHERE o.created_at < g.created_at OR o.created_at > pg_temp.ref()'),
    ('payment amount differs from its order total',
     'SELECT count(*) FROM payments p JOIN orders o ON o.id = p.order_id WHERE p.amount_cents <> o.total_cents'),
    ('succeeded/refunded payment on a pending or canceled order, or refunded mismatch',
     'SELECT count(*) FROM payments p JOIN orders o ON o.id = p.order_id WHERE (o.status IN (''pending'',''canceled'') AND p.status <> ''failed'') OR (o.status = ''refunded'') <> (p.status = ''refunded'') AND p.status <> ''failed'''),
    ('payment dated before its order or in the future',
     'SELECT count(*) FROM payments p LEFT JOIN orders o ON o.id = p.order_id WHERE p.paid_at > pg_temp.ref() OR p.paid_at < o.created_at'),
    ('refund inconsistent with its payment',
     'SELECT count(*) FROM refunds r JOIN payments p ON p.id = r.payment_id WHERE p.status <> ''refunded'' OR r.amount_cents > p.amount_cents OR r.refunded_at < p.paid_at OR r.refunded_at > pg_temp.ref()'),
    ('refunded payment without a refund row',
     'SELECT count(*) FROM payments p WHERE p.status = ''refunded'' AND NOT EXISTS (SELECT 1 FROM refunds r WHERE r.payment_id = p.id)'),
    -- ===== people =====
    ('organization without any user',
     'SELECT count(*) FROM organizations o WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.org_id = o.id)'),
    ('user created before their org or in the future',
     'SELECT count(*) FROM users u JOIN organizations o ON o.id = u.org_id WHERE u.created_at < o.created_at OR u.created_at > pg_temp.ref()'),
    ('last_login_at not backed by a successful login',
     'SELECT count(*) FROM users u WHERE u.last_login_at IS DISTINCT FROM (SELECT max(occurred_at) FROM login_events l WHERE l.user_id = u.id AND l.success)'),
    -- ===== support =====
    ('ticket timeline broken',
     'SELECT count(*) FROM support_tickets t JOIN users u ON u.id = t.user_id WHERE t.resolved_at < t.created_at OR t.created_at < u.created_at OR t.created_at > pg_temp.ref() OR t.org_id <> u.org_id OR ((t.status IN (''resolved'',''closed'')) <> (t.resolved_at IS NOT NULL))'),
    ('survey on an unresolved ticket or before resolution',
     'SELECT count(*) FROM csat_surveys c JOIN support_tickets t ON t.id = c.ticket_id WHERE t.resolved_at IS NULL OR c.submitted_at < t.resolved_at OR c.submitted_at > pg_temp.ref()'),
    ('comment outside ticket lifetime',
     'SELECT count(*) FROM ticket_comments c JOIN support_tickets t ON t.id = c.ticket_id WHERE c.created_at < t.created_at OR c.created_at > COALESCE(t.resolved_at, pg_temp.ref())'),
    -- ===== usage =====
    ('feature usage outside subscription lifetime',
     'SELECT count(*) FROM feature_usage_daily f JOIN subscriptions s ON s.org_id = f.org_id WHERE f.usage_date < s.started_at::date OR f.usage_date > COALESCE(s.canceled_at, pg_temp.ref())::date'),
    ('api traffic outside key lifetime',
     'SELECT count(*) FROM api_requests_daily a JOIN api_keys k ON k.id = a.api_key_id WHERE a.request_date < k.created_at::date OR (k.revoked_at IS NOT NULL AND a.request_date >= k.revoked_at::date) OR a.request_date > pg_temp.ref()::date'),
    -- ===== sales =====
    ('converted lead predates nothing sensible',
     'SELECT count(*) FROM leads l JOIN organizations o ON o.id = l.converted_org_id WHERE o.created_at < l.created_at'),
    ('opportunity timeline broken',
     'SELECT count(*) FROM opportunities o WHERE o.closed_at < o.created_at OR o.created_at > pg_temp.ref() OR ((o.stage IN (''won'',''lost'')) <> (o.closed_at IS NOT NULL))'),
    ('email event outside lead lifetime or campaign',
     'SELECT count(*) FROM email_events e JOIN leads l ON l.id = e.lead_id WHERE e.occurred_at < l.created_at OR e.occurred_at > pg_temp.ref() OR l.campaign_id IS DISTINCT FROM e.campaign_id'),
    -- ===== HR / system =====
    ('expense outside employment',
     'SELECT count(*) FROM expense_reports x JOIN employees e ON e.id = x.employee_id WHERE x.submitted_at < e.hired_at OR x.submitted_at > COALESCE(e.terminated_at, pg_temp.ref())'),
    ('audit/notification dated in the future or before the user existed',
     'SELECT (SELECT count(*) FROM audit_log a LEFT JOIN users u ON u.id = a.actor_user_id WHERE a.occurred_at > pg_temp.ref() OR a.occurred_at < COALESCE(u.created_at, ''-infinity'')) + (SELECT count(*) FROM notifications n JOIN users u ON u.id = n.user_id WHERE n.sent_at > pg_temp.ref() OR n.sent_at < u.created_at OR n.read_at < n.sent_at OR n.read_at > pg_temp.ref())'),
    -- ===== distribution guards: enough variety to ask interesting questions =====
    ('too few recent churn events (need >= 8 in last 30 days)',
     'SELECT (count(*) < 8)::int FROM subscriptions WHERE status = ''canceled'' AND canceled_at >= pg_temp.ref() - interval ''30 days'''),
    ('too few enterprise subscriptions (need >= 15)',
     'SELECT (count(*) < 15)::int FROM subscriptions WHERE plan_tier = ''enterprise'''),
    ('too few past_due subscriptions (need >= 8)',
     'SELECT (count(*) < 8)::int FROM subscriptions WHERE status = ''past_due'''),
    ('login activity looks uniform (need 5-40% of users active in 7 days, 20-70% in 30 days)',
     'SELECT (a7 < 0.05 * n OR a7 > 0.40 * n OR a30 < 0.20 * n OR a30 > 0.70 * n)::int FROM (SELECT count(*)::numeric AS n, count(*) FILTER (WHERE last_login_at > pg_temp.ref() - interval ''7 days'') AS a7, count(*) FILTER (WHERE last_login_at > pg_temp.ref() - interval ''30 days'') AS a30 FROM users) s'),
    ('dates look constant: random() evaluated once instead of per row (prospect leads, lost deals, hire dates)',
     'SELECT ((SELECT count(DISTINCT created_at) FROM leads WHERE converted_org_id IS NULL) < 100 OR (SELECT count(DISTINCT closed_at) FROM opportunities WHERE stage = ''lost'') < 20 OR (SELECT count(DISTINCT hired_at) FROM employees) < 20)::int'),
    ('marketing channels look degenerate (every channel needs >= 30 leads and a conversion rate strictly between 0 and 60 percent)',
     'SELECT count(*) FROM (SELECT c.channel FROM campaigns c LEFT JOIN leads l ON l.campaign_id = c.id GROUP BY c.channel HAVING count(l.id) < 30 OR avg((l.status = ''converted'')::int) NOT BETWEEN 0.01 AND 0.60) bad'),
    ('email funnel degenerate (need >= 20 opened and >= 5 clicked events, and fewer opens than sends)',
     'SELECT ((count(*) FILTER (WHERE event_type = ''opened'') < 20) OR (count(*) FILTER (WHERE event_type = ''clicked'') < 5) OR (count(*) FILTER (WHERE event_type = ''opened'') >= count(*) FILTER (WHERE event_type = ''sent'')))::int FROM email_events'),
    ('too few upgrades/downgrades/reactivations (need >= 10 / 3 / 3)',
     'SELECT ((count(*) FILTER (WHERE event_type = ''upgraded'') < 10) OR (count(*) FILTER (WHERE event_type = ''downgraded'') < 3) OR (count(*) FILTER (WHERE event_type = ''reactivated'') < 3))::int FROM subscription_events')
  ) AS t(name, q)
  LOOP
    EXECUTE r.q INTO n;
    total := total + 1;
    IF n <> 0 THEN
      failures := failures || '  - ' || r.name || ' (' || n || E')\n';
    END IF;
  END LOOP;

  IF failures <> '' THEN
    RAISE EXCEPTION E'Data consistency check FAILED:\n%', failures;
  END IF;
  RAISE NOTICE 'Data consistency: all % checks passed.', total;
END
$chk$;
