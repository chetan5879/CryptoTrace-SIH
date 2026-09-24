
# 🔎 CryptoTrace: Autonomous Blockchain Forensics & Intelligence

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=flat-square&logo=postgresql)](https://www.postgresql.org/)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-F7931E?style=flat-square&logo=scikit-learn&logoColor=white)](https://scikit-learn.org/)
[![NetworkX](https://img.shields.io/badge/NetworkX-00517C?style=flat-square)](https://networkx.org/)
[![SIH Ready](https://img.shields.io/badge/SIH_2026-Law_Enforcement_Tech-FF9900?style=flat-square)](#)

**CryptoTrace** is a comprehensive, multi-chain forensic tracing platform engineered for Indian Law Enforcement agencies to investigate cryptocurrency-based cybercrime. 

Built to combat task-fraud, phishing, and money laundering, CryptoTrace autonomously maps fund flows, applies machine-learning anomaly detection, and generates court-ready NCRP (National Cyber Crime Reporting Portal) compliance dossiers.

---

## 🚀 Key Features

* **Universal Multi-Chain Intelligence:** Natively supports 100% of token and gas transfers across **Ethereum, Polygon, BNB Chain (EVMs), Bitcoin (UTXO), and Tron (TRX/TRC-20)**.
* **Explainable AI Risk Scoring:** Utilizes an **Isolation Forest** machine learning model alongside strict financial heuristics (peeling chains, pass-through ratios, rapid consolidation) to assign accurate risk scores (0-100) to intermediary wallets.
* **Dynamic OSINT Entity Database:** Replaces static dictionaries with a live PostgreSQL intelligence database. Law enforcement can instantly tag new VASP (Virtual Asset Service Provider) off-ramps, mixers, and Indian exchanges (WazirX, CoinDCX) without system downtime.
* **Bypass Anti-Bot Defenses:** Built-in Cloudflare evasion and smart-contract abstraction parsing ensures clean, actionable data retrieval from block explorers.
* **Automated Forensic Reporting:** Instantly compiles the Vis.js interactive node graph and ML risk justifications into a timestamped, digitally structured PDF dossier for legal prosecution.

## 🛠️ Architecture & Tech Stack

**Backend Engine:**
* **Framework:** FastAPI (Python) for asynchronous, high-concurrency API routing.
* **Graph Mathematics:** NetworkX for multi-directed graph traversal and fan-in/fan-out shortest-path calculations.
* **Machine Learning:** `scikit-learn` (Isolation Forest) for unsupervised transaction pattern anomaly detection.
* **Database:** PostgreSQL for persistent case management and live entity intelligence overrides.

**Blockchain Adapters:**
* **EVM Chains:** Alchemy API (JSON-RPC)
* **Bitcoin:** Mempool.space API (Raw UTXO evaluation)
* **Tron:** TronScan Unified API (TRC-20 & Native TRX aggregation)

**Frontend Dashboard:**
* **Visualization:** Vis.js Network for interactive, multi-hop nodal analysis.
* **Export:** jsPDF for generating forensic reports.

---

## ⚙️ Local Installation & Setup

**1. Clone the repository**
```bash
git clone [https://github.com/chetan5879/CryptoTrace-SIH.git](https://github.com/chetan5879/CryptoTrace-SIH.git)
cd CryptoTrace-SIH

```

**2. Create a virtual environment and install dependencies**

```bash
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
pip install -r requirements.txt

```

**3. Configure Environment Variables**
Create a `.env` file in the root directory and add the following keys:

```env
# Required for EVM (Ethereum, Polygon, BNB) tracing
ALCHEMY_API_KEY=your_alchemy_api_key_here

# Required for Case Management & Entity Intelligence
DATABASE_URL=postgresql://postgres:password@localhost:5432/cryptotrace

```

**4. Initialize Database & Start the Backend**

```bash
uvicorn main:app --reload

```

**5. Launch the Frontend**
Open `index.html` via Live Server (Port 5500) or your preferred local web server.

---

## 🧠 The Intelligence Pipeline (How it Works)

1. **Input Normalization:** The engine cleans inputs, handling case-insensitive EVM `0x` hashes alongside strict, case-sensitive Base58 Bitcoin and Tron addresses.
2. **Recursive Traversal:** The system pulls transaction histories for the suspect, mapping outbound capital flight and inbound consolidation up to a maximum defined hop-depth.
3. **Entity Override:** Nodes are cross-referenced with the PostgreSQL `known_entities` table. Identified Mixers (e.g., Tornado Cash) are hard-flagged as Critical (99/100). KYC-compliant exchanges are flagged as Safe (0/100).
4. **Heuristic Evaluation:** Unidentified intermediary wallets are subjected to algorithmic evaluation:
* *Rapid Movement:* Funds turned around in under 24 hours.
* *Layering:* High Fan-Out (1 sender -> many receivers).
* *Consolidation:* High Fan-In (many senders -> 1 receiver).
* *Peeling Chains:* Structured routing utilizing 80/20 split thresholds.


5. **ML Anomaly Injection:** The Isolation Forest model evaluates the total graph matrix, tagging nodes that mathematically deviate from standard human transaction behavior.

🚀 Recent Architecture & Feature Updates
1. Multi-Chain Universal Blockchain Adapters

    EVM Networks (Ethereum, Polygon, BNB Chain): Integrated high-performance RPC querying via Alchemy to track external, internal, and ERC-20 token movements.

    Bitcoin (UTXO): Integrated the open-source Mempool.space API to parse native BTC inputs, outputs, and transaction timestamps without requiring paid API keys.

    Tron (TRC-20 & TRX): Developed a Cloudflare-bypassed scraping adapter targeting TronScan to extract active TRC-20 USDT and native TRX capital flows.

2. Autonomous OSINT Threat Ingestion

    Live OFAC Sanctions Sync: Implemented a background asynchronous task (asyncio) that queries the live U.S. Treasury OFAC sanctioned address feeds every 24 hours.

    Automated Database Patching: Automatically upserts newly blacklisted threat actors directly into the PostgreSQL known_entities table on server startup without requiring system reboots.

3. Smart Address Auto-Detection & Mismatch Safeguard

    Regex Format Recognition: Built real-time input parsers that automatically identify whether a pasted string is an EVM (0x...), Tron (T...), or Bitcoin (1/3/bc1) address.

    Network Alignment & Error Banning: Automatically switches the blockchain dropdown to match the detected asset and triggers a strict mismatch guard banner if an investigator attempts to query an invalid network combination.

4. Advanced VASP & Mixer Attribution Engine

    PostgreSQL-Powered Classification: Dynamically attributes nodes during graph traversal, distinguishing between centralized exchanges (Safe Off-Ramps/VASPs) and privacy mixers/illicit pools (Critical Risk).

    Machine Learning Anomaly Detection: Leverages an Isolation Forest model alongside heuristic rules to detect high fan-in/fan-out consolidation, round-amount structuring, peeling chains, and rapid 24-hour turnarounds.

5. Court-Admissible NCRP Forensic Dossiers

    Automated PDF Generation: Compiles multi-hop graph results into structured, professional PDF dossiers using jsPDF and auto-tables.

    Official Law Enforcement Stamping: Automatically stamps reports with the active investigator's profile (Officer Name, Badge/ID, and Cyber Crime Unit) for immediate legal freeze-notice submission.
## ⚖️ Disclaimer

*This software is developed as a prototype for the Smart India Hackathon. It is intended strictly for authorized law enforcement, academic research, and cybersecurity analysis. Do not utilize this tool for unauthorized surveillance.*

```

```
