"""Linux single-host limiter shared by threads and Uvicorn workers for one API key.
All processes must use the same directory. Separate hosts/containers need a shared
limiter; other applications using the same key are outside this limiter's scope.
"""
import fcntl
import hashlib
import os
from pathlib import Path
import tempfile
import time

INTERVAL_SECONDS = 1.1  # Conservative: one 250-CU history call per second, with margin.

def wait_for_slot(key, deadline):
    directory = Path(os.getenv('NODEREAL_RATE_DIR', str(Path(tempfile.gettempdir()) / f'cryptotrace-rates-{os.getuid()}')))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = directory / (hashlib.sha256(key.encode()).hexdigest()+'.lock')
    fd = os.open(filename, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('NodeReal rate-limit queue exceeded trace time budget')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(min(.05, remaining))
        try:
            raw = lock.read().strip()
            last = float(raw) if raw else 0
            now = time.monotonic()
            # Future monotonic timestamps can remain after a host reboot; reset them.
            delay = max(0, last+INTERVAL_SECONDS-now) if last <= now else 0
            if now+delay >= deadline:
                raise TimeoutError('NodeReal rate-limit queue exceeded trace time budget')
            if delay:
                time.sleep(delay)
            lock.seek(0)
            lock.truncate()
            lock.write(str(time.monotonic()))
            lock.flush()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
