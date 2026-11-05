-- Seed for the supporting tables (support, usage, marketing, HR, system, misc).
-- Rules baked in: nothing is dated after pg_temp.ref(); activity stays inside the
-- lifetimes of the users/orgs/subscriptions it belongs to. 99_checks.sql verifies it.
\ir ref_include.inc
SELECT setseed(0.43);

-- ---------- misc customer data ----------
INSERT INTO addresses (org_id, kind, city, country, postal_code)
SELECT o.id, 'billing', (ARRAY['Austin','London','Berlin','Pune','Recife','Toronto'])[1 + o.id % 6], o.country, lpad((10000 + o.id * 37 % 89999)::text, 5, '0')
FROM organizations o;
INSERT INTO addresses (org_id, kind, city, country, postal_code)
SELECT o.id, 'shipping', (ARRAY['Denver','Leeds','Munich','Mumbai','Salvador','Calgary'])[1 + o.id % 6], o.country, lpad((20000 + o.id * 53 % 79999)::text, 5, '0')
FROM organizations o WHERE o.id % 5 < 2;

INSERT INTO org_settings (org_id, key, value, updated_at)
SELECT o.id, k.key, k.val, o.created_at + random() * (pg_temp.ref() - o.created_at)
FROM organizations o
CROSS JOIN LATERAL (VALUES
   ('timezone',  (ARRAY['UTC','America/New_York','Europe/Berlin','Asia/Kolkata'])[1 + o.id % 4]),
   ('locale',    (ARRAY['en-US','en-GB','de-DE'])[1 + o.id % 3]),
   ('invoice_emails', CASE WHEN o.id % 4 = 0 THEN 'off' ELSE 'on' END)
) k(key, val);

INSERT INTO coupons (code, percent_off, valid_from, valid_until, max_redemptions)
SELECT 'SAVE' || (g * 5), g * 5, pg_temp.ref() - interval '300 days', pg_temp.ref() + interval '60 days', 20 * g
FROM generate_series(1,8) g;

INSERT INTO coupon_redemptions (coupon_id, org_id, redeemed_at)
SELECT x.cid, o.id, GREATEST(o.created_at, c.valid_from) + x.r * (pg_temp.ref() - GREATEST(o.created_at, c.valid_from))
FROM (SELECT 1 + floor(random()*8)::int AS cid, 1 + floor(random()*150)::int AS oid, random() AS r
      FROM generate_series(1,60) OFFSET 0) x
JOIN coupons c ON c.id = x.cid JOIN organizations o ON o.id = x.oid;

-- ---------- logins; then users.last_login_at is DERIVED from them ----------
INSERT INTO login_events (user_id, occurred_at, success, ip_country)
SELECT u.id,
       GREATEST(u.created_at, pg_temp.ref() - interval '90 days')
         + random() * (pg_temp.ref() - GREATEST(u.created_at, pg_temp.ref() - interval '90 days')),
       random() < 0.92,
       (ARRAY['US','UK','DE','IN','BR','CA'])[1 + floor(random()*6)::int]
FROM users u CROSS JOIN generate_series(1,12) g;

UPDATE users u SET last_login_at = (SELECT max(occurred_at) FROM login_events l WHERE l.user_id = u.id AND l.success);

-- ---------- support ----------
INSERT INTO support_agents (full_name, team, hired_at)
SELECT 'Agent ' || g, (ARRAY['tier1','tier1','tier2','billing'])[1 + g % 4], pg_temp.ref() - interval '90 days' - g * interval '50 days'
FROM generate_series(1,12) g;

INSERT INTO support_tickets (org_id, user_id, assigned_agent_id, status, priority, category, subject, created_at, resolved_at)
SELECT u.org_id, u.id,
       CASE WHEN x.status = 'open' AND x.r_a < 0.1 THEN NULL ELSE 1 + floor(x.r_a2*12)::int END,
       x.status, x.priority, x.category, 'Question about ' || x.category,
       t.c,
       CASE WHEN x.status IN ('resolved','closed')
            THEN LEAST(t.c + interval '1 hour' + x.r_res * interval '5 days', pg_temp.ref()) END
FROM (SELECT 1 + floor(random() * (SELECT count(*) FROM users))::int AS uid,
             (ARRAY['open','pending','resolved','resolved','resolved','closed','closed'])[1 + floor(random()*7)::int] AS status,
             (ARRAY['low','normal','normal','high','urgent'])[1 + floor(random()*5)::int] AS priority,
             (ARRAY['billing','bug','how_to','feature_request'])[1 + floor(random()*4)::int] AS category,
             random() r_a, random() r_a2, random() r_res, random() r_c
      FROM generate_series(1,900) OFFSET 0) x
JOIN users u ON u.id = x.uid
CROSS JOIN LATERAL (SELECT u.created_at + x.r_c * (pg_temp.ref() - u.created_at) AS c) t;

INSERT INTO ticket_comments (ticket_id, author_type, body, created_at)
SELECT t.id, CASE WHEN k % 2 = 1 THEN 'user' ELSE 'agent' END,
       (ARRAY['Thanks for reaching out.','Could you share more details?','We are looking into it.','This should now be resolved.'])[1 + floor(random()*4)::int],
       t.created_at + LEAST(k * interval '2 hours', COALESCE(t.resolved_at, pg_temp.ref()) - t.created_at)
FROM support_tickets t CROSS JOIN generate_series(1,4) k
WHERE k <= 1 + (t.id % 4);

INSERT INTO csat_surveys (ticket_id, score, submitted_at)
SELECT t.id, (ARRAY[1,2,3,4,4,5,5,5])[1 + floor(random()*8)::int],
       LEAST(t.resolved_at + random() * interval '2 days', pg_temp.ref())
FROM support_tickets t WHERE t.status IN ('resolved','closed') AND t.id % 5 < 2;

-- ---------- product usage ----------
INSERT INTO features (key, name, category)
SELECT k, initcap(replace(k, '_', ' ')), c FROM (VALUES
  ('dashboards','core'),('reports','core'),('alerts','core'),('exports','core'),
  ('sso','security'),('audit_trail','security'),('api_access','platform'),('webhooks','platform'),
  ('custom_roles','security'),('scheduled_reports','core'),('data_import','platform'),('mobile_app','core')
) v(k, c);

INSERT INTO feature_usage_daily (org_id, feature_id, usage_date, event_count)
SELECT s.org_id, f.id, pg_temp.ref()::date - d, 1 + floor(random()*200)::int
FROM subscriptions s CROSS JOIN features f CROSS JOIN generate_series(0,59) d
WHERE (s.org_id * 7 + f.id * 13) % 5 < 2
  AND random() < 0.5
  AND pg_temp.ref()::date - d >= s.started_at::date
  AND pg_temp.ref()::date - d <= COALESCE(s.canceled_at, pg_temp.ref())::date;

INSERT INTO api_keys (org_id, label, created_at, revoked_at)
SELECT x.org_id, 'key-' || x.org_id || '-' || x.k,
       x.created,
       CASE WHEN s.status = 'canceled' THEN s.canceled_at
            WHEN x.r_rev < 0.2 THEN x.created + x.r_rev2 * (pg_temp.ref() - x.created) END
FROM (SELECT s.org_id, k.k,
             s.started_at + random() * (COALESCE(s.canceled_at, pg_temp.ref()) - s.started_at) AS created,
             random() r_rev, random() r_rev2
      FROM subscriptions s CROSS JOIN generate_series(1,2) k(k)
      WHERE s.plan_tier <> 'free' AND s.status <> 'trialing' AND (k.k = 1 OR random() < 0.4) OFFSET 0) x
JOIN subscriptions s ON s.org_id = x.org_id;

INSERT INTO api_requests_daily (api_key_id, request_date, request_count, error_count)
SELECT x.id, x.dt, x.cnt, floor(x.cnt * x.er)::int
FROM (SELECT k.id, pg_temp.ref()::date - d AS dt, 10 + floor(random()*5000)::int AS cnt, random() * 0.1 AS er
      FROM api_keys k CROSS JOIN generate_series(0,29) d
      WHERE pg_temp.ref()::date - d >= k.created_at::date
        AND (k.revoked_at IS NULL OR pg_temp.ref()::date - d < k.revoked_at::date) OFFSET 0) x;

-- ---------- marketing and sales ----------
INSERT INTO campaigns (name, channel, budget_cents, started_at, ended_at)
SELECT 'Campaign ' || g, (ARRAY['email','ads','webinar','content'])[1 + g % 4], 100000 * (5 + g),
       pg_temp.ref() - interval '500 days' + g * interval '40 days',
       pg_temp.ref() - interval '500 days' + g * interval '40 days' + interval '60 days'
FROM generate_series(0,9) g;

INSERT INTO sales_reps (full_name, region, hired_at)
SELECT 'Rep ' || g, (ARRAY['NA','EMEA','APAC','LATAM'])[1 + g % 4], pg_temp.ref() - interval '200 days' - g * interval '60 days'
FROM generate_series(1,8) g;

-- leads that became customers (about 60% of orgs): created 5..60 days before the org
INSERT INTO leads (campaign_id, company_name, contact_email, status, created_at, converted_org_id)
SELECT (SELECT c.id FROM campaigns c WHERE c.started_at <= lc.t AND c.ended_at >= lc.t ORDER BY random() LIMIT 1),
       o.name, 'lead-org' || o.id || '@example.test', 'converted', lc.t, o.id
FROM organizations o
CROSS JOIN LATERAL (SELECT o.created_at - (5 + random()*55) * interval '1 day' AS t) lc
WHERE o.id % 10 < 6;

-- other prospects
INSERT INTO leads (campaign_id, company_name, contact_email, status, created_at, converted_org_id)
SELECT CASE WHEN random() < 0.75
            THEN (SELECT c.id FROM campaigns c WHERE c.started_at <= lc.t AND c.ended_at >= lc.t ORDER BY random() LIMIT 1) END,
       'Prospect ' || g, 'lead' || g || '@example.test',
       (ARRAY['new','qualified','lost'])[1 + floor(random()*3)::int], lc.t, NULL
FROM generate_series(1,400) g
CROSS JOIN LATERAL (SELECT pg_temp.ref() - random() * interval '450 days' AS t) lc;

INSERT INTO opportunities (lead_id, rep_id, stage, amount_cents, created_at, closed_at)
SELECT l.id, 1 + floor(random()*8)::int, 'won', GREATEST(s.mrr_cents, 4900) * 12,
       l.created_at + interval '1 day', o.created_at - interval '1 day'
FROM leads l JOIN organizations o ON o.id = l.converted_org_id JOIN subscriptions s ON s.org_id = o.id;

INSERT INTO opportunities (lead_id, rep_id, stage, amount_cents, created_at, closed_at)
SELECT l.id, 1 + floor(random()*8)::int,
       CASE l.status WHEN 'lost' THEN 'lost'
                     WHEN 'qualified' THEN (ARRAY['proposal','negotiation'])[1 + floor(random()*2)::int]
                     ELSE 'prospecting' END,
       100000 * (1 + floor(random()*30)::int),
       LEAST(l.created_at + interval '1 day', pg_temp.ref()),
       CASE WHEN l.status = 'lost' THEN LEAST(l.created_at + interval '30 days', pg_temp.ref()) END
FROM leads l WHERE l.converted_org_id IS NULL AND l.status <> 'new';

INSERT INTO email_events (campaign_id, lead_id, event_type, occurred_at)
SELECT l.campaign_id, l.id, e.t, LEAST(l.created_at + e.off, pg_temp.ref())
FROM leads l
CROSS JOIN LATERAL (VALUES ('sent', interval '1 day', 1.0), ('opened', interval '2 days', 0.5),
                           ('clicked', interval '3 days', 0.15), ('unsubscribed', interval '4 days', 0.03)) e(t, off, p)
WHERE l.campaign_id IS NOT NULL AND random() < e.p;

-- ---------- HR (internal company, unrelated to customers) ----------
INSERT INTO departments (name, cost_center) VALUES
  ('Engineering','CC100'),('Sales','CC200'),('Support','CC300'),('Marketing','CC400'),('Finance','CC500'),('People','CC600');

INSERT INTO office_locations (city, country, headcount_capacity) VALUES
  ('Austin','US',60),('London','UK',40),('Berlin','DE',30),('Pune','IN',80),('Remote','--',200);

INSERT INTO employees (department_id, full_name, email, title, hired_at, terminated_at, salary_cents)
SELECT 1 + g % 6, 'Employee ' || g, 'employee' || g || '@company.test',
       (ARRAY['Associate','Engineer','Senior','Manager'])[1 + g % 4],
       h.hired,
       CASE WHEN g % 10 = 0 THEN h.hired + interval '60 days' + random() * (pg_temp.ref() - h.hired - interval '60 days') END,
       6000000 + 100000 * floor(random()*100)::int
FROM generate_series(1,40) g
CROSS JOIN LATERAL (SELECT pg_temp.ref() - interval '120 days' - random() * interval '1500 days' AS hired) h;

INSERT INTO expense_reports (employee_id, amount_cents, category, status, submitted_at)
SELECT e.id, 2000 + floor(random()*200000)::int,
       (ARRAY['travel','software','meals','equipment'])[1 + floor(random()*4)::int],
       (ARRAY['submitted','approved','approved','rejected','paid','paid'])[1 + floor(random()*6)::int],
       e.hired_at + x.r * (COALESCE(e.terminated_at, pg_temp.ref()) - e.hired_at)
FROM (SELECT 1 + floor(random()*40)::int AS eid, random() r FROM generate_series(1,150) OFFSET 0) x
JOIN employees e ON e.id = x.eid;

-- ---------- system ----------
INSERT INTO feature_flags (key, enabled, rollout_percent, updated_at)
SELECT 'flag_' || g, g % 3 <> 0, CASE WHEN g % 3 = 0 THEN 0 ELSE 25 * (1 + g % 4) END,
       pg_temp.ref() - g * interval '9 days'
FROM generate_series(1,10) g;

INSERT INTO audit_log (actor_user_id, action, entity_type, entity_id, occurred_at)
SELECT x.uid,
       (ARRAY['login','update_settings','export_data','delete_user','create_api_key'])[1 + floor(random()*5)::int],
       (ARRAY['user','organization','api_key','subscription'])[1 + floor(random()*4)::int],
       1 + floor(random()*150)::int,
       b.base + x.r * (pg_temp.ref() - b.base)
FROM (SELECT CASE WHEN random() < 0.1 THEN NULL ELSE 1 + floor(random() * (SELECT count(*) FROM users))::int END AS uid, random() r
      FROM generate_series(1,1000) OFFSET 0) x
LEFT JOIN users u ON u.id = x.uid
CROSS JOIN LATERAL (SELECT COALESCE(u.created_at, pg_temp.ref() - interval '400 days') AS base) b;

INSERT INTO notifications (user_id, kind, sent_at, read_at)
SELECT u.id, x.kind, s.sent,
       CASE WHEN x.r_read < 0.6 THEN LEAST(s.sent + x.r_read2 * interval '2 days', pg_temp.ref()) END
FROM (SELECT 1 + floor(random() * (SELECT count(*) FROM users))::int AS uid,
             (ARRAY['invoice','security','product','marketing'])[1 + floor(random()*4)::int] AS kind,
             random() r_s, random() r_read, random() r_read2
      FROM generate_series(1,1500) OFFSET 0) x
JOIN users u ON u.id = x.uid
CROSS JOIN LATERAL (SELECT u.created_at + x.r_s * (pg_temp.ref() - u.created_at) AS sent) s;

ANALYZE;
