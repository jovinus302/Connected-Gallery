"""Repair representations of already analyzed photos; no new semantic analysis."""
import json
import urllib.request
import urllib.error
from pathlib import Path


def api(path, post=False):
    request = urllib.request.Request('http://127.0.0.1:8765' + path,
                                     data=b'{}' if post else None,
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    initial = api('/progress')
    missing = initial['missing_index_ids']
    added = 0
    failures = []
    for index, pid in enumerate(missing):
        try:
            added += api(f'/assets/{pid}/reindex', post=True)['indexes_added']
        except Exception as exc:
            failures.append({'item': index + 1, 'error': type(exc).__name__})
        if (index + 1) % 10 == 0:
            print(json.dumps({'checked': index + 1, 'total': len(missing)}), flush=True)
    final = api('/progress')
    report = {'initial_missing_index_photos': len(missing), 'indexes_added': added,
              'failures': failures, 'remaining_missing_index_photos': len(final['missing_index_ids']),
              'photo_count': final['photo_count'], 'analyzed_count': final['analyzed_count'],
              'ready_count': final['ready_count']}
    Path('docs/index-repair-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
