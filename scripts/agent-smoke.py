"""End-to-end REAL proxy agent on synthetic photos, separate from personal evaluation."""

import asyncio, io, json, time
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image, ImageDraw
from connected_gallery.domain.models import *
from connected_gallery.adapters.store import Store
from connected_gallery.adapters.models import LocalModels
from connected_gallery.adapters.proxy import ProxyGateway
from connected_gallery.agent_runtime.runner import GraphAgentRunner


async def main():
    load_dotenv()
    root = Path("work/agent-smoke")
    store = Store(root)
    for pid, year, color in [
        ("red-2020", 2020, "red"),
        ("red-2015", 2015, "red"),
        ("blue-2015", 2015, "blue"),
    ]:
        store.upsert(
            PhotoAsset(
                id=pid,
                device_id="synthetic",
                version="1",
                captured_at=f"{year}-06-01T12:00:00Z",
                time_source="exif",
                width=256,
                height=256,
            )
        )
        im = Image.new("RGB", (256, 256), "white")
        ImageDraw.Draw(im).rectangle((64, 64, 192, 192), fill=color)
        b = io.BytesIO()
        im.save(b, "JPEG")
        store.put_image(pid, b.getvalue())
    runner = GraphAgentRunner(store, LocalModels(Path(".runtime")), ProxyGateway())
    started = time.monotonic()
    request = RunRequest(
        role="explorer",
        explore=ExploreInput(
            anchor=SemanticAnchor(
                photo_id="red-2020",
                box=Box(x=0.25, y=0.25, width=0.5, height=0.5),
                label="빨간 사각형",
            ),
            year=2015,
        ),
    )
    result = await asyncio.wait_for(
        runner.execute("synthetic-live-" + new_id(), request), 180
    )
    assert all(x["photo_id"].endswith("2015") for x in result["items"]), result
    assert any(x["photo_id"] == "red-2015" for x in result["items"]), result
    report = {
        "source": "synthetic-real-proxy",
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "result": result,
    }
    Path("docs/agent-smoke-result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True))
    store.close()


asyncio.run(main())
