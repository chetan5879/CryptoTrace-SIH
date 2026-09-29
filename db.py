import os
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
load_dotenv()

@contextmanager
def db():
    url = os.getenv('DATABASE_URL')
    if not url:
        raise RuntimeError('DATABASE_URL must be set; no default database credentials are provided')
    conn = psycopg2.connect(url, connect_timeout=5, options='-c statement_timeout=15000')
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur
    finally:
        conn.close()

def init_db():
    from pathlib import Path
    with db() as cur:
        cur.execute(Path(__file__).with_name('schema.sql').read_text())

def audit(cur, user_id, action, request=None, detail=None):
    from psycopg2.extras import Json
    ip = request.client.host if request and request.client else 'local-cli'
    agent = request.headers.get('user-agent', '')[:512] if request else 'local-cli'
    cur.execute('INSERT INTO ct_audit(user_id,action,ip,user_agent,detail) VALUES (%s,%s,%s,%s,%s)',
                (user_id, action, ip, agent, Json(detail or {})))
