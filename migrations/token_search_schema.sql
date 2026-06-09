-- Token discovery schema migration (PostgreSQL / Supabase)

CREATE TABLE IF NOT EXISTS token_registry (
    id SERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    contract_address VARCHAR(128) NOT NULL,
    token_name VARCHAR(128) DEFAULT '',
    symbol VARCHAR(32) DEFAULT '',
    logo_url VARCHAR(512) DEFAULT '',
    verified BOOLEAN DEFAULT FALSE,
    primary_dex VARCHAR(64) DEFAULT '',
    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    search_count INT DEFAULT 0,
    metadata JSONB,
    CONSTRAINT uq_token_registry UNIQUE (chain, contract_address)
);
CREATE INDEX IF NOT EXISTS idx_token_registry_symbol ON token_registry (symbol);
CREATE INDEX IF NOT EXISTS idx_token_registry_search_count ON token_registry (search_count);

CREATE TABLE IF NOT EXISTS token_search_cache (
    id SERIAL PRIMARY KEY,
    query_normalized VARCHAR(128) NOT NULL,
    results_json JSONB,
    result_count INT DEFAULT 0,
    sources_used JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_cache_query ON token_search_cache (query_normalized);
CREATE INDEX IF NOT EXISTS idx_search_cache_expires ON token_search_cache (expires_at);

CREATE TABLE IF NOT EXISTS token_metadata (
    id SERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    contract_address VARCHAR(128) NOT NULL,
    market_cap DOUBLE PRECISION DEFAULT 0,
    liquidity DOUBLE PRECISION DEFAULT 0,
    volume_24h DOUBLE PRECISION DEFAULT 0,
    price_usd DOUBLE PRECISION DEFAULT 0,
    price_change_24h DOUBLE PRECISION DEFAULT 0,
    holder_count INT DEFAULT 0,
    dex VARCHAR(64) DEFAULT '',
    pair_address VARCHAR(128) DEFAULT '',
    verified BOOLEAN DEFAULT FALSE,
    metadata JSONB,
    fetched_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_token_metadata_identity ON token_metadata (chain, contract_address);

CREATE TABLE IF NOT EXISTS trending_tokens (
    id SERIAL PRIMARY KEY,
    chain VARCHAR(32) NOT NULL,
    contract_address VARCHAR(128) NOT NULL,
    token_name VARCHAR(128) DEFAULT '',
    symbol VARCHAR(32) DEFAULT '',
    logo_url VARCHAR(512) DEFAULT '',
    volume_24h DOUBLE PRECISION DEFAULT 0,
    liquidity DOUBLE PRECISION DEFAULT 0,
    market_cap DOUBLE PRECISION DEFAULT 0,
    search_count INT DEFAULT 0,
    trend_score DOUBLE PRECISION DEFAULT 0,
    dex VARCHAR(64) DEFAULT '',
    verified BOOLEAN DEFAULT FALSE,
    rank_position INT DEFAULT 0,
    computed_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trending_score ON trending_tokens (trend_score);

CREATE TABLE IF NOT EXISTS search_history (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) DEFAULT '',
    query VARCHAR(128) NOT NULL,
    selected_chain VARCHAR(32) DEFAULT '',
    selected_address VARCHAR(128) DEFAULT '',
    selected_symbol VARCHAR(32) DEFAULT '',
    searched_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_search_history_session ON search_history (session_id, searched_at);
