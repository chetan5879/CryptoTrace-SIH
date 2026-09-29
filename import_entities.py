"""Reviewed JSON import and read-only legacy export. Run as the database administrator."""
import argparse
import json
from pathlib import Path
from db import db, audit
from main import EntityModel
from ingestion import validate_address


def validate_rows(rows):
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError('Expected a JSON array of at most 10000 sourced attributions')
    result = []
    seen = set()
    for raw in rows:
        row = EntityModel.model_validate(raw).model_dump()
        row['wallet_address'] = validate_address(row['wallet_address'], row['blockchain'])
        key = (row['blockchain'], row['wallet_address'])
        if key in seen:
            raise ValueError('Duplicate chain/address in import')
        seen.add(key)
        result.append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', help='JSON input or legacy export output')
    parser.add_argument('--export-legacy', action='store_true')
    parser.add_argument('--apply', action='store_true', help='Default is validation only')
    parser.add_argument('--admin', help='Existing active administrator username for audit')
    args = parser.parse_args()
    if args.export_legacy:
        with db() as cur:
            cur.execute('SELECT wallet_address,name,is_vasp,is_mixer FROM known_entities ORDER BY wallet_address')
            rows = [{**dict(r), 'blockchain':'', 'source':'', 'is_sanctioned':False} for r in cur.fetchall()]
        with Path(args.file).open('x') as stream:
            json.dump(rows, stream, indent=2)
        print('Exported review candidates. Fill network/source and restore original Base58 casing from a trusted source before import.')
        return
    rows = validate_rows(json.loads(Path(args.file).read_text()))
    if not args.apply:
        print(f'Validated {len(rows)} rows; no database changes. Review sources, then use --apply --admin USER.')
        return
    if not args.admin:
        parser.error('--apply requires --admin')
    with db() as cur:
        cur.execute("SELECT id FROM ct_users WHERE username=%s AND active=TRUE AND role='admin'", (args.admin.lower(),))
        user = cur.fetchone()
        if not user:
            raise SystemExit('Active administrator not found')
        for row in rows:
            # Preserve existing analyst decisions; edit existing labels explicitly through the UI.
            cur.execute('''INSERT INTO ct_entities(blockchain,wallet_address,name,source,is_vasp,is_mixer,is_sanctioned,updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                tuple(row[k] for k in ['blockchain','wallet_address','name','source','is_vasp','is_mixer','is_sanctioned'])+(user['id'],))
            if cur.rowcount:
                audit(cur,user['id'],'entity_imported',detail=row)
    print('Import complete. Existing labels preserved. Run a new trace to apply labels.')

if __name__ == '__main__':
    main()
