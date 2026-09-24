import os
import time
import uuid
import json
import base64
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests
import numpy as np
from sklearn.ensemble import IsolationForest
import networkx as nx
from web3 import Web3

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

# 1. Load environment variables first
load_dotenv()

# 2. Mock Entity Database (Phase 5)

# KNOWN ENTITIES (VASPs, MIXERS & INDIAN EXCHANGES)


# 3. Initialize the FastAPI app
app = FastAPI(
    title="CryptoTrace",
    description="Crypto Fraud Investigation and Blockchain Analytics Platform",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)   

# --------------------------------------------------
# PHASE 7: POSTGRESQL DATABASE STORAGE
# --------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/cryptotrace")

def get_db_connection():
    """Opens a connection to the PostgreSQL database."""
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Cases Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY,
            wallet_address TEXT,
            blockchain TEXT,
            fraud_type TEXT,
            risk_score INTEGER,
            status TEXT,
            max_hops INTEGER DEFAULT 2,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Dynamic Entities Table (The Permanent Solution)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS known_entities (
            wallet_address TEXT PRIMARY KEY,
            name TEXT,
            is_vasp BOOLEAN,
            is_mixer BOOLEAN
        )
    """)
    
    # 3. Auto-seed the database if it is empty
    cursor.execute("SELECT COUNT(*) FROM known_entities")
    if cursor.fetchone()[0] == 0:
        seed_data = [
            ("0x27f706edde3ad952ef647dd67e24e38cd0803dd6", "WazirX Hot Wallet", True, False),
            ("0x3235b2b2915cd67df9adbfcfdc093c063cfbc4fc", "CoinDCX Hot Wallet", True, False),
            ("tmua6yqfcex8ehbfyeg5y7s4dqzsjirey9", "Binance Tron Hot Wallet", True, False),
            ("t9yd14nj9j7xab4dbgeix9h8unkkhxuwwb", "Tron Network Black Hole (Burn)", True, False),
            ("0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc", "Tornado Cash (Mixer)", False, True)
        ]
        cursor.executemany("INSERT INTO known_entities (wallet_address, name, is_vasp, is_mixer) VALUES (%s, %s, %s, %s)", seed_data)
        
    conn.commit()
    cursor.close()
    conn.close()

# Helper function to query the DB during traces
def get_entity_data(address: str):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM known_entities WHERE wallet_address = %s", (address.lower(),))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return dict(row) if row else {}

@app.on_event("startup")
def on_startup():
    init_db()

class CaseModel(BaseModel):
    case_id: str
    wallet_address: str
    blockchain: str
    fraud_type: str
    max_hops: int = 2


@app.post("/cases")
def create_case(case: CaseModel):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO cases (case_id, wallet_address, blockchain, fraud_type, risk_score, status, max_hops)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (case_id) DO UPDATE SET
            wallet_address = EXCLUDED.wallet_address,
            blockchain = EXCLUDED.blockchain,
            fraud_type = EXCLUDED.fraud_type,
            max_hops = EXCLUDED.max_hops
        """,
        (case.case_id, case.wallet_address.lower(), case.blockchain, case.fraud_type, 0, "Tracing", case.max_hops)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "success"}


@app.patch("/cases/{case_id}")
def update_case_score(case_id: str, risk_score: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE cases SET risk_score = %s, status = 'Completed' WHERE case_id = %s",
        (risk_score, case_id)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "updated"}

@app.get("/cases")
def get_cases():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM cases ORDER BY timestamp DESC LIMIT 10")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(row) for row in rows]

class EntityModel(BaseModel):
    wallet_address: str
    name: str
    is_vasp: bool = False
    is_mixer: bool = False

@app.post("/entities")
def add_known_entity(entity: EntityModel):
    """Instantly categorizes a wallet in the database to prevent false positives/negatives."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO known_entities (wallet_address, name, is_vasp, is_mixer)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (wallet_address) DO UPDATE SET
            name = EXCLUDED.name,
            is_vasp = EXCLUDED.is_vasp,
            is_mixer = EXCLUDED.is_mixer
        """,
        (entity.wallet_address.lower(), entity.name, entity.is_vasp, entity.is_mixer)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "success", "message": f"{entity.name} added to intelligence database."}

@app.get("/stats")
def get_dashboard_stats():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Total count
    cursor.execute("SELECT COUNT(*) as total FROM cases")
    total_cases = cursor.fetchone()["total"] or 0
    
    # Risk category counts
    cursor.execute("""
        SELECT 
            COUNT(*) FILTER (WHERE risk_score >= 80) AS critical,
            COUNT(*) FILTER (WHERE risk_score >= 50 AND risk_score < 80) AS high,
            COUNT(*) FILTER (WHERE risk_score >= 20 AND risk_score < 50) AS medium,
            COUNT(*) FILTER (WHERE risk_score < 20) AS low
        FROM cases
    """)
    risk_counts = cursor.fetchone()
    
    # Fraud typology counts
    cursor.execute("""
        SELECT fraud_type, COUNT(*) as count 
        FROM cases 
        GROUP BY fraud_type 
        ORDER BY count DESC
    """)
    typology_rows = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    # Calculate percentages
    def pct(val):
        return round((val / total_cases * 100)) if total_cases > 0 else 0

    risk_distribution = {
        "critical": {"count": risk_counts["critical"], "pct": pct(risk_counts["critical"])},
        "high": {"count": risk_counts["high"], "pct": pct(risk_counts["high"])},
        "medium": {"count": risk_counts["medium"], "pct": pct(risk_counts["medium"])},
        "low": {"count": risk_counts["low"], "pct": pct(risk_counts["low"])},
    }

    return {
        "active_cases": total_cases,
        "high_risk": risk_counts["critical"] + risk_counts["high"],
        "wallets_traced": total_cases * 15,
        "risk_distribution": risk_distribution,
        "typologies": [dict(r) for r in typology_rows]
    }

# --------------------------------------------------
# STANDARD ROUTES & ALCHEMY INTEGRATION
# --------------------------------------------------
@app.get("/")
def home():
    return {"message": "CryptoTrace API is running", "status": "success"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}



FAN_THRESHOLD_DEFAULT = 5      
MAX_PAGES_PER_WALLET = 3       
HARD_MAX_HOPS = 4              
DEEP_MAX_HOPS = 6              
MAX_WALLETS_PER_HOP = 25       
MAX_TOTAL_WALLETS_DEEP = 500   
REQUEST_TIMEOUT_SECONDS = 15

# ==========================================
# UNIVERSAL BLOCKCHAIN ADAPTERS
# ==========================================
def get_transfers(wallet, direction, blockchain="Ethereum"):
    """Routes the request to the correct native blockchain API and standardizes the output."""
    chain = blockchain.lower()
    
    if chain in ["ethereum", "polygon", "bnb chain"]:
        return fetch_evm_transfers(wallet, direction, chain)
    elif chain == "bitcoin":
        return fetch_bitcoin_transfers(wallet, direction)
    elif chain == "tron":
        return fetch_tron_transfers(wallet, direction)
    else:
        return []

def fetch_evm_transfers(wallet, direction, chain_lower):
    """Fetches EVM data using Alchemy"""
    api_key = os.getenv("ALCHEMY_API_KEY")
    if not api_key: return []

    # Dynamically route Alchemy endpoints based on EVM chain
    base = "eth-mainnet.g.alchemy.com/v2/"
    if chain_lower == "polygon": base = "polygon-mainnet.g.alchemy.com/v2/"
    elif chain_lower == "bnb chain": base = "bnb-mainnet.g.alchemy.com/v2/"
        
    url = f"https://{base}{api_key}"
    all_transfers = []
    
    params = {
        "fromBlock": "0x0", "toBlock": "latest",
        "category": ["external", "internal", "erc20"],
        "withMetadata": True, "excludeZeroValue": True, "maxCount": "0x32"
    }
    if direction == "incoming": params["toAddress"] = wallet
    else: params["fromAddress"] = wallet

    payload = {"jsonrpc": "2.0", "id": 1, "method": "alchemy_getAssetTransfers", "params": [params]}
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            all_transfers.extend(res.json().get("result", {}).get("transfers", []))
    except Exception:
        pass
        
    return all_transfers

def fetch_bitcoin_transfers(wallet, direction):
    """Fetches UTXO data using the open-source Mempool.space API (No API Key Required)"""
    transfers = []
    try:
        res = requests.get(f"https://mempool.space/api/address/{wallet}/txs", timeout=10)
        if res.status_code == 200:
            for tx in res.json():
                tx_hash = tx.get("txid")
                timestamp = None
                if tx.get("status", {}).get("block_time"):
                    timestamp = datetime.utcfromtimestamp(tx["status"]["block_time"]).isoformat() + "Z"
                
                if direction == "incoming":
                    from_addr = tx.get("vin", [{}])[0].get("prevout", {}).get("scriptpubkey_address", "Unknown_BTC_Input")
                    for vout in tx.get("vout", []):
                        if vout.get("scriptpubkey_address") == wallet:
                            amt_btc = vout.get("value", 0) / 10**8
                            transfers.append({"hash": tx_hash, "from": from_addr, "to": wallet, "value": str(amt_btc), "asset": "BTC", "metadata": {"blockTimestamp": timestamp}})
                else:
                    is_sender = any(vin.get("prevout", {}).get("scriptpubkey_address") == wallet for vin in tx.get("vin", []))
                    if is_sender:
                        for vout in tx.get("vout", []):
                            to_addr = vout.get("scriptpubkey_address")
                            if to_addr and to_addr != wallet:
                                amt_btc = vout.get("value", 0) / 10**8
                                transfers.append({"hash": tx_hash, "from": wallet, "to": to_addr, "value": str(amt_btc), "asset": "BTC", "metadata": {"blockTimestamp": timestamp}})
    except Exception as e:
        print(f"BTC Fallback: {e}")
    return transfers

def fetch_tron_transfers(wallet, direction):
    """Fetches TRC-20 and Approvals while bypassing Cloudflare bot-protection"""
    transfers = []
    wallet = wallet.strip() 
    
    # CRITICAL FIX: Spoof a real web browser so Cloudflare doesn't block the Python request
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    try:
        # 1. Primary: TronGrid API (Most reliable for all standard TRC-20 transfers)
        trc20_url = f"https://api.trongrid.io/v1/accounts/{wallet}/transactions/trc20?limit=50"
        res_trc20 = requests.get(trc20_url, headers=headers, timeout=10)
        if res_trc20.status_code == 200:
            for tx in res_trc20.json().get("data", []):
                from_addr = tx.get("from", "").strip()
                to_addr = tx.get("to", "").strip()
                
                if direction == "incoming" and to_addr != wallet: continue
                if direction == "outgoing" and from_addr != wallet: continue
                    
                ts_ms = tx.get("block_timestamp")
                timestamp = datetime.utcfromtimestamp(ts_ms / 1000.0).isoformat() + "Z" if ts_ms else None
                
                decimals = int(tx.get("token_info", {}).get("decimals", 6))
                symbol = tx.get("token_info", {}).get("symbol", "TRC20").upper()
                amt = float(tx.get("value", 0)) / (10 ** decimals) if decimals else float(tx.get("value", 0))
                
                transfers.append({
                    "hash": tx.get("transaction_id"), "from": from_addr, "to": to_addr, 
                    "value": str(amt), "asset": symbol, "metadata": {"blockTimestamp": timestamp}
                })

        # 2. Secondary: TronScan for Approvals (Catches Address Poisoning Scams) ## deleted

                
    except Exception as e:
        print(f"Tron API Fallback Error: {e}")
        
    return transfers

def to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None

def compute_fan_metrics(node_id, outgoing_transfers, incoming_transfers, threshold):
    out_recipients = set()
    for t in outgoing_transfers:
        frm = t.get("from") or ""
        to = t.get("to") or ""
        if frm == node_id and to and to != node_id:
            out_recipients.add(to)

    in_senders = set()
    for t in incoming_transfers:
        frm = t.get("from") or ""
        to = t.get("to") or ""
        if to == node_id and frm and frm != node_id:
            in_senders.add(frm)

    flags = []
    if len(out_recipients) >= threshold:
        flags.append("high_fan_out")
    if len(in_senders) >= threshold:
        flags.append("high_fan_in")

    return len(out_recipients), len(in_senders), flags


def trace_fund_flow(address, max_hops, wallet_cap=None, max_total_wallets=None, fan_threshold=FAN_THRESHOLD_DEFAULT, blockchain="Ethereum"):    
    address = address.strip()
    # 1. ONLY lowercase the origin address if it's an EVM chain
    
    is_evm = blockchain.lower() in ["ethereum", "polygon", "bnb chain"]
    if is_evm:
        address = address.lower()

    graph = nx.MultiDiGraph()
    graph.add_node(address, type="reported_wallet", hop=0)

    first_hop_transfers = []
    first_hop_transfers.extend(get_transfers(address, "incoming", blockchain))
    first_hop_transfers.extend(get_transfers(address, "outgoing", blockchain))

    current_hop_funds = {}
    current_hop_wallets = set()

    for transfer in first_hop_transfers:
        from_address = transfer.get("from") or ""
        to_address = transfer.get("to") or ""
        
        # Respect case-sensitivity based on the network
        if is_evm:
            from_address = from_address.lower()
            to_address = to_address.lower()
            
        if not from_address or not to_address:
            continue

        asset = transfer.get("asset")
        amount = transfer.get("value")
        metadata = transfer.get("metadata", {})
        timestamp = metadata.get("blockTimestamp")

        # Fetch from PostgreSQL instead of static dictionary
        from_entity = get_entity_data(from_address)
        to_entity = get_entity_data(to_address)


        graph.add_node(from_address, type="exchange" if from_entity.get("is_vasp") else "wallet", hop=1, entity_name=from_entity.get("name"))
        graph.add_node(to_address, type="exchange" if to_entity.get("is_vasp") else "wallet", hop=1, entity_name=to_entity.get("name"))
        graph.add_edge(from_address, to_address, tx_hash=transfer.get("hash"), asset=asset, amount=amount, timestamp=timestamp, hop=1)

        if from_address == address:
            current_hop_wallets.add(to_address)
            if to_address not in current_hop_funds:
                current_hop_funds[to_address] = []
            current_hop_funds[to_address].append({"asset": asset, "amount": amount, "timestamp": timestamp, "tx_hash": transfer.get("hash")})

    fan_out, fan_in, flags = compute_fan_metrics(address, first_hop_transfers, first_hop_transfers, fan_threshold)
    graph.nodes[address]["fan_out_count"] = fan_out
    graph.nodes[address]["fan_in_count"] = fan_in
    graph.nodes[address]["flags"] = flags

    hop_level = 2
    truncated_wallets = []
    visited_wallets = set()   
    total_wallets_expanded = 0

    while hop_level <= max_hops and current_hop_wallets:
        current_hop_wallets = {w for w in current_hop_wallets if w not in visited_wallets}

        if wallet_cap and len(current_hop_wallets) > wallet_cap:
            def total_received(wallet):
                return sum((to_decimal(f["amount"]) or Decimal(0)) for f in current_hop_funds.get(wallet, []))
            ranked_wallets = sorted(current_hop_wallets, key=total_received, reverse=True)
            current_hop_wallets = set(ranked_wallets[:wallet_cap])
            for wallet in ranked_wallets[wallet_cap:]:
                truncated_wallets.append({"wallet": wallet, "hop": hop_level, "reason": "per_hop_limit"})

        next_hop_funds = {}
        next_hop_wallets = set()

        for wallet in current_hop_wallets:
            if max_total_wallets and total_wallets_expanded >= max_total_wallets:
                truncated_wallets.append({"wallet": wallet, "hop": hop_level, "reason": "overall_limit"})
                continue

            visited_wallets.add(wallet)
            total_wallets_expanded += 1
            received_funds = current_hop_funds.get(wallet, [])
            if not received_funds:
                continue

            # MASSIVE BUG FIX: Uses 'wallet' here instead of 'address'
            transfers = get_transfers(wallet, "outgoing", blockchain)
            incoming_transfers = get_transfers(wallet, "incoming", blockchain)

            fan_out, fan_in, flags = compute_fan_metrics(wallet, transfers, incoming_transfers, fan_threshold)
            if wallet in graph.nodes:
                graph.nodes[wallet]["fan_out_count"] = fan_out
                graph.nodes[wallet]["fan_in_count"] = fan_in
                graph.nodes[wallet]["flags"] = flags

            for transfer in transfers:
                from_address = transfer.get("from") or ""
                to_address = transfer.get("to") or ""

                if is_evm:
                    from_address = from_address.lower()
                    to_address = to_address.lower()

                if from_address != wallet or to_address == wallet:
                    continue

                asset = transfer.get("asset")
                amount = transfer.get("value")
                timestamp = transfer.get("metadata", {}).get("blockTimestamp")
                sent_amount = to_decimal(amount)

                if sent_amount is None or sent_amount <= 0:
                    continue

                possible_continuation = False
                flow_strength = None
                time_delta_seconds = None

                for received in received_funds:
                    if received.get("asset") != asset:
                        continue

                    if received.get("timestamp") and timestamp:
                        try:
                            received_time = datetime.fromisoformat(received.get("timestamp").replace("Z", "+00:00"))
                            sent_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                            if sent_time > received_time:
                                time_delta_seconds = (sent_time - received_time).total_seconds()
                        except ValueError:
                            pass

                    received_amount = to_decimal(received.get("amount"))
                    if received_amount and received_amount > 0:
                        amount_ratio = sent_amount / received_amount
                        if Decimal("0.80") <= amount_ratio <= Decimal("1.20"):
                            flow_strength = "strong"
                            possible_continuation = True
                            break
                        elif Decimal("0.20") <= amount_ratio < Decimal("0.80"):
                            flow_strength = "possible"
                            possible_continuation = True
                            break

                if not possible_continuation:
                    continue

                is_rapid = time_delta_seconds is not None and time_delta_seconds < 86400
                to_entity = get_entity_data(to_address)  
                              
                graph.add_node(to_address, type="exchange" if to_entity.get("is_vasp") else "wallet", hop=hop_level, entity_name=to_entity.get("name"))
                graph.add_edge(from_address, to_address, tx_hash=transfer.get("hash"), asset=asset, amount=amount, timestamp=timestamp, hop=hop_level, fund_flow_continuation=True, flow_strength=flow_strength, rapid_movement=is_rapid, turnaround_seconds=time_delta_seconds)
                
                next_hop_wallets.add(to_address)
                if to_address not in next_hop_funds:
                    next_hop_funds[to_address] = []
                next_hop_funds[to_address].append({"asset": asset, "amount": amount, "timestamp": timestamp, "tx_hash": transfer.get("hash")})

        current_hop_wallets = next_hop_wallets
        current_hop_funds = next_hop_funds
        hop_level += 1

    try:
        hop_distances = nx.single_source_shortest_path_length(graph, address)
        for node in graph.nodes():
            if node in hop_distances:
                graph.nodes[node]["hop"] = hop_distances[node]
    except nx.NetworkXError:
        graph.nodes[address]["hop"] = 0

    graph.nodes[address]["type"] = "reported_wallet"
    graph.nodes[address]["hop"] = 0

    # --------------------------------------------------
    # ML ANOMALY DETECTION & EXPLAINABLE RISK
    # --------------------------------------------------
    ml_anomalies = set()
    node_order = list(graph.nodes())
    node_features = [[graph.nodes[n].get("fan_in_count", 0), graph.nodes[n].get("fan_out_count", 0)] for n in node_order]
        
    if len(node_features) > 10:
        model = IsolationForest(contamination=0.05, random_state=42)
        predictions = model.fit_predict(node_features)
        for i, pred in enumerate(predictions):
            if pred == -1:
                ml_anomalies.add(node_order[i])

    for node_id in graph.nodes():
        score = 0
        reasons = []
        node_data = graph.nodes[node_id]
        
        # Fetch from PostgreSQL for accurate risk assessment
        entity = get_entity_data(node_id)

        if entity.get("is_mixer"):
            score = 99
            reasons.append("Critical: Known Mixer/Sanctioned Entity")
        elif entity.get("is_vasp"):
            score = 0
            reasons.append("Safe: Known Exchange")
        elif node_data.get("type") == "reported_wallet":
            score = 0
            reasons.append("Reported Wallet")
        else:
            score += 10
            reasons.append("Involved in fund flow")
            flags = node_data.get("flags", [])
            
            if "high_fan_in" in flags:
                score += 25
                reasons.append("High Fan-In (Potential Consolidation)")
            if "high_fan_out" in flags:
                score += 25
                reasons.append("High Fan-Out (Potential Layering)")

            has_rapid = any(d.get("rapid_movement") for _, _, d in graph.in_edges(node_id, data=True)) or \
                        any(d.get("rapid_movement") for _, _, d in graph.out_edges(node_id, data=True))
            if has_rapid:
                score += 30
                reasons.append("Rapid Movement (Under 24h turnaround)")

            total_in = sum(to_decimal(d.get("amount", 0)) or Decimal(0) for _, _, d in graph.in_edges(node_id, data=True))
            total_out = sum(to_decimal(d.get("amount", 0)) or Decimal(0) for _, _, d in graph.out_edges(node_id, data=True))
            
            if total_in > 0 and total_out > 0:
                retention_ratio = (total_in - total_out) / total_in
                if retention_ratio < Decimal("0.05") and has_rapid:
                    score += 20
                    reasons.append("Pass-Through Wallet")
                    
            has_round_amounts = False
            for _, _, data in graph.out_edges(node_id, data=True):
                amt = to_decimal(data.get("amount", 0))
                if amt and amt > 0 and amt % 1 == 0:  
                    has_round_amounts = True
                    break
            
            if has_round_amounts:
                score += 15
                reasons.append("Round Amount Structuring")

            out_edges = list(graph.out_edges(node_id, data=True))
            if len(out_edges) == 2:
                total_out_peel = sum((to_decimal(e[2].get("amount", 0)) or Decimal(0)) for e in out_edges)
                if total_out_peel > 0:
                    ratios = [(to_decimal(e[2].get("amount", 0)) or Decimal(0)) / total_out_peel for e in out_edges]
                    if any(r >= Decimal("0.85") for r in ratios) and any(r <= Decimal("0.15") for r in ratios):
                        score += 25
                        reasons.append("Peeling Chain Activity")

            if node_id in ml_anomalies:
                score += 20
                reasons.append("AI Detection: Unusual Transaction Pattern")

        graph.nodes[node_id]["risk_score"] = min(score, 100)
        graph.nodes[node_id]["risk_reasons"] = reasons

    return {
        "wallet_address": address,
        "max_hops": max_hops,
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "truncated_wallets": truncated_wallets,
        "nodes": [{"id": n, **attr} for n, attr in graph.nodes(data=True)],
        "edges": [{"from": s, "to": t, **attr} for s, t, _, attr in graph.edges(data=True, keys=True)]
    }

@app.get("/wallet/{address}/graph")
def get_wallet_graph(address: str, max_hops: int = 2, fan_threshold: int = FAN_THRESHOLD_DEFAULT, blockchain: str = "Ethereum"):
    # (Optional: You can remove the Web3.is_address check here since Bitcoin/Tron addresses aren't valid Web3 addresses)
    if max_hops < 1 or max_hops > HARD_MAX_HOPS:
        raise HTTPException(status_code=400, detail=f"max_hops must be between 1 and {HARD_MAX_HOPS}")
    return trace_fund_flow(address, max_hops, wallet_cap=MAX_WALLETS_PER_HOP, fan_threshold=fan_threshold, blockchain=blockchain)