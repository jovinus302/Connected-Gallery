"""Run the synthetic gallery only on loopback, with a one-use local browser login.

Use the same Python environment/PYTHONPATH as prepare-demo.py. This foreground
process stops with Ctrl+C; callers launching it in the background should capture
the process ID and hide its window. It never starts a tunnel or reads private DBs.
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import secrets
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "server"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(PROJECT / ".runtime" / "demo"))
    parser.add_argument("--env-file", help="Read model settings only; never reuse production server credentials")
    parser.add_argument("--model-dir")
    parser.add_argument("--port", default=8877, type=int)
    parser.add_argument("--prepared-only", action="store_true", help="Read prepared results without recovering, creating or cancelling runs")
    args = parser.parse_args()
    root = Path(args.data_dir).resolve()
    marker = root / "synthetic-demo.json"
    if not marker.exists() or json.loads(marker.read_text(encoding="utf-8")).get("synthetic") is not True:
        raise SystemExit("Prepare a separate synthetic gallery with prepare-demo.py first")
    if not (root / "gallery.sqlite").is_file():
        raise SystemExit("Synthetic gallery has not been seeded")
    if args.env_file:
        from dotenv import dotenv_values
        values = dotenv_values(args.env_file)
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CG_MODEL", "CG_FALLBACK_MODEL"):
            if values.get(key):
                os.environ[key] = values[key]
    from connected_gallery.application.demo_profile import apply_demo_model
    apply_demo_model(root)
    if args.model_dir:
        os.environ["CG_MODEL_DIR"] = str(Path(args.model_dir).resolve())
    os.environ["CG_DATA_DIR"] = str(root)
    os.environ["CG_AUTO_ORGANIZE"] = "0"
    os.environ["CG_ANALYSIS_CONCURRENCY"] = "1"
    os.environ.pop("CG_SERVER_TOKEN", None)
    from connected_gallery.bootstrap.auth import server_token
    # Pin the synthetic gallery token before create_app's ordinary dotenv load.
    os.environ["CG_SERVER_TOKEN"] = server_token(root)
    from connected_gallery.bootstrap.demo import DemoSession
    from connected_gallery.bootstrap.api import create_app
    import uvicorn

    launch_key = secrets.token_urlsafe(32)
    session = DemoSession(launch_key, args.port, live_enabled=not args.prepared_only)
    app = create_app(root, demo=session, recover_runs=not args.prepared_only)
    app.state.service.auto_enabled = False
    launch_path = root / "demo-launch.html"
    # This local-only file is deliberately outside version control. The one-use
    # key is submitted in a POST body, never a URL, frontend bundle or log.
    launch_path.write_text(
        '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="referrer" content="no-referrer">'
        '<title>Connected Gallery 로컬 데모</title><body style="font-family:system-ui;padding:60px">'
        '<h1>Connected Gallery</h1><p>이 PC의 가상 사진 갤러리를 엽니다.</p>'
        f'<form id="launch" method="post" action="{session.origin}/demo/session">'
        f'<input type="hidden" name="key" value="{html.escape(launch_key, quote=True)}">'
        '<button type="submit">데모 열기</button></form>'
        '<p>시작 키는 한 번만 사용할 수 있습니다. 연결 후에는 이 파일을 닫아도 됩니다.</p>'
        '<script>document.getElementById("launch").submit()</script></body></html>', encoding="utf-8")
    (root / "demo-launch-key.txt").write_text(launch_key, encoding="utf-8")
    (root / "demo-process.json").write_text(json.dumps({"pid": os.getpid(), "origin": session.origin}), encoding="utf-8")
    print("Local demo: " + session.origin + "/demo", flush=True)
    print("Open this local file after startup: " + str(launch_path), flush=True)
    print("Alternative one-use key is in: " + str(root / "demo-launch-key.txt"), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
