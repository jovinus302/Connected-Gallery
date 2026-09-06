"""Download explicitly selected, pinned model artifacts. No personal photos are read."""

import hashlib
import json
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
model_dir = root / ".runtime" / "models"
model_dir.mkdir(parents=True, exist_ok=True)
repo = "opencv/opencv_zoo"
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/commits/main",
    headers={"User-Agent": "ConnectedGallery"},
)
sha = json.load(urllib.request.urlopen(req))["sha"]
lock = {}
for name in [
    "face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx",
]:
    folder = "face_detection_yunet" if "yunet" in name else "face_recognition_sface"
    url = (
        f"https://media.githubusercontent.com/media/{repo}/{sha}/models/{folder}/{name}"
    )
    path = model_dir / name
    if not path.exists():
        urllib.request.urlretrieve(url, path)
    lock[name] = {
        "revision": sha,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "url": url,
    }
(root / "server" / "face-model-lock.json").write_text(json.dumps(lock, indent=2))
from huggingface_hub import HfApi, snapshot_download

pins = {}
for repo in [
    "google/siglip2-base-patch16-224",
    "intfloat/multilingual-e5-small",
    "IDEA-Research/grounding-dino-tiny",
]:
    sha = HfApi().model_info(repo).sha
    pins[repo] = sha
    snapshot_download(
        repo,
        revision=sha,
        max_workers=1,
        ignore_patterns=["*.bin", "*.h5", "*.msgpack", "onnx/*"],
    )
(root / "server" / "model-lock.json").write_text(json.dumps(pins, indent=2))
print("Selected model artifacts downloaded and revisions recorded.")
