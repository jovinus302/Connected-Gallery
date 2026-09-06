"""Exercise three API hops using real, already analyzed photos.

This checks the PC integration; it does not replace Android UI acceptance.
Only aggregate measurements are written to docs/; IDs stay in work/.
"""
import json
import sqlite3
import time
import urllib.request
from pathlib import Path
from uuid import uuid4


def api(path, payload=None):
    request = urllib.request.Request('http://127.0.0.1:8765' + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def main():
    db = sqlite3.connect('file:.runtime/gallery.sqlite?mode=ro', uri=True)
    analyses = {a['photo_id']: a for (raw,) in db.execute('SELECT data FROM analyses')
                for a in [json.loads(raw)]}
    db.close()
    first = next((a for a in analyses.values() if any(r['kind'] == 'object' for r in a['regions'])), None)
    if first is None:
        raise RuntimeError('No analyzed object region available')
    current = first
    visited = {current['photo_id']}
    report, private = [], []
    for hop in range(1, 4):
        region = next((r for r in current['regions'] if r['kind'] == 'object'), current['regions'][0])
        anchor = {k: region[k] for k in ('photo_id', 'box', 'label', 'kind')}
        anchor['region_id'] = region['id']
        started = time.monotonic()
        run = api('/runs', {'role': 'explorer', 'explore': {
            'anchor': anchor, 'direction': 'related', 'year': None, 'request_revision': hop,
        }, 'idempotency_key': 'api-check-' + str(uuid4())})
        rid = run['id']
        first_seconds = None
        cursor = 0
        while run['status'] in ('queued', 'running'):
            events = api(f'/runs/{rid}/events?after={cursor}')
            cursor = events['cursor']
            if first_seconds is None and any(e['kind'] == 'results' for e in events['events']):
                first_seconds = round(time.monotonic() - started, 2)
            if time.monotonic() - started > 65:
                api(f'/runs/{rid}/cancel', {})
                run = api(f'/runs/{rid}')
                break
            time.sleep(0.5)
            run = api(f'/runs/{rid}')
        result = run.get('result') or {}
        items = result.get('items', [])
        elapsed = round(time.monotonic() - started, 2)
        if first_seconds is None and run.get('result') is not None:
            first_seconds = elapsed  # First observed through the final-state poll.
        row = {'hop': hop, 'status': run['status'], 'result_count': len(items),
               'first_result_seconds': first_seconds,
               'total_seconds': elapsed, 'error': run.get('error')}
        report.append(row)
        private.append({'run_id': rid, 'anchor': anchor, 'result': result})
        print(json.dumps(row), flush=True)
        candidates = [x['photo_id'] for x in items if x['photo_id'] not in visited]
        next_photo = None
        for pid in candidates:
            analysis = api(f'/assets/{pid}/analysis')
            if analysis.get('regions'):
                next_photo = analysis
                break
        if next_photo is None:
            break
        current = next_photo
        visited.add(current['photo_id'])
    Path('work/connect-check-private.json').write_text(json.dumps(private, ensure_ascii=False), encoding='utf-8')
    Path('docs/connect-api-benchmark.json').write_text(json.dumps({
        'scope': 'PC API only; Android UI acceptance still required',
        'library_analysis_in_progress': True, 'hops': report,
    }, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
