"""Verify immutable anchor and enforced year constraints through the real API."""
import json
import argparse
import sqlite3
import time
import urllib.request
from pc_client import urlopen
from pathlib import Path
from uuid import uuid4


def api(path, payload=None):
    request = urllib.request.Request('http://127.0.0.1:8765' + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--direction', choices=['all', 'related', 'same_moment'], default='all')
    parser.add_argument('--report', default='docs/modifier-api-benchmark.json')
    args = parser.parse_args()
    deadline = api('/health').get('explore_timeout_seconds', 45) + 20
    prior = json.loads(Path('work/connect-check-private.json').read_text(encoding='utf-8'))
    anchor = prior[0]['anchor']
    years = api('/manifest')['years']
    selected_year = min(years)
    results = []
    for revision, (direction, year) in enumerate([('related', selected_year), ('same_moment', None)], 10):
        if args.direction != 'all' and args.direction != direction:
            continue
        start = time.monotonic()
        run = api('/runs', {'role': 'explorer', 'explore': {'anchor': anchor,
              'direction': direction, 'year': year, 'request_revision': revision},
              'idempotency_key': 'modifier-check-' + str(uuid4())})
        rid = run['id']
        while run['status'] in ('queued', 'running'):
            if time.monotonic() - start > deadline:
                api(f'/runs/{rid}/cancel', {})
                run = api(f'/runs/{rid}')
                break
            time.sleep(0.5)
            run = api(f'/runs/{rid}')
        db = sqlite3.connect('file:.runtime/gallery.sqlite?mode=ro', uri=True)
        stored = json.loads(db.execute('SELECT request FROM runs WHERE id=?', (rid,)).fetchone()[0])
        items = (run.get('result') or {}).get('items', [])
        result_years = [db.execute('SELECT year FROM photos WHERE id=?', (x['photo_id'],)).fetchone()[0] for x in items]
        db.close()
        row = {'direction': direction, 'year': year, 'status': run['status'],
               'seconds': round(time.monotonic()-start, 2), 'result_count': len(items),
               'anchor_preserved': stored['explore']['anchor'] == anchor,
               'year_constraint_met': year is None or all(y == year for y in result_years),
               'error': run.get('error')}
        results.append(row)
        print(json.dumps(row), flush=True)
    Path(args.report).write_text(json.dumps({
        'scope': 'PC API; Android scrubber/back-stack still requires unlocked-device validation',
        'results': results}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
