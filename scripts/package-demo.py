"""Package source, an applicable binary patch, and sanitized prepared sample data.

The real repository index and runtime are never modified. Git's --no-index diff
handles untracked source additions. SQLite's backup API produces a consistent
snapshot; run/event history and feedback are removed only from the copied DB.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import subprocess
import sys
import tempfile
import threading
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "server"))
from connected_gallery.application.demo_profile import public_demo_marker
from connected_gallery.adapters.store import encoded
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import ExploreInput, ExplorationResult, PhotoAsset, PhotoAnalysis, RunRequest, SemanticAnchor
from connected_gallery.domain.context import (
    CONTEXT_POLICY, CONTEXT_SPEC, CONTEXT_WORDING_MODEL, ContextEvidence,
    PhotoContext, context_wording_fields,
)
EXCLUDED_PARTS = {".git", ".runtime", "runtime", ".venv", "venv", "node_modules", "build", "dist", ".gradle",
                  "__pycache__", ".pytest_cache", ".ruff_cache", ".idea", "outputs", "work", "tmp", "temp"}
EXCLUDED_SUFFIXES = {".log", ".pyc", ".pyo", ".sqlite", ".sqlite3", ".db", ".apk", ".aab", ".zip",
                     ".pem", ".key", ".p12", ".pfx", ".tmp", ".bak", ".pid", ".iml"}
EXCLUDED_NAMES = {"local.properties", "server-token.txt", "demo-launch.html", "demo-launch-key.txt",
                  "pc-connection.json", "credentials.json", "service-account.json"}
UNTRACKED_SUFFIXES = {".py", ".kt", ".kts", ".md", ".json", ".xml", ".toml", ".lock", ".properties", ".txt",
                      ".cmd", ".ps1", ".bat", ".sh", ".js", ".cjs", ".mjs", ".css", ".html", ".svg", ".yml", ".yaml"}
README = """# Connected Gallery — prepared synthetic demo

The companion ready-data archive contains processed AI-generated sample photos and the prepared
gallery database. It contains no model keys, server tokens, browser sessions,
generation prompts, agent checkpoints, or execution histories.

1. Extract the companion source ZIP and install its Python dependencies.
2. Extract the ready-data archive's `.runtime/demo` folder into that source directory.
3. Run `python scripts/start-demo.py --data-dir .runtime/demo --prepared-only`.
4. Open http://127.0.0.1:8877/demo and enter the one-use key from the local path
   printed by the launcher. The server creates fresh local credentials; launch
   keys and browser sessions are not included in either archive.

The server binds only http://127.0.0.1:8877. Prepared-only mode never calls models.
Opening a photo automatically shows its prepared context below the image. Subject
connections remain a separate view. Unprepared targets or contexts remain marked
as needing preparation; a failed preparation is not an empty result. Personal photos and a
phone connection are unnecessary. The timings/quality report is a separate file.
The public model profile in synthetic-demo.json selects prepared caches. Explicit
compatible_connection_models keep older verified results in their original model
namespaces; new preparation uses the primary model. Context has its own model.
The launcher reads it automatically; it contains no provider credentials and does
not change production model defaults. Existing analyses can predate this connection
preparation model profile; their original observations are retained.
Synthetic dates, when present, retain the explicit demo_fixture source and are
displayed as demo settings, never as actual capture dates.
"""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git(project, *args, accepted=(0,)):
    process = subprocess.run(["git", "--no-optional-locks", "-c", "core.quotepath=false", *args], cwd=project,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode not in accepted:
        raise ValueError("Git packaging command failed; verify this is a local repository with HEAD")
    return process.stdout


def allowed_source(name, *, tracked):
    path = PurePosixPath(name)
    parts = [part.lower() for part in path.parts]
    if path.is_absolute() or ".." in parts or any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in parts):
        return False
    base = path.name.lower()
    if ((base == ".env" or base.startswith(".env.")) and base != ".env.example"):
        return False
    if base in EXCLUDED_NAMES or base.startswith("demo-launch") or "credentials" in base or "service-account" in base:
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES or base.endswith("~"):
        return False
    return tracked or path.suffix.lower() in UNTRACKED_SUFFIXES or base in {".gitignore", ".env.example", "dockerfile", "makefile"}


def source_files(project):
    tracked = {p.decode("utf-8") for p in git(project, "ls-files", "-z", "--cached").split(b"\0") if p}
    # Staged deletions no longer appear in the index but still belong in the
    # HEAD-to-working-tree patch.
    tracked |= {p.decode("utf-8") for p in git(project, "ls-tree", "-r", "--name-only", "-z", "HEAD").split(b"\0") if p}
    untracked = {p.decode("utf-8") for p in git(project, "ls-files", "-z", "--others", "--exclude-standard").split(b"\0") if p}
    tracked = {name for name in tracked if allowed_source(name, tracked=True)}
    untracked = {name for name in untracked if allowed_source(name, tracked=False)}
    selected = {}
    for name in sorted(tracked | untracked):
        if not allowed_source(name, tracked=name in tracked):
            continue
        path = project / name
        if not path.exists():
            continue  # Deletions are represented in the patch.
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(project):
            raise ValueError("Source archive cannot follow symlinks or paths outside the project")
        selected[name] = path.read_bytes()
    return selected, tracked, untracked


def binary_patch(project, tracked, untracked):
    changed = [p.decode("utf-8") for p in git(project, "diff", "--name-only", "-z", "HEAD", "--").split(b"\0") if p]
    chunks = []
    # Diff one path at a time to stay below Windows command-line limits. Disable
    # external diff/text conversion: source packaging must not execute hooks.
    for name in sorted(changed):
        if name in tracked and allowed_source(name, tracked=True):
            chunks.append(git(project, "diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv", "HEAD", "--", name))
    for name in sorted(untracked):
        if allowed_source(name, tracked=False):
            chunks.append(git(project, "diff", "--no-index", "--binary", "--full-index", "--no-ext-diff", "--no-textconv",
                              "--", "/dev/null", name, accepted=(0, 1)))
    return b"".join(chunks)


def database_state(db):
    return {"data_version": db.execute("PRAGMA data_version").fetchone()[0],
            "revision": db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0],
            "active_runs": db.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]}


def checked_context(cached, versions, cache_revision, revision):
    """A portable context remains a validated prepared view after logs are removed."""
    required = {"kind", "photo_id", "context_spec", "context_policy", "context", "evidence"}
    if set(cached) != required or cached.get("kind") != "photo_context":
        raise ValueError("A cached photo context has an invalid envelope")
    source = cached.get("photo_id")
    ids = set(versions)
    if not isinstance(source, str) or source not in ids:
        raise ValueError("A cached photo context references an unknown source photo")
    if (type(cached.get("context_spec")) is not int or cached["context_spec"] != CONTEXT_SPEC
            or cached.get("context_policy") != CONTEXT_POLICY or cache_revision != revision):
        raise ValueError("A cached photo context has a stale version or revision")
    try:
        context = PhotoContext.model_validate(cached["context"])
    except ValueError:
        raise ValueError("A cached photo context has an invalid result") from None
    if not context.complete:
        raise ValueError("An incomplete photo context cannot be packaged as prepared")
    members = {pid for group in context.groups for pid in group.photo_ids}
    if source in members:
        raise ValueError("A photo context cannot include its source in a related group")
    if not members.issubset(ids):
        raise ValueError("A cached photo context group references an unknown photo")
    try:
        evidence = ContextEvidence.model_validate(cached["evidence"])
    except ValueError:
        raise ValueError("A cached photo context has invalid inspection evidence") from None
    inspected = set(evidence.inspected_photo_ids)
    if not inspected.issubset(ids):
        raise ValueError("Photo context inspection evidence references an unknown photo")
    if (len(inspected) != len(evidence.inspected_photo_ids) or source not in inspected
            or not members.issubset(inspected)):
        raise ValueError("Photo context source and members require distinct inspected photo evidence")
    if (evidence.gallery_revision != revision or evidence.source_version != versions[source]
            or set(evidence.photo_versions) != inspected
            or any(evidence.photo_versions[pid] != versions[pid] for pid in inspected)):
        raise ValueError("Photo context inspection evidence has stale or missing photo versions")
    expected = {(group.id, pid) for group in context.groups for pid in group.photo_ids}
    reviewed = [(item.group_id, item.photo_id) for item in evidence.reviewed_members]
    if len(reviewed) != len(expected) or set(reviewed) != expected:
        raise ValueError("Photo context review evidence must cover every membership exactly once")
    if not context.groups and inspected != ids:
        raise ValueError("An empty photo context requires inspection evidence for every photo")
    planned = set(evidence.planned_photo_ids)
    if (len(planned) != len(evidence.planned_photo_ids) or source in planned
            or not planned.issubset(inspected)):
        raise ValueError("Photo context observation plan lacks complete distinct inspection evidence")
    wording_paths = {field["path"] for field in context_wording_fields(context)}
    if (evidence.wording_review_model != CONTEXT_WORDING_MODEL
            or len(evidence.wording_checked_paths) != len(wording_paths)
            or set(evidence.wording_checked_paths) != wording_paths):
        raise ValueError("Photo context wording evidence must cover every exact field with the configured reviewer")


class PackagingGallery:
    """Minimal read-only adapter: validation cannot initialize or migrate a Store."""
    def __init__(self, db):
        self.db, self.lock = db, threading.RLock()

    @property
    def revision(self):
        return self.db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0]

    def photo(self, pid):
        row = self.db.execute("SELECT data FROM photos WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise ValueError("Unknown packaged photo")
        return PhotoAsset.model_validate_json(row[0])

    def photos(self, year=None):
        values = [PhotoAsset.model_validate_json(row[0]) for row in self.db.execute("SELECT data FROM photos ORDER BY id")]
        return values if year is None else [value for value in values if value.year == year]

    def analysis(self, pid):
        row = self.db.execute("SELECT data FROM analyses WHERE photo_id=?", (pid,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_get(self, key):
        row = self.db.execute("SELECT revision,data FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[1]) if row and row[0] == self.revision else None


def connection_keys(service, models):
    """Portable demo choices are current analyzed regions and whole-photo defaults.

    A hash is not source provenance by itself. Reconstruct original keys from
    current metadata, never infer their model from a result's claim or relabel it.
    Other historical/custom selections must be removed by the staging command.
    """
    identities = {}
    for photo in service.store.photos():
        anchors = [SemanticAnchor(photo_id=photo.id)]
        raw = service.store.analysis(photo.id)
        if raw is not None:
            analysis = PhotoAnalysis.model_validate(raw)
            if analysis.photo_id != photo.id or any(region.photo_id != photo.id for region in analysis.regions):
                raise ValueError("A packaged analysis has an inconsistent source")
            anchors += [SemanticAnchor(photo_id=photo.id, region_id=region.id, box=region.box,
                                       label=region.label, kind=region.kind) for region in analysis.regions]
        for anchor in anchors:
            query = ExploreInput(anchor=anchor)
            for model in models:
                req = RunRequest(role="explorer", explore=query)
                for key in (service.cache_key(req, model=model), service.empty_cache_key(query, model=model)):
                    if key in identities:
                        raise ValueError("A packaged current selection has duplicate identities")
                    identities[key] = (query, model)
    return identities


def checked_photos(db, profile=None):
    photos = []
    for pid, payload in db.execute("SELECT id,data FROM photos ORDER BY id"):
        value = json.loads(payload)
        if value.get("id") != pid or value.get("device_id") != "synthetic-demo":
            raise ValueError("Every packaged photo must be from device_id synthetic-demo")
        if value.get("time_source") == "demo_fixture":
            try:
                captured = datetime.fromisoformat(value["captured_at"])
                if captured.tzinfo is None or captured.utcoffset() is None:
                    raise ValueError("Naive fixture date")
            except (KeyError, TypeError, ValueError):
                raise ValueError("A demo fixture date requires an explicit timezone-aware timestamp") from None
        photos.append((pid, value))
    if not photos:
        raise ValueError("The synthetic gallery is empty")
    ids = {pid for pid, _ in photos}
    for table in ["analyses", "vectors", "artifacts"]:
        if any(row[0] not in ids for row in db.execute(f"SELECT DISTINCT photo_id FROM {table}")):
            raise ValueError("An analysis/index references an asset outside the synthetic gallery")
    revision = db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0]
    # The supplied public marker is already validated. No process model settings
    # are changed during packaging or while checking a particular namespace.
    profile = profile or {"model": os.getenv("CG_MODEL", "gpt-5.4-mini")}
    primary = profile.get("model", "gpt-5.4-mini")
    models = [primary, *profile.get("compatible_connection_models", [])]
    context_model = profile.get("context_model", primary)
    service = RunService(PackagingGallery(db), None)
    identities = connection_keys(service, models)
    for key, cache_revision, payload in db.execute("SELECT key,revision,data FROM cache"):
        cached = json.loads(payload)
        if not isinstance(cached, dict):
            raise ValueError("A cached result must be an object")
        if cached.get("kind") == "photo_context" or {"context", "context_spec", "context_policy"}.intersection(cached):
            checked_context(cached, {pid: value.get("version") for pid, value in photos}, cache_revision, revision)
            source = cached["photo_id"]
            expected_key = hashlib.sha256(encoded(["photo-context", CONTEXT_SPEC, CONTEXT_POLICY, CONTEXT_WORDING_MODEL,
                context_model, source, service.store.photo(source).version, revision]).encode()).hexdigest()
            if key != expected_key:
                raise ValueError("A cached photo context has a different model or current selection key")
            try:
                service.contexts.cached_context(source, cached)
            except ValueError:
                raise ValueError("A cached photo context fails the current prepared service contract") from None
            continue
        if any(item.get("photo_id") not in ids for item in cached.get("items", [])):
            raise ValueError("A cached connection references an unknown photo")
        if any(pid not in ids for group in cached.get("groups", []) for pid in group.get("photo_ids", [])):
            raise ValueError("A cached group references an unknown photo")
        try:
            value = ExplorationResult.model_validate(cached)
        except ValueError:
            raise ValueError("A cached connection has an invalid prepared result or negative proof") from None
        if cache_revision != revision or not value.complete or value.grouping_status != "ready":
            raise ValueError("A cached connection is stale or not completely prepared")
        if key not in identities:
            raise ValueError("A cached connection has an unsupported model or current selection key; stage current data first")
        query, model = identities[key]
        accepted_key, accepted = service._prepared_entry_for_model(query, model)
        if accepted_key != key or accepted is None:
            raise ValueError("A cached connection's evidence does not match its original model and current selection")
    return photos


def checked_staging_inventory(root, db, profile):
    """Pin a staged positive's original namespace even without a model field.

    This is an integrity check against the existing public staging inventory,
    not cryptographic attestation of a provider or a new semantic judgment.
    """
    path = root / "stage-report.json"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("The staging inventory must be a regular local file")
    content = path.read_bytes()
    try:
        report = json.loads(content)
        records = report["validation"]["cache_records"]
        expected = {record["key"]: (record["revision"], record["payload_sha256"]) for record in records}
        actual = {key: (revision, sha256(payload)) for key, revision, payload in db.execute(
            "SELECT key,revision,CAST(data AS BLOB) FROM cache")}
        if (report.get("staging_only") is not True
                or report.get("retained_payload_bytes_and_revisions_unchanged") is not True
                or len(expected) != len(records) or expected != actual
                or report["revision"] != db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0]
                or report["model"] != profile["model"]
                or report.get("context_model", report["model"]) != profile.get("context_model", profile["model"])
                or report.get("compatible_connection_models", []) != profile.get("compatible_connection_models", [])):
            raise ValueError("Staging identity changed")
        identities = connection_keys(RunService(PackagingGallery(db), None),
                                     [profile["model"], *profile.get("compatible_connection_models", [])])
        for record in records:
            if record["kind"] == "connect":
                if record["key"] not in identities or record.get("cache_model") != identities[record["key"]][1]:
                    raise ValueError("Staged connection namespace changed")
            elif record["kind"] != "context" or record["key"] in identities:
                raise ValueError("Staged cache role changed")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("Prepared cache keys, namespaces or payload bytes differ from the staging inventory") from None
    return sha256(content)


def package(args):
    project, root, output = args.source_dir.resolve(), args.data_dir.resolve(), args.output_dir.resolve()
    marker = root / "synthetic-demo.json"
    if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")).get("synthetic") is not True:
        raise ValueError("A marked synthetic gallery is required")
    public_marker = public_demo_marker(root, default_model=os.getenv("CG_MODEL", "gpt-5.4-mini"))
    demo_model = public_marker.get("model")
    if output == root or output.is_relative_to(root):
        raise ValueError("Deliverables must be outside the original runtime")
    names = ["connected-gallery-source.zip", "connected-gallery-changes.patch", "connected-gallery-ready-data.zip", "demo-package-report.json"]
    if any((output / name).exists() for name in names):
        raise ValueError("Choose an output folder without existing package deliverables")
    db = sqlite3.connect((root / "gallery.sqlite").as_uri() + "?mode=ro", uri=True)
    try:
        before = database_state(db)
        if before["active_runs"]:
            raise ValueError("Preparation is active; package only after queued/running jobs finish")
        photos = checked_photos(db, public_marker)
        staging_inventory_sha256 = checked_staging_inventory(root, db, public_marker)
        files, tracked, untracked = source_files(project)
        if not files:
            raise ValueError("No source files selected")
        base_commit = git(project, "rev-parse", "HEAD").decode().strip()
        patch = binary_patch(project, tracked, untracked)
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".package-demo-", dir=output) as temp_name:
            temp = Path(temp_name).resolve()
            if temp.parent != output:
                raise ValueError("Temporary packaging directory escaped its output folder")
            snapshot = temp / "gallery.sqlite"
            target = sqlite3.connect(snapshot)
            try:
                db.backup(target)
                target.execute("PRAGMA journal_mode=DELETE")
                target.execute("PRAGMA secure_delete=ON")
                for table in ["runs", "events", "feedback", "spaces"]:
                    target.execute(f"DELETE FROM {table}")
                # Stored local URIs are unnecessary for a portable demo.
                for pid, value in photos:
                    value["local_uri"] = ""
                    target.execute("UPDATE photos SET data=? WHERE id=?", (json.dumps(value, ensure_ascii=False), pid))
                target.commit()
                target.execute("VACUUM")
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Packaged SQLite integrity check failed")
                packaged_photos = checked_photos(target, public_marker)
                if checked_staging_inventory(root, target, public_marker) != staging_inventory_sha256:
                    raise ValueError("Staging inventory changed during packaging")
                counts = {table: target.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                          for table in ["photos", "analyses", "vectors", "artifacts", "cache", "runs", "events"]}
                counts["photo_context_cache"] = target.execute(
                    "SELECT count(*) FROM cache WHERE json_extract(data,'$.kind')='photo_context'").fetchone()[0]
                counts["connection_cache"] = counts["cache"] - counts["photo_context_cache"]
                if target.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0] != before["revision"]:
                    raise ValueError("Packaged revision changed")
            finally:
                target.close()
            with zipfile.ZipFile(temp / names[0], "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for name, content in files.items():
                    archive.writestr("connected-gallery/" + name, content)
                archive.writestr("connected-gallery/DEMO-README.md", README)
            (temp / names[1]).write_bytes(patch)
            image_report = []
            with zipfile.ZipFile(temp / names[2], "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.write(snapshot, ".runtime/demo/gallery.sqlite")
                archive.writestr(".runtime/demo/synthetic-demo.json", json.dumps(public_marker))
                archive.writestr("DEMO-README.md", README)
                for pid, _ in packaged_photos:
                    image_name = hashlib.sha256(pid.encode()).hexdigest() + ".jpg"
                    image_path = root / "images" / image_name
                    if image_path.is_symlink() or not image_path.resolve().is_relative_to(root) or not image_path.is_file():
                        raise ValueError("Processed sample image is missing or outside runtime")
                    content = image_path.read_bytes()
                    archive.writestr(".runtime/demo/images/" + image_name, content)
                    image_report.append({"photo_id": pid, "sha256": sha256(content), "bytes": len(content)})
            if database_state(db) != before:
                raise ValueError("Gallery changed during packaging; wait for preparation and retry")
            if checked_staging_inventory(root, db, public_marker) != staging_inventory_sha256:
                raise ValueError("Staging inventory changed during packaging")
            after_files, after_tracked, after_untracked = source_files(project)
            if files != after_files or tracked != after_tracked or untracked != after_untracked or git(project, "rev-parse", "HEAD").decode().strip() != base_commit:
                raise ValueError("Source changed during packaging; wait for implementation and retry")
            report = {"synthetic": True, "base_commit": base_commit, "revision": before["revision"], "model": demo_model,
                      "context_model": public_marker.get("context_model", demo_model),
                      "compatible_connection_models": public_marker.get("compatible_connection_models", []),
                      "staging_inventory_sha256": staging_inventory_sha256,
                      "source_file_count": len(files) + 1, "database": counts, "photos": image_report,
                      "excluded": ["credentials", "browser launch/session files", "checkpoints", "runs", "events", "feedback", "spaces", "local URIs"],
                      "files": {name: {"sha256": sha256((temp / name).read_bytes()), "bytes": (temp / name).stat().st_size}
                                for name in names[:3]}}
            report["files"][names[0]]["file_count"] = len(files) + 1
            report["files"][names[1]]["diff_file_count"] = patch.count(b"\ndiff --git ") + int(patch.startswith(b"diff --git "))
            report["files"][names[2]]["file_count"] = len(packaged_photos) + 3
            (temp / names[3]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            # All validations precede publication. Only newly created outputs
            # are moved; no original source, runtime or git index is touched.
            for name in names:
                (temp / name).replace(output / name)
        print(json.dumps({key: value for key, value in report.items() if key != "photos"}, ensure_ascii=False))
        return report
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=PROJECT)
    parser.add_argument("--data-dir", type=Path, default=PROJECT / ".runtime" / "demo")
    parser.add_argument("--output-dir", type=Path, required=True)
    try:
        package(parser.parse_args())
    except (ValueError, OSError, sqlite3.Error) as exc:
        # Runtime/provider content is never included in error messages.
        raise SystemExit(str(exc) if isinstance(exc, ValueError) else f"Packaging failed ({type(exc).__name__})") from None


if __name__ == "__main__":
    main()
