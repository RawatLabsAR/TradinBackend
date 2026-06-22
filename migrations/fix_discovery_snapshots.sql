-- Repair legacy discovery_snapshots tables missing columns expected by the backend ORM.

ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS category VARCHAR(32);
ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS chain VARCHAR(32) NOT NULL DEFAULT '';
ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS payload JSONB;
ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS sources_used JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS scanned_at TIMESTAMPTZ;
ALTER TABLE discovery_snapshots ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

UPDATE discovery_snapshots SET category = 'new_dex' WHERE category IS NULL;
UPDATE discovery_snapshots SET chain = '' WHERE chain IS NULL;
UPDATE discovery_snapshots SET sources_used = '[]'::jsonb WHERE sources_used IS NULL;
UPDATE discovery_snapshots SET scanned_at = COALESCE(scanned_at, created_at, NOW()) WHERE scanned_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_discovery_category_chain
    ON discovery_snapshots (category, chain);
CREATE INDEX IF NOT EXISTS ix_discovery_scanned ON discovery_snapshots (scanned_at);
