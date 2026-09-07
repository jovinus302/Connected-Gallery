"""Seed and prepare a separate gallery from image bytes, never demo answer labels.

The input directory contains only images with opaque names. Generation prompts and
evaluation expectations are deliberately not accepted by this program.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "server"))


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def grouping_timeout_seconds(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise argparse.ArgumentTypeError("Grouping timeout must be an integer from 45 to 90 seconds")
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Grouping timeout must be an integer from 45 to 90 seconds") from None
    if not 45 <= seconds <= 90:
        raise argparse.ArgumentTypeError("Grouping timeout must be an integer from 45 to 90 seconds")
    return seconds


def preparation_organizer(gateway, timeout_seconds):
    from connected_gallery.agent_runtime.organizer import ResultOrganizer
    return ResultOrganizer(gateway, timeout=grouping_timeout_seconds(timeout_seconds))


async def bounded_prepare(items, run_one, workers):
    """Start only the bounded next jobs; do not queue the entire gallery."""
    if workers not in (1, 2):
        raise ValueError("Preparation workers must be 1 or 2")
    items, pending = iter(items), set()
    exhausted = False
    try:
        while pending or not exhausted:
            while len(pending) < workers and not exhausted:
                try:
                    item = next(items)
                except StopIteration:
                    exhausted = True
                else:
                    pending.add(asyncio.create_task(run_one(item)))
            if pending:
                done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    pending.remove(task)
                    yield task.result()
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def main(args):
    from connected_gallery.agent_runtime.runner import GraphAgentRunner, validate_exploration_responses
    exploration_responses = validate_exploration_responses(getattr(args, "exploration_responses", 6))
    grouping_timeout = grouping_timeout_seconds(getattr(args, "grouping_timeout_seconds", 45))
    model_timeout = getattr(args, "model_timeout_seconds", 30)
    if not isinstance(model_timeout, int) or isinstance(model_timeout, bool) or not 15 <= model_timeout <= 60:
        raise ValueError("Model attempt timeout must be an integer from 15 to 60 seconds")
    from dotenv import load_dotenv
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    if args.model_dir:
        os.environ["CG_MODEL_DIR"] = str(Path(args.model_dir).resolve())
    os.environ["CG_AUTO_ORGANIZE"] = "0"
    os.environ["CG_ANALYSIS_CONCURRENCY"] = "1"
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

    from connected_gallery.application.demo_profile import prepare_demo_profile, connection_models
    workers = getattr(args, "workers", 1)
    refresh = bool(getattr(args, "refresh", False))
    if workers not in (1, 2):
        raise ValueError("Preparation workers must be 1 or 2")
    data = Path(args.data_dir).resolve()
    prepare_demo_profile(data, getattr(args, "model", None),
                         compatible_connection_models=getattr(args, "compatible_model", None))

    from PIL import Image
    from connected_gallery.adapters.store import Store
    from connected_gallery.adapters.models import LocalModels
    from connected_gallery.adapters.proxy import ProxyGateway
    from connected_gallery.agent_runtime.reviewer import EvidenceReviewer
    from connected_gallery.agent_specs.versions import AGENT_SPEC_VERSION, RETRIEVAL_POLICY
    from connected_gallery.application.service import RunService
    from connected_gallery.domain.models import PhotoAsset, RunRequest, ExploreInput, SemanticAnchor, Region

    store = Store(data)
    models = LocalModels(data)
    gateway = ProxyGateway(attempt_timeout=model_timeout, repeat_primary=False)
    runner = GraphAgentRunner(store, models, gateway, EvidenceReviewer(gateway),
                              explorer_gateway=gateway, result_organizer=preparation_organizer(gateway, grouping_timeout),
                              exploration_responses=exploration_responses)
    service = RunService(store, runner)
    service.auto_enabled = False
    service.interactive = asyncio.Semaphore(workers)
    report_path = data / "preparation-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"analysis": {}, "connections": {}}

    def save():
        report["revision"] = store.revision
        report["agent_spec"] = AGENT_SPEC_VERSION
        report["retrieval_policy"] = RETRIEVAL_POLICY
        report["connection_model"] = gateway.primary
        report["compatible_connection_models"] = connection_models(gateway.primary)[1:]
        report["preparation_workers"] = workers
        report["refresh_requested"] = refresh
        report["grouping_timeout_seconds"] = grouping_timeout
        report["model_timeout_seconds"] = model_timeout
        report["exploration_responses"] = exploration_responses
        report["exploration_tool_calls"] = 2 * exploration_responses
        temp = report_path.with_suffix(".tmp")
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(report_path)

    async def wait_run(created):
        rid = created["id"]
        started = time.monotonic()
        while True:
            state = service.get(rid)
            if state["status"] not in ("queued", "running"):
                return state, round(time.monotonic() - started, 3)
            await asyncio.sleep(.5)

    try:
        if args.stage in ("seed", "all"):
            images = sorted(p for p in Path(args.samples).resolve().iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
            if not images:
                raise SystemExit("No sample images")
            for path in images:
                payload = path.read_bytes()
                digest = hashlib.sha256(payload).hexdigest()
                # The opaque identifier is derived from bytes, not scenario names.
                pid = digest[:32]
                with Image.open(path) as im:
                    width, height = im.size
                store.upsert(PhotoAsset(id=pid, device_id="synthetic-demo", version=digest,
                                        width=width, height=height, time_source="unknown"))
                store.put_image(pid, payload)
            emit({"stage": "seed", "photos": len(images), "revision": store.revision})

        if args.stage in ("analyze", "all"):
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise SystemExit("Set existing model configuration before analysis")
            for photo in store.photos():
                if args.photo_id and photo.id != args.photo_id:
                    continue
                if store.analysis(photo.id):
                    continue
                state, seconds = await wait_run(service.start(RunRequest(role="analyst", photo_ids=[photo.id])))
                result = {"run_id": state["id"], "status": state["status"], "seconds": seconds,
                          "model": gateway.primary,
                          "regions": len((store.analysis(photo.id) or {}).get("regions", []))}
                report["analysis"][photo.id] = result
                save()
                emit({"stage": "analysis", "photo_id": photo.id, **result})

        if args.stage in ("prepare", "all"):
            pending = [p.id for p in store.photos() if not store.analysis(p.id)]
            if pending:
                raise SystemExit(f"Finish analysis before preparing connections: {len(pending)} pending")
            def queries():
                prepared = 0
                for photo in store.photos():
                    if args.photo_id and photo.id != args.photo_id:
                        continue
                    for value in store.analysis(photo.id).get("regions", []):
                        region = Region.model_validate(value)
                        if args.region_id and region.id != args.region_id:
                            continue
                        query = ExploreInput(anchor=SemanticAnchor(photo_id=photo.id, region_id=region.id,
                                                 box=region.box, kind=region.kind, label=region.label))
                        if not refresh and service.ready(query)["state"] == "ready":
                            continue
                        if args.limit is not None and prepared >= args.limit:
                            return
                        prepared += 1
                        yield photo.id, region.id, query

            async def run_one(item):
                photo_id, region_id, query = item
                request = RunRequest(role="explorer", explore=query)
                created = service.start(request, refresh_prepared=True) if refresh else service.start(request)
                state, seconds = await wait_run(created)
                return photo_id, region_id, query, state, seconds

            async for photo_id, region_id, query, state, seconds in bounded_prepare(queries(), run_one, workers):
                result = state.get("result") or {}
                ready = service.ready(query)
                record = {"run_id": state["id"], "status": state["status"], "seconds": seconds, "model": gateway.primary,
                          "model_timeout_seconds": model_timeout,
                          "exploration_responses": exploration_responses,
                          "exploration_tool_calls": 2 * exploration_responses,
                          "grouping_timeout_seconds": grouping_timeout,
                          "agent_spec": AGENT_SPEC_VERSION, "revision": store.revision,
                          "items": len(result.get("items", [])), "groups": len(result.get("groups", [])),
                          "grouping_status": result.get("grouping_status", "legacy"),
                          "refresh_requested": refresh,
                          "ready": ready["state"] == "ready", "ready_cache_model": ready.get("cache_model")}
                report["connections"][region_id] = record
                save()
                emit({"stage": "connection", "photo_id": photo_id, "region_id": region_id, **record})
        save()
    finally:
        await service.stop(preserve_pending=True)
        store.close()


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=PROJECT / ".runtime" / "demo")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--model", help="Public model name for this synthetic demo profile; preserves provider credentials and fallback")
    parser.add_argument("--compatible-model", action="append",
                        help="Also read verified Connect caches from this public model namespace; repeat for multiple models (maximum 4)")
    parser.add_argument("--refresh", action="store_true",
                        help="Explicitly rerun matching prepared Connect choices in the primary namespace; photo/region filters and limit still apply")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=1,
                        help="Bounded connection preparation workers; analysis remains sequential")
    parser.add_argument("--grouping-timeout-seconds", type=grouping_timeout_seconds, default=45,
                        help="Offline grouping stage budget, 45-90 seconds; still limited by the remaining explorer budget")
    parser.add_argument("--model-timeout-seconds", type=int, choices=range(15, 61), default=30,
                        help="Single model attempt budget; the overall explorer wall-clock limit still applies")
    parser.add_argument("--exploration-responses", type=int, choices=range(6, 13), default=6,
                        help="Offline Explorer response budget (6-12); tool calls are twice this value and the overall deadline is unchanged")
    parser.add_argument("--stage", choices=("seed", "analyze", "prepare", "all"), default="all")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--photo-id", help="Prepare a selected source ID; never used as an expected result")
    parser.add_argument("--region-id", help="Prepare a selected region ID using the ordinary pipeline")
    return parser


if __name__ == "__main__":
    asyncio.run(main(argument_parser().parse_args()))
