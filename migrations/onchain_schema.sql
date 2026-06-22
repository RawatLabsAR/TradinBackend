-- On-chain analytics schema migration (PostgreSQL)
-- Run manually if not using create_all, or for reference

CREATE TABLE IF NOT EXISTS onchain_trades (
    id BIGSERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    token_address VARCHAR(128) NOT NULL,
    wallet VARCHAR(128) NOT NULL,
    side VARCHAR(8) NOT NULL,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    usd_value DOUBLE PRECISION NOT NULL DEFAULT 0,
    price_usd DOUBLE PRECISION NULL,
    timestamp TIMESTAMP NOT NULL,
    dex VARCHAR(64) DEFAULT '',
    tx_hash VARCHAR(128) DEFAULT '',
    block_number BIGINT NULL,
    raw_source VARCHAR(32) DEFAULT '',
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_onchain_trade_dedup UNIQUE (chain, tx_hash, token_address, wallet, side)
);
CREATE INDEX IF NOT EXISTS idx_trades_token_time ON onchain_trades (chain, token_address, timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_wallet_time ON onchain_trades (chain, wallet, timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_usd_value ON onchain_trades (usd_value);

CREATE TABLE IF NOT EXISTS wallet_stats (
    id SERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    wallet VARCHAR(128) NOT NULL,
    total_trades INT DEFAULT 0,
    buy_count INT DEFAULT 0,
    sell_count INT DEFAULT 0,
    total_volume_usd DOUBLE PRECISION DEFAULT 0,
    realized_pnl_usd DOUBLE PRECISION DEFAULT 0,
    win_rate DOUBLE PRECISION DEFAULT 0,
    avg_roi_pct DOUBLE PRECISION DEFAULT 0,
    trade_accuracy DOUBLE PRECISION DEFAULT 0,
    smart_money_score DOUBLE PRECISION DEFAULT 0,
    is_whale BOOLEAN DEFAULT FALSE,
    is_smart_money BOOLEAN DEFAULT FALSE,
    is_sniper BOOLEAN DEFAULT FALSE,
    first_seen_at TIMESTAMP NULL,
    last_active_at TIMESTAMP NULL,
    metadata JSONB,
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_wallet_stats UNIQUE (chain, wallet)
);
CREATE INDEX IF NOT EXISTS idx_wallet_stats_score ON wallet_stats (smart_money_score);

CREATE TABLE IF NOT EXISTS holder_snapshots (
    id SERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    token_address VARCHAR(128) NOT NULL,
    holder_count INT DEFAULT 0,
    top10_pct DOUBLE PRECISION DEFAULT 0,
    top50_pct DOUBLE PRECISION DEFAULT 0,
    snapshot_at TIMESTAMP NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_holder_snap_token_time ON holder_snapshots (chain, token_address, snapshot_at);

CREATE TABLE IF NOT EXISTS liquidity_events (
    id BIGSERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    token_address VARCHAR(128) NOT NULL,
    pool_address VARCHAR(128) DEFAULT '',
    event_type VARCHAR(16) NOT NULL,
    wallet VARCHAR(128) DEFAULT '',
    token_amount DOUBLE PRECISION DEFAULT 0,
    usd_value DOUBLE PRECISION DEFAULT 0,
    liquidity_usd DOUBLE PRECISION DEFAULT 0,
    timestamp TIMESTAMP NOT NULL,
    tx_hash VARCHAR(128) DEFAULT '',
    dex VARCHAR(64) DEFAULT '',
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_liq_event UNIQUE (chain, tx_hash, token_address, event_type)
);
CREATE INDEX IF NOT EXISTS idx_liq_token_time ON liquidity_events (chain, token_address, timestamp);

CREATE TABLE IF NOT EXISTS whale_wallets (
    id SERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    wallet VARCHAR(128) NOT NULL,
    token_address VARCHAR(128) DEFAULT '',
    event_type VARCHAR(32) NOT NULL,
    usd_value DOUBLE PRECISION DEFAULT 0,
    description TEXT,
    tx_hash VARCHAR(128) DEFAULT '',
    detected_at TIMESTAMP NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_whale_token_time ON whale_wallets (chain, token_address, detected_at);

CREATE TABLE IF NOT EXISTS smart_money_wallets (
    id SERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    wallet VARCHAR(128) NOT NULL,
    token_address VARCHAR(128) DEFAULT '',
    score DOUBLE PRECISION DEFAULT 0,
    win_rate DOUBLE PRECISION DEFAULT 0,
    avg_roi_pct DOUBLE PRECISION DEFAULT 0,
    trade_accuracy DOUBLE PRECISION DEFAULT 0,
    total_volume_usd DOUBLE PRECISION DEFAULT 0,
    last_trade_at TIMESTAMP NULL,
    metadata JSONB,
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_smart_money UNIQUE (chain, wallet, token_address)
);
CREATE INDEX IF NOT EXISTS idx_smart_money_score ON smart_money_wallets (score);

CREATE TABLE IF NOT EXISTS token_metrics (
    id SERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    token_address VARCHAR(128) NOT NULL,
    buy_volume_usd DOUBLE PRECISION DEFAULT 0,
    sell_volume_usd DOUBLE PRECISION DEFAULT 0,
    net_flow_usd DOUBLE PRECISION DEFAULT 0,
    unique_wallets INT DEFAULT 0,
    unique_buyers INT DEFAULT 0,
    unique_sellers INT DEFAULT 0,
    whale_buy_volume_usd DOUBLE PRECISION DEFAULT 0,
    whale_sell_volume_usd DOUBLE PRECISION DEFAULT 0,
    smart_money_score_avg DOUBLE PRECISION DEFAULT 0,
    holder_count INT DEFAULT 0,
    holder_growth_pct DOUBLE PRECISION DEFAULT 0,
    liquidity_usd DOUBLE PRECISION DEFAULT 0,
    liquidity_change_pct DOUBLE PRECISION DEFAULT 0,
    early_buyer_count INT DEFAULT 0,
    sniper_count INT DEFAULT 0,
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP NOT NULL,
    metadata JSONB,
    computed_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_token_metrics_token_period ON token_metrics (chain, token_address, period_end);

CREATE TABLE IF NOT EXISTS sync_checkpoints (
    id SERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    token_address VARCHAR(128) NOT NULL,
    source VARCHAR(32) NOT NULL,
    sync_type VARCHAR(32) NOT NULL,
    last_timestamp TIMESTAMP NULL,
    last_block BIGINT NULL,
    last_cursor VARCHAR(256) DEFAULT '',
    records_synced INT DEFAULT 0,
    status VARCHAR(16) DEFAULT 'idle',
    error_message TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_sync_checkpoint UNIQUE (chain, token_address, source, sync_type)
);

CREATE TABLE IF NOT EXISTS onchain_ohlcv_candles (
    id BIGSERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    token_address VARCHAR(128) NOT NULL,
    pool_address VARCHAR(128) NOT NULL DEFAULT '',
    timeframe VARCHAR(16) NOT NULL,
    aggregate INT DEFAULT 1,
    timestamp TIMESTAMP NOT NULL,
    open_usd DOUBLE PRECISION DEFAULT 0,
    high_usd DOUBLE PRECISION DEFAULT 0,
    low_usd DOUBLE PRECISION DEFAULT 0,
    close_usd DOUBLE PRECISION DEFAULT 0,
    volume_usd DOUBLE PRECISION DEFAULT 0,
    raw_source VARCHAR(32) DEFAULT 'geckoterminal',
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_onchain_ohlcv_candle UNIQUE (chain, token_address, pool_address, timeframe, aggregate, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_token_time ON onchain_ohlcv_candles (chain, token_address, timestamp);
CREATE INDEX IF NOT EXISTS idx_ohlcv_pool_time ON onchain_ohlcv_candles (chain, pool_address, timestamp);
