"""Prepare every photo's context in a marked synthetic gallery, without answer files."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "server"))


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--data-dir", type=Path, required=True)
    result.add_argument("--env-file", type=Path)
    result.add_argument("--model-dir", type=Path)
    result.add_argument("--model")
    result.add_argument("--workers", type=int, choices=(1, 2), default=1)
    result.add_argument("--passes", type=int, choices=(1, 2, 3), default=1)
    result.add_argument("--photo-id", help="Optional source photo to prepare; never an expected related photo")
    return result


async def main(args):
    root = args.data_dir.resolve()
    marker = root / "synthetic-demo.json"
    if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")).get("synthetic") is not True:
        raise ValueError("A pre-existing marked synthetic gallery is required")
    if not (root / "gallery.sqlite").is_file():
        raise ValueError("Seed and analyze synthetic photos before preparing contexts")
    from dotenv import load_dotenv
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ValueError("Existing model configuration is required for preparation")
    if args.model_dir:
        os.environ["CG_MODEL_DIR"] = str(args.model_dir.resolve())
    os.environ["CG_AUTO_ORGANIZE"] = "0"
    os.environ["CG_ANALYSIS_CONCURRENCY"] = str(args.workers)
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

    from connected_gallery.application.demo_profile import prepare_demo_profile
    prepare_demo_profile(root, args.model)
    from connected_gallery.adapters.store import Store
    from connected_gallery.adapters.models import LocalModels
    from connected_gallery.adapters.proxy import ProxyGateway
    from connected_gallery.agent_runtime.runner import GraphAgentRunner
    from connected_gallery.application.service import RunService
    from connected_gallery.domain.context import CONTEXT_SPEC, CONTEXT_POLICY
    from connected_gallery.domain.models import RunRequest

    store = Store(root)
    service = None
    try:
        photos = store.photos()
        if not photos or any(p.device_id != "synthetic-demo" for p in photos):
            raise ValueError("Only synthetic demo photos can be prepared with this command")
        if any(store.analysis(p.id) is None for p in photos):
            raise ValueError("Every source photo must be analyzed first")
        if args.photo_id and args.photo_id not in {p.id for p in photos}:
            raise ValueError("Unknown source photo")
        models = LocalModels(root)
        gateway = ProxyGateway(attempt_timeout=45, repeat_primary=False)
        service = RunService(store, GraphAgentRunner(store, models, gateway))
        service.auto_enabled = False
        service.interactive = asyncio.Semaphore(args.workers)
        service.background = asyncio.Semaphore(args.workers)
        revision = store.revision
        report_path = root / "context-preparation-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"attempts": []}
        report.update(revision=revision, context_spec=CONTEXT_SPEC, context_policy=CONTEXT_POLICY,
                      model=gateway.primary, workers=args.workers, synthetic=True)

        def save():
            states = {p.id: service.context_ready(p.id)["state"] for p in store.photos()}
            report["states"] = states
            report["counts"] = {name: sum(s == name for s in states.values())
                                for name in ("ready", "empty", "pending", "running", "failed")}
            tmp = report_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(report_path)

        for pass_index in range(1, args.passes + 1):
            queue = asyncio.Queue()
            for photo in photos:
                if (not args.photo_id or args.photo_id == photo.id) and service.context_ready(photo.id)["state"] not in ("ready", "empty"):
                    queue.put_nowait(photo.id)

            async def worker():
                while not queue.empty():
                    try:
                        photo_id = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    if store.revision != revision:
                        raise ValueError("Gallery changed; stop and prepare the new snapshot")
                    started = time.monotonic()
                    created = service.start(RunRequest(role="context", photo_ids=[photo_id]))
                    while service.get(created["id"])["status"] in ("queued", "running"):
                        await asyncio.sleep(.5)
                    run = service.get(created["id"])
                    envelope = service.context_ready(photo_id)
                    context = envelope.get("context") or {}
                    record = {"photo_id": photo_id, "run_id": created["id"], "pass": pass_index,
                              "status": run["status"], "state": envelope["state"],
                              "seconds": round(time.monotonic() - started, 3),
                              "groups": len(context.get("groups", [])),
                              "members": len({pid for g in context.get("groups", []) for pid in g["photo_ids"]}),
                              "revision": revision, "context_spec": CONTEXT_SPEC}
                    report["attempts"].append(record)
                    save()
                    print(json.dumps({"stage": "context", **record}, ensure_ascii=False), flush=True)
                    queue.task_done()

            workers = [asyncio.create_task(worker()) for _ in range(args.workers)]
            try:
                await asyncio.gather(*workers)
            finally:
                for task in workers:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
            save()
        print(json.dumps({"stage": "summary", "revision": revision, **report["counts"]}), flush=True)
        # A nonzero result means real remaining work, never fabricate successful empty contexts.
        return 0 if not any(report["counts"][s] for s in ("pending", "running", "failed")) else 2
    finally:
        if service is not None:
            await service.stop(preserve_pending=True)
        store.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(parser().parse_args())))
