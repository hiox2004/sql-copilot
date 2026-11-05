-- 28 additional tables around the core 8 (36 total). Many are deliberate DISTRACTORS:
-- names that look related to the core tables so retrieval has real work to do
-- (plans vs subscriptions.plan_tier, employees vs users, tickets vs orders, ...).
-- Money columns are integer CENTS. No row data from these goes into the search index.

-- ===== Billing extras =====
CREATE TABLE plans (                         -- price LIST; subscriptions.mrr_cents is what customers actually pay
    id                  SERIAL PRIMARY KEY,
    tier                TEXT NOT NULL UNIQUE CHECK (tier IN ('free','pro','enterprise')),
    name                TEXT NOT NULL,
    monthly_price_cents INTEGER NOT NULL CHECK (monthly_price_cents >= 0),
    seats_included      INTEGER NOT NULL,
    is_public           BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE subscription_events (           -- history: upgrades, downgrades, cancels, reactivations
    id                SERIAL PRIMARY KEY,
    subscription_id   INTEGER NOT NULL REFERENCES subscriptions(id),
    event_type        TEXT NOT NULL CHECK (event_type IN ('created','upgraded','downgraded','canceled','reactivated','payment_failed')),
    from_tier         TEXT,
    to_tier           TEXT,
    mrr_cents_before  INTEGER,
    mrr_cents_after   INTEGER,
    occurred_at       TIMESTAMPTZ NOT NULL
);

CREATE TABLE coupons (
    id               SERIAL PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,
    percent_off      INTEGER NOT NULL CHECK (percent_off BETWEEN 1 AND 100),
    valid_from       TIMESTAMPTZ NOT NULL,
    valid_until      TIMESTAMPTZ NOT NULL,
    max_redemptions  INTEGER
);

CREATE TABLE coupon_redemptions (
    id           SERIAL PRIMARY KEY,
    coupon_id    INTEGER NOT NULL REFERENCES coupons(id),
    org_id       INTEGER NOT NULL REFERENCES organizations(id),
    redeemed_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE refunds (                       -- one row per payment whose status is 'refunded'
    id            SERIAL PRIMARY KEY,
    payment_id    INTEGER NOT NULL REFERENCES payments(id),
    amount_cents  INTEGER NOT NULL CHECK (amount_cents > 0),
    reason        TEXT NOT NULL CHECK (reason IN ('customer_request','duplicate','fraud','service_issue')),
    refunded_at   TIMESTAMPTZ NOT NULL
);

-- ===== Support =====
CREATE TABLE support_agents (                -- our support staff (not customers' users, not employees)
    id          SERIAL PRIMARY KEY,
    full_name   TEXT NOT NULL,               -- PII
    team        TEXT NOT NULL CHECK (team IN ('tier1','tier2','billing')),
    hired_at    TIMESTAMPTZ NOT NULL
);

CREATE TABLE support_tickets (
    id                 SERIAL PRIMARY KEY,
    org_id             INTEGER NOT NULL REFERENCES organizations(id),
    user_id            INTEGER NOT NULL REFERENCES users(id),
    assigned_agent_id  INTEGER REFERENCES support_agents(id),
    status             TEXT NOT NULL CHECK (status IN ('open','pending','resolved','closed')),
    priority           TEXT NOT NULL CHECK (priority IN ('low','normal','high','urgent')),
    category           TEXT NOT NULL CHECK (category IN ('billing','bug','how_to','feature_request')),
    subject            TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL,
    resolved_at        TIMESTAMPTZ
);

CREATE TABLE ticket_comments (
    id           SERIAL PRIMARY KEY,
    ticket_id    INTEGER NOT NULL REFERENCES support_tickets(id),
    author_type  TEXT NOT NULL CHECK (author_type IN ('user','agent')),
    body         TEXT NOT NULL,              -- free text: never indexed
    created_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE csat_surveys (                  -- customer satisfaction after a ticket
    id            SERIAL PRIMARY KEY,
    ticket_id     INTEGER NOT NULL UNIQUE REFERENCES support_tickets(id),
    score         INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
    submitted_at  TIMESTAMPTZ NOT NULL
);

-- ===== Product usage =====
CREATE TABLE features (
    id        SERIAL PRIMARY KEY,
    key       TEXT NOT NULL UNIQUE,
    name      TEXT NOT NULL,
    category  TEXT NOT NULL
);

CREATE TABLE feature_usage_daily (
    id           SERIAL PRIMARY KEY,
    org_id       INTEGER NOT NULL REFERENCES organizations(id),
    feature_id   INTEGER NOT NULL REFERENCES features(id),
    usage_date   DATE NOT NULL,
    event_count  INTEGER NOT NULL CHECK (event_count >= 0),
    UNIQUE (org_id, feature_id, usage_date)
);

CREATE TABLE api_keys (
    id          SERIAL PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organizations(id),
    label       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ
);

CREATE TABLE api_requests_daily (
    id             SERIAL PRIMARY KEY,
    api_key_id     INTEGER NOT NULL REFERENCES api_keys(id),
    request_date   DATE NOT NULL,
    request_count  INTEGER NOT NULL CHECK (request_count >= 0),
    error_count    INTEGER NOT NULL CHECK (error_count >= 0),
    CHECK (error_count <= request_count)
);

CREATE TABLE login_events (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    occurred_at  TIMESTAMPTZ NOT NULL,
    success      BOOLEAN NOT NULL,
    ip_country   TEXT NOT NULL
);

-- ===== Marketing and sales =====
CREATE TABLE campaigns (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    channel       TEXT NOT NULL CHECK (channel IN ('email','ads','webinar','content')),
    budget_cents  INTEGER NOT NULL CHECK (budget_cents >= 0),
    started_at    TIMESTAMPTZ NOT NULL,
    ended_at      TIMESTAMPTZ
);

CREATE TABLE leads (                         -- prospects BEFORE they become organizations
    id                SERIAL PRIMARY KEY,
    campaign_id       INTEGER REFERENCES campaigns(id),
    company_name      TEXT NOT NULL,
    contact_email     TEXT NOT NULL,         -- PII
    status            TEXT NOT NULL CHECK (status IN ('new','qualified','converted','lost')),
    created_at        TIMESTAMPTZ NOT NULL,
    converted_org_id  INTEGER REFERENCES organizations(id),
    CHECK ((status = 'converted') = (converted_org_id IS NOT NULL))
);

CREATE TABLE sales_reps (
    id         SERIAL PRIMARY KEY,
    full_name  TEXT NOT NULL,                -- PII
    region     TEXT NOT NULL CHECK (region IN ('NA','EMEA','APAC','LATAM')),
    hired_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE opportunities (                 -- sales pipeline deals (not orders)
    id            SERIAL PRIMARY KEY,
    lead_id       INTEGER NOT NULL REFERENCES leads(id),
    rep_id        INTEGER NOT NULL REFERENCES sales_reps(id),
    stage         TEXT NOT NULL CHECK (stage IN ('prospecting','proposal','negotiation','won','lost')),
    amount_cents  INTEGER NOT NULL CHECK (amount_cents >= 0),
    created_at    TIMESTAMPTZ NOT NULL,
    closed_at     TIMESTAMPTZ
);

CREATE TABLE email_events (
    id           SERIAL PRIMARY KEY,
    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id),
    lead_id      INTEGER NOT NULL REFERENCES leads(id),
    event_type   TEXT NOT NULL CHECK (event_type IN ('sent','opened','clicked','unsubscribed')),
    occurred_at  TIMESTAMPTZ NOT NULL
);

-- ===== Internal HR (our own company, unrelated to customers) =====
CREATE TABLE departments (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    cost_center  TEXT NOT NULL
);

CREATE TABLE employees (
    id               SERIAL PRIMARY KEY,
    department_id    INTEGER NOT NULL REFERENCES departments(id),
    full_name        TEXT NOT NULL,          -- PII
    email            TEXT NOT NULL UNIQUE,   -- PII
    title            TEXT NOT NULL,
    hired_at         TIMESTAMPTZ NOT NULL,
    terminated_at    TIMESTAMPTZ,
    salary_cents     INTEGER NOT NULL        -- sensitive
);

CREATE TABLE expense_reports (
    id             SERIAL PRIMARY KEY,
    employee_id    INTEGER NOT NULL REFERENCES employees(id),
    amount_cents   INTEGER NOT NULL CHECK (amount_cents > 0),
    category       TEXT NOT NULL CHECK (category IN ('travel','software','meals','equipment')),
    status         TEXT NOT NULL CHECK (status IN ('submitted','approved','rejected','paid')),
    submitted_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE office_locations (
    id                 SERIAL PRIMARY KEY,
    city               TEXT NOT NULL,
    country            TEXT NOT NULL,
    headcount_capacity INTEGER NOT NULL
);

-- ===== System =====
CREATE TABLE audit_log (
    id             SERIAL PRIMARY KEY,
    actor_user_id  INTEGER REFERENCES users(id),     -- NULL = system action
    action         TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    entity_id      INTEGER,
    occurred_at    TIMESTAMPTZ NOT NULL
);

CREATE TABLE feature_flags (
    id               SERIAL PRIMARY KEY,
    key              TEXT NOT NULL UNIQUE,
    enabled          BOOLEAN NOT NULL,
    rollout_percent  INTEGER NOT NULL CHECK (rollout_percent BETWEEN 0 AND 100),
    updated_at       TIMESTAMPTZ NOT NULL
);

CREATE TABLE notifications (
    id        SERIAL PRIMARY KEY,
    user_id   INTEGER NOT NULL REFERENCES users(id),
    kind      TEXT NOT NULL CHECK (kind IN ('invoice','security','product','marketing')),
    sent_at   TIMESTAMPTZ NOT NULL,
    read_at   TIMESTAMPTZ
);

-- ===== Misc customer data =====
CREATE TABLE addresses (
    id           SERIAL PRIMARY KEY,
    org_id       INTEGER NOT NULL REFERENCES organizations(id),
    kind         TEXT NOT NULL CHECK (kind IN ('billing','shipping')),
    city         TEXT NOT NULL,
    country      TEXT NOT NULL,
    postal_code  TEXT NOT NULL
);

CREATE TABLE org_settings (
    id          SERIAL PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organizations(id),
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (org_id, key)
);

CREATE INDEX ON subscription_events(subscription_id);
CREATE INDEX ON coupon_redemptions(org_id);
CREATE INDEX ON refunds(payment_id);
CREATE INDEX ON support_tickets(org_id);
CREATE INDEX ON support_tickets(user_id);
CREATE INDEX ON ticket_comments(ticket_id);
CREATE INDEX ON feature_usage_daily(org_id, usage_date);
CREATE INDEX ON api_keys(org_id);
CREATE INDEX ON api_requests_daily(api_key_id);
CREATE INDEX ON login_events(user_id);
CREATE INDEX ON leads(campaign_id);
CREATE INDEX ON opportunities(lead_id);
CREATE INDEX ON email_events(lead_id);
CREATE INDEX ON expense_reports(employee_id);
CREATE INDEX ON audit_log(actor_user_id);
CREATE INDEX ON notifications(user_id);

-- Comments: raw material for the semantic dictionary (and the confusion-resolving notes).
COMMENT ON TABLE plans IS 'Price LIST per tier. NOT what customers pay; use subscriptions.mrr_cents for actual revenue.';
COMMENT ON TABLE subscription_events IS 'History of subscription changes (upgrades, downgrades, cancels, reactivations, failed payments).';
COMMENT ON COLUMN subscriptions.mrr_cents IS 'Monthly price in CENTS at the subscription''s current/last state. For CURRENT MRR only count status IN (active, past_due).';
COMMENT ON TABLE refunds IS 'One row per payment with status refunded. Revenue should use succeeded payments only.';
COMMENT ON TABLE support_agents IS 'Our support staff. Not customer users, not HR employees.';
COMMENT ON TABLE support_tickets IS 'Customer support requests raised by users.';
COMMENT ON TABLE leads IS 'Sales prospects before they become organizations. converted leads link to organizations.';
COMMENT ON TABLE opportunities IS 'Sales pipeline deals. Not the same as orders.';
COMMENT ON TABLE employees IS 'Our own company staff (HR). Not customer users.';
COMMENT ON TABLE feature_usage_daily IS 'Daily usage counts per organization and product feature.';
COMMENT ON TABLE audit_log IS 'Security/audit trail of user and system actions.';
