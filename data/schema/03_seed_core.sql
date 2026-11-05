-- Core seed: organizations, users, subscriptions (+history), invoices, products, orders, payments.
-- Deterministic: dates hang off pg_temp.ref() (pinned "today"), randomness off setseed().
-- Consistency is enforced by 99_checks.sql.
\ir ref_include.inc
SELECT setseed(0.42);

-- ---------- reference: plan price list ----------
INSERT INTO plans (tier, name, monthly_price_cents, seats_included, is_public) VALUES
  ('free', 'Free', 0, 1, TRUE),
  ('pro', 'Pro', 9900, 10, TRUE),
  ('enterprise', 'Enterprise', 250000, 100, FALSE);

-- ---------- 150 organizations, created 60..900 days before ref ----------
INSERT INTO organizations (name, industry, country, created_at)
SELECT 'Org ' || g,
       (ARRAY['fintech','health','retail','education','logistics','media'])[1 + floor(random()*6)::int],
       (ARRAY['US','UK','DE','IN','BR','CA'])[1 + floor(random()*6)::int],
       pg_temp.ref() - interval '60 days' - random() * interval '840 days'
FROM generate_series(1,150) g;

-- ---------- users: one admin per org + 300 more (last_login_at is filled from login_events later) ----------
INSERT INTO users (org_id, email, full_name, role, created_at)
SELECT o.id, 'admin' || o.id || '@example.test', 'Admin ' || o.id, 'admin',
       o.created_at + random() * interval '2 days'
FROM organizations o;

INSERT INTO users (org_id, email, full_name, role, created_at)
SELECT x.org_id, 'user' || x.g || '@example.test', 'User ' || x.g, x.role,
       o.created_at + x.r * (pg_temp.ref() - o.created_at)
FROM (SELECT g,
             1 + floor(random()*150)::int AS org_id,
             (ARRAY['admin','member','member','viewer'])[1 + floor(random()*4)::int] AS role,
             random() AS r
      FROM generate_series(1,300) g OFFSET 0) x
JOIN organizations o ON o.id = x.org_id;

-- ---------- subscriptions: draw randomness ONCE per org, then derive everything ----------
CREATE TEMP TABLE _draw AS
SELECT o.id AS org_id, o.created_at AS org_created,
       random() r_tier, random() r_status, random() r_start, random() r_ck, random() r_cp,
       random() r_price, random() r_hist, random() r_hpos, random() r_react, random() r_p1, random() r_p2
FROM organizations o ORDER BY o.id;

CREATE TEMP TABLE _s2 AS
SELECT d.*,
       t.tier,
       CASE WHEN t.tier = 'free' THEN CASE WHEN r_status < 0.80 THEN 'active' ELSE 'canceled' END
            ELSE CASE WHEN r_status < 0.10 THEN 'trialing'
                      WHEN r_status < 0.70 THEN 'active'
                      WHEN r_status < 0.82 THEN 'past_due'
                      ELSE 'canceled' END END AS status,
       CASE t.tier WHEN 'free' THEN 0
                   WHEN 'pro' THEN 4900 + 1000 * floor(r_price*11)::int
                   ELSE 150000 + 50000 * floor(r_price*18)::int END AS mrr
FROM _draw d
CROSS JOIN LATERAL (SELECT CASE WHEN d.r_tier < 0.35 THEN 'free' WHEN d.r_tier < 0.80 THEN 'pro' ELSE 'enterprise' END AS tier) t;

CREATE TEMP TABLE _s3 AS
SELECT s.*,
       CASE WHEN status = 'trialing' THEN pg_temp.ref() - (1 + r_start*13) * interval '1 day'
            ELSE org_created + r_start * interval '30 days' END AS start_at
FROM _s2 s;

CREATE TEMP TABLE _s4 AS
SELECT s.*,
       CASE WHEN status = 'canceled' THEN
              CASE WHEN r_ck < 0.45
                   THEN GREATEST(pg_temp.ref() - r_cp * interval '30 days', start_at + interval '10 days')
                   ELSE start_at + interval '10 days' + r_cp * (pg_temp.ref() - start_at - interval '10 days') END
       END AS canceled_at
FROM _s3 s;

CREATE TEMP TABLE _s5 AS
SELECT s.*, COALESCE(canceled_at, pg_temp.ref()) AS end_at,
       CASE WHEN status IN ('active','canceled') AND tier = 'pro' AND r_hist < 0.25 THEN 'free'
            WHEN status IN ('active','canceled') AND tier = 'pro' AND r_hist < 0.35 THEN 'enterprise'
            WHEN status IN ('active','canceled') AND tier = 'enterprise' AND r_hist < 0.35 THEN 'pro'
            ELSE tier END AS init_tier
FROM _s4 s;

CREATE TEMP TABLE _s6 AS
SELECT s.*,
       CASE WHEN init_tier = tier THEN mrr WHEN init_tier = 'free' THEN 0
            WHEN init_tier = 'pro' THEN 9900 ELSE 200000 END AS init_mrr,
       CASE WHEN init_tier <> tier
            THEN start_at + interval '5 days' + r_hpos * 0.9 * (end_at - start_at - interval '5 days') END AS change_at,
       CASE WHEN status = 'active' AND start_at < pg_temp.ref() - interval '90 days' AND r_react < 0.10
            THEN start_at + interval '20 days' + r_p1 * 0.5 * (pg_temp.ref() - start_at - interval '60 days') END AS t1
FROM _s5 s;

CREATE TEMP TABLE _s7 AS
SELECT s.*,
       CASE WHEN t1 IS NOT NULL
            THEN t1 + interval '5 days' + r_p2 * (0.5 * (pg_temp.ref() - start_at - interval '60 days') - interval '5 days') END AS t2,
       NULL::int AS sub_id
FROM _s6 s;

INSERT INTO subscriptions (org_id, plan_tier, status, mrr_cents, started_at, canceled_at)
SELECT org_id, tier, status, mrr, start_at, canceled_at FROM _s7 ORDER BY org_id;

UPDATE _s7 SET sub_id = s.id FROM subscriptions s WHERE s.org_id = _s7.org_id;

-- ---------- invoices: monthly from start, price follows tier history, none in cancel gaps ----------
INSERT INTO invoices (subscription_id, amount_cents, status, issued_at, due_at, paid_at)
SELECT sub_id, price, 'paid', issued, issued + interval '14 days', LEAST(issued + interval '3 days', pg_temp.ref())
FROM (
  SELECT h.sub_id, h.t1, h.t2,
         h.start_at + (m || ' months')::interval AS issued,
         CASE WHEN h.change_at IS NOT NULL AND h.start_at + (m || ' months')::interval < h.change_at
              THEN h.init_mrr ELSE h.mrr END AS price,
         CASE h.status WHEN 'canceled' THEN h.canceled_at
                       WHEN 'past_due' THEN pg_temp.ref() - interval '15 days'
                       ELSE pg_temp.ref() END AS cap
  FROM _s7 h CROSS JOIN generate_series(0,36) m
  WHERE h.tier <> 'free' AND h.status <> 'trialing'
) q
WHERE issued <= cap AND price > 0 AND NOT (t1 IS NOT NULL AND issued >= t1 AND issued < t2);

-- past-due subscriptions: their newest invoice is unpaid
UPDATE invoices i SET status = 'open', paid_at = NULL
FROM (SELECT DISTINCT ON (i2.subscription_id) i2.id
      FROM invoices i2 JOIN _s7 h ON h.sub_id = i2.subscription_id
      WHERE h.status = 'past_due'
      ORDER BY i2.subscription_id, i2.issued_at DESC) l
WHERE i.id = l.id;

-- ---------- subscription history ----------
INSERT INTO subscription_events (subscription_id, event_type, from_tier, to_tier, mrr_cents_before, mrr_cents_after, occurred_at)
SELECT sub_id, 'created', NULL, init_tier, 0, init_mrr, start_at FROM _s7
UNION ALL
SELECT sub_id, CASE WHEN mrr > init_mrr THEN 'upgraded' ELSE 'downgraded' END, init_tier, tier, init_mrr, mrr, change_at
  FROM _s7 WHERE change_at IS NOT NULL
UNION ALL
SELECT sub_id, 'canceled', tier, tier, mrr, 0, canceled_at FROM _s7 WHERE status = 'canceled'
UNION ALL
SELECT sub_id, 'canceled', tier, tier, mrr, 0, t1 FROM _s7 WHERE t1 IS NOT NULL
UNION ALL
SELECT sub_id, 'reactivated', tier, tier, 0, mrr, t2 FROM _s7 WHERE t1 IS NOT NULL
UNION ALL
SELECT i.subscription_id, 'payment_failed', s.plan_tier, s.plan_tier, i.amount_cents, i.amount_cents, i.due_at
  FROM invoices i JOIN subscriptions s ON s.id = i.subscription_id WHERE i.status = 'open';

-- ---------- products, orders, items ----------
INSERT INTO products (name, category, price_cents, is_active)
SELECT 'Product ' || g,
       (ARRAY['addon','training','hardware','support'])[1 + floor(random()*4)::int],
       1000 + 500 * floor(random()*40)::int,
       random() < 0.9
FROM generate_series(1,25) g;

INSERT INTO orders (org_id, status, created_at)
SELECT x.org_id, x.status, o.created_at + x.r * (pg_temp.ref() - o.created_at)
FROM (SELECT 1 + floor(random()*150)::int AS org_id,
             (ARRAY['paid','paid','paid','paid','pending','refunded','canceled'])[1 + floor(random()*7)::int] AS status,
             random() AS r
      FROM generate_series(1,1200) OFFSET 0) x
JOIN organizations o ON o.id = x.org_id;

INSERT INTO order_items (order_id, product_id, quantity, unit_price_cents)
SELECT o.id, p.id, 1 + floor(random()*5)::int, p.price_cents
FROM orders o
CROSS JOIN LATERAL (SELECT id, price_cents FROM products WHERE o.id > 0 ORDER BY random() LIMIT 1 + (o.id % 4)) p;

UPDATE orders o SET total_cents = s.total
FROM (SELECT order_id, SUM(quantity * unit_price_cents) AS total FROM order_items GROUP BY order_id) s
WHERE s.order_id = o.id;

-- ---------- payments ----------
INSERT INTO payments (order_id, amount_cents, method, status, paid_at)
SELECT id, total_cents,
       (ARRAY['card','card','bank_transfer','paypal'])[1 + floor(random()*4)::int],
       CASE WHEN status = 'refunded' THEN 'refunded' ELSE 'succeeded' END,
       LEAST(created_at + interval '1 day', pg_temp.ref())
FROM orders WHERE status IN ('paid','refunded');

-- failed attempts on some pending orders
INSERT INTO payments (order_id, amount_cents, method, status, paid_at)
SELECT id, total_cents, 'card', 'failed', LEAST(created_at + interval '1 hour', pg_temp.ref())
FROM orders WHERE status = 'pending' AND id % 3 <> 0;

INSERT INTO payments (invoice_id, amount_cents, method, status, paid_at)
SELECT id, amount_cents, (ARRAY['card','card','bank_transfer'])[1 + floor(random()*3)::int], 'succeeded', paid_at
FROM invoices WHERE status = 'paid';

-- unpaid invoices: a failed attempt on the due date
INSERT INTO payments (invoice_id, amount_cents, method, status, paid_at)
SELECT id, amount_cents, 'card', 'failed', due_at FROM invoices WHERE status = 'open';

-- 5% of paid invoices needed a retry: an earlier failed attempt
INSERT INTO payments (invoice_id, amount_cents, method, status, paid_at)
SELECT id, amount_cents, 'card', 'failed', paid_at - interval '1 day'
FROM invoices WHERE status = 'paid' AND random() < 0.05 AND paid_at - interval '1 day' >= issued_at;

-- ---------- refunds: one per refunded payment ----------
INSERT INTO refunds (payment_id, amount_cents, reason, refunded_at)
SELECT id, amount_cents,
       (ARRAY['customer_request','duplicate','fraud','service_issue'])[1 + floor(random()*4)::int],
       LEAST(paid_at + random() * interval '10 days', pg_temp.ref())
FROM payments WHERE status = 'refunded';

ANALYZE;
