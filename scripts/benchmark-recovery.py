"""Re-analyze previously failed, already authorized photos in an isolated store.

Only aggregate timings leave work/. Images and semantic content stay local or are
sent to the user's configured proxy, exactly as in normal analysis.
"""
import asyncio
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv
from connected_gallery.adapters.store import Store
from connected_gallery.adapters.models import LocalModels
from connected_gallery.adapters.proxy import ProxyGateway
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.domain.models import PhotoAsset, RunRequest, new_id


async def main():
    load_dotenv()
    source = Path('.runtime')
    db = sqlite3.connect('file:.runtime/gallery.sqlite?mode=ro', uri=True)
    ids = []
    for (raw,) in db.execute("SELECT request FROM runs WHERE status='failed' ORDER BY started"):
        request = json.loads(raw)
        if request['role'] == 'analyst':
            pid = request['photo_ids'][0]
            if pid not in ids:
                ids.append(pid)
        if len(ids) == 6:
            break
    if not ids:
        raise RuntimeError('No previously failed photos to evaluate')
    target = Store(Path('work') / ('recovery-check-' + new_id()))
    for pid in ids:
        asset = PhotoAsset.model_validate_json(db.execute('SELECT data FROM photos WHERE id=?', (pid,)).fetchone()[0])
        target.upsert(asset)
        image_path = source / 'images' / (hashlib.sha256(pid.encode()).hexdigest() + '.jpg')
        target.put_image(pid, image_path.read_bytes())
    db.close()
    models = LocalModels(source)
    runner = GraphAgentRunner(target, models, ProxyGateway())
    semaphore = asyncio.Semaphore(3)
    rows = []

    async def analyze(index, pid):
        async with semaphore:
            rid = new_id()
            started = time.monotonic()
            row = {'sample': index + 1}
            try:
                result = await asyncio.wait_for(runner.execute(rid, RunRequest(role='analyst', photo_ids=[pid])), 180)
                row.update(status='completed', regions=len(result['regions']))
            except Exception as exc:
                row.update(status='failed', error=type(exc).__name__)
            row['seconds'] = round(time.monotonic() - started, 2)
            row['model_turns'] = len(target.rows("SELECT seq FROM events WHERE run_id=? AND kind='model_timing'", (rid,)))
            row['tool_timings'] = [json.loads(r['data']) for r in target.rows("SELECT data FROM events WHERE run_id=? AND kind='tool_timing'", (rid,))]
            rows.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != 'tool_timings'}), flush=True)

    start = time.monotonic()
    await asyncio.gather(*(analyze(i, pid) for i, pid in enumerate(ids)))
    import torch
    report = {'sample_selection': 'first six distinct previously failed actual photos',
              'concurrency': 3, 'cold_start_included': True, 'torch': torch.__version__,
              'device': torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU',
              'wall_seconds': round(time.monotonic() - start, 2),
              'completed': sum(r['status'] == 'completed' for r in rows),
              'total': len(rows), 'samples': sorted(rows, key=lambda r: r['sample'])}
    Path('docs/recovery-benchmark.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    target.close()


asyncio.run(main())
