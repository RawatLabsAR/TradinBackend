-- Token discovery schema (PostgreSQL)
-- Obsolete tables (token_search_cache, token_metadata, trending_tokens) removed —
-- search cache and metadata are in-memory; trending is computed on-read from token_registry.

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

-- Drop legacy cache tables if they exist from an earlier deployment
DROP TABLE IF EXISTS token_search_cache;
DROP TABLE IF EXISTS token_metadata;
DROP TABLE IF EXISTS trending_tokens;
