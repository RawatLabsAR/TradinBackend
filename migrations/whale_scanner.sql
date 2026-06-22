-- Whale scanner cron job tables

CREATE TABLE IF NOT EXISTS whale_scan_candidates (
    id SERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    contract_address VARCHAR(128) NOT NULL,
    symbol VARCHAR(32),
    token_name VARCHAR(128),
    source VARCHAR(64),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_scanned_at TIMESTAMPTZ,
    liquidity_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    volume_24h DOUBLE PRECISION NOT NULL DEFAULT 0,
    age_hours DOUBLE PRECISION NOT NULL DEFAULT 0,
    dex VARCHAR(64),
    CONSTRAINT uq_whale_scan_candidate UNIQUE (chain, contract_address)
);
CREATE INDEX IF NOT EXISTS ix_whale_scan_candidate_scan ON whale_scan_candidates (last_scanned_at);

CREATE TABLE IF NOT EXISTS whale_scan_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    tokens_scanned INTEGER NOT NULL DEFAULT 0,
    whales_detected INTEGER NOT NULL DEFAULT 0,
    messages_sent INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    error TEXT
);

CREATE TABLE IF NOT EXISTS whale_scan_notifications (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES whale_scan_runs(id) ON DELETE SET NULL,
    candidate_id INTEGER NOT NULL REFERENCES whale_scan_candidates(id) ON DELETE CASCADE,
    event_type VARCHAR(32) NOT NULL DEFAULT 'digest',
    usd_value DOUBLE PRECISION NOT NULL DEFAULT 0,
    telegram_message_id INTEGER,
    notified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_whale_scan_notify_candidate ON whale_scan_notifications (candidate_id, notified_at);
