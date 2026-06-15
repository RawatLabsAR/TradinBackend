-- Discovery no longer uses the database (in-memory cache only).
-- Run once on Supabase if these tables were created by an earlier version:

DROP TABLE IF EXISTS discovery_snapshots;
DROP TABLE IF EXISTS cex_listing_records;
