"""Exercise Analyst and Organizer with real models on a synthetic reference card."""

import asyncio, io, json, time
from pathlib import Path
from PIL import Image, ImageDraw
from dotenv import load_dotenv
from connected_gallery.adapters.store import Store
from connected_gallery.adapters.models import LocalModels
from connected_gallery.adapters.proxy import ProxyGateway
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.domain.models import *


async def main():
    load_dotenv()
    store = Store(Path("work/analysis-smoke"))
    store.upsert(
        PhotoAsset(
            id="reference-card",
            device_id="synthetic",
            version="1",
            width=512,
            height=256,
        )
    )
    im = Image.new("RGB", (512, 256), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((40, 40, 150, 210), fill="red")
    d.text((190, 90), "SAVE THIS\nWINE 2020", fill="black", font_size=28)
    b = io.BytesIO()
    im.save(b, "JPEG")
    store.put_image("reference-card", b.getvalue())
    runner = GraphAgentRunner(store, LocalModels(Path(".runtime")), ProxyGateway())
    report = {}
    for role in ["analyst", "organizer"]:
        start = time.monotonic()
        request = RunRequest(
            role=role, photo_ids=["reference-card"] if role == "analyst" else []
        )
        result = await asyncio.wait_for(
            runner.execute("smoke-" + new_id(), request), 240
        )
        report[role] = {"seconds": round(time.monotonic() - start, 2), "result": result}
        print(role, "submitted", flush=True)
    assert store.analysis("reference-card") is not None
    Path("docs/analysis-smoke-result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    store.close()


asyncio.run(main())
