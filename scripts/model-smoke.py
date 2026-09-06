"""Actual local model smoke on synthetic pixels; not a Gallery quality benchmark."""

import json, time
from pathlib import Path
from PIL import Image, ImageDraw
from connected_gallery.adapters.models import LocalModels

models = LocalModels(Path(".runtime"))
report = {}
im = Image.new("RGB", (512, 256), "white")
draw = ImageDraw.Draw(im)
draw.rectangle((50, 80, 170, 210), fill="red")
draw.text((210, 100), "HELLO 2020", fill="black", font_size=32)
for name, fn in [
    ("visual_image", lambda: models.image(im)),
    ("visual_text", lambda: models.text("a red rectangle", visual=True)),
    ("korean_text", lambda: models.text("예방접종 안내문")),
    ("ground", lambda: models.ground(im, "a red rectangle.")),
    ("faces", lambda: models.faces(im)),
    ("ocr", lambda: models.ocr(im)),
]:
    start = time.monotonic()
    try:
        value = fn()
        report[name] = {
            "ok": True,
            "seconds": round(time.monotonic() - start, 2),
            "shape": list(value[1].shape) if isinstance(value, tuple) else None,
        }
    except Exception as e:
        report[name] = {"ok": False, "error": type(e).__name__ + ": " + str(e)[:300]}
    print(name, report[name], flush=True)
Path("docs/model-smoke-result.json").write_text(
    json.dumps(report, indent=2), encoding="utf-8"
)
if not all(x["ok"] for x in report.values()):
    raise SystemExit(1)
