"""Loopback-only browser shell with an independently scoped, expiring session.

An explicit launcher passes a one-use key through a local file form POST. Visiting
the public shell alone never grants a session. Provider credentials remain on the
server, and browser cookies cannot mutate the gallery or start background analysis.
"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse


WEB_ROOT = Path(__file__).resolve().parents[3] / "web" / "demo"
COOKIE = "cg_demo_session"


class DemoSession:
    def __init__(self, launch_key: str, port: int = 8877, *, live_enabled=True):
        if len(launch_key) < 32:
            raise ValueError("A strong one-time demo launch key is required")
        if port == 8765 or not 1024 <= port <= 65535:
            raise ValueError("Choose a separate unprivileged demo port")
        self.origin = f"http://127.0.0.1:{port}"
        self.host = f"127.0.0.1:{port}"
        self.launch_key = launch_key
        self.launch_until = time.monotonic() + 1800
        self.session = None
        self.session_until = 0.0
        self.live_enabled = live_enabled
        self.owned_runs = set()

    @staticmethod
    def public_path(path):
        return path in {"/demo", "/demo/", "/demo/app.js", "/demo/style.css", "/demo/session"}

    def check_request(self, request):
        # Do not trust forwarded headers. The launcher also binds only loopback.
        if request.headers.get("host", "") != self.host:
            return JSONResponse({"detail": "Local demo host required"}, status_code=403)
        if (not self.live_enabled and request.method not in {"GET", "HEAD"} and
                not (request.method == "POST" and request.url.path in {
                    "/demo/session", "/demo/logout", "/explorations/ready"})):
            return JSONResponse({"detail": "Prepared-only demo does not start or mutate work"}, status_code=403)
        origin = request.headers.get("origin")
        local_bootstrap = request.url.path == "/demo/session" and origin == "null"
        if origin and origin != self.origin and not local_bootstrap:
            return JSONResponse({"detail": "Cross-origin demo access denied"}, status_code=403)
        site = request.headers.get("sec-fetch-site")
        public_navigation = request.method == "GET" and self.public_path(request.url.path)
        if site in {"cross-site", "same-site"} and not local_bootstrap and not public_navigation:
            return JSONResponse({"detail": "Cross-site demo access denied"}, status_code=403)
        return None

    def cookie_authorized(self, request):
        supplied = request.cookies.get(COOKIE, "")
        if not self.session or time.monotonic() > self.session_until:
            return False
        if not secrets.compare_digest(supplied.encode("utf-8"), self.session.encode("ascii")):
            return False
        path, method = request.url.path, request.method
        if method == "GET":
            return path in {"/demo/catalog", "/health"} or (
                path.startswith("/assets/") and path.endswith(("/preview", "/analysis", "/context"))
            ) or path.startswith("/runs/")
        if method == "POST" and request.headers.get("origin") == self.origin:
            if path in {"/explorations/ready", "/demo/logout"}:
                return True
            if self.live_enabled:
                if path.startswith("/assets/") and path.endswith("/context/prepare"):
                    return True
                return path == "/runs" or any(path == f"/runs/{rid}/cancel" for rid in self.owned_runs)
        return False

    def response_headers(self, response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )

    def install(self, app, store):
        @app.get("/demo")
        @app.get("/demo/")
        def shell():
            return FileResponse(WEB_ROOT / "index.html", media_type="text/html")

        @app.get("/demo/app.js")
        def script():
            return FileResponse(WEB_ROOT / "app.js", media_type="text/javascript")

        @app.get("/demo/style.css")
        def style():
            return FileResponse(WEB_ROOT / "style.css", media_type="text/css")

        @app.post("/demo/session")
        async def session(request: Request):
            body = await request.body()
            if len(body) > 1024:
                raise HTTPException(413, "Session request too large")
            content_type = request.headers.get("content-type", "")
            is_form = content_type.startswith("application/x-www-form-urlencoded")
            try:
                key = (parse_qs(body.decode()).get("key", [""])[0] if is_form
                       else json.loads(body).get("key", ""))
            except (ValueError, AttributeError, UnicodeDecodeError):
                raise HTTPException(400, "Invalid session request")
            if (not isinstance(key, str) or not self.launch_key or
                    time.monotonic() > self.launch_until or
                    not secrets.compare_digest(key.encode("utf-8"), self.launch_key.encode("ascii"))):
                raise HTTPException(401, "Invalid or already used demo launch key")
            self.launch_key = None
            self.session = secrets.token_urlsafe(32)
            self.session_until = time.monotonic() + 8 * 3600
            response = RedirectResponse("/demo", status_code=303) if is_form else JSONResponse({"ready": True})
            response.set_cookie(COOKIE, self.session, httponly=True, samesite="lax", max_age=8 * 3600, path="/")
            return response

        @app.post("/demo/logout")
        def logout():
            self.session = None
            response = JSONResponse({"signed_out": True})
            response.delete_cookie(COOKIE, path="/")
            return response

        @app.get("/demo/catalog")
        def catalog(q: str = Query(default="", max_length=100)):
            query = q.strip().casefold()
            analyses = {r["photo_id"]: json.loads(r["data"]) for r in store.rows("SELECT photo_id,data FROM analyses")}
            assets = []
            for p in store.photos():
                a = analyses.get(p.id) or {}
                observed = " ".join([a.get("description", ""), a.get("ocr", "")] +
                                    [r.get("label", "") + " " + r.get("evidence", "") for r in a.get("regions", [])])
                if query and not all(term in observed.casefold() for term in query.split()):
                    continue
                assets.append({"id": p.id, "version": p.version, "width": p.width, "height": p.height,
                               "description": a.get("description", ""), "region_count": len(a.get("regions", [])),
                               "analyzed": bool(a)})
            return {"assets": assets, "total": len(store.photos()), "revision": store.revision,
                    "synthetic": True, "search_kind": "stored_observation_text", "live_enabled": self.live_enabled}
