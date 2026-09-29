# CryptoTrace v2.4.0 — online attribution and cache

This is a development release based on the four supplied files. It is **not approved for government production deployment**. Use synthetic or authorised test cases until the acceptance work below is complete.

## Update highlights

Read **BEGINNER_GUIDE.md** for the full what/how/why walkthrough and NCRP acceptance explanation.

- Airy repulsive graph layout up to 150 nodes; spaced hop bands above that, with a manual layout switch.
- No canvas address labels at any zoom. Interactive hover card with full-address copy, click-to-pin, related investigation and keyboard/touch inspection.
- Connected-edge highlighting and an explicitly labelled temporary neighbourhood view. Reports retain all retrieved records.
- Bounded zoom/pan, Fit graph and upper-right minimise/full-screen/close icons with tooltips.
- Dashboard guidance moved to Help; the large card now contains investigation actions.
- Redesigned landscape dossier with local embedded fonts, graph overview, full ledgers, diagnostics, snapshot digest and analyst review worksheet. No claimed NCRP approval or invented signatures.
- New graph/report scripts and local fonts require extracting the complete ZIP, including the updated `main.py` allowlist.

## Upgrading to 2.4

Read ONLINE_ATTRIBUTION.md first. Run `python -m pip install -r requirements.txt` and `python manage.py migrate` with your migration account before restarting. This release adds persistent source/address cache tables. Earlier no-migration statements below refer only to the 2.2/2.3 updates.

## Start locally

Requires Python 3.12 and a running PostgreSQL instance. Back up your existing database first.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
# Edit DATABASE_URL and your provider keys in .env.
python manage.py migrate
python manage.py create-user administrator --role admin
python manage.py create-user investigator --role investigator
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Open **http://127.0.0.1:8000**. The server serves the dashboard and API together; do not use VS Code Live Server or open index.html directly. Use exactly the origin configured in APP_ORIGIN. The login password is entered interactively and is never a command-line argument. No default login exists.

Pinned icon/font, graph and PDF assets are included and served locally. `python vendor_assets.py` re-fetches the pinned versions and records their hashes. Review licenses and dependencies before release. The backend still sends queried wallet addresses to Alchemy, NodeReal, TronScan or Mempool.space. Local hosting alone does **not** eliminate that disclosure.

## Upgrade from an existing v2.1 / v2.1.1 installation

1. Stop Uvicorn with Ctrl+C and extract this complete ZIP into a new folder.
2. Copy your existing `.env` into that folder. Keep your existing database and provider settings.
3. Activate your Python environment (or create one and install `requirements.txt`).
4. Start `python -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers`.
5. Open http://127.0.0.1:8000 and press **Ctrl+Shift+R** to refresh cached styles. Use your existing login.

This graph/report update needs **no database reset, schema migration or account recreation**. Replace the complete project, including `main.py` and `assets/`, so the new local icon/report fonts and scripts can be served.

### Dashboard repairs

- Restored locally served Font Awesome icons with no external font dependency.
- Unified typography, buttons, form controls, spacing, cards and responsive navigation across all eight screens.
- Replaced the misleading coloured zero-case risk chart with an empty state; populated charts use the returned case counts.
- Corrected wallet-validation feedback, empty tables and case pagination.
- Retained graph tabs, full-screen view, clipboard and report controls.

## What changed

- Tron address casing preserved in requests, database entries, node matching and entity lookups; Base58Check checksum validated.
- Tron native TRX and confirmed successful TRC20 transfers retrieved separately; decimals zero handled correctly; key sent in the documented header.
- Ethereum/Polygon use Alchemy with pagination and JSON-RPC error checking.
- BNB uses NodeReal MegaNode `nr_getAssetTransfers`: incoming and outgoing external, internal and BEP-20 histories. Configure NODEREAL_API_KEY with the key from your free BSC mainnet account. The Etherscan dependency is removed. API errors and rate/usage limits produce visible incomplete results.
- Provider errors, partial pages, graph/request limits and empty successful results appear in graph diagnostics and reports.
- Reported node role stays intact; distinct transaction events retained; outgoing transactions are not suppressed by an arbitrary amount-ratio filter.
- Bitcoin uses transaction nodes to avoid inventing a one-to-one mapping between UTXO inputs and outputs.
- Up to ten independent graph tabs, full-screen/restore, minimise/reopen, per-tab zoom state, full-address hover, selected-node copy, and related-wallet investigation. Open graph tabs are memory-only; database snapshots can be reopened after sign-in.
- Same-origin login, Argon2id password hashes, hashed opaque session tokens, HttpOnly/SameSite cookies, CSRF and Origin checks, 8-hour absolute and 30-minute idle expiry, logout/revocation, database-backed sign-in throttling.
- Investigator case ownership enforced at the API; administrators can view all cases and update source-labelled entities. No public self-registration.
- PostgreSQL audit events include UTC time, account, observed IP and truncated User-Agent. User-Agent is self-reported; IP is not a verified physical location. No external geolocation service receives case or investigator details.
- Each trace gets a saved immutable-at-application-level snapshot, provenance, retrieval status and SHA-256 digest. The original snapshot is reopened for reporting rather than silently tracing fresh data.
- Dynamic dashboard content uses DOM text nodes; no inline event handlers or unsafe HTML interpolation. CSP blocks external scripts; no wildcard CORS.
- Scores come from the backend. Removed the client API that could overwrite a case's score. Removed fabricated dashboard counts.

## Investigation meaning and bounds

The graph is a set of **observed relationships**, not proof that the same stolen funds traversed a path. The origin includes incoming/outgoing history; deeper expansion follows outgoing relationships. Defaults: three pages per provider category, 25 expanded wallets, 500 nodes, 2,000 edges, 60 HTTP calls and a 90-second upstream time budget, up to four hops. Per-request timeouts are also enforced. Limits intentionally prevent a synchronous trace from consuming unlimited resources; visible diagnostics preserve this distinction.

`observed` means supported provider requests were exhausted within the configured scope. It does not mean complete blockchain history. `no_transfers_found` means no qualifying records were retrieved. `partial` identifies limits/errors, and `unavailable` means the origin's history requests failed. Fraud allegations, sanctions and inactivity do not erase historical blockchain records. Never infer innocence from a one-node result or score zero.

NFTs, bridges, Tron internal/TRC10 transfers, unconfirmed transactions and cross-chain attribution are not covered. Current BTC address validation is syntax-level; Tron uses a checksum, EVM uses syntax. API responses must still be reconciled with independent explorer data. Fallback event identities preserve repeated identical transfers but require further provider-specific validation when a stable log index is unavailable. Pagination is not anchored to one chain block; chain growth/reorgs can change pages during retrieval.

The old in-graph IsolationForest and amount-based pass-through/peeling rules were removed from this release: incomplete wallet histories and mixing token denominations made their outputs unsuitable as factual findings. Current transparent triage rules use high fan-in/out and chronological same-asset receive/send relationships, plus explicitly sourced analyst labels. They have not been calibrated against labelled fraud data. Exchange attribution never means "safe". Mixer and sanctions labels are distinct. New entities are chain scoped and require a source. There is no automatic unverified sanctions-feed ingestion; add a vetted update process with additions, removals and review dates before production.

## Existing database and files

New tables use the `ct_` prefix. The original `cases` and `known_entities` tables are retained unchanged. Because old cases had no owner and some Tron/BTC addresses were lowercased irreversibly, ownership cannot safely be inferred.

```bash
python import_legacy.py --owner investigator          # dry run
python import_legacy.py --owner investigator --apply  # explicit assignment
```

Review skipped addresses and restore their original spelling from the original complaint/explorer. Do not attempt to guess Base58 casing. Legacy scores are not promoted as evidence, and cases require retracing. Legacy seed entity labels need independent source verification before adding them through the admin `/entities` API. Preserve old database exports under your retention policy.

Extract the complete project archive into its own directory: main.py now depends on the included db.py, security.py, ingestion.py, graph_engine.py and schema.sql. Replacing only the old four files is insufficient.

## Accounts and evidence

```bash
python manage.py reset-password investigator
python manage.py disable-user investigator
```

Both commands revoke that user's active sessions. Run account/migration commands with a restricted operator role that can manage users; the web service should have the grants illustrated in `deploy/database-roles.sql.example`.

The Access history screen shows your own events (all users for admins). Case history offers saved trace versions. Reports are investigation drafts, not a certified NCRP format or a claim of court admissibility. A digest can detect changes relative to a trusted digest; it is not a digital signature, independent timestamp or chain-of-custody certification. The digest is computed over the canonical JSON payload before the response-only `evidence_sha256` field is added (`sort_keys=True`, compact separators, UTF-8, `ensure_ascii=False`). Database triggers and permissions deter application-level alteration, not a malicious database administrator. Raw provider response preservation, trusted timestamping and separately controlled immutable evidence storage remain deployment work.

## Production deployment preparation

Templates under `deploy/` are examples for review, not applied configuration:

1. Dedicated application and migration DB roles; secret manager; TLS on DB traffic where remote; encrypted storage and encrypted backups with tested recovery.
2. Set APP_ENV=production, APP_ORIGIN=https://your-approved-host, and an exact ALLOWED_HOSTS list. Terminate TLS at the controlled reverse proxy. Bind Uvicorn to loopback. Trust forwarded headers only from that proxy; never use a wildcard trusted-proxy setting.
3. Review the Nginx rate/body/concurrency limits and systemd service. Only production HTTPS enables the Secure cookie and HSTS requirements.
4. Integrate agency SSO and MFA, account approvals, recovery, team case assignments and session administration. This release has local accounts and two roles, not enterprise identity management.
5. Security testing: independent VAPT, authorization/IDOR and CSRF tests against a real PostgreSQL deployment, dependency/SBOM scan, secret scan, rate-limit/concurrency tests, proxy-IP validation, incident-response drills.
6. Data quality testing: supplied known Tron/BNB wallets reconciled against explorer counts and transactions; high-volume pagination, provider errors, internal transfers, decimals, reorgs, sanctions removal, and labelled scoring evaluation.
7. Scale: durable background trace jobs, cancellation, progress, retries with provider quota management, monitoring and alerting. Current traces are synchronous and bounded; a server restart can interrupt a trace. A recorded `trace_started` event without a corresponding result needs review.
8. Evidence/legal/agency review: applicable retention, access, procurement, reporting format and evidentiary requirements; chain-of-custody procedures; analyst training and documented limitations. Obtain the target department's acceptance requirements before claiming deployment readiness.
9. Data sovereignty: agency-approved provider agreements or self-hosted indexers/nodes. Public provider calls expose wallet queries even when the app and database are on premises.

## Verification

```bash
python -m pytest -q
node --check script.js
node --check events.js
node --check graph-ui.js
node --check reports.js
```

See TEST_REPORT.md for exactly what was run and what remains unverified. No live agency data, credentials or production deployment were used.

## Provider/security references used

- [Alchemy transfer endpoint and category support](https://www.alchemy.com/docs/data/transfers-api/transfers-endpoints/alchemy-get-asset-transfers)
- [NodeReal transfer history](https://docs.nodereal.io/reference/nr_getassettransfers), [CUPS limits](https://docs.nodereal.io/docs/cups-rate-limit), [BNB history API costs](https://nodereal.io/api-marketplace/transaction-receipts-bsc)
- [TronScan TRC20 schema and authentication](https://docs.tronscan.org/en/api/transactions-and-transfers/token-trc20-transfers), [TRX history](https://docs.tronscan.org/en/api/wallet/transfer-trx)
- [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html), [CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)


## Upgrade from the first v2 ZIP to NodeReal

1. Stop the old Uvicorn process with Ctrl+C. Extract the updated complete ZIP into a new folder. Keep your old folder as a backup.
2. Copy your existing `.env` into the new project folder, keeping your database settings, APP_ENV, APP_ORIGIN and other provider keys.
3. Remove the obsolete `ETHERSCAN_API_KEY` line and add `NODEREAL_API_KEY=your_actual_key`. Enter only the API key, not the full endpoint URL. Keep this secret locally.
4. Activate a Python virtual environment and install `requirements.txt` if this folder has no environment. No new Python dependencies or schema migration are needed for this adapter change. If you have not finished initial setup, follow the Start locally section first.
5. Start `python -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers` and open http://127.0.0.1:8000.
6. Sign in, select BNB Chain, and begin with one hop. Inspect retrieval diagnostics and compare the result to a known wallet on a block explorer.

### What 300 CUPS means

CUPS means **compute units per second**, not requests or transactions per second. NodeReal currently lists `nr_getAssetTransfers` at **250 CU per request**. A response can contain many transfers, and extra pages require extra calls. At a 300-CUPS allowance the adapter conservatively sends at most one history call every 1.1 seconds. One incoming and one outgoing page cost about 500 CU, before retries. Six pages cost about 1,500 CU. The current 60-request trace cap allows at most about 15,000 CU of NodeReal history attempts; time limits or shared-server contention can stop a trace earlier.

This should be practical for development and small demonstrations. It is not a guarantee of acceptable response times for many simultaneous investigators. Your **monthly CU allowance** is separate from the per-second limit: check your account dashboard rather than assuming a particular free monthly quota. NodeReal's public pricing pages contain inconsistent monthly figures.

The limiter uses Linux file locks and a hashed-key filename in a private temporary directory. All threads and Uvicorn workers using the same key and directory share the limit. For multiple services, set the same NODEREAL_RATE_DIR; for multiple hosts/isolated containers, use a shared distributed limiter before scaling. Requests from other applications using the same NodeReal account also count toward its provider-side limit and are not coordinated by this app.

Only HTTP 429 and NodeReal's documented CUPS error `-32005` receive up to three paced attempts. Authentication/other RPC errors do not retry. Retries and waits count against the existing request/time budgets. Diagnostics record actual attempted HTTP calls and an estimated 250 CU per attempt, not an authoritative billing figure.

The adapter does not set a recent-only block filter. NodeReal accepts optional range filters and limits explicit ranges; omission avoids hardcoding a short recent window. **An exhausted cursor does not certify all-time blockchain coverage**. Live account access, default history range, internal transfer coverage and pagination still need reconciliation against known wallets. The source returns token decimals inconsistently as decimal strings or prefixed hex; both are handled. Missing decimals produce a visible schema error rather than an invented amount.

## Version 2.3 update

Read UPDATE_2_3.md for the network-selection fix, Bitcoin UTXO improvements, entity registry/import, saved transaction explorer, colour/tooltip changes and NCRP research. Existing v2.2 users retain the same database and accounts.
