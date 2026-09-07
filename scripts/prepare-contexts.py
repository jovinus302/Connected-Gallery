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
    result.add_argument("--context-model", help="Optional context writer model; preserves the Connect model profile")
    result.add_argument("--workers", type=int, choices=(1, 2), default=1)
    result.add_argument("--passes", type=int, choices=(1, 2, 3), default=1)
    result.add_argument("--photo-id", help="Optional source photo to prepare; never an expected related photo")
    result.add_argument("--refresh", action="store_true",
                        help="Explicitly prepare the selected photo again while preserving its previous context; requires --photo-id")
    return result


async def main(args):
    refresh = bool(getattr(args, "refresh", False))
    if refresh and not args.photo_id:
        raise ValueError("Context refresh requires an explicit --photo-id")
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

    from connected_gallery.application.demo_profile import prepare_demo_profile, effective_context_model
    prepare_demo_profile(root, args.model, context_model=getattr(args, "context_model", None))
    from connected_gallery.adapters.store import Store
    from connected_gallery.adapters.models import LocalModels
    from connected_gallery.adapters.proxy import ProxyGateway
    from connected_gallery.agent_runtime.runner import GraphAgentRunner
    from connected_gallery.application.service import RunService
    from connected_gallery.domain.context import CONTEXT_SPEC, CONTEXT_POLICY, CONTEXT_WORDING_MODEL
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
                      model=effective_context_model(), context_model=effective_context_model(),
                      connection_model=gateway.primary, wording_review_model=CONTEXT_WORDING_MODEL,
                      workers=args.workers, synthetic=True, refresh_requested=refresh)
        successful_refreshes = set()
        current_attempts = []

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
                selected = not args.photo_id or args.photo_id == photo.id
                needs_preparation = (photo.id not in successful_refreshes if refresh else
                                     service.context_ready(photo.id)["state"] not in ("ready", "empty"))
                if selected and needs_preparation:
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
                    created = (service.contexts.start(photo_id, refresh_prepared=True) if refresh else
                               service.start(RunRequest(role="context", photo_ids=[photo_id])))
                    while service.get(created["id"])["status"] in ("queued", "running"):
                        await asyncio.sleep(.5)
                    run = service.get(created["id"])
                    envelope = service.context_ready(photo_id)
                    context = envelope.get("context") or {}
                    new_result_valid = False
                    if run["status"] == "completed" and isinstance(run.get("result"), dict):
                        try:
                            prepared = service.contexts.cache_value(photo_id, run["result"])
                            new_result_valid = (prepared["context"]["complete"] is True and
                                                store.cache_get(service.contexts.key(photo_id)) == prepared)
                        except (ValueError, TypeError, KeyError):
                            pass
                    if refresh and new_result_valid:
                        successful_refreshes.add(photo_id)
                    record = {"photo_id": photo_id, "run_id": created["id"], "pass": pass_index,
                              "status": run["status"], "state": envelope["state"],
                              "refresh_requested": refresh, "new_result_prepared": new_result_valid,
                              "previous_result_still_available": refresh and not new_result_valid and envelope["state"] in ("ready", "empty"),
                              "seconds": round(time.monotonic() - started, 3),
                              "groups": len(context.get("groups", [])),
                              "members": len({pid for g in context.get("groups", []) for pid in g["photo_ids"]}),
                              "revision": revision, "context_spec": CONTEXT_SPEC,
                              "context_model": effective_context_model(), "connection_model": gateway.primary,
                              "wording_review_model": CONTEXT_WORDING_MODEL}
                    report["attempts"].append(record)
                    current_attempts.append(record)
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
        report["current_invocation"] = {
            "refresh_requested": refresh, "attempts": len(current_attempts),
            "new_results_prepared": sum(row["new_result_prepared"] for row in current_attempts),
            "selected_refresh_completed": args.photo_id in successful_refreshes if refresh else None}
        save()
        print(json.dumps({"stage": "summary", "revision": revision, **report["counts"],
                          **report["current_invocation"]}), flush=True)
        # A nonzero result means real remaining work, never fabricate successful empty contexts.
        if refresh:
            return 0 if args.photo_id in successful_refreshes else 2
        return 0 if not any(report["counts"][s] for s in ("pending", "running", "failed")) else 2
    finally:
        if service is not None:
            await service.stop(preserve_pending=True)
        store.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(parser().parse_args())))
