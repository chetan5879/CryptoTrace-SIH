# CryptoTrace 2.4: online VASP/mixer attribution and caching

## Install this update

Stop the old server with Ctrl+C. Extract the entire ZIP into a new folder and copy your existing working `.env` into it. Keep your existing PostgreSQL database and accounts. Open a terminal inside the extracted CryptoTrace-v2 folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Unlike the previous UI-only update, **this version requires the additive migration**. It creates ct_attribution_sources and ct_online_entities; it does not delete cases, accounts, saved traces or reviewed labels. Run migration with your database migration/owner account. If your web service uses a restricted database role, also apply the new grants in deploy/database-roles.sql.example using your database administrator. Do not grant the web process superuser access.

Open http://127.0.0.1:8000, press Ctrl+Shift+R and use your existing login. Online attribution is enabled by default, including when your older .env has no new setting. No new paid API key is required.

Optional initial refresh before starting the server:

```bash
python manage.py refresh-attribution
```

This command uses your configured database operator access. You can also sign in as administrator and use Diagnostics & Setup → Online attribution cache → Refresh sources. A cold refresh adds latency; subsequent matches normally use cached data. Refreshes have a bounded time budget, so review the source statuses if only some files were retrieved.

## What happens automatically

1. Each encountered address is matched by its exact blockchain and normalized address against your reviewed local registry.
2. A reviewed entry always wins, including a reviewed correction that removes the VASP/mixer classification.
3. If no reviewed entry exists, the resolver checks the persistent online-result cache.
4. On a cache miss, it refreshes expired approved public source lists and performs an exact chain/address match locally. It does not submit each suspect wallet to a web search service.
5. Supported matches are cached in PostgreSQL with the entity name, classification, original source URL, feed URL, source date, retrieval date and source-content SHA-256. They appear as **external, unreviewed** labels in graph reasons and the dossier.
6. Later traces reuse the cache. The PostgreSQL cache survives application restarts and code-folder updates.

No-match results are cached too; they are not a clean-wallet finding. Source failures are separately recorded as unavailable. Conflicting entity/category claims are kept for review and do not automatically classify the node.

## Sources and coverage

The free provider is the GraphSense public TagPack repository:
https://github.com/graphsense/graphsense-tagpacks

The resolver discovers exchange-wallets-*.yaml reserve-disclosure packs from this approved repository. Newly published packs following that schema/name pattern can be picked up on a later refresh. It downloads at most 27 qualifying exchange packs plus selected Tornado Cash, Blender.io and Sinbad.io packs. Individual files must be at most 256 KiB. Large BitMEX packs, generic exchange-token word clouds, inferred clusters, user coinjoin participation and arbitrary third-party websites are excluded.

Supported chain codes are ETH, BTC, TRX, BSC/BEP20 and MATIC/POLYGON. A label for Ethereum is never copied to the same-looking address on BNB or Polygon. Ambiguous BNB and unsupported BEP2 entries are not assigned to BSC. Tron and Bitcoin Base58 casing is preserved.

Coverage varies by source and network. In particular, public reserve packs are not a complete Polygon attribution service. This is **not a general internet search engine, an exhaustive VASP directory, or a guarantee that every new exchange or mixer will be identified**. If a new address/entity is absent from these sources, it remains unidentified. New mixer source families require an additional reviewed adapter/configuration update. More providers can be added later using the same source/evidence model.

Many source records are historical. Fetching a 2022 disclosure today does not make its ownership assertion current. Historical mixer labels do not imply a current sanctions designation: automatic lookup never sets is_sanctioned. The system identifies source claims about specific addresses, not legal VASP registration, customers, ownership of nearby addresses or a fiat cash-out.

## Refresh and cache rules

- Source/catalog refresh: eligible after 24 hours, performed on demand during an uncached lookup. This is not a scheduled background crawler.
- Successful address matches, conflicts and no-match results: expire no later than the underlying fresh source window, up to 24 hours.
- Source/network errors: ten-minute retry delay to avoid repeated failing calls.
- Expired source data is retained for inspection but is not silently reused as a fresh attribution.
- A successful source refresh invalidates active address-cache entries; new traces resolve against refreshed data. Removed labels therefore disappear from new results after successful refresh/relookup.
- An administrator can force refresh through the UI or CLI. Existing saved investigation snapshots are never rewritten.
- One database advisory lock coordinates refresh across workers. Independent downloads are limited to four concurrent workers, a 45-second overall target budget, fixed endpoints and per-request timeouts. A final in-flight read can take up to its socket timeout beyond the target budget.

## What investigators see

Origin remains purple; external VASP matches use black and mixer matches use brown. Hover reasons state external/unreviewed status, the source date and retrieval date. The report's VASP & Mixer Leads table records the distinction too. In v3 an exact, unconflicted mixer match from the approved source pipeline contributes +60 once while retaining its external/unreviewed status and historical date. Local corrections still take priority.

In Diagnostics & Setup, click Check online sources to see last retrieval dates, failures and cached matches. Administrators can click Review label to copy a candidate into the local registry form. Verify it, correct any details, then click Save attribution. Copying the candidate into the form alone does not approve it. Local review does not imply independent verification by the software.

## Disable network attribution

Set this in your local .env and restart the server:

```dotenv
ONLINE_ATTRIBUTION_ENABLED=false
```

Reviewed local labels still work. Cached external classifications are not used in this mode. Transaction-history APIs remain controlled by the existing provider configuration.

## Validation and limits

Automated tests cover malformed/unsafe YAML, file-size limits, exact chain matching, conflict handling, cache reuse across resolver instances, expiry/removal, local overrides, unavailable versus no-match outcomes, disabled lookup and risk-score separation. Browser tests cover cached-label display/review and graph/report integration. Tests use synthetic database/API fixtures; no connection to your PostgreSQL instance or live transaction-provider credentials was supplied. This is not fraud-detection accuracy validation or government certification.
