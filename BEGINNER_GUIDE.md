# Version 3.0 update

Read `UPGRADE_V3.md` first for the current ML/scoring behaviour, unified workspace and separate worker. The older walkthrough below describes the original dashboard.

# CryptoTrace 2.3: a beginner's guide

This guide describes the code in this release, not the older project handoff. Read it alongside the included README and TEST_REPORT. The application is an investigation prototype: it retrieves supported blockchain records, displays their relationships, stores a case snapshot and produces a review dossier. It does not determine guilt, identify every wallet owner or certify a report for court.

## 1. Install this update without losing your work

Your existing PostgreSQL database holds your users, cases and saved traces. The project folder holds the application code. Updating the folder does not require deleting the database.

1. In the terminal running Uvicorn, press **Ctrl+C**. Keep the old project folder as a backup.
2. Extract the complete replacement ZIP into a new folder. Open the extracted `CryptoTrace-v2` folder in a terminal. You should see `main.py`, `index.html`, `graph-ui.js`, `reports.js` and `assets/` together.
3. Copy the existing `.env` from your working project into this folder. In Ubuntu Files, press **Ctrl+H** to see it. Do not replace it with `.env.example`: that example contains placeholders, not your working settings.
4. Create a Python environment and install the application's dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

5. Open http://127.0.0.1:8000 and press **Ctrl+Shift+R** to clear cached page assets. Sign in with your existing username and password.

**This update requires no database reset, schema migration or account recreation if v2.1 already works.** First-time installations must follow the initial database and account instructions in README.md. Never put real secrets into GitHub, screenshots or a shared ZIP.

If you forgot the investigator password, stop the server and run `python manage.py reset-password investigator` from the configured project environment. Replace `investigator` with your actual username. This revokes that account's existing sessions. Then restart the server.

## 2. The main parts: what each one does and why it exists

| Part | Plain-language role | Why we use it |
| --- | --- | --- |
| HTML (`index.html`) | Defines the screens, forms, controls and dialogs | Gives the browser a clear page structure |
| CSS (`style.css`) | Controls sizes, colours, spacing and mobile layout | Keeps the interface consistent and readable |
| JavaScript (`script.js`, `events.js`) | Handles clicks, form inputs, API requests and dashboard state | Makes the application interactive without reloading each screen |
| Vis Network (`graph-ui.js` plus local vendor asset) | Draws nodes and transfer arrows, handles dragging and zoom | Investigators can explore relationships visually |
| jsPDF + AutoTable (`reports.js`) | Produces the dossier and paginated tables in your browser | Exports a portable report with full identifiers and original amount strings |
| Python / FastAPI (`main.py`) | Receives browser requests, validates them and coordinates work | Provides one controlled entry point for authentication, cases and traces |
| Uvicorn | Runs FastAPI as a web server | Makes the application reachable at the configured address and port |
| PostgreSQL | Stores users, sessions, cases, trace snapshots, entity labels and audit events | Keeps work after a browser or server restart and enforces ownership rules |
| Provider adapters (`ingestion.py`) | Ask blockchain data services for transfers and convert their responses | Different chains return different formats; the graph needs a common structure |
| Graph processor (`graph_engine.py`) | Expands wallets by hops, preserves transfer events and computes indicators | Turns individual records into a bounded investigation graph |
| Security helpers (`security.py`) | Check passwords, sessions, request origin, CSRF tokens and permissions | Prevent unauthenticated access and common cross-site request attacks |

A blockchain node or data provider is a source of chain records. A graph node is a dot in your diagram. These are different meanings of the word “node.”

**Two changes from the early handoff matter:** this release uses Python dictionaries, edge lists and a `deque` for breadth-first traversal; it does not currently use NetworkX. IsolationForest is also not active. The earlier unsupervised model was removed because incomplete samples and unvalidated features could produce misleading claims. The current score is an explicit rule-based triage indicator.

## 3. What happens when you sign in

The browser sends your username and password to the same FastAPI server that serves the page. The server compares the password against an Argon2id hash stored in PostgreSQL. It does not store a plain-text password.

After successful authentication, the browser receives a random session cookie. The database keeps a hash of the session token. The cookie is HttpOnly, so page JavaScript cannot read it, and SameSite is Strict. Production HTTPS mode also enables the Secure flag. The session has an eight-hour maximum lifetime and expires after 30 minutes without authenticated activity.

Requests that change data also carry a CSRF token, and the server checks their Origin. This helps prevent another website from silently using your browser's signed-in session to issue commands. Parameterised SQL separates database commands from submitted values.

Investigators can access their own cases. Administrators can access all cases and manage source-labelled entities. Account creation is an operator task, not an open public registration page. Access history records events such as successful/failed login, case opening and trace creation, along with the observed IP and browser User-Agent. The User-Agent can be falsified; an IP is not verified geographical location. The browser PDF download itself is not currently a server-side export audit event.

## 4. What happens when you execute a trace

1. **Input checking.** You choose a chain and enter the reported address. Ethereum, Polygon and BNB use similar `0x...` address formats, so you must select the correct network. Tron uses case-sensitive Base58Check addresses; the backend verifies their checksum. Bitcoin validation is currently syntax-level. The UI's “format matches” message does not verify address ownership or activity.
2. **Case registration.** The server creates a case owned by your account. The case ID is an internal reference. Typing an NCRP number does not connect to NCRP or verify that number.
3. **History retrieval.** The appropriate provider adapter requests supported transfers. It handles pages, errors, timeouts and amount conversions. It retains exact amount strings rather than rounding values for display.
4. **Normalisation.** Different responses become a shared structure: event identifier, transaction hash, sender, recipient, amount, asset identity and timestamp when available.
5. **Breadth-first expansion.** The reported wallet is hop 0. Its immediate connections are around hop 1. Additional outgoing relationships are explored up to the requested depth. Incoming and outgoing transfers are shown at the origin; downstream expansion follows outgoing relationships. Bitcoin also inserts transaction nodes to represent UTXO relationships correctly.
6. **Indicators and attribution.** The engine checks observed fan-in/fan-out, chronological same-asset receive/send events and any chain-specific analyst entity labels in the database.
7. **Snapshot preservation.** The completed result receives a trace ID, retrieval time, recorded investigator, diagnostics, scoring version and a SHA-256 digest. PostgreSQL stores it as a trace snapshot. A case can have multiple trace versions.
8. **Presentation.** The browser draws the returned data. Layout changes, zoom, dragging and temporary focus do not change the stored snapshot or re-fetch blockchain data.

Tracing runs as a bounded synchronous server operation using synchronous provider requests. This is not yet a durable background job queue. Closing the page does not provide a reliable cancel action, and a server interruption can end a running trace. One investigator's concurrent traces are restricted with a database advisory lock.

## 5. Where the data comes from

| Selected network | Source in this release | Supported retrieval |
| --- | --- | --- |
| Ethereum | Alchemy | External, supported internal and ERC-20 transfers |
| Polygon | Alchemy | Requests external, internal and ERC-20 categories; actual coverage depends on provider support and entitlement |
| BNB Chain | NodeReal MegaNode | External, internal and BEP-20 transfer history |
| Tron | TronScan | Native TRX and successful confirmed TRC-20 transfers |
| Bitcoin | Mempool.space | Transactions parsed into inputs and outputs with transaction nodes |

An API key identifies your account to a provider and its usage limits. It does not grant unlimited records. NodeReal's CUPS is a compute-unit-per-second limit. The adapter currently budgets 250 CU per history attempt and spaces shared local workers by at least 1.1 seconds; your monthly allowance is a separate constraint. Confirm costs and entitlements in your provider account before planning a large deployment.

The app deliberately limits work: up to four requested hops, three pages per provider category, 25 expanded wallets, 500 graph nodes, 2,000 edges, 60 attempted HTTP calls and a 90-second provider time budget. A visible node is not necessarily a wallet whose entire history was fetched. Increasing hop depth does not bypass those limits.

The present version does not cover all NFTs, bridges, Tron internal/TRC10 movements or cross-chain attribution. Provider pagination is not a block-anchored forensic acquisition. A reorganisation or new transactions can affect pages. Raw provider-response preservation is not yet implemented; the database snapshot contains normalised results and diagnostics.

The page, icon fonts, graph library and PDF libraries are local. **Wallet queries still leave the server for those external data providers.** An on-premises government installation needs approved provider arrangements or self-hosted indexers before claiming sovereign end-to-end data processing.

## 6. How to interpret retrieval status and scores

| Display | Meaning | What to check |
| --- | --- | --- |
| Observed | Supported provider windows were exhausted within this trace's scope | Reconcile important transactions; this is not a guarantee of all-time completeness |
| Partial | At least one limit or retrieval problem occurred | Read the category, wallet, page count and error/limit details |
| No transfers found | No qualifying transfers were retrieved | Check the selected chain, supported transfer types and independent explorer history |
| Unavailable | Origin history requests failed and no edges were returned | Check API keys, entitlement, quota, network access and provider diagnostics |
| Unknown score | There is not enough retrieved/expanded data to assign a zero-like result | Treat it as missing information |

A ban, frozen token balance or old inactivity does not erase blockchain history. One purple dot therefore cannot be interpreted as proof that the address is clean or that a ban explains the missing graph.

The current score is the capped sum of explicit signals: high fan-in adds 25, high fan-out adds 25, and a same-asset receive/send pair within 24 hours adds 20. Analyst-labelled mixers add 60; an analyst-labelled sanctions match sets the base to 99 before other additions. Scores cap at 100. The case score is the maximum recorded node score, not necessarily the reported wallet's score and not a percentage probability of fraud.

An exchange can naturally have many senders and recipients. A temporal receive/send match does not prove the same funds moved. A mixer label is not a conviction. Sanctions and entity labels require current, attributable sources. This release does not automatically ingest an unverified OFAC feed. No labelled dataset has established the accuracy of these scoring rules, and an exchange label does not force a score to zero.

## 7. The new graph: controls and design decisions

- **No address labels on the canvas.** Zooming in enlarges the dots and edges; it does not reveal address text. Hover over a node to see its abbreviated and full identifier, score and reasons.
- **Copy from the hover card.** The button copies the full identifier. Clicking a node pins the card so it will not disappear while you inspect it. Close the card to resume ordinary hover behaviour. Keyboard and touch users can use the node selector.
- **Repulsive / airy layout.** Auto uses a repulsive physics simulation for graphs up to 150 nodes. Nodes push apart while linked nodes attract each other; a collision pass separates nearby dots, then physics stops so the view stays stable. This is similar in purpose to the earlier “antigravity” behaviour.
- **Spaced hops for dense graphs.** Above 150 nodes, Auto starts with structured hop bands. A broad, spaced arrangement is more predictable than allowing hundreds of dots to keep moving. You may switch either way manually. The threshold is a design choice, not a scientific boundary.
- **Connected-edge highlighting.** Hover highlights the node's direct edges and fades unrelated ones. Repeated transfers between the same pair receive curved paths. Nodes are drawn above edges with opaque fills and borders.
- **Focus connections.** This temporarily shows one node and its immediate neighbours. The displayed count states that it is a subset. Press Focus connections again, or use “Show all nodes”, to restore the full view. The PDF still exports all retrieved records.
- **Bounded navigation.** Zoom-out stops at 80% of the fitted scale. Zoom-in is capped. Panning is constrained to the graph bounds and corrects empty positions so at least one visible node stays within the viewport. “Fit graph” always returns to the entire graph. Resizing the window recalculates the bounds.
- **Window controls at the upper right.** Minus minimises while preserving graph tabs. The square toggles full screen/restore. Cross closes the current in-memory tab; the saved database trace remains. Hover each icon for its explanation.

It is not possible to guarantee a crossing-free drawing of every arbitrary transaction network. The combination of spacing, faint edges, hover highlighting and explicit neighbourhood focus addresses readability without deleting evidence or silently merging transfers. The PDF's overview map combines parallel paths visually; its transfer ledger preserves the individual events.

Up to ten graph tabs can be open. They keep separate layouts and view states while the page remains open. A refresh or logout clears the in-memory tabs; reopen preserved snapshots through Investigation Reports. “Investigate” on a wallet opens a prefilled new investigation form. You still execute that new trace explicitly.

## 8. The dossier: what it contains and what it does not certify

The report now uses a navy header, consistent embedded typefaces, summary cards, alternating table rows and numbered pages. It contains:

1. Case metadata, retrieval status, maximum node score and snapshot digest.
2. A fitted overview of every retrieved node, independent of screen zoom or focus.
3. A node ledger with full identifiers, hop distances, roles/entity names, scores and recorded reasons.
4. Retrieval coverage by provider/category, including messages, page/record counters and expansion limits.
5. A full transfer ledger with event IDs, transaction hashes, sender/recipient, original asset amounts, asset identity and timestamps/relationship type where recorded.
6. Interpretation limits and a blank analyst/reviewer handover worksheet.

The report is built from the open saved result, not from a silent fresh trace. It does not add “AI detected” claims or invented agency stamps. Amounts of different tokens are not added into one misleading total. Very large traces naturally produce long ledgers; this preserves the records rather than dropping rows to make the PDF shorter.

A hash is a fingerprint of bytes. Here, the backend hashes the canonical JSON snapshot with sorted keys, compact separators and UTF-8, before adding the response-only `evidence_sha256` field. Recreating that same encoding is necessary to compare the hash. The printed digest is **not the PDF's hash**. Anyone with sufficient access could change a report and print a different hash; trusted custody and controlled storage are essential. A digest is not a digital signature or a court certification.

## 9. Why the earlier “NCRP COMPLIANT” heading was unsupported

The uploaded older report prints “NCRP COMPLIANT,” “OFFICIAL INVESTIGATION RECORD,” and “Stamped By: Investigator.” Those words did not demonstrate approval by I4C, the receiving police department or a court. The previous redesign removed them to avoid overstating the report's standing; that correction did not require making the layout plain.

NCRP is the National Cyber Crime Reporting Portal. Its public FAQ describes complaint submission, supporting evidence, references and the role of the concerned State/UT police. I did not find a public self-certification process for a third-party application's dossier. A reference number typed into CryptoTrace is not validated by the portal. Our application has no official NCRP integration or documented agency approval.

Three separate goals should be pursued:

| Goal | Practical next step |
| --- | --- |
| A report usable as supporting material | Obtain the receiving cybercrime unit's required format, mandatory fields, submission method and review process; map this dossier to those requirements |
| Acceptance of the software by an agency | Request a supervised pilot through the sponsoring department/I4C channel, agree on acceptance criteria, validate known cases and failure cases, and obtain written sign-off for the agreed scope |
| Proper electronic-evidence treatment | Work with the investigator, forensic expert and legal team on source acquisition, preservation, custody, reproducibility, hash records and the applicable certificate/signature requirements |

The Bharatiya Sakshya Adhiniyam, 2023 addresses electronic records in section 63 and provides a certificate Schedule with party and expert portions. Applicability and transitional rules need legal review for the actual proceeding. The program cannot truthfully fill in device-operation assertions, an expert's conclusions or signatures on behalf of those people. The blank review page in this dossier is not that statutory certificate.

Before claiming government readiness, prioritise real PostgreSQL integration testing, independent wallet-history reconciliation, raw-response retention, a controlled evidence store, versioned attribution sources, calibrated scoring, export audit events, agency identity/SSO and MFA, independent security assessment, load/rate-limit testing, encrypted backups with recovery drills, deployment hardening and documented retention/access procedures. The provided deployment templates are starting points, not completed certification.

## 10. A practical first test after updating

1. Sign in and check that icons and text sizes look consistent. Open **Help** from the dashboard; it contains the explanation previously occupying the large card.
2. Start a one-hop investigation on the correct chain. Read the retrieval status before interpreting the score.
3. Hover a wallet and use Copy address. Paste into a plain-text editor to confirm the entire address copied, including Tron casing.
4. Zoom in and out. No canvas address labels should appear. Try Fit graph and change layout.
5. Pin a card, focus its connections, restore all nodes, minimise, reopen, and toggle full screen.
6. Export the dossier. Compare its node/edge counts, address, retrieval timestamp and snapshot ID to the open trace. Verify significant transaction hashes independently.
7. Reopen that saved trace after refreshing the page. It should show the original saved result. A new live investigation is a separate retrieval and can contain different data.

The release's automated browser checks use synthetic fixtures, including 118 and 500 nodes. They verify UI behaviour and report preservation; they do not establish live provider completeness or legal validity. TEST_REPORT.md records the exact completed checks and remaining gaps.

## Official and technical references

Sources checked during this update, 28 September 2026. Requirements and provider plans can change.

- NCRP FAQ, supporting evidence, complaint handling and hashes: https://cybercrime.gov.in/Webform/FAQ.aspx
- MHA C&IS division and I4C functions: https://www.mha.gov.in/en/divisionofmha/cyber-and-information-security-cis-division
- Bharatiya Sakshya Adhiniyam, 2023, official text, section 63 and Schedule: https://www.indiacode.nic.in/indiacode/bitstream/123456789/20063/1/aa202347.pdf
- Vis Network physics: https://visjs.github.io/vis-network/docs/network/physics.html
- Vis Network interactions and view methods: https://visjs.github.io/vis-network/docs/network/index.html
- Provider and security references are also listed in README.md.

## Version 2.3 additions

See UPDATE_2_3.md for a step-by-step explanation of Bitcoin tracing, entity management and imports, saved transaction selection, graph colour precedence, focus toggle and the distinction between NCRP complaints and software approval.

## Version 2.4: online attribution

Read ONLINE_ATTRIBUTION.md for the required migration, automatic external label lookup, persistent caching, source dates and administrator review. Local reviewed labels take priority; external mixer labels do not automatically add risk points.
