"""Verify simultaneous first use of lazy vision dependencies on a synthetic card."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image, ImageDraw
from connected_gallery.adapters.models import LocalModels


def main():
    models = LocalModels(Path('.runtime'))
    photo = Image.new('RGB', (512, 256), 'white')
    ImageDraw.Draw(photo).text((40, 80), 'WINE 2020', fill='black', font_size=32)
    calls = {'image': lambda: models.image(photo), 'text': lambda: models.text('테스트 안내문'),
             'ocr': lambda: models.ocr(photo), 'ground': lambda: models.ground(photo, 'text. sign.')}
    def run(item):
        name, fn = item
        start = time.monotonic()
        try:
            fn()
            return {'name': name, 'status': 'ok', 'seconds': round(time.monotonic()-start, 2)}
        except Exception as exc:
            return {'name': name, 'status': 'failed', 'error': type(exc).__name__}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, calls.items()))
    report = {'synthetic': True, 'concurrent_cold_calls': 4, 'results': results}
    Path('docs/model-startup-smoke.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
    if any(r['status'] != 'ok' for r in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
