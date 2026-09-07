"""Queue one recovery attempt per photo/version and deployed agent revision.

Reads the local journal; all mutations go through the running server API. Active
or already analyzed photos are skipped, including jobs queued by Android.
"""
import hashlib
import json
import sqlite3
import urllib.request
from pc_client import urlopen


def main():
    with urlopen('http://127.0.0.1:8765/health', timeout=10) as response:
        spec = json.load(response).get('agent_spec', 0)
        if spec < 2:
            raise RuntimeError('Start the repaired server first')
    db = sqlite3.connect('file:.runtime/gallery.sqlite?mode=ro', uri=True)
    active = {pid for (raw,) in db.execute("SELECT request FROM runs WHERE status IN ('queued','running')")
              for pid in json.loads(raw).get('photo_ids', [])}
    pending = set()
    for (raw,) in db.execute("SELECT request FROM runs WHERE status IN ('failed','incomplete')"):
        request = json.loads(raw)
        if request['role'] == 'analyst':
            pending.update(request['photo_ids'])
    queued = 0
    for pid in sorted(pending - active):
        photo = db.execute('SELECT version FROM photos WHERE id=?', (pid,)).fetchone()
        if not photo or db.execute('SELECT 1 FROM analyses WHERE photo_id=?', (pid,)).fetchone():
            continue
        key = f'recovery-v{spec}-' + hashlib.sha256((pid + ':' + photo[0]).encode()).hexdigest()
        if db.execute('SELECT 1 FROM runs WHERE key=?', (key,)).fetchone():
            continue
        body = json.dumps({'role': 'analyst', 'photo_ids': [pid], 'idempotency_key': key}).encode()
        req = urllib.request.Request('http://127.0.0.1:8765/runs', data=body,
                                     headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=10) as response:
            json.load(response)
        queued += 1
    db.close()
    print(json.dumps({'recovery_jobs_queued': queued}))


if __name__ == '__main__':
    main()
