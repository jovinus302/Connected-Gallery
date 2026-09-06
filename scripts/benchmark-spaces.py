"""Test Organizer on an isolated subset of already analyzed real photos."""
import argparse
import asyncio
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4
from dotenv import load_dotenv
from connected_gallery.adapters.store import Store
from connected_gallery.adapters.models import LocalModels
from connected_gallery.adapters.proxy import ProxyGateway
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.domain.models import PhotoAsset, PhotoAnalysis, RunRequest


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        raise ValueError('limit must be between 1 and 1000')
    load_dotenv()
    source = sqlite3.connect('file:.runtime/gallery.sqlite?mode=ro', uri=True)
    store = Store(Path('work') / ('spaces-check-' + str(uuid4())))
    rows = source.execute('SELECT p.data,a.data FROM photos p JOIN analyses a ON a.photo_id=p.id ORDER BY p.id LIMIT ?', (args.limit,)).fetchall()
    for raw_asset, raw_analysis in rows:
        asset = PhotoAsset.model_validate_json(raw_asset)
        store.upsert(asset)
        image = Path('.runtime/images') / (hashlib.sha256(asset.id.encode()).hexdigest() + '.jpg')
        store.put_image(asset.id, image.read_bytes())
        store.save_analysis(PhotoAnalysis.model_validate_json(raw_analysis))
        for vector in source.execute('SELECT * FROM vectors WHERE photo_id=?', (asset.id,)):
            store.write('INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)', vector)
    source.close()
    rid = str(uuid4())
    start = time.monotonic()
    report = {'scope': 'isolated analyzed subset; not the final 1000-photo Spaces run', 'photos': len(rows)}
    try:
        runner = GraphAgentRunner(store, LocalModels(Path('.runtime')), ProxyGateway())
        result = await asyncio.wait_for(runner.execute(rid, RunRequest(role='organizer')), 600)
        report.update(status='completed', spaces=len(result['spaces']),
                      unique_members=len({x['photo_id'] for s in result['spaces'] for x in s['items']}))
    except Exception as exc:
        report.update(status='failed', error=type(exc).__name__)
    report['seconds'] = round(time.monotonic() - start, 2)
    report['model_turns'] = len(store.rows("SELECT seq FROM events WHERE run_id=? AND kind='model_timing'", (rid,)))
    report['tool_errors'] = [json.loads(r['data']).get('error') for r in store.rows("SELECT data FROM events WHERE run_id=? AND kind='tool_error'", (rid,))]
    Path('docs/spaces-subset-benchmark.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
    store.close()


asyncio.run(main())
