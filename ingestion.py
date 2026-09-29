"""Bounded, observable history adapters. Provider exhaustion is not chain completeness."""
from contextlib import contextmanager
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import requests
from nodereal_limit import wait_for_slot

CHAINS = ('Ethereum', 'Polygon', 'BNB Chain', 'Tron', 'Bitcoin')
EVM = CHAINS[:3]

class ProviderError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable

def normalize(address, chain):
    return address.strip().lower() if chain in EVM else address.strip()

def validate_address(address, chain):
    if chain not in CHAINS:
        raise ValueError('Unsupported blockchain')
    address = normalize(address, chain)
    if chain in EVM:
        valid = re.fullmatch(r'0x[0-9a-f]{40}', address)
    elif chain == 'Tron':
        valid = re.fullmatch(r'T[1-9A-HJ-NP-Za-km-z]{33}', address)
        if valid:
            alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
            n = 0
            for c in address:
                n = n * 58 + alphabet.index(c)
            raw = n.to_bytes(25, 'big')
            valid = raw[0] == 0x41 and hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:]
    else:
        # Syntax only; the provider validates BTC checksums. Do not lowercase Base58.
        valid = re.fullmatch(r'[13][1-9A-HJ-NP-Za-km-z]{25,34}|bc1[ac-hj-np-z02-9]{11,87}', address)
    if not valid:
        raise ValueError('Invalid address for selected blockchain (Tron requires original case and checksum)')
    return address

def amount(raw, decimals):
    decimals = int(decimals)
    if not 0 <= decimals <= 255:
        raise ValueError('Invalid token decimals')
    with localcontext() as ctx:
        ctx.prec = 120
        value = Decimal(str(raw)) / (Decimal(10) ** decimals)
    if not value.is_finite() or value < 0:
        raise ValueError('Invalid transfer value')
    return format(value, 'f')

def stamp(value, milliseconds=False):
    return datetime.fromtimestamp(int(value) / (1000 if milliseconds else 1), timezone.utc).isoformat() if value else None

class History:
    def __init__(self, max_pages=3, deadline_seconds=90, max_requests=60):
        self.max_pages = max_pages
        self.deadline = time.monotonic() + deadline_seconds
        self.max_requests = max_requests
        self.requests = 0
        self.diagnostics = []
        self.cache = {}
        self.session = requests.Session()

    def close(self):
        self.session.close()

    def request(self, method, url, **kwargs):
        if time.monotonic() >= self.deadline or self.requests >= self.max_requests:
            raise ProviderError('Trace request/time budget reached; history is incomplete')
        self.requests += 1
        try:
            response = self.session.request(method, url, timeout=max(0.1, min(12, self.deadline-time.monotonic())), **kwargs)
            if response.status_code != 200:
                raise ProviderError(f'Provider HTTP {response.status_code}; check credentials, entitlement or rate limits', retryable=response.status_code == 429)
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            # Never expose a URL containing API credentials.
            raise ProviderError('Provider timed out, could not connect, or returned invalid JSON') from exc

    @contextmanager
    def record_guard(self):
        """Retain valid siblings when a provider record has an unexpected schema."""
        try:
            yield
        except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
            diag = getattr(self, '_active_diag', None)
            if diag is None:
                raise
            diag['skipped_records'] = diag.get('skipped_records', 0) + 1

    def fetch(self, wallet, chain):
        key = (chain, normalize(wallet, chain))
        if key in self.cache:
            return self.cache[key]
        wallet = key[1]
        rows = []
        if chain in ('Ethereum', 'Polygon'):
            jobs = [('Alchemy', d, lambda d=d: self.alchemy(wallet, chain, d)) for d in ('incoming', 'outgoing')]
        elif chain == 'BNB Chain':
            jobs = [('NodeReal MegaNode', d, lambda d=d: self.bnb(wallet, d)) for d in ('incoming', 'outgoing')]
        elif chain == 'Tron':
            jobs = [('TronScan', k, lambda k=k: self.tron(wallet, k)) for k in ('TRX', 'TRC20')]
        else:
            jobs = [('Mempool.space', 'UTXO', lambda: self.bitcoin(wallet))]
        for provider, category, job in jobs:
            diag = dict(wallet=wallet, blockchain=chain, provider=provider, category=category,
                        status='ok', pages=0, records=0, fetched_at=datetime.now(timezone.utc).isoformat())
            self.diagnostics.append(diag)
            self._active_diag = diag
            start_requests = self.requests
            try:
                for batch, exhausted in job():
                    rows.extend(batch)
                    diag['pages'] += 1
                    diag['records'] += len(batch)
                    diag['status'] = 'ok' if exhausted else 'truncated'
            except (ProviderError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
                diag['status'] = 'partial' if diag['pages'] else 'error'
                diag['message'] = str(exc) if isinstance(exc, ProviderError) else 'Unexpected provider response schema; history incomplete'
            if diag.get('skipped_records'):
                diag['status'] = 'partial'
                diag['message'] = 'Some provider records could not be parsed; valid records retained. History incomplete.'
            if chain == 'BNB Chain':
                diag['request_attempts'] = self.requests-start_requests
                diag['estimated_cu'] = (self.requests-start_requests)*250
                diag['scope_note'] = 'No block-range filter requested. Provider history coverage is unverified; pages are bounded.'
        unique = {}
        for row in rows:
            row['from'] = normalize(row['from'], chain)
            row['to'] = normalize(row['to'], chain)
            if wallet not in (row['from'], row['to']) and not row.get('associated'):
                continue
            unique[row['id']] = row
        self.cache[key] = list(unique.values())
        return self.cache[key]

    @staticmethod
    def transfer(txid, sender, receiver, value, asset, asset_id, timestamp, event_id, **extra):
        if not txid or not sender or not receiver:
            raise ValueError('Missing transfer identity')
        return dict(id=str(event_id), hash=txid, **{'from': sender, 'to': receiver}, value=str(value),
                    asset=str(asset)[:32], asset_id=asset_id, metadata={'blockTimestamp': timestamp}, **extra)

    def alchemy(self, wallet, chain, direction):
        key = os.getenv('ALCHEMY_API_KEY')
        if not key:
            raise ProviderError('ALCHEMY_API_KEY is not configured')
        host = 'eth-mainnet' if chain == 'Ethereum' else 'polygon-mainnet'
        params = dict(fromBlock='0x0', toBlock='latest', category=['external', 'internal', 'erc20'],
                      withMetadata=True, excludeZeroValue=True, maxCount='0x64', order='desc')
        params['toAddress' if direction == 'incoming' else 'fromAddress'] = wallet
        seen = set()
        for page in range(self.max_pages):
            doc = self.request('POST', f'https://{host}.g.alchemy.com/v2/{key}',
                json={'jsonrpc': '2.0', 'id': 1, 'method': 'alchemy_getAssetTransfers', 'params': [params]})
            if doc.get('error'):
                code = doc['error'].get('code') if isinstance(doc['error'], dict) else None
                safe_code = str(code) if isinstance(code, int) else 'unspecified'
                raise ProviderError(f'Alchemy JSON-RPC error {safe_code}; verify selected network, app network access and API key')
            result = doc['result']
            batch = []
            for i, tx in enumerate(result['transfers']):
                with self.record_guard():
                    raw = tx.get('rawContract') or {}
                    contract = (raw.get('address') or 'native').lower()
                    value = tx.get('value')
                    if raw.get('value') is not None and raw.get('decimal') is not None:
                        dec = raw['decimal']
                        dec = int(dec, 16) if isinstance(dec, str) and dec.startswith('0x') else int(dec)
                        value = amount(int(raw['value'], 16), dec)
                    if value is None or not tx.get('from') or not tx.get('to'):
                        raise ValueError('Incomplete Alchemy transfer')
                    event_id = tx.get('uniqueId')
                    if not event_id:
                        raise ValueError('Missing Alchemy event identifier')
                    batch.append(self.transfer(tx['hash'], tx['from'], tx['to'], value, tx.get('asset') or 'UNKNOWN',
                        chain+':'+contract, tx.get('metadata', {}).get('blockTimestamp'), chain+':'+event_id))
            cursor = result.get('pageKey')
            yield batch, not cursor
            if not cursor:
                break
            if cursor in seen:
                raise ProviderError('Provider repeated pagination cursor')
            seen.add(cursor)
            params['pageKey'] = cursor

    def nodereal_rpc(self, key, params):
        """At most three attempts, all paced and counted against the trace budget."""
        for attempt in range(3):
            if self.requests >= self.max_requests:
                raise ProviderError('Trace request budget reached; NodeReal history is incomplete')
            try:
                wait_for_slot(key, self.deadline)
            except (TimeoutError, OSError) as exc:
                raise ProviderError('NodeReal pacing unavailable or trace time budget reached; history incomplete') from exc
            try:
                doc = self.request('POST', f'https://bsc-mainnet.nodereal.io/v1/{key}',
                    json={'jsonrpc': '2.0', 'id': 1, 'method': 'nr_getAssetTransfers', 'params': [dict(params)]})
            except ProviderError as exc:
                if exc.retryable and attempt < 2:
                    continue
                raise
            if not isinstance(doc, dict):
                raise ProviderError('NodeReal returned an unexpected response')
            error = doc.get('error')
            if error:
                # Do not echo provider messages, which can contain credential-bearing URLs.
                if isinstance(error, dict) and str(error.get('code')) == '-32005':
                    if attempt < 2:
                        continue
                    raise ProviderError('NodeReal CUPS limit persisted after three paced attempts; retry later')
                code = error.get('code') if isinstance(error, dict) else None
                safe_code = str(code) if isinstance(code, int) else 'unspecified'
                raise ProviderError(f'NodeReal error {safe_code}; verify nr_getAssetTransfers entitlement, key and CU quota')
            result = doc.get('result')
            if not isinstance(result, dict) or not isinstance(result.get('transfers'), list):
                raise ProviderError('NodeReal response is missing the transfer list')
            return result

    def bnb(self, wallet, direction):
        key = os.getenv('NODEREAL_API_KEY', '').strip()
        if not key:
            raise ProviderError('BNB requires NODEREAL_API_KEY from your free MegaNode account')
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,256}', key):
            raise ProviderError('NODEREAL_API_KEY must contain only the key, not the full RPC URL')
        # Documented NodeReal categories differ from Alchemy: token category is "20".
        # Do not invent a recent-only block window that would hide older wallet activity.
        params = {'category': ['external', 'internal', '20'], 'order': 'desc',
                  'excludeZeroValue': True, 'maxCount': '0x64'}
        params['toAddress' if direction == 'incoming' else 'fromAddress'] = wallet
        seen_cursors, occurrences = set(), {}
        for page in range(self.max_pages):
            result = self.nodereal_rpc(key, params)
            batch = []
            for tx in result['transfers']:
                with self.record_guard():
                    category = tx.get('category')
                    if category not in ('external', 'internal', '20'):
                        raise ValueError('Unexpected NodeReal transfer category')
                    status = tx.get('receiptsStatus')
                    if status is not None and status not in (1, '1', '0x1'):
                        continue
                    token = category == '20'
                    decimals = tx.get('decimal') if token else 18
                    if decimals is None:
                        raise ValueError('Missing NodeReal token decimals')
                    decimals = int(decimals, 16) if isinstance(decimals, str) and decimals.startswith('0x') else int(decimals)
                    value = amount(int(tx['value'], 16) if isinstance(tx['value'], str) else int(tx['value']), decimals)
                    if Decimal(value) == 0:
                        continue
                    sender, receiver = tx['from'], tx['to']
                    if not sender or not receiver:
                        raise ValueError('Missing NodeReal transfer address')
                    if normalize(wallet, 'BNB Chain') != normalize(receiver if direction == 'incoming' else sender, 'BNB Chain'):
                        continue
                    contract = tx.get('contractAddress') if token else 'native'
                    if not contract:
                        raise ValueError('Missing NodeReal token contract')
                    contract = contract.lower()
                    event = next((tx[k] for k in ('uniqueId', 'logIndex', 'traceId') if tx.get(k) is not None), None)
                    if event is None:
                        fingerprint = hashlib.sha256(json.dumps([tx['hash'], category, sender.lower(), receiver.lower(), contract, value]).encode()).hexdigest()
                        ordinal = occurrences.get(fingerprint, 0)
                        occurrences[fingerprint] = ordinal+1
                        event = f'{fingerprint}:{ordinal}'
                    timestamp = tx.get('blockTimestamp', tx.get('blockTimeStamp'))
                    if isinstance(timestamp, str) and timestamp.startswith('0x'):
                        timestamp = int(timestamp, 16)
                    batch.append(self.transfer(tx['hash'], sender, receiver, value,
                        tx.get('asset') or ('UNKNOWN' if token else 'BNB'), 'BNB Chain:'+contract,
                        stamp(timestamp), f"BNB:{category}:{tx['hash']}:{event}"))
            cursor = result.get('pageKey', result.get('PageKey'))
            if cursor and cursor in seen_cursors:
                raise ProviderError('NodeReal repeated a pagination cursor; remaining history is incomplete')
            yield batch, not cursor
            if not cursor:
                break
            seen_cursors.add(cursor)
            params['pageKey'] = cursor

    def tron(self, wallet, kind):
        headers = {'Accept': 'application/json'}
        if os.getenv('TRONSCAN_API_KEY'):
            headers['TRON-PRO-API-KEY'] = os.environ['TRONSCAN_API_KEY']
        token = kind == 'TRC20'
        path = 'token_trc20/transfers' if token else 'transfer/trx'
        occurrences = {}
        for page in range(self.max_pages):
            params = {'limit': 50, 'start': page*50}
            params.update({'relatedAddress': wallet, 'confirm': '0'} if token else {'address': wallet, 'direction': 0, 'reverse': 'true'})
            doc = self.request('GET', f'https://apilist.tronscanapi.com/api/{path}', params=params, headers=headers)
            if doc.get('code') not in (None, 200):
                raise ProviderError('TronScan returned an API error')
            records = doc['token_transfers' if token else 'data']
            if not isinstance(records, list):
                raise ValueError('Missing transfer array')
            batch = []
            for i, tx in enumerate(records):
                with self.record_guard():
                    if token and (tx.get('contract_type', 'trc20') != 'trc20' or tx.get('event_type', 'Transfer') != 'Transfer'):
                        continue
                    if tx.get('finalResult', tx.get('contract_ret', 'SUCCESS')) != 'SUCCESS' or tx.get('revert', 0):
                        continue
                    if 'confirmed' not in tx:
                        raise ValueError('Missing confirmation status')
                    if tx.get('confirmed') not in (True, 1, '1'):
                        continue
                    info = tx.get('tokenInfo') or doc.get('tokenInfo') or {}
                    decimals = info.get('tokenDecimal', tx.get('decimals', 6 if not token else None))
                    if decimals is None:
                        raise ValueError('Missing token decimals')
                    value = amount(tx['quant'] if token else tx['amount'], decimals)
                    if Decimal(value) == 0:
                        continue
                    txid = tx['transaction_id'] if token else tx['hash']
                    sender, receiver = (tx['from_address'], tx['to_address']) if token else (tx['from'], tx['to'])
                    # Exact comparison: Base58Check is case sensitive.
                    if wallet not in (sender, receiver):
                        continue
                    event = tx.get('event_index', tx.get('log_index'))
                    if event is None:
                        fingerprint = hashlib.sha256(json.dumps([txid, sender, receiver, tx.get('contract_address'), value]).encode()).hexdigest()
                        ordinal = occurrences.get(fingerprint, 0)
                        occurrences[fingerprint] = ordinal + 1
                        event = f'{fingerprint}:{ordinal}'
                    batch.append(self.transfer(txid, sender, receiver, value, info.get('tokenAbbr', kind),
                        'Tron:'+(tx.get('contract_address') or info.get('tokenId') or 'native'),
                        stamp(tx.get('block_ts') if token else tx.get('block_timestamp'), True), f'Tron:{kind}:{txid}:{event}'))
            yield batch, len(records) < 50
            if len(records) < 50:
                break

    def bitcoin(self, wallet):
        suffix = ''
        for page in range(self.max_pages):
            records = self.request('GET', f'https://mempool.space/api/address/{wallet}/txs/chain{suffix}')
            if not isinstance(records, list):
                raise ValueError('Missing Bitcoin transaction array')
            batch = []
            for tx in records:
                with self.record_guard():
                    if not tx.get('status', {}).get('confirmed'):
                        continue
                    txnode = 'btc-tx:'+tx['txid']
                    timestamp = stamp(tx['status'].get('block_time'))
                    spends_wallet = any((v.get('prevout') or {}).get('scriptpubkey_address') == wallet for v in tx['vin'])
                    # Full transaction context, not an assumed pairing of input and output owners.
                    for i, vin in enumerate(tx['vin']):
                        prev = vin.get('prevout') or {}
                        sender = prev.get('scriptpubkey_address')
                        if not sender:
                            sender = 'btc-script:'+hashlib.sha256(str(prev.get('scriptpubkey', 'coinbase:'+tx['txid'])).encode()).hexdigest()
                        if vin.get('is_coinbase'):
                            continue
                        batch.append(self.transfer(tx['txid'], sender, txnode, amount(prev['value'], 8), 'BTC',
                            'Bitcoin:native', timestamp, f"BTC:{tx['txid']}:vin:{i}", utxo=True, associated=True,
                            expand_context=spends_wallet, utxo_details={'kind':'input','vin':i,'prev_txid':vin.get('txid'),
                            'prev_vout':vin.get('vout'),'value_sats':prev['value'],'fee_sats':tx.get('fee')}))
                    for i, out in enumerate(tx['vout']):
                        receiver = out.get('scriptpubkey_address') or 'btc-script:'+hashlib.sha256(str(out.get('scriptpubkey', '')).encode()).hexdigest()
                        batch.append(self.transfer(tx['txid'], txnode, receiver, amount(out['value'], 8), 'BTC',
                            'Bitcoin:native', timestamp, f"BTC:{tx['txid']}:vout:{i}", utxo=True, associated=True,
                            expand_context=spends_wallet, follow_output=spends_wallet,
                            utxo_details={'kind':'output','vout':i,'value_sats':out['value'],'fee_sats':tx.get('fee'),
                            'script_type':out.get('scriptpubkey_type')}))
            yield batch, len(records) < 25
            if len(records) < 25:
                break
            suffix = '/'+records[-1]['txid']
