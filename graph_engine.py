"""Observed transfer relationships; scores are triage indicators, not proof of crime."""
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from ingestion import History, normalize


def trace_fund_flow(address, max_hops=2, fan_threshold=5, blockchain='Ethereum', entity_lookup=None, history=None):
    address = normalize(address, blockchain)
    owned_history = history is None
    history = history or History()
    lookup = entity_lookup or (lambda address, chain: {})
    nodes, edges, seen_edges, expanded = {}, [], set(), set()
    queue = deque([(address, 0)])
    truncations = []
    entities = {}
    def add_node(wallet, hop):
        if wallet not in nodes:
            entity = {} if wallet.startswith(('btc-tx:', 'btc-script:')) else lookup(wallet, blockchain)
            entities[wallet] = entity
            nodes[wallet] = dict(id=wallet, hop=hop, type='reported_wallet' if wallet == address else
                ('transaction' if wallet.startswith('btc-tx:') else ('mixer' if entity.get('is_mixer') else 'exchange' if entity.get('is_vasp') else 'script' if wallet.startswith('btc-script:') else 'wallet')),
                entity_name=entity.get('name'), entity_source=entity.get('source'),
                attribution_status=entity.get('attribution_status','analyst_reviewed' if entity else 'unknown'),
                attribution_evidence=entity.get('evidence_sources',[]),
                attribution_source_date=entity.get('source_date'),
                is_vasp=bool(entity.get('is_vasp')), is_mixer=bool(entity.get('is_mixer')),
                is_sanctioned=bool(entity.get('is_sanctioned')),
                entity_updated_at=str(entity.get('updated_at') or ''), risk_score=None, risk_reasons=[], flags=[])
        nodes[wallet]['hop'] = min(hop, nodes[wallet]['hop'])
    add_node(address, 0)
    try:
        while queue:
            wallet, depth = queue.popleft()
            if wallet in expanded or depth >= max_hops:
                continue
            if len(expanded) >= 25:
                truncations.append({'wallet': wallet, 'reason': '25 expanded wallets limit'})
                continue
            expanded.add(wallet)
            transfers = history.fetch(wallet, blockchain)
            # At the origin show both directions. Downstream show all observed outgoing transfers,
            # without hiding transactions behind amount-ratio heuristics.
            selected = transfers if depth == 0 else [t for t in transfers if t['from'] == wallet or t.get('expand_context', t.get('associated', False))]
            fanin = {t['from'] for t in transfers if t['to'] == wallet and t['from'] != wallet}
            fanout = {t['to'] for t in transfers if t['from'] == wallet and t['to'] != wallet}
            nodes[wallet].update(fan_in_count=len(fanin), fan_out_count=len(fanout), observed=True)
            for tx in selected:
                if tx['id'] in seen_edges:
                    continue
                unseen = set((tx['from'], tx['to'])) - set(nodes)
                if len(nodes) + len(unseen) > 500 or len(edges) >= 2000:
                    truncations.append({'wallet': wallet, 'reason': 'graph node/edge limit'})
                    break
                seen_edges.add(tx['id'])
                add_node(tx['from'], depth + 1)
                add_node(tx['to'], depth + 1)
                edges.append(dict(id=tx['id'], **{'from':tx['from'], 'to':tx['to']}, tx_hash=tx['hash'],
                    asset=tx['asset'], asset_id=tx['asset_id'], amount=tx['value'],
                    timestamp=tx['metadata'].get('blockTimestamp'), hop=depth+1,
                    relationship='utxo_transaction' if tx.get('utxo') else 'observed_transfer', rapid_movement=False, utxo_details=tx.get('utxo_details')))
                target = tx['to']
                if (tx['from'] == wallet or tx.get('follow_output', tx.get('associated', False))) and target != address and not target.startswith(('btc-tx:', 'btc-script:')):
                    queue.append((target, depth+1))
        for wallet, node in nodes.items():
            entity = entities[wallet]
            reasons = node['risk_reasons']
            if wallet == address:
                reasons.append('Reported address; allegation requires corroboration')
            if entity:
                reasons.append(('External unreviewed attribution: ' if entity.get('attribution_status')=='external_unreviewed' else 'Analyst attribution: ')+entity['name']+'; source: '+entity.get('source', 'unspecified'))
                if entity.get('attribution_status')=='external_unreviewed':
                    reasons.append('Source date: '+entity.get('source_date','unspecified')+'; retrieved: '+entity.get('fetched_at','unspecified')+'; current control unverified')
            if entity.get('is_vasp'):
                reasons.append('Exchange attribution does not establish innocence or ownership')
            if wallet.startswith(('btc-tx:', 'btc-script:')):
                reasons.append('UTXO transaction node; outputs are not attributed to a single input owner')
                continue
            observations = [d for d in history.diagnostics if d['wallet'] == wallet]
            complete = bool(observations) and all(d['status'] == 'ok' for d in observations)
            node['coverage'] = 'provider_window_exhausted' if complete else ('partial' if observations else 'not_expanded')
            score = 0
            if entity.get('is_mixer') and entity.get('attribution_status')!='external_unreviewed':
                score += 60
                reasons.append('Analyst-labelled mixer; verify source and date')
            if entity.get('is_sanctioned'):
                score = 99
                reasons.append('Analyst-labelled sanctions match; verify current designation')
            for field, label in [('fan_in_count','High fan-in'), ('fan_out_count','High fan-out')]:
                if node.get(field, 0) >= fan_threshold:
                    score += 25
                    reasons.append(label+' in retrieved sample (+25)')
            incoming = [e for e in edges if e['to'] == wallet]
            outgoing = [e for e in edges if e['from'] == wallet]
            rapid = False
            for out in outgoing:
                for inc in incoming:
                    if out['asset_id'] != inc['asset_id'] or not out['timestamp'] or not inc['timestamp']:
                        continue
                    try:
                        seconds = (datetime.fromisoformat(out['timestamp'].replace('Z','+00:00')) - datetime.fromisoformat(inc['timestamp'].replace('Z','+00:00'))).total_seconds()
                    except ValueError:
                        continue
                    if 0 <= seconds < 86400:
                        out['rapid_movement'] = True
                        rapid = True
                        break
            if rapid:
                score += 20
                reasons.append('Same-asset receive/send within 24h (+20); fund continuity unproven')
            node['risk_score'] = min(score, 100) if (complete or score > 0) else None
            if not complete:
                reasons.append('Incomplete or unexpanded history; absence of flags is not a clean result')
            node['flags'] = list(reasons)
        # Exact output-spend references are linked only when both transactions were retrieved.
        outputs = {(e['tx_hash'], e['utxo_details']['vout']): e for e in edges
                   if e.get('utxo_details') and e['utxo_details']['kind'] == 'output'}
        for edge in edges:
            detail = edge.get('utxo_details') or {}
            parent = outputs.get((detail.get('prev_txid'), detail.get('prev_vout')))
            if detail.get('kind') == 'input' and parent:
                parent['utxo_details']['spent_by_txid'] = edge['tx_hash']
                parent['utxo_details']['spent_by_vin'] = detail['vin']
                detail['funding_event_id'] = parent['id']
        diagnostics = history.diagnostics
        bad = any(d['status'] != 'ok' for d in diagnostics) or bool(truncations)
        status = 'partial' if bad else ('no_transfers_found' if not edges else 'observed')
        if diagnostics and all(d['status'] == 'error' for d in diagnostics) and not edges:
            status = 'unavailable'
        scores = [n['risk_score'] for n in nodes.values() if n['risk_score'] is not None]
        return dict(wallet_address=address, blockchain=blockchain, max_hops=max_hops, fan_threshold=fan_threshold,
            node_count=len(nodes), edge_count=len(edges), nodes=list(nodes.values()), edges=edges,
            risk_score=max(scores) if scores else None, status=status, diagnostics=diagnostics,
            truncated_wallets=truncations, fetched_at=datetime.now(timezone.utc).isoformat(),
            coverage_note='Bounded provider history, confirmed supported assets only. No transfers found does not prove no historical activity. '
                'Downstream expansion follows outgoing relationships and does not prove the same funds moved. '
                'NFTs, bridges and Tron internal/TRC10 transfers are not covered. Bitcoin uses UTXO transaction nodes.',
            scoring_version='transparent-triage-v2; unvalidated; ML disabled pending evaluation')
    finally:
        if owned_history:
            history.close()
