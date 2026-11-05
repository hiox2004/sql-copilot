-- Deterministic fake data. Safe to re-run only on an empty database.
SELECT setseed(0.42);

-- 60 organizations
INSERT INTO organizations (name, industry, country, created_at)
SELECT 'Org ' || g,
       (ARRAY['fintech','health','retail','education','logistics','media'])[1 + floor(random()*6)::int],
       (ARRAY['US','UK','DE','IN','BR','CA'])[1 + floor(random()*6)::int],
       NOW() - (random()*900 || ' days')::interval
FROM generate_series(1,60) g;

-- 3 users per organization on average (180)
INSERT INTO users (org_id, email, full_name, role, created_at, last_login_at)
SELECT 1 + floor(random()*60)::int,
       'user' || g || '@example.test',
       'User ' || g,
       (ARRAY['admin','member','member','viewer'])[1 + floor(random()*4)::int],
       NOW() - (random()*800 || ' days')::interval,
       CASE WHEN random() < 0.85 THEN NOW() - (random()*60 || ' days')::interval END
FROM generate_series(1,180) g;

-- one subscription per organization
INSERT INTO subscriptions (org_id, plan_tier, status, mrr_cents, started_at, canceled_at)
SELECT o.id, t.tier, t.status,
       CASE t.tier WHEN 'free' THEN 0
                   WHEN 'pro' THEN 4900 + 1000*floor(random()*10)::int
                   ELSE 100000 + 10000*floor(random()*20)::int END,
       t.started,
       CASE WHEN t.status = 'canceled' THEN t.started + (random()*200 + 10 || ' days')::interval END
FROM organizations o
CROSS JOIN LATERAL (
    SELECT (ARRAY['free','pro','pro','enterprise'])[1 + floor(random()*4 + o.id*0)::int] AS tier,
           (ARRAY['trialing','active','active','active','past_due','canceled'])[1 + floor(random()*6 + o.id*0)::int] AS status,
           NOW() - (random()*700 + 30 || ' days')::interval AS started
) t;

-- invoices: 6 monthly invoices per paying subscription
INSERT INTO invoices (subscription_id, amount_cents, status, issued_at, due_at, paid_at)
SELECT s.id, s.mrr_cents,
       CASE WHEN m = 0 AND s.status = 'past_due' THEN 'open' ELSE 'paid' END,
       NOW() - (m || ' months')::interval,
       NOW() - (m || ' months')::interval + INTERVAL '14 days',
       CASE WHEN m = 0 AND s.status = 'past_due' THEN NULL
            ELSE NOW() - (m || ' months')::interval + INTERVAL '3 days' END
FROM subscriptions s, generate_series(0,5) m
WHERE s.mrr_cents > 0;

-- 15 products
INSERT INTO products (name, category, price_cents, is_active)
SELECT 'Product ' || g,
       (ARRAY['addon','training','hardware','support'])[1 + floor(random()*4)::int],
       1000 + 500*floor(random()*40)::int,
       random() < 0.9
FROM generate_series(1,15) g;

-- 400 orders, 1-4 items each
INSERT INTO orders (org_id, status, created_at)
SELECT 1 + floor(random()*60)::int,
       (ARRAY['paid','paid','paid','pending','refunded','canceled'])[1 + floor(random()*6)::int],
       NOW() - (random()*500 || ' days')::interval
FROM generate_series(1,400);

INSERT INTO order_items (order_id, product_id, quantity, unit_price_cents)
SELECT o.id, p.id, 1 + floor(random()*5)::int, p.price_cents
FROM orders o
CROSS JOIN LATERAL (
    SELECT id, price_cents FROM products
    WHERE o.id > 0 ORDER BY random() LIMIT 1 + (o.id % 4)
) p;

UPDATE orders o SET total_cents = s.total
FROM (SELECT order_id, SUM(quantity * unit_price_cents) AS total FROM order_items GROUP BY order_id) s
WHERE s.order_id = o.id;

-- payments for orders that are not pending/canceled, and for paid invoices
INSERT INTO payments (order_id, amount_cents, method, status, paid_at)
SELECT id, total_cents,
       (ARRAY['card','card','bank_transfer','paypal'])[1 + floor(random()*4)::int],
       CASE WHEN status = 'refunded' THEN 'refunded' ELSE 'succeeded' END,
       created_at + INTERVAL '1 day'
FROM orders WHERE status IN ('paid','refunded') AND total_cents > 0;

INSERT INTO payments (invoice_id, amount_cents, method, status, paid_at)
SELECT id, amount_cents,
       (ARRAY['card','card','bank_transfer'])[1 + floor(random()*3)::int],
       'succeeded', paid_at
FROM invoices WHERE status = 'paid';

ANALYZE;
