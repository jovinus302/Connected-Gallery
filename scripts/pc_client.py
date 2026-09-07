"""Authenticated local maintenance requests; never print the credential."""
import os
from pathlib import Path
from urllib.request import Request, urlopen as _urlopen
from dotenv import load_dotenv
from connected_gallery.bootstrap.auth import server_token


def urlopen(request, *args, **kwargs):
    project = Path(__file__).resolve().parents[1]
    load_dotenv(project / ".env")
    root = Path(os.getenv("CG_DATA_DIR", str(project / ".runtime")))
    if not root.is_absolute():
        root = project / root
    if isinstance(request, str):
        request = Request(request)
    if request.full_url.startswith("http://127.0.0.1:8765/"):
        request.add_header("Authorization", "Bearer " + server_token(root))
    return _urlopen(request, *args, **kwargs)
