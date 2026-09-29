# CryptoTrace 3.0 requirement coverage

This checklist describes implemented behaviour and its boundaries. It does not certify SIH compliance, court acceptance, production capacity or fraud-detection accuracy.

| Requested item | Delivered implementation | Remaining external input or boundary |
|---|---|---|
| Active Isolation Forest | Deterministic real sklearn inference, 12 engineered features, feature export, train/evaluate CLI, model hash, explicit status in graph/report | No independently labelled operational dataset supplied. Exploratory mode requires 20 eligible distinct wallets. Production accuracy remains unestablished. |
| ML risk fusion | Optional +10 anomaly contribution once after per-chain held-out metric gates | Reference dataset and independent review required; default exploratory output does not alter risk |
| Peeling detection | EVM repeated dominant-output candidates and BTC exact-spend connected split patterns | Bounded observed history, no asserted change ownership |
| Multi-hop laundering patterns | Pass-through candidates, chronological layering paths, fan-in/out, rapid turnaround and whole-unit patterns | Pattern flags are hypotheses, not laundering findings |
| Cross-chain fund-flow correlation | Unified case graph, reviewed bridge/asset matching, LI.FI completed-transfer adapter and automatic supported destination queueing | LI.FI links cover ETH/Polygon/BNB only and remain provider-reported; BTC/Tron have candidate matching. Broad bridge coverage needs additional protocol adapters. |
| Exchange deposit/withdrawal correlation | Exact sourced exchange labels and endpoint leads remain visible | Particular customer withdrawals cannot be connected to deposits without exchange/internal evidence |
| Continuous monitoring | Persistent watchlists and separate polling worker, fresh retrieval, baseline and due schedules | 5-minute minimum interval, bounded provider history, not full real-time block streaming |
| Automatic alerts | Persistent alerts with case/watch/transaction/risk/trigger/time, deduplication, acknowledgement | In-app delivery only; no email/SMS integration or outbound notification has been configured |
| Victim complaint intake | Structured form and JSON import, timezone/date validation, amount/currency, victim/complaint/evidence references, automatic queued traces | Evidence references only; secure document-file storage is a separate agency deployment concern |
| VASP intelligence | Reviewed registry plus sourced online cache retained; potential service-hub behaviour flag added; automatic sourced mixer +60 | Behaviour alone never invents an entity name or 0.91 confidence. Public label coverage remains incomplete. |
| Formal risk categories | UNKNOWN/LOW/MEDIUM/HIGH/CRITICAL and recorded rule/ML contributions | Weights are explicit policy, not empirically calibrated fraud probabilities |
| Automated clustering | Shared-counterparty groups recorded with pattern/ML outputs | Structural grouping only; no common-control assertion or trained cluster classifier |
| Persistent indexing | Normalised events indexed by chain/address/hash/time, case associations, fresh-window cache, raw response evidence | Incremental case/watch index rather than full-chain archive. Full archival data requires infrastructure and reorg/finality strategy. |
| Queue / larger datasets | Durable jobs, leases, crash recovery, per-investigator exclusion, paginated events, unified latest snapshots | Per-trace and graph display bounds documented; production load and multi-host rate limiting remain deployment work |
| Unified dashboard | Multiple chains per case, graph and relationship types, chain/address/entity/risk filters, indexed asset/time search | Graph view caps at 2,000 nodes after filtering; full event index is paginated |
| SAHYOG/NCRP interface | Versioned complaint schema and local case export, explicit connector protocol, connector-status screen | Official API specification, credentials and agency acceptance are required for live submission |
| Investigation API | Authenticated intake, jobs, watchlists, alerts, case graph, events, evidence, features and export endpoints | Intended for same-origin authenticated clients; machine-to-machine credentials require an agency-specific contract |
| Reports | Existing PDF gains patterns/ML/raw-evidence references; unified case JSON and printable review summary | Review drafts, not official NCRP documents; no legal approval generated |
| Evidence preservation | Canonical source-response hashes, provenance links, immutable raw/trace records, case-authorised retrieval, audited actions | JSON response content is preserved, not raw network packets. Hashes are not signatures or trusted timestamps. |

## Deliberately not claimed

- Verified fraud probability or court-approved AI.
- Complete historical transaction retrieval for every provider/address.
- Arbitrary cross-chain tracking through every bridge, mixer or exchange.
- Live SAHYOG/NCRP access without an authorised interface.
- Full-chain archival indexing or production-scale throughput measurements.
- A guarantee that this prototype is ready for government deployment without acceptance testing.

See `UPGRADE_V3.md` for commands, exact policies and operator responsibilities.
