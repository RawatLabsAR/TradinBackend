-- Tradin PostgreSQL schema — user data + discovery persistence
-- Backend also creates these via SQLAlchemy on startup; this file documents the schema.

-- ── Watchlist (per user, synced across devices) ─────────────────────────────
CREATE TABLE IF NOT EXISTS watchlist_items (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id VARCHAR(32) NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_watchlist_user_product UNIQUE (user_id, product_id)
);
CREATE INDEX IF NOT EXISTS ix_watchlist_user_sort ON watchlist_items (user_id, sort_order);

-- ── Portfolio holdings (per user) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolio_holdings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id VARCHAR(32) NOT NULL,
    quantity DOUBLE PRECISION NOT NULL,
    avg_cost DOUBLE PRECISION NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_portfolio_user_product UNIQUE (user_id, product_id)
);
CREATE INDEX IF NOT EXISTS ix_portfolio_user ON portfolio_holdings (user_id);

-- ── Discovery scan snapshots (shared, survives restarts) ────────────────────
CREATE TABLE IF NOT EXISTS discovery_snapshots (
    id SERIAL PRIMARY KEY,
    category VARCHAR(32) NOT NULL,
    chain VARCHAR(32) NOT NULL DEFAULT '',
    payload JSONB NOT NULL,
    sources_used JSONB NOT NULL DEFAULT '[]'::jsonb,
    scanned_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_discovery_category_chain UNIQUE (category, chain)
);
CREATE INDEX IF NOT EXISTS ix_discovery_scanned ON discovery_snapshots (scanned_at);

-- ── Paper trades (if not already created) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS paper_trades (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id VARCHAR(32) NOT NULL,
    side VARCHAR(8) NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    exit_price DOUBLE PRECISION,
    quantity DOUBLE PRECISION NOT NULL,
    fee_pct DOUBLE PRECISION NOT NULL DEFAULT 0.001,
    pnl DOUBLE PRECISION,
    pnl_pct DOUBLE PRECISION,
    notes TEXT,
    source VARCHAR(32),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_paper_trades_user_id ON paper_trades (user_id);
CREATE INDEX IF NOT EXISTS ix_paper_trades_user_open ON paper_trades (user_id, closed_at);
