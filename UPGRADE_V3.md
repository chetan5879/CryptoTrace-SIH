# CryptoTrace 3.0 upgrade and operating guide

This release extends the supplied 2.4 ZIP. The original dashboard remains available. The new **Unified cases, monitoring and ML** link opens `/workspace.html` using the same login session.

## Install without losing your existing cases

1. Stop the web server. Back up PostgreSQL with your normal database backup procedure and verify that you can restore it.
2. Extract the new ZIP into a separate folder. Copy your working `.env` into that folder. Keep the same database; do not create replacement accounts unnecessarily.
3. In the extracted `CryptoTrace-v3` folder, run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
```

Run migration with the database owner/migration role. It creates additive tables and preserves existing cases, users, traces and reviewed entity labels. If the application uses a restricted role, apply the v3 grants in `deploy/database-roles.sql.example` as the database administrator, then restore the application's restricted DATABASE_URL. Never make the web service a database superuser.

For local testing, retain:

```dotenv
APP_ENV=development
APP_ORIGIN=http://127.0.0.1:8000
ALLOWED_HOSTS=127.0.0.1,localhost
```

Start the web server:

```bash
source .venv/bin/activate
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Open a second terminal in the same folder and start the worker:

```bash
source .venv/bin/activate
python worker.py
```

Keep both running. Open `http://127.0.0.1:8000`, hard-refresh with Ctrl+Shift+R, sign in with your existing account, then open **Unified cases, monitoring and ML**.

## First end-to-end run

1. Open **Complaint intake**. Enter a unique case ID, victim reference, complaint reference, incident time, amount/currency and a suspect wallet with its correct chain. Evidence fields are references, not file uploads or automatic web downloads.
2. Submit. The case and job are committed to PostgreSQL. In **Background jobs**, refresh until the job finishes. Failed jobs can be retried.
3. Open the case. Add wallets on other supported chains to the same case. Each queued trace produces a separate immutable snapshot. The unified view combines the latest wallet/chain snapshots.
4. Inspect patterns and ML status, graph relationships and the indexed transaction table. Filters include chain, wallet, entity text, minimum risk, asset and time (graph and table controls apply to their respective views).
5. Export the case JSON, download raw evidence or print the case review summary. Individual trace dossiers still use the existing PDF generator and now include pattern and ML sections.
6. Under **Monitoring & alerts**, enter the case/wallet, interval and risk threshold. The first successful poll seeds a baseline. Later newly observed events at or above the trace risk threshold produce persistent alerts. Acknowledge alerts after review.

## Isolation Forest is implemented and executes

Feature schema `wallet-same-asset-v1` computes incoming/outgoing counts, fan-in/out, distinct counterparties, observed transactions/hour, mean interval, amount coefficient of variation, observed outflow/inflow ratio, rapid pairs, split counts and whole-unit outflow fraction. Assets are separated. Bitcoin transaction/script vertices are excluded from wallet modelling.

A wallet/asset needs at least five events with timestamps and an exhausted supported provider window to be eligible. This does not certify complete chain history. Bounded histories and differing activity windows remain sources of bias.

Two modes:

- **Exploratory mode (default without a reference):** a trace needs 20 eligible distinct wallets. A deterministic 200-tree Isolation Forest fits that trace and reports scores. It is explicitly labelled `exploratory_same_trace`, uses contamination 0.05 and random_state 42, and does not add risk points. This mode is an investigation aid, not validation.
- **Reference mode:** a locally trained JSON reference is installed. The model scores even a single eligible wallet against that reference. No executable pickle is loaded. Feature and scikit-learn versions must match. The model/reference hash and feature values are recorded in each snapshot.

If data or a compatible reference is missing, the UI reports why: `insufficient_data`, `insufficient_reference`, `no_chain_reference`, or `model_unavailable`. It does not silently invent an anomaly score.

`anomaly_score` is the negated scikit-learn sample score (larger means more anomalous), not a calibrated probability. A negative `decision_function` flags an outlier. Displayed feature deviations compare inputs with reference medians; they are not causal explanations of the forest.

### Train and evaluate a reference

Use **Export case features** to obtain rows with source hashes and observation times. Curate independent training and evaluation JSON arrays. Each row requires:

```json
{
  "wallet": "address-or-dataset-wallet-identifier",
  "chain": "Ethereum",
  "asset_id": "Ethereum:native",
  "eligible": true,
  "source": "dataset citation or trace-sha256:...",
  "observed_at": "2026-01-01T00:00:00Z",
  "features": {
    "incoming_count": 10, "outgoing_count": 8,
    "fan_in": 5, "fan_out": 4, "counterparties": 9,
    "tx_per_hour": 2, "mean_interval_seconds": 1800,
    "amount_cv": 0.5, "out_in_ratio": 0.96,
    "rapid_pairs": 2, "peel_splits": 0, "round_fraction": 0.25
  },
  "label": 0
}
```

The values above demonstrate the format only. Do not treat the example as genuine training data. Evaluation labels must be independently substantiated; unknown does not mean benign. The training routine requires at least 100 training and 30 evaluation rows per included chain, both evaluation classes, disjoint wallets, and evaluation times later than all training observations. These are minimum software checks, not evidence of adequate sample size or representativeness. Deduplicate related entities and matched activity windows during dataset preparation.

```bash
python ml_engine.py --train training.json --evaluate evaluation.json
```

This writes `models/reference.json` and reports held-out precision, recall, false-positive rate and confusion counts. Model files stay local and are not served as static assets. Restart web and worker after replacing the reference.

Optional risk fusion:

```bash
python ml_engine.py --train training.json --evaluate evaluation.json --enable-fusion
```

Fusion is permitted only if every evaluated chain reaches the explicit policy gates: precision >=0.80, recall >=0.50 and false-positive rate <=0.10. When enabled, a model outlier contributes +10 once per wallet. These thresholds and points are engineering policy, not scientific or court certification. Representative independent evaluation and review are still required. No production reference or fraud-accuracy claim is supplied with this ZIP because no verified labelled dataset was provided.

## Pattern rules and scoring

- Existing fan-in/fan-out (+25 each), rapid same-asset turnaround (+20), reviewed mixer (+60) and reviewed sanctions rules remain.
- An unconflicted exact mixer label from the approved online source pipeline now contributes **+60 once**. It remains marked external/unreviewed with its historical source date. A local reviewed correction overrides it. VASP classification does not set risk to zero.
- Observed pass-through candidate (+15): same-asset outflow/inflow within 5%, rapid pairs and observed span <=24h. It is not a balance-retention calculation.
- Account-chain peeling candidate (+15): two consecutive 80–99% dominant-output splits within bounded 24h windows.
- Bitcoin peeling (+25): repeated split transactions connected by exact previous-output spend references. Change-address ownership remains unproven.
- Layering candidate (+10): three chronological same-asset hops within 24h, with distinct vertices.
- Whole-unit amount pattern (+5): >=5 outgoing events, >=80% whole-unit amounts. This is denomination-dependent and does not establish threshold evasion.
- Potential service hub (0 points): high fan-in and fan-out identifies a possible service role. The system does not fabricate an exchange name or numerical confidence.
- Shared-counterparty clusters group wallets with identical observed neighbour sets of size >=2. They are relationship groups, not common-owner conclusions.

Scores cap at 100. Categories are LOW <20, MEDIUM 20–49, HIGH 50–79, CRITICAL >=80, UNKNOWN when insufficient evidence supports scoring. These policy weights are not calibrated fraud probabilities. Each added pattern retains event IDs and an explanation. Overlapping patterns can remain correlated; inspect score components.

## Cross-chain operation

A case can contain wallets on Ethereum, Polygon, BNB Chain, Tron and Bitcoin. Each chain/address is a distinct vertex; identical EVM address text across chains does not establish a transfer.

**Automatic candidate matching:** administrators configure exact asset identities and bridge endpoints under **Bridge & asset registry**. Transfers into a registered bridge and out of a registered bridge on another chain qualify only with the same mapped asset, destination time 0–2h later, and received/sent amount ratio 95–100.5%. Results remain `unverified` amount/time candidates, including when several matches are possible. Token-symbol equality alone is insufficient.

**Bridge-provider evidence:** the LI.FI status adapter is implemented for source/destination chains Ethereum, Polygon and BNB Chain. It requires a completed response tied to the requested source transaction and chain. The response is hashed and retained. The link is labelled `provider_reported`, not independently proven. A newly discovered supported destination wallet is added to the case and queued for a one-hop trace, subject to 100 wallets/case and 50 pending jobs/user.

Manual lookup requires the source transaction to be indexed in the case. It discloses that public hash to LI.FI. For automatic lookups of registered bridge deposits, add:

```dotenv
LIFI_ENABLED=true
```

Restart web/worker. At most three unique source transactions per trace are queried automatically. An optional LIFI_API_KEY can be configured if your service access requires it. No arbitrary URL is accepted. Not every bridge or historical transaction is covered. Unsupported or incomplete statuses produce no link, not a clean result. Bitcoin/Tron cross-chain links currently rely on reviewed registry-based candidates; direct bridge-provider verification is limited to the three named EVM networks.

Exchange deposits and withdrawals are not automatically equated: proving a specific customer's exchange-internal path requires authorised exchange records. There is no reliable generic internet substitute for those records.

## Indexing, queue and evidence

The PostgreSQL event index persists retrieved records by chain/event ID and indexes sender, receiver, transaction hash and time. Ownership-filtered case associations control retrieval. Fresh successful wallet windows reuse a five-minute cache. Monitoring bypasses the cache. Raw provider JSON responses are stored separately with canonical SHA-256 hashes, timestamps and provider names; API-key URLs and headers are excluded. This preserves response content, not original HTTP byte-for-byte transport evidence. Trace hashes identify immutable snapshots. Normalized index entries can refresh; prior trace snapshots and raw response records remain append-only.

This is an **incremental investigation index**, not a full archival index of every block on five chains. Watch polling currently re-queries bounded address history, rather than maintaining chain-wide block cursors. Full archival indexing needs nodes/archive providers, storage planning, reorganisation handling and operational load testing.

Jobs use PostgreSQL `FOR UPDATE SKIP LOCKED`, ten-minute leases and recovery of abandoned jobs (maximum three lease attempts). Explicit failures remain visible for retry. A per-investigator advisory lock prevents simultaneous traces for that investigator. Watchlists persist and are polled at configurable intervals of 300–86400 seconds. Alerts deduplicate by watch/event, and coverage warnings deduplicate per watch/day. “New” means newly observed since the baseline, not necessarily newly mined. Delayed/provider-window omissions can miss activity.

Per-trace bounds remain 25 expanded wallets, 500 nodes and 2,000 edges with provider time/request budgets. The unified case view combines up to 100 latest wallet/chain snapshots. Its graph renders at most 2,000 filtered nodes to protect browser responsiveness. The event table pages through the persistent index 200 rows at a time. These are disclosed bounds, not an unmeasured large-scale throughput claim.

## SAHYOG/NCRP boundary

`POST /workspace/complaints` validates `cryptotrace.case.v1` documents. `GET /workspace/integration` exposes the schema and connector status. `GET /workspace/cases/{id}/export` produces a versioned case export with trace-hash manifest, overview and a canonical export digest. Existing saved-trace and raw-evidence endpoints expose the supporting records to authorised case users. Input/output schemas differ deliberately; an export is an evidence package, not a complaint import.

`agency_connector.py` defines configuration, idempotent submission and submission-status methods. Its default implementation refuses live submission. Complete it only against the official authorised contract, including authentication, field mapping, consent/access requirements, retries, acknowledgement IDs and agency acceptance testing. No genuine government endpoint/credential was supplied, so no live government integration or NCRP approval is claimed.

## Deployment checks and external dependencies

```bash
python manage.py check-deployment
python -m pytest -q
```

The local integration test below creates test records and must use a disposable test database only:

```bash
DATABASE_URL='postgresql://TEST_USER:TEST_PASSWORD@127.0.0.1/TEST_DATABASE' python tests/integration_v3.py
```

Deploy web and worker separately. The service examples require an existing dedicated OS user, `/srv/cryptotrace`, correct permissions and a writable `/srv/cryptotrace/run`. Keep one common NODEREAL_RATE_DIR when web and workers share a host; use a distributed provider limiter before scaling across hosts. The example's private temporary directories must not isolate that shared limiter path.

Production requires HTTPS APP_ORIGIN and APP_ENV=production, restricted DB roles, protected backups, secrets handling and agency-specific retention/access policy. The web and worker retain the original case/session/CSRF checks. Audit records use application and database controls; a privileged database administrator can still alter the installation. Run production PostgreSQL multi-worker contention, provider quota and load tests in your target environment before deployment. This ZIP is not a government certification or a guarantee of operational security.
