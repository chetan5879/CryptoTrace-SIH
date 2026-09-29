# CryptoTrace 2.3 validation

- 56 Python tests passed, including provider pagination/errors, pacing, partial-record retention, full Bitcoin transaction context and exact retrieved output-spend references, attribution metadata, import validation, access controls, CSRF/session behaviour and protected entity reads.
- Real Chromium renderer with synthetic API responses: all eight pages, local fonts/icons, responsive layouts, login, graph tabs, hover/copy, fullscreen/minimise, related investigation and PDF export passed.
- 118-node and 500-node graph checks passed: no canvas address labels or native edge tooltips; VASP/mixer colours; same-button focus restore; spacing; bounded zoom/pan; full evidence preserved during focus.
- Saved case/trace selection, full-address transaction filtering and administrator registry edit passed in browser fixtures.
- Synthetic 33-page PDF generated with all fixture node identifiers, event IDs and exact amount strings retained. Graph, VASP/mixer section and wallet-register pages rendered with Poppler and visually inspected.
- Historical Binance starter labels passed offline schema/address validation. No labels were written to a real database here.

Limits: provider responses, authentication and database interactions are mocked in tests. No live Alchemy, NodeReal or TronScan credentials or user PostgreSQL instance were supplied. These results are regression checks, not measured fraud-detection accuracy, exhaustive chain-history validation, production penetration testing, government certification or proof of legal admissibility. One Starlette/httpx test-client deprecation warning remains; tests pass.

## Version 2.4 attribution validation

69 Python tests passed, including external-source YAML validation, exact chain matching (BEP20 versus ambiguous BNB), rejecting aliases/custom YAML tags, size bounds, conflict handling, cache persistence via a database fixture, expiry/removal, local override precedence, disabled lookup, source-unavailable results and unreviewed mixer score isolation. Online status/cache API reads require authentication; force refresh requires administrator access.

Chromium fixtures passed cached-label display and review-form loading, saved transaction selection, registry editing, 118/500-node graph interactions and a 33-page PDF containing the external-attribution status/source date. Live public source contents were inspected during implementation, but network requests in this environment were intermittent and timed out; no claim of complete live feed acquisition or real PostgreSQL integration is made. Refresh failures are visible and do not become clean-wallet conclusions.
