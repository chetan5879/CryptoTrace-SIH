-- Idempotent additive migration. Existing legacy tables are retained unchanged.
CREATE TABLE IF NOT EXISTS ct_users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','investigator')), active BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ct_sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES ct_users(id), csrf TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
 expires_at TIMESTAMPTZ NOT NULL, ip TEXT NOT NULL, user_agent TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ct_audit (
 id BIGSERIAL PRIMARY KEY, user_id TEXT REFERENCES ct_users(id), action TEXT NOT NULL,
 occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(), ip TEXT NOT NULL, user_agent TEXT NOT NULL,
 detail JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ct_audit_time ON ct_audit(occurred_at DESC);
CREATE INDEX IF NOT EXISTS ct_audit_login ON ct_audit(action,ip,occurred_at DESC);
CREATE TABLE IF NOT EXISTS ct_cases (
 case_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES ct_users(id), wallet_address TEXT NOT NULL,
 blockchain TEXT NOT NULL, fraud_type TEXT NOT NULL, max_hops INTEGER NOT NULL CHECK(max_hops BETWEEN 1 AND 4),
 risk_score INTEGER CHECK(risk_score BETWEEN 0 AND 100), status TEXT NOT NULL DEFAULT 'Pending',
 timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ct_traces (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES ct_cases(case_id), user_id TEXT NOT NULL REFERENCES ct_users(id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), payload JSONB NOT NULL, sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ct_traces_case ON ct_traces(case_id,created_at DESC);
CREATE TABLE IF NOT EXISTS ct_entities (
 blockchain TEXT NOT NULL, wallet_address TEXT NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL,
 is_vasp BOOLEAN NOT NULL DEFAULT FALSE, is_mixer BOOLEAN NOT NULL DEFAULT FALSE,
 is_sanctioned BOOLEAN NOT NULL DEFAULT FALSE, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_by TEXT NOT NULL REFERENCES ct_users(id), PRIMARY KEY(blockchain,wallet_address)
);
-- Application-level append-only audit/trace records; this does not defend against a DB administrator.
CREATE OR REPLACE FUNCTION ct_prevent_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Append-only investigation record'; END; $$;
DROP TRIGGER IF EXISTS ct_audit_immutable ON ct_audit;
CREATE TRIGGER ct_audit_immutable BEFORE UPDATE OR DELETE ON ct_audit FOR EACH ROW EXECUTE FUNCTION ct_prevent_mutation();
DROP TRIGGER IF EXISTS ct_trace_immutable ON ct_traces;
CREATE TRIGGER ct_trace_immutable BEFORE UPDATE OR DELETE ON ct_traces FOR EACH ROW EXECUTE FUNCTION ct_prevent_mutation();

-- External-source cache is separate from administrator-reviewed attributions.
CREATE TABLE IF NOT EXISTS ct_attribution_sources (
 source_id TEXT PRIMARY KEY, payload JSONB NOT NULL DEFAULT '[]'::jsonb,
 fetched_at TIMESTAMPTZ, retry_after TIMESTAMPTZ NOT NULL DEFAULT now(),
 last_error TEXT, skipped INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ct_online_entities (
 blockchain TEXT NOT NULL, wallet_address TEXT NOT NULL, payload JSONB NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('matched','not_found','conflict','unavailable')),
 checked_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(blockchain,wallet_address)
);

-- v3: additive case workspace, durable queue and evidence index.
CREATE TABLE IF NOT EXISTS ct_complaints (
 case_id TEXT PRIMARY KEY REFERENCES ct_cases(case_id), metadata JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ct_case_wallets (
 case_id TEXT NOT NULL REFERENCES ct_cases(case_id), blockchain TEXT NOT NULL,
 wallet_address TEXT NOT NULL, PRIMARY KEY(case_id,blockchain,wallet_address)
);
INSERT INTO ct_case_wallets SELECT case_id,blockchain,wallet_address FROM ct_cases ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS ct_jobs (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES ct_cases(case_id), user_id TEXT NOT NULL REFERENCES ct_users(id),
 kind TEXT NOT NULL CHECK(kind IN ('trace','monitor')), payload JSONB NOT NULL,
 state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','done','failed','cancelled')),
 attempts INTEGER NOT NULL DEFAULT 0, lease_token TEXT, lease_until TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ, result JSONB, error TEXT
);
CREATE INDEX IF NOT EXISTS ct_jobs_queue ON ct_jobs(state,created_at);
CREATE TABLE IF NOT EXISTS ct_watchlists (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES ct_cases(case_id), user_id TEXT NOT NULL REFERENCES ct_users(id),
 blockchain TEXT NOT NULL, wallet_address TEXT NOT NULL, interval_seconds INTEGER NOT NULL CHECK(interval_seconds BETWEEN 300 AND 86400),
 threshold INTEGER NOT NULL CHECK(threshold BETWEEN 0 AND 100), enabled BOOLEAN NOT NULL DEFAULT TRUE,
 next_poll TIMESTAMPTZ NOT NULL DEFAULT now(), baseline_set BOOLEAN NOT NULL DEFAULT FALSE,
 UNIQUE(case_id,blockchain,wallet_address)
);
CREATE TABLE IF NOT EXISTS ct_alerts (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES ct_cases(case_id), watch_id TEXT REFERENCES ct_watchlists(id),
 dedup_key TEXT UNIQUE NOT NULL, severity TEXT NOT NULL, payload JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), acknowledged_at TIMESTAMPTZ, acknowledged_by TEXT REFERENCES ct_users(id)
);
CREATE TABLE IF NOT EXISTS ct_watch_seen (
 watch_id TEXT NOT NULL REFERENCES ct_watchlists(id), event_id TEXT NOT NULL, PRIMARY KEY(watch_id,event_id)
);
CREATE TABLE IF NOT EXISTS ct_wallet_cache (
 blockchain TEXT NOT NULL, wallet_address TEXT NOT NULL, payload JSONB NOT NULL,
 diagnostics JSONB NOT NULL, evidence_refs JSONB NOT NULL DEFAULT '[]', fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(blockchain,wallet_address)
);
CREATE TABLE IF NOT EXISTS ct_raw_evidence (
 sha256 TEXT PRIMARY KEY, provider TEXT NOT NULL, payload JSONB NOT NULL, fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ct_event_index (
 blockchain TEXT NOT NULL, event_id TEXT NOT NULL, sender TEXT NOT NULL, receiver TEXT NOT NULL,
 tx_hash TEXT NOT NULL, asset_id TEXT NOT NULL, occurred_at TIMESTAMPTZ, payload JSONB NOT NULL,
 PRIMARY KEY(blockchain,event_id)
);
CREATE INDEX IF NOT EXISTS ct_event_sender ON ct_event_index(blockchain,sender,occurred_at);
CREATE INDEX IF NOT EXISTS ct_event_receiver ON ct_event_index(blockchain,receiver,occurred_at);
CREATE INDEX IF NOT EXISTS ct_event_tx ON ct_event_index(blockchain,tx_hash);
CREATE TABLE IF NOT EXISTS ct_case_events (
 case_id TEXT NOT NULL REFERENCES ct_cases(case_id), blockchain TEXT NOT NULL, event_id TEXT NOT NULL,
 PRIMARY KEY(case_id,blockchain,event_id), FOREIGN KEY(blockchain,event_id) REFERENCES ct_event_index(blockchain,event_id)
);
CREATE TABLE IF NOT EXISTS ct_case_evidence (
 case_id TEXT NOT NULL REFERENCES ct_cases(case_id), sha256 TEXT NOT NULL REFERENCES ct_raw_evidence(sha256),
 PRIMARY KEY(case_id,sha256)
);
CREATE TABLE IF NOT EXISTS ct_cross_links (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES ct_cases(case_id), payload JSONB NOT NULL,
 evidence_sha256 TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(case_id,evidence_sha256)
);
CREATE TABLE IF NOT EXISTS ct_asset_registry (
 blockchain TEXT NOT NULL, asset_id TEXT NOT NULL, canonical_asset TEXT NOT NULL,
 source TEXT NOT NULL, updated_by TEXT NOT NULL REFERENCES ct_users(id), PRIMARY KEY(blockchain,asset_id)
);
CREATE TABLE IF NOT EXISTS ct_bridge_registry (
 blockchain TEXT NOT NULL, wallet_address TEXT NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL,
 updated_by TEXT NOT NULL REFERENCES ct_users(id), PRIMARY KEY(blockchain,wallet_address)
);
DROP TRIGGER IF EXISTS ct_raw_immutable ON ct_raw_evidence;
CREATE TRIGGER ct_raw_immutable BEFORE UPDATE OR DELETE ON ct_raw_evidence FOR EACH ROW EXECUTE FUNCTION ct_prevent_mutation();
DROP TRIGGER IF EXISTS ct_cross_immutable ON ct_cross_links;
CREATE TRIGGER ct_cross_immutable BEFORE UPDATE OR DELETE ON ct_cross_links FOR EACH ROW EXECUTE FUNCTION ct_prevent_mutation();
