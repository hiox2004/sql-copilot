-- Core SaaS schema (8 tables). Money is stored as integer CENTS.
--
--   organizations 1--* users
--   organizations 1--* subscriptions 1--* invoices *--1 payments (optional)
--   organizations 1--* orders 1--* order_items *--1 products
--   payments.order_id -> orders, payments.invoice_id -> invoices (at least one set)

CREATE TABLE organizations (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    industry    TEXT,
    country     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    org_id        INTEGER NOT NULL REFERENCES organizations(id),
    email         TEXT NOT NULL UNIQUE,          -- PII: keep out of the dictionary
    full_name     TEXT NOT NULL,                 -- PII
    role          TEXT NOT NULL CHECK (role IN ('admin','member','viewer')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE subscriptions (
    id           SERIAL PRIMARY KEY,
    org_id       INTEGER NOT NULL REFERENCES organizations(id),
    plan_tier    TEXT NOT NULL CHECK (plan_tier IN ('free','pro','enterprise')),
    status       TEXT NOT NULL CHECK (status IN ('trialing','active','past_due','canceled')),
    mrr_cents    INTEGER NOT NULL CHECK (mrr_cents >= 0),   -- monthly recurring revenue, CENTS
    started_at   TIMESTAMPTZ NOT NULL,
    canceled_at  TIMESTAMPTZ,
    CHECK ((status = 'canceled') = (canceled_at IS NOT NULL)),
    -- a free plan has no price and can never be past due; paid plans always have a price
    CHECK (plan_tier <> 'free' OR (mrr_cents = 0 AND status <> 'past_due')),
    CHECK (plan_tier = 'free' OR mrr_cents > 0)
);

CREATE TABLE invoices (
    id               SERIAL PRIMARY KEY,
    subscription_id  INTEGER NOT NULL REFERENCES subscriptions(id),
    amount_cents     INTEGER NOT NULL CHECK (amount_cents >= 0),
    status           TEXT NOT NULL CHECK (status IN ('open','paid','void')),
    issued_at        TIMESTAMPTZ NOT NULL,
    due_at           TIMESTAMPTZ NOT NULL,
    paid_at          TIMESTAMPTZ,
    CHECK ((status = 'paid') = (paid_at IS NOT NULL))
);

CREATE TABLE products (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,
    price_cents  INTEGER NOT NULL CHECK (price_cents > 0),   -- list price, CENTS
    is_active    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE orders (
    id           SERIAL PRIMARY KEY,
    org_id       INTEGER NOT NULL REFERENCES organizations(id),
    status       TEXT NOT NULL CHECK (status IN ('pending','paid','refunded','canceled')),
    total_cents  INTEGER NOT NULL DEFAULT 0,                 -- sum of its items, CENTS
    created_at   TIMESTAMPTZ NOT NULL
);

-- Bridge table: orders <-> products. Revenue questions must join through it.
CREATE TABLE order_items (
    id                SERIAL PRIMARY KEY,
    order_id          INTEGER NOT NULL REFERENCES orders(id),
    product_id        INTEGER NOT NULL REFERENCES products(id),
    quantity          INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents  INTEGER NOT NULL CHECK (unit_price_cents > 0)  -- price at purchase time
);

CREATE TABLE payments (
    id            SERIAL PRIMARY KEY,
    order_id      INTEGER REFERENCES orders(id),
    invoice_id    INTEGER REFERENCES invoices(id),
    amount_cents  INTEGER NOT NULL CHECK (amount_cents > 0),
    method        TEXT NOT NULL CHECK (method IN ('card','bank_transfer','paypal')),
    status        TEXT NOT NULL CHECK (status IN ('succeeded','failed','refunded')),
    paid_at       TIMESTAMPTZ NOT NULL,
    CHECK (order_id IS NOT NULL OR invoice_id IS NOT NULL)
);

CREATE INDEX ON users(org_id);
CREATE INDEX ON subscriptions(org_id);
CREATE INDEX ON invoices(subscription_id);
CREATE INDEX ON orders(org_id);
CREATE INDEX ON order_items(order_id);
CREATE INDEX ON order_items(product_id);
CREATE INDEX ON payments(order_id);
CREATE INDEX ON payments(invoice_id);

-- Table/column comments: raw material for the semantic data dictionary.
COMMENT ON TABLE  organizations IS 'Customer companies (accounts).';
COMMENT ON TABLE  users IS 'People belonging to an organization.';
COMMENT ON TABLE  subscriptions IS 'One row per organization subscription to a plan tier.';
COMMENT ON COLUMN subscriptions.mrr_cents IS 'Monthly recurring revenue in CENTS. Divide by 100.0 for dollars.';
COMMENT ON COLUMN subscriptions.status IS 'trialing, active, past_due, canceled. canceled_at is set only when canceled.';
COMMENT ON TABLE  invoices IS 'Bills issued for subscriptions.';
COMMENT ON TABLE  products IS 'One-off purchasable products.';
COMMENT ON TABLE  orders IS 'One-off purchases by an organization. total_cents is in CENTS.';
COMMENT ON TABLE  order_items IS 'Line items linking orders to products (bridge table).';
COMMENT ON TABLE  payments IS 'Payment attempts against an order or an invoice. amount_cents is in CENTS.';
