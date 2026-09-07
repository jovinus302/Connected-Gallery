from __future__ import annotations
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from connected_gallery.domain.models import SyncRequest, RunRequest, Feedback, Box
from pydantic import BaseModel


class RegionPreview(BaseModel):
    box: Box
    jpeg_base64: str


from connected_gallery.adapters.store import Store, encoded
from connected_gallery.adapters.models import LocalModels
from connected_gallery.adapters.proxy import ProxyGateway
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.application.service import RunService
from connected_gallery.application.indexing import AnalysisIndexing


def create_app(root=None, runner_factory=None):
    load_dotenv()
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    root = Path(root or os.getenv("CG_DATA_DIR", ".runtime"))
    store = Store(root)
    models = LocalModels(root)
    runner = (
        runner_factory(store)
        if runner_factory
        else GraphAgentRunner(store, models, ProxyGateway())
    )
    service = RunService(store, runner)
    indexing = AnalysisIndexing(store, models)

    @asynccontextmanager
    async def lifespan(app):
        await service.recover()
        yield
        await service.stop(preserve_pending=True)
        store.close()

    app = FastAPI(title="Connected Gallery", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.service = service

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "revision": store.revision,
            "proxy_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
            "agent_spec": 7,
            "analysis_concurrency": service.analysis_concurrency,
            "explore_timeout_seconds": service.explore_timeout,
        }

    @app.get("/progress")
    def progress():
        report = indexing.report()
        report["runs"] = store.rows("SELECT json_extract(request,'$.role') AS role,status,count(*) AS count FROM runs GROUP BY 1,2")
        return report

    @app.post("/assets/{pid}/reindex")
    async def reindex(pid: str):
        import asyncio
        return await asyncio.to_thread(indexing.repair, pid)

    @app.get("/manifest")
    def manifest():
        return {
            "api_version": 1,
            "max_assets": 1000,
            "directions": ["related", "same_moment"],
            "years": sorted({p.year for p in store.photos() if p.year}, reverse=True),
            "model": os.getenv("CG_MODEL", "gpt-5.4-mini"),
        }

    @app.post("/assets/sync")
    async def sync(req: SyncRequest):
        if req.deleted_ids:
            await service.stop(preserve_pending=True)
        for pid in req.deleted_ids:
            store.delete(pid)
        for asset in req.assets:
            previous = store.rows("SELECT version FROM photos WHERE id=?", (asset.id,))
            if previous and previous[0]["version"] != asset.version:
                service.cancel_analysis_for_photo(asset.id)
            store.upsert(asset)
        if req.deleted_ids:
            await service.recover()
        return {
            "revision": store.revision,
            "need_preview": [
                p.id for p in req.assets if not store.image_path(p.id).exists()
            ],
        }

    @app.put("/assets/{pid}/preview")
    async def upload(pid: str, request: Request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 16 * 1024 * 1024:
                raise HTTPException(413, "Preview too large")
        import asyncio

        await asyncio.to_thread(store.put_image, pid, bytes(data))
        return {"saved": True}

    @app.post("/assets/{pid}/region-preview")
    async def region_preview(pid: str, body: RegionPreview):
        import base64, asyncio

        if len(body.jpeg_base64) > 16 * 1024 * 1024:
            raise HTTPException(413, "Region too large")
        data = base64.b64decode(body.jpeg_base64, validate=True)
        await asyncio.to_thread(store.put_region_image, pid, body.box, data)
        return {"saved": True}

    @app.get("/assets")
    def photos():
        return {"assets": [p.model_dump(mode="json") for p in store.photos()]}

    @app.get("/assets/{pid}/analysis")
    def analysis(pid: str):
        store.photo(pid)
        return store.analysis(pid) or {
            "photo_id": pid,
            "regions": [],
            "description": "",
            "pending": True,
        }

    @app.get("/assets/{pid}/preview")
    def preview(pid: str):
        path = store.image_path(pid)
        if not path.exists():
            raise HTTPException(404, "Preview not synced")
        return FileResponse(path, media_type="image/jpeg")

    @app.delete("/assets/{pid}")
    async def delete(pid: str):
        await service.stop(preserve_pending=True)
        store.delete(pid)
        await service.recover()
        return {"deleted": True, "revision": store.revision}

    @app.post("/runs")
    async def start(req: RunRequest):
        return service.start(req)

    @app.get("/runs/{rid}")
    def get_run(rid: str):
        return service.get(rid)

    @app.post("/runs/{rid}/cancel")
    async def cancel(rid: str):
        return service.cancel(rid)

    @app.get("/runs/{rid}/events")
    def events(rid: str, after: int = 0):
        service.get(rid)
        rows = store.rows(
            "SELECT seq,kind,data,at FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 100",
            (rid, after),
        )
        return {
            "events": [{**r, "data": json.loads(r["data"])} for r in rows],
            "cursor": rows[-1]["seq"] if rows else after,
        }

    @app.get("/spaces")
    def spaces():
        return {"spaces": store.spaces(), "revision": store.revision}

    @app.post("/feedback")
    def feedback(value: Feedback):
        if value.photo_id:
            store.photo(value.photo_id)
        if value.kind in ("space_include", "space_exclude"):
            rows = store.rows("SELECT data FROM spaces WHERE id=?", (value.space_id,))
            if not rows or not value.photo_id:
                raise ValueError("Valid Space and photo required")
            s = json.loads(rows[0]["data"])
            s["items"] = [x for x in s["items"] if x["photo_id"] != value.photo_id]
            if value.kind == "space_include":
                s["items"].append(
                    {"photo_id": value.photo_id, "reason": "사용자가 포함한 사진"}
                )
            store.write(
                "UPDATE spaces SET data=? WHERE id=?", (encoded(s), value.space_id)
            )
        if value.kind == "person_name":
            a = store.analysis(value.photo_id)
            if not a or value.region_id not in {r["id"] for r in a["regions"]}:
                raise ValueError("Valid region required")
            for r in a["regions"]:
                if r["id"] == value.region_id:
                    r["label"] = value.value
            store.write(
                "UPDATE analyses SET data=? WHERE photo_id=?",
                (encoded(a), value.photo_id),
            )
        store.write(
            "INSERT OR IGNORE INTO feedback VALUES(?,?)",
            (value.event_id, value.model_dump_json()),
        )
        if value.kind != "metric":
            store.bump()
        return {"saved": True}

    return app
