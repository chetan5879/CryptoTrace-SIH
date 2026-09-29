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
