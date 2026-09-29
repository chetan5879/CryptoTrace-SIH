# CryptoTrace 2.3: changes, installation and investigation guide

## Install without losing cases or accounts

1. Stop Uvicorn with Ctrl+C. Keep your current project folder as a backup.
2. Extract the complete replacement ZIP into a new folder.
3. Copy your working `.env` into the extracted `CryptoTrace-v2` folder. Keep the same DATABASE_URL and provider keys. Do not delete or recreate PostgreSQL.
4. Open a terminal inside that folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

5. Open http://127.0.0.1:8000 and press Ctrl+Shift+R. Use your existing login. A working v2.2 database needs no migration for this update. For first installation, follow README.md instead.
6. Select the correct blockchain explicitly and run a NEW trace. Saved evidence retains the old data and labels; the update does not rewrite old snapshots.

## What the screenshots establish

The BNB Binance address (`0x8894…2d4e3`) and Poly Network BNB address (`0x0d6e…32c71`) were displayed in Ethereum tabs. Ethereum, Polygon and BNB all use the same address format; the address alone cannot identify the incident network. Choose BNB Chain for those BNB test cases. The Polygon `0x5dc…63214` appeared in both Ethereum and Polygon tabs. Use Polygon for its Polygon incident test.

The Polygon screenshot says UNAVAILABLE, which means retrieval requests failed. It does not establish that the wallet had no transactions. Its collapsed diagnostics are not visible in the screenshot, so the exact failure remains unconfirmed. In this release, diagnostics expand automatically for partial/unavailable results and show safe RPC error codes. Check Alchemy app network access and credentials if Polygon fails.

An inactive, frozen or sanctioned address can retain historical on-chain activity. A single origin dot is not evidence that an address was banned. A high incident-linked address score is not guaranteed: current scores are heuristics on the retrieved sample, not a validated incident-history classifier. Known incident attribution and observed behavioural scores are different evidence.

Provider parsing now retains valid records if another record has an unexpected schema. Skipped records are counted and coverage is marked partial. NodeReal retains paced retries and bounded pagination; this does not certify full-history coverage or free-tier entitlement. No live provider API keys were supplied for this update, so real NodeReal, Alchemy and TronScan access was not tested.

## Bitcoin: what is now traced

UTXO means unspent transaction output. A Bitcoin transaction consumes specific previous outputs and creates new outputs. The ledger reveals those references; it does not reveal which person owns each output or a unique matching between each input and each output.

The updated adapter retrieves confirmed address history using chain pagination. The graph retains all available inputs and outputs of each retrieved transaction. Diamonds represent transactions; circles represent addresses. Scripts without a conventional address get a script identifier. Coinbase inputs are not invented as payments from an address.

Each input stores its previous transaction ID and output index, its input index and satoshi value. Outputs store their output index, satoshi value and script type. Fees are retained when available. When both funding and spending transactions were retrieved, the report links the exact output to the spending transaction/input. Missing spend linkage means not established in this retrieved sample, not necessarily unspent.

Downstream expansion follows recipients of transactions that spend the expanded wallet's outputs. It does not expand unrelated incoming co-recipients as if they received the victim's money. Later activity from a recipient address is relationship exploration, not proof the same stolen output was spent. CoinJoin, change ownership and service-internal accounting need additional evidence. The app does not claim reliable ownership clustering, proportional taint or exhaustive spend-chain reconstruction.

## Colours and graph controls

- Purple: reported origin, even if it has a VASP or mixer label.
- Black: sourced VASP/exchange label.
- Brown: sourced mixer label; takes precedence over VASP if both flags exist.
- Red: score 80-100; orange: 50-79; yellow: 20-49; green: 0-19.
- Grey: unknown score. Unknown histories must not be painted green as though cleared.

Entity colour takes priority over score, while the hover card still shows the score and flags. Node addresses remain hidden on the canvas. The single interactive card shows address, entity name, reasons and Copy. Edge inspection uses the same card and shows the transaction hash, endpoints, amount, time and UTXO metadata. The old native edge tooltip has been removed.

Focus connections now toggles: press once for the selected node's neighbours, press the same button again to restore all nodes. Reports retain the full snapshot even while the graph is focused. Fit graph, bounded zoom/pan, multiple tabs and window controls remain available.

## VASP and mixer registry

Open Diagnostics & Setup, then Wallet & entity registry. Every authenticated investigator can search labels. An administrator can add or edit a label by network and full address, with a name, source reference/date and classification. Changes are audited and apply to NEW traces. The application does not automatically treat an exchange as safe.

Graph results include a list of VASP/mixer matches; click one to inspect it. Dossiers include a separate VASP & Mixer Leads table with sources and counts of incoming/outgoing graph relationships. A matched exchange receiving funds is a lead for follow-up, not proof of a fiat withdrawal. Establishing a customer account or conversion normally requires appropriately obtained exchange records and analyst corroboration.

To populate a small initial registry, the ZIP includes four Binance addresses from its historical November 2022 disclosure, with the source URL. These are historical attributions, not current ownership guarantees or 'fraud-free' labels. Review the file before importing. From the configured project folder, using the database administrator's environment:

```bash
python import_entities.py examples/reviewed-entity-starter.json
python import_entities.py examples/reviewed-entity-starter.json --apply --admin administrator
```

Replace `administrator` with your existing administrator username. The first command only validates. The second imports and audits new labels, preserving existing entries. If you only have an investigator account, create an admin through `python manage.py create-user administrator --role admin` using your database administrator access; enter its new password when prompted. There is no default admin password.

To recover your old known_entities table:

```bash
python import_entities.py legacy-entities-review.json --export-legacy
```

This creates a review file without modifying the old table. Fill in the correct blockchain and source for every entry. Restore original Tron/Bitcoin Base58 casing from trusted records; simply capitalizing the first letter does not repair a lowercased address. Validate and then import the reviewed file with the same commands as above. The old source had unsourced/misclassified entries (including a burn address marked as VASP); it should not be silently trusted.

## Transaction Explorer and Diagnostics

Transaction Explorer now has saved case and trace selectors. Choose a case, then a dated snapshot to populate its ledger. Filtering matches full addresses, not just abbreviated strings. The selectors use the current case page; Reports has Older cases/Newer cases controls. Use Refresh cases after changing pages if needed. Snapshots contain only records actually saved, and an imported legacy case may have no saved transfers.

A downloaded PDF is an export, not a database connection. Opening it in the browser does not select the original trace. Load the corresponding saved case/trace, or run a new trace if only an old PDF remains. The older supplied dossier contained a node table but not a reconstructable transfer ledger; missing transaction records cannot be invented from node addresses.

Diagnostics remains because it helps investigate empty graphs: it checks backend/database availability and provider-key configuration. A configured key is not proof that an API works or the plan includes a method. Trace-specific diagnostics contain actual request failures and retrieval limits. No secret key is displayed.

## What 'node attribution ledger' means

It was a table mapping graph nodes to their addresses, roles, entity names and recorded risk reasons. It was not an official government ledger. It is now called Wallet & Entity Register, with a separate VASP & Mixer Leads section for easier reading.

## NCRP: official information versus readiness recommendations

I found an official complainant checklist, not a public certification checklist that grants 'NCRP-approved' status to third-party tracing software or its PDFs. Earlier AI-generated software checklists should be treated as recommendations unless each item is tied to an applicable official instrument or written agency requirement. A polished PDF or a heading saying NCRP does not confer approval.

The official portal checklist asks for incident date/time, incident description, complainant identification, and financial-fraud transaction details such as bank/wallet/merchant, transaction reference, date and amount. Blockchain hashes are not substitutes for banking UTRs where those are applicable. Follow the live portal for its current upload fields and limits.

Official source: https://cybercrime.gov.in/Webform/Crime_AuthoLogin.aspx
Portal FAQ: https://cybercrime.gov.in/Webform/FAQ.aspx

Electronic-evidence admissibility is a separate legal question. Section 63 and the Schedule of the Bharatiya Sakshya Adhiniyam address electronic records and certification. A CryptoTrace PDF and its snapshot hash do not themselves satisfy every condition or replace the applicable certificate and responsible attestations. Have the receiving agency/legal reviewer determine the process for the actual proceeding.

Official legislation: https://www.indiacode.nic.in/bitstream/123456789/20063/1/aa202347.pdf

Practical next steps, presented as engineering/governance recommendations rather than an official approval list: seek written acceptance/integration criteria from the receiving LEA/I4C; agree on evidence export and custody procedures; validate against independently reconciled transactions; review source-label quality; conduct independent security/deployment review; establish backup, access, retention and incident-response procedures. Ask the receiving authority whether any empanelment or procurement-specific certification applies. This release is not government-certified or independently security-audited.

## References for implementation and labels

- Bitcoin Esplora transaction fields and address chain history: https://github.com/Blockstream/esplora/blob/master/API.md
- NodeReal transfers: https://docs.nodereal.io/reference/nr_getassettransfers
- Alchemy transfers: https://www.alchemy.com/docs/data/transfers-api/transfers-endpoints/alchemy-get-asset-transfers
- Tron native transfers: https://docs.tronscan.org/en/api/wallet/transfer-trx
- Binance historical wallet disclosure: https://www.binance.com/en-IN/blog/community/2895840147147652626
