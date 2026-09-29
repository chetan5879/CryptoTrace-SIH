# CryptoTrace 3.0 validation record

- 95 Python tests passed. Includes existing ingestion/security tests and new Isolation Forest, chronological peeling, exact UTXO spends, cross-chain candidate separation, reference evaluation and access-control tests.
- Synthetic end-to-end integration passed on the PostgreSQL engine in PGlite with a test-only wire-protocol compatibility shim: additive migration twice, login/CSRF, complaint ingestion, durable job execution, event indexing, raw evidence, cache reuse, monitoring baseline, alert deduplication, acknowledgement, export and immutable evidence trigger.
- That embedded test does not validate separate PostgreSQL sessions, concurrent worker leases, production isolation or load capacity. Run tests/integration_v3.py on a disposable native PostgreSQL database and perform concurrent-worker acceptance testing before production.
- Chromium workspace test passed: case graph, intake, queued wallet, alerts, retries, mobile width and no JavaScript errors. API responses were synthetic.
- Existing Chromium graph/report regression passed: 118/500-node layouts, hover/copy, focus, bounded zoom/pan, window controls, mobile and a 34-page synthetic PDF with complete fixture ledgers. The new ML/pattern PDF page was rendered and visually inspected.
- No live user database or production provider credentials were used. LI.FI response validation used documented synthetic payloads. Live bridge/provider coverage and quota performance remain unverified.
- Isolation Forest tests validate software execution, deterministic output and evaluation plumbing. Synthetic results are not evidence of real-world fraud-detection accuracy. No validated production reference dataset is bundled.

## Repeat locally

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
# Optional browser tooling
python -m pip install playwright==1.51.0 pypdf
python -m playwright install chromium --only-shell
python tests/workspace_review.py
```

The older graph/report browser test expects a static project server on 127.0.0.1:8765. The database integration test must only target a disposable test database. See UPGRADE_V3.md.
