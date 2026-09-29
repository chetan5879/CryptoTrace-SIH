import hashlib
import os
import secrets
from datetime import datetime, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException, Request
from db import db, audit

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
COOKIE = 'ct_session'

def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def origin_check(request):
    origin = request.headers.get('origin')
    expected = os.getenv('APP_ORIGIN', 'http://127.0.0.1:8000').rstrip('/')
    if origin != expected:
        raise HTTPException(403, 'Untrusted or missing request origin')

def require_user(request: Request):
    token = request.cookies.get(COOKIE, '')
    if len(token) < 32 or len(token) > 128:
        raise HTTPException(401, 'Sign in required')
    with db() as cur:
        cur.execute('''SELECT u.id,u.username,u.role,s.csrf,s.token_hash FROM ct_sessions s
                       JOIN ct_users u ON u.id=s.user_id WHERE s.token_hash=%s AND u.active
                       AND s.expires_at>now() AND s.last_seen>now()-interval '30 minutes' ''', (digest(token),))
        user = cur.fetchone()
        if not user:
            raise HTTPException(401, 'Session expired; sign in again')
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin_check(request)
            if not secrets.compare_digest(request.headers.get('x-csrf-token',''), user['csrf']):
                raise HTTPException(403, 'Invalid CSRF token')
        cur.execute('UPDATE ct_sessions SET last_seen=now() WHERE token_hash=%s', (user['token_hash'],))
    return dict(user)

def require_admin(request: Request):
    user = require_user(request)
    if user['role'] != 'admin':
        raise HTTPException(403, 'Administrator access required')
    return user

def check_password(password, encoded):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False

def visible_case(cur, case_id, user):
    cur.execute('SELECT * FROM ct_cases WHERE case_id=%s AND (owner_id=%s OR %s)',
                (case_id,user['id'],user['role']=='admin'))
    case = cur.fetchone()
    if not case:
        raise HTTPException(404, 'Case not found')
    return dict(case)
