from __future__ import annotations
import base64
import concurrent.futures
import hashlib
import io
import json
import threading
import time
from datetime import datetime
from pydantic import BaseModel, Field, model_validator
from connected_gallery.domain.models import (
    Box,
    PhotoAnalysisSubmission,
    ExplorationResult,
    SpaceProposal,
)
from connected_gallery.adapters.store import encoded
from connected_gallery.agent_specs.budgets import run_timeout
from connected_gallery.domain.context import PhotoContext

# A reused full-photo line belongs to the requested region when most of it lies
# inside: OCR line boxes routinely overhang a hand-drawn selection edge.
REUSED_LINE_OVERLAP = 0.5
INITIAL_CANDIDATE_CHANNELS = ("visual", "text_literal", "text_semantic", "faces")
INITIAL_CANDIDATE_INSTRUCTION = (
    "host-retrieved leads from the selected anchor: similarity and keyword hits, not accepted "
    "results and not evidence of relation. Many leads are irrelevant. Do not submit a lead unless "
    "you verify the selected meaning in that lead's own image; when the leads do not show it, "
    "search with your own strategy before submitting. You may submit in your first response only "
    "when the attached images already verify your result"
)


class InspectArgs(BaseModel):
    photo_ids: list[str] = Field(max_length=8)


class RegionArgs(BaseModel):
    photo_id: str
    box: Box | None = None


class RecognizeTextArgs(RegionArgs):
    # Only recognize_text takes this escape hatch. RegionArgs stays the shared
    # shape of every other region tool and of the artifact cache keys.
    refresh: bool = False


class ListArgs(BaseModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class GroundArgs(RegionArgs):
    query: str


class EmbedArgs(BaseModel):
    photo_ids: list[str] = Field(default_factory=list, max_length=8)
    regions: list[RegionArgs] = Field(default_factory=list, max_length=8)
    include_text: bool = True


class SearchArgs(BaseModel):
    query: str
    limit: int = Field(default=20, ge=1, le=100)


class VisualArgs(BaseModel):
    query: str = ""
    photo_id: str | None = None
    box: Box | None = None
    limit: int = Field(default=20, ge=1, le=100)


class FaceArgs(RegionArgs):
    face_index: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class LocationArgs(BaseModel):
    latitude: float
    longitude: float
    radius_km: float = Field(gt=0, le=20040)


class TimeArgs(BaseModel):
    start: datetime
    end: datetime
    center: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def window(self):
        if any(d.tzinfo is None for d in (self.start, self.end, self.center) if d is not None):
            raise ValueError("Use timezone-aware timestamps")
        if self.start > self.end:
            raise ValueError("Time window start must precede end")
        if self.center is not None and not self.start <= self.center <= self.end:
            raise ValueError("Center must be inside the chosen time window")
        return self


class GalleryTools:
    def __init__(self, store, models, request, run_id):
        self.store = store
        self.models = models
        self.request = request
        self.run_id = run_id
        self.deadline = (
            time.monotonic()
            + run_timeout(request.role)
        )
        self.seen = set()
        self.covered = set()
        self.searched = set()
        # Concurrently executed tools share this toolkit. Reentrant, because a
        # guarded update (list_photos) reports guarded coverage in the same call.
        self.tracking = threading.RLock()
        # One rendering of the same (photo, box, version) per run; the metadata
        # text block is still rebuilt from current analysis on every call.
        self.render_memo = {}
        self.render_waits = {}
        self.render_lock = threading.RLock()
        self.result = None
        self.defer_results = False
        self.versions = {p.id: p.version for p in store.photos()}
        self.definitions = {
            "list_photos": (
                ListArgs,
                "Page through photo metadata and existing analysis.",
            ),
            "inspect_photos": (
                InspectArgs,
                "View up to 8 actual photo images. Required before selecting results.",
            ),
            "inspect_region": (
                RegionArgs,
                "View an actual image crop; coordinates are normalized in the oriented image.",
            ),
            "recognize_text": (
                RecognizeTextArgs,
                "Read text using Korean OCR. Returns recognition evidence and normalized x,y,width,height "
                "boxes in the FULL oriented photo, even for a crop. Copy matching boxes directly. "
                "For a region, already recognized full-photo lines are reused by default; "
                "set refresh=true to force OCR on the exact crop when the reused lines look incomplete.",
            ),
            "ground_regions": (
                GroundArgs,
                "Find objects for a descriptive query. Returns normalized x,y,width,height boxes "
                "in the FULL oriented photo, even when searching a crop. Copy these boxes directly.",
            ),
            "analyze_faces": (
                RegionArgs,
                "Detect faces and index face embeddings; does not identify names. "
                "Boxes are normalized x,y,width,height in the FULL oriented photo.",
            ),
            "ensure_embeddings": (
                EmbedArgs,
                "Create/reuse image and optional existing description embeddings.",
            ),
            "search_visual": (
                VisualArgs,
                "Find visual candidates by text or photo/crop. Candidate vectors must exist.",
            ),
            "search_text": (
                SearchArgs,
                "Retrieve text evidence by semantic embedding and literal text independently.",
            ),
            "search_faces": (
                FaceArgs,
                "Search by a selected detected face index in source photo/crop.",
            ),
            "search_location": (
                LocationArgs,
                "Retrieve photos within an explicitly chosen radius.",
            ),
            "search_time": (
                TimeArgs,
                "Retrieve candidates in a time window YOU choose, nearest the optional center. "
                "User year remains enforced. Time proximity is not proof of the same event; inspect images.",
            ),
            "read_spaces": (
                ListArgs,
                "Read existing Spaces and explicit user feedback.",
            ),
        }
        if request.role != "organizer":
            self.definitions.pop("read_spaces", None)
        submit = {
            "analyst": ("submit_photo_analysis", PhotoAnalysisSubmission),
            "explorer": ("submit_exploration_result", ExplorationResult),
            "organizer": ("submit_space_proposal", SpaceProposal),
            "context": ("submit_photo_context", PhotoContext),
        }[request.role]
        self.definitions[submit[0]] = (
            submit[1],
            "Validate and persist your evidence-grounded result. Use actual IDs only.",
        )
        if request.role == "analyst":
            observation_tools = {"inspect_photos", "inspect_region", "recognize_text",
                                 "ground_regions", "analyze_faces", "ensure_embeddings",
                                 "submit_photo_analysis"}
            self.definitions = {k: v for k, v in self.definitions.items() if k in observation_tools}
        elif request.role in ("explorer", "context"):
            self.definitions.pop("read_spaces", None)

    def schemas(self):
        schemas = [
            {"name": n, "description": d, "input_schema": m.model_json_schema()}
            for n, (m, d) in self.definitions.items()
        ]
        for schema in schemas:
            if schema["name"] == "submit_exploration_result":
                schema["input_schema"]["properties"].pop("empty_evidence", None)
        return schemas

    def allowed(self):
        year = self.request.explore.year if self.request.explore else None
        return {p.id for p in self.store.photos(year)}

    def candidate_ids(self):
        ids = self.allowed()
        if self.request.explore:
            ids.discard(self.request.explore.anchor.photo_id)
        return ids

    def authorize(self, photo_id, source=True):
        if time.monotonic() > self.deadline:
            raise ValueError("Run deadline exceeded")
        states = self.store.rows("SELECT status FROM runs WHERE id=?", (self.run_id,))
        if states and states[0]["status"] not in ("running", "queued"):
            raise ValueError("Run is no longer active")
        p = self.store.photo(photo_id)
        if self.versions.get(photo_id) != p.version:
            raise ValueError("Photo changed during run; start a new run")
        seeds = set(self.request.photo_ids)
        if self.request.explore:
            seeds.add(self.request.explore.anchor.photo_id)
        if photo_id not in self.allowed() and not (source and photo_id in seeds):
            raise ValueError("Photo outside selected year")
        return p

    def render(self, photo_id, box, version):
        """Encode the transported JPEG once per run; identical requests wait."""
        key = (photo_id, encoded(box.model_dump()) if box else None, version)
        with self.render_lock:
            if key in self.render_memo:
                return self.render_memo[key]
            wait = self.render_waits.setdefault(key, threading.Lock())
        with wait:
            with self.render_lock:
                if key in self.render_memo:
                    return self.render_memo[key]
            image = self.store.read_image(photo_id, box)
            image.thumbnail((1536, 1536))
            out = io.BytesIO()
            image.save(out, "JPEG", quality=85)
            data = base64.b64encode(out.getvalue()).decode()
            with self.render_lock:
                self.render_memo[key] = data
        return data

    def image_block(self, photo_id, box=None):
        asset = self.authorize(photo_id)
        data = self.render(photo_id, box, asset.version)
        blocks = [
            {
                "type": "text",
                "text": encoded(
                    {
                        "photo_id": photo_id,
                        "captured_at": asset.captured_at,
                        "time_source": asset.time_source,
                        # A whole-photo caption can describe objects outside a crop
                        # and must not substitute for the selected visual evidence.
                        "analysis": self.store.analysis(photo_id) if box is None else None,
                        "box": box.model_dump() if box else None,
                    }
                ),
            },
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": data,
                },
            },
        ]
        # Observation credit only for a block a caller can actually transport:
        # a half-built attachment is dropped, and its photo must stay unseen.
        with self.tracking:
            self.seen.add(photo_id)
        return blocks

    def artifact_key(self, name, photo, args):
        """The only derivation of an artifact cache key."""
        return hashlib.sha256(
            encoded(
                [
                    name,
                    photo.id,
                    photo.version,
                    args.model_dump(),
                    self.models.pins if hasattr(self.models, "pins") else {},
                ]
            ).encode()
        ).hexdigest()

    def stored_artifact(self, name, args):
        """Read an existing artifact without running inference; None when absent."""
        p = self.authorize(args.photo_id)
        rows = self.store.rows(
            "SELECT data FROM artifacts WHERE key=?", (self.artifact_key(name, p, args),)
        )
        return json.loads(rows[0]["data"]) if rows else None

    def artifact(self, name, args, fn):
        p = self.authorize(args.photo_id)
        key = self.artifact_key(name, p, args)
        rows = self.store.rows("SELECT data FROM artifacts WHERE key=?", (key,))
        if rows:
            return json.loads(rows[0]["data"])
        value = fn(self.store.read_image(p.id, args.box))
        self.authorize(p.id)
        self.store.write(
            "INSERT OR REPLACE INTO artifacts VALUES(?,?,?)",
            (key, p.id, encoded(value)),
        )
        return value

    def invoke(self, name, raw):
        if name not in self.definitions:
            raise ValueError("Unknown tool")
        args = self.definitions[name][0].model_validate(raw)
        if name.startswith("submit_") and name != "submit_photo_analysis":
            with self.store.lock:
                result = getattr(self, name)(args)
        else:
            result = getattr(self, name)(args)
        self.store.event(self.run_id, "tool", {"name": name, **self.tracking_snapshot()})
        return result

    def tracking_snapshot(self):
        with self.tracking:
            return {"seen": sorted(self.seen), "covered": sorted(self.covered),
                    "searched": sorted(self.searched)}

    def coverage_status(self):
        photos = self.store.photos(self.request.explore.year if self.request.explore else None)
        with self.tracking:
            covered = set(self.covered)
        return {"covered_count": sum(p.id in covered for p in photos),
                "total_count": len(photos),
                "next_uncovered_offset": next((i for i, p in enumerate(photos) if p.id not in covered), None)}

    def list_photos(self, args):
        photos = self.store.photos(
            self.request.explore.year if self.request.explore else None
        )
        page = photos[args.offset : args.offset + args.limit]
        with self.tracking:
            self.covered.update(p.id for p in page)
        output = [self.catalog_entry(p) for p in page]
        return {
            "total": len(photos),
            "next_offset": args.offset + len(page),
            "coverage": self.coverage_status(),
            "photos": output,
        }

    def catalog_entry(self, photo):
        analysis = self.store.analysis(photo.id)
        # Bound transport context; full evidence is available via inspection.
        summary = None if analysis is None else {
            "description_excerpt": analysis["description"][:160],
            "ocr_excerpt": analysis.get("ocr", "")[:64],
            "region_count": len(analysis.get("regions", [])),
            "truncated": len(analysis["description"]) > 160 or len(analysis.get("ocr", "")) > 64,
        }
        return {"photo_id": photo.id, "captured_at": photo.captured_at,
                "time_source": photo.time_source, "summary": summary,
                "image_ready": self.store.image_path(photo.id).exists()}

    def inspect_photos(self, args):
        content = []
        for pid in args.photo_ids:
            content += self.image_block(pid)
        return content

    def inspect_region(self, args):
        return self.image_block(args.photo_id, args.box)

    def recognize_text(self, args):
        if args.box is not None and not getattr(args, "refresh", False):
            reused = self.reused_full_photo_lines(args.photo_id, args.box)
            # An empty filter is not evidence of no text in the region: fall
            # through to the exact crop, which is what today's cost already is.
            if reused:
                return {"coordinate_space": "full_oriented_photo_normalized_xywh",
                        "texts": reused, "source": "full_photo_ocr"}
        # The cache key stays [name, photo id, version, {photo_id, box}, pins];
        # refresh is a request flag, never part of the stored artifact identity.
        region = RegionArgs(photo_id=args.photo_id, box=args.box)
        result = self.artifact("ocr-v1", region, self.models.ocr)
        image = self.store.read_image(args.photo_id, args.box)
        return {"coordinate_space": "full_oriented_photo_normalized_xywh",
                "texts": self.ocr_lines(result, image.size, args.box),
                "source": "region_ocr"}

    def ocr_lines(self, result, size, crop):
        lines = []
        for page in result["pages"]:
            evidence = page.get("res", page)
            for text, score, xyxy in zip(evidence["rec_texts"], evidence["rec_scores"],
                                         evidence["rec_boxes"], strict=True):
                box = self.pixel_box(xyxy, size, crop)
                if box is not None:
                    lines.append({"text": text, "score": score, "box": box})
        return lines

    def reused_full_photo_lines(self, photo_id, box):
        """Lines of an existing full-photo OCR artifact that fall inside `box`.

        None when no full-photo artifact exists. Stored rec_boxes are pixels of
        the full stored image, which is the same file that was recognized, so
        normalizing by its size puts them in the returned coordinate space.
        """
        stored = self.stored_artifact("ocr-v1", RegionArgs(photo_id=photo_id, box=None))
        if stored is None:
            return None
        size = self.store.read_image(photo_id).size
        return [line for line in self.ocr_lines(stored, size, None)
                if self.inside_ratio(line["box"], box) >= REUSED_LINE_OVERLAP]

    @staticmethod
    def inside_ratio(box, region):
        """Fraction of a normalized full-photo box's area inside a region."""
        area = box["width"] * box["height"]
        if area <= 0:
            return 0.0
        width = min(box["x"] + box["width"], region.x + region.width) - max(box["x"], region.x)
        height = min(box["y"] + box["height"], region.y + region.height) - max(box["y"], region.y)
        return max(0.0, width) * max(0.0, height) / area

    def ground_regions(self, args):
        result = self.artifact(
            "ground-v1", args, lambda im: self.models.ground(im, args.query)
        )
        # Cached detector evidence is pixel xyxy in the exact input image.
        # Convert here, not in the language model: uploaded previews can have
        # different dimensions from PhotoAsset and a crop has a different origin.
        image = self.store.read_image(args.photo_id, args.box)
        labels = result.get("text_labels", result.get("labels", []))
        detections = []
        for i, xyxy in enumerate(result["boxes"]):
            box = self.pixel_box(xyxy, image.size, args.box)
            if box is None:
                continue
            detections.append({"index": i, "label": labels[i],
                               "score": result["scores"][i], "box": box})
        return {"coordinate_space": "full_oriented_photo_normalized_xywh",
                "detections": detections}

    @classmethod
    def pixel_box(cls, xyxy, size, crop):
        left, top, right, bottom = xyxy
        width, height = size
        left, right = max(0, left / width), min(1, right / width)
        top, bottom = max(0, top / height), min(1, bottom / height)
        if right <= left or bottom <= top:
            return None
        return cls.full_photo_box({"x": left, "y": top, "width": right - left,
                                   "height": bottom - top}, crop)

    @staticmethod
    def full_photo_box(box, crop):
        local = Box.model_validate(box)
        if crop is None:
            return local.model_dump()
        return Box(x=crop.x + local.x * crop.width,
                   y=crop.y + local.y * crop.height,
                   width=local.width * crop.width,
                   height=local.height * crop.height).model_dump()

    def analyze_faces(self, args):
        result = self.artifact("sface-v1", args, self.models.faces)
        face_list = []
        for i, f in enumerate(result["faces"]):
            key = f"{args.photo_id}:face:{hashlib.sha256(encoded(args.model_dump()).encode()).hexdigest()[:12]}:{i}"
            self.store.vector(key, args.photo_id, "sface", f["vector"])
            face_list.append({"index": i, "box": self.full_photo_box(f["box"], args.box), "artifact": key})
        return {"coordinate_space": "full_oriented_photo_normalized_xywh", "faces": face_list}

    def ensure_embeddings(self, args):
        results = []
        for pid in args.photo_ids:
            p = self.authorize(pid)
            key = f"{pid}:image:{p.version}:{self.models.visual_space}"
            if not self.store.rows("SELECT key FROM vectors WHERE key=?", (key,)):
                space, vec = self.models.image(self.store.read_image(pid))
                self.store.vector(key, pid, space, vec)
            a = self.store.analysis(pid)
            if args.include_text and a:
                text = a["description"] + " " + a.get("ocr", "")
                tkey = f"{pid}:text:{hashlib.sha256(text.encode()).hexdigest()}:{self.models.text_space}"
                if not self.store.rows("SELECT key FROM vectors WHERE key=?", (tkey,)):
                    space, vec = self.models.text(text, query=False)
                    self.store.vector(tkey, pid, space, vec)
            results.append(pid)
        for region in args.regions:
            p = self.authorize(region.photo_id)
            key = (
                f"{p.id}:crop:"
                + hashlib.sha256(
                    encoded(
                        [p.version, region.model_dump(), self.models.visual_space]
                    ).encode()
                ).hexdigest()
            )
            if not self.store.rows("SELECT key FROM vectors WHERE key=?", (key,)):
                space, vec = self.models.image(self.store.read_image(p.id, region.box))
                self.authorize(p.id)
                self.store.vector(key, p.id, space, vec)
            results.append(key)
        return {"indexed": results}

    def index_coverage_sets(self, space):
        """Read-only coverage. Grants no search credit; index_coverage does."""
        eligible = self.candidate_ids()
        indexed = {
            r["photo_id"]
            for r in self.store.rows(
                "SELECT DISTINCT photo_id FROM vectors WHERE space=?", (space,)
            )
        } & eligible
        return indexed, eligible

    def index_coverage(self, space):
        indexed, eligible = self.index_coverage_sets(space)
        with self.tracking:
            self.searched.update(indexed)
        missing = eligible - indexed
        return {
            "indexed_count": len(indexed),
            "eligible_count": len(eligible),
            "unindexed_ids": sorted(missing)[:20],
            "unindexed_count": len(missing),
        }

    def search_visual(self, args):
        if args.photo_id:
            self.authorize(args.photo_id)
            space, vec = self.models.image(
                self.store.read_image(args.photo_id, args.box)
            )
        elif args.query:
            space, vec = self.models.text(args.query, visual=True)
        else:
            raise ValueError("A query or image is required")
        return {
            "candidates": self.store.search(space, vec, self.candidate_ids(), args.limit),
            "coverage": self.index_coverage(space),
        }

    def search_text(self, args):
        allowed = self.candidate_ids()
        # Literal and semantic channels are separate evidence, never fixed-score fusion.
        literal = []
        if args.query.strip():
            query = '"' + args.query.replace('"', '""') + '"'
            literal = [
                {"photo_id": r["photo_id"]}
                for r in self.store.rows(
                    "SELECT photo_id FROM evidence_fts WHERE evidence_fts MATCH ?",
                    (query,),
                )
                if r["photo_id"] in allowed
            ][: args.limit]
        try:
            space, vec = self.models.text(args.query)
            semantic = self.store.search(space, vec, allowed, args.limit)
            error = None
        except Exception as e:
            semantic = []
            error = type(e).__name__
        return {
            "literal": literal,
            "semantic": semantic,
            "semantic_error": error,
            "coverage": self.index_coverage(self.models.text_space),
        }

    def search_faces(self, args):
        result = self.artifact(
            "sface-v1",
            RegionArgs(photo_id=args.photo_id, box=args.box),
            self.models.faces,
        )
        if args.face_index >= len(result["faces"]):
            raise ValueError("Face index not found")
        return {
            "candidates": self.store.search(
                "sface",
                result["faces"][args.face_index]["vector"],
                self.candidate_ids(),
                args.limit,
            )
        }

    def anchor_text_queries(self, anchor, errors):
        """Label first, then cached in-box OCR text when it says something else.

        The selected label is what the user actually chose. Region OCR text can
        collapse to one very common token when a line straddles the selection
        edge, which retrieves the whole gallery; it stays a second query, never
        the only one.
        """
        queries = []
        if anchor.label.strip():
            queries.append(("label", anchor.label))
        recognized = self.anchor_ocr_text(anchor, errors)
        if recognized and recognized != anchor.label:
            queries.append(("ocr", recognized))
        return queries

    def anchor_ocr_text(self, anchor, errors):
        """Text for the initial lead channels: cached OCR only, never inference."""
        try:
            stored = self.stored_artifact(
                "ocr-v1", RegionArgs(photo_id=anchor.photo_id, box=None)
            )
            if stored is not None:
                size = self.store.read_image(anchor.photo_id).size
                lines = self.ocr_lines(stored, size, None)
                if anchor.box is not None:
                    lines = [line for line in lines
                             if self.inside_ratio(line["box"], anchor.box) >= REUSED_LINE_OVERLAP]
                text = " ".join(line["text"] for line in lines if line["text"].strip())
                if text.strip():
                    return text[:400]
        except Exception as e:
            errors["text_query"] = type(e).__name__
        return ""

    def initial_candidates(self, anchor, limit):
        """Host-retrieved leads supplied before the explorer's first response.

        Channels run concurrently and fail independently; a failed channel is an
        unavailable evidence source, not an empty gallery. No OCR inference runs
        here, and no coverage or search credit is granted: only the caller's
        image_block records what the model actually observes.
        """
        started = time.monotonic()
        allowed = self.candidate_ids()
        errors = {}
        queries = self.anchor_text_queries(anchor, errors)

        def visual():
            space, vector = self.models.image(
                self.store.read_image(anchor.photo_id, anchor.box)
            )
            return self.store.search(space, vector, allowed, limit)

        def by_query(retrieve):
            """Every query of the channel in order; the label's hits come first."""
            hits, taken = [], set()
            for source, text in queries:
                for hit in retrieve(text):
                    if hit["photo_id"] in taken:
                        continue
                    taken.add(hit["photo_id"])
                    hits.append({**hit, "query_source": source})
            return hits[:limit]

        def text_literal():
            def literal(text):
                match = '"' + text.replace('"', '""') + '"'
                return [
                    {"photo_id": r["photo_id"]}
                    for r in self.store.rows(
                        "SELECT photo_id FROM evidence_fts WHERE evidence_fts MATCH ?", (match,)
                    )
                    if r["photo_id"] in allowed
                ][:limit]

            return by_query(literal)

        def text_semantic():
            def semantic(text):
                space, vector = self.models.text(text)
                return self.store.search(space, vector, allowed, limit)

            return by_query(semantic)

        def faces():
            if anchor.kind != "person":
                return []
            detected = self.artifact(
                "sface-v1",
                RegionArgs(photo_id=anchor.photo_id, box=anchor.box),
                self.models.faces,
            )["faces"]
            largest = sorted(detected, key=lambda f: f["box"]["width"] * f["box"]["height"],
                             reverse=True)[:3]
            hits = []
            for face in largest:
                hits += self.store.search("sface", face["vector"], allowed, limit)
            return hits

        runners = {"visual": visual, "text_literal": text_literal,
                   "text_semantic": text_semantic, "faces": faces}
        results = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(runners), thread_name_prefix="initial-candidates"
        ) as pool:
            futures = {name: pool.submit(runners[name]) for name in INITIAL_CANDIDATE_CHANNELS}
            for name, future in futures.items():
                try:
                    results[name] = future.result()
                except Exception as e:
                    results[name] = []
                    errors[name] = type(e).__name__
        evidence, queues = {}, {}
        for name in INITIAL_CANDIDATE_CHANNELS:
            queue = []
            for hit in results[name]:
                pid = hit.get("photo_id")
                if pid is None or pid == anchor.photo_id or pid not in allowed:
                    continue
                queue.append(pid)
                entry = evidence.setdefault(pid, {"photo_id": pid, "channels": [],
                                                  "similarity": {}, "literal_match": False,
                                                  "query_source": None})
                if name not in entry["channels"]:
                    entry["channels"].append(name)
                if name == "text_literal":
                    entry["literal_match"] = True
                if entry["query_source"] is None and hit.get("query_source"):
                    entry["query_source"] = hit["query_source"]
                if "similarity" in hit:
                    score = round(float(hit["similarity"]), 4)
                    if score > entry["similarity"].get(name, -2):
                        entry["similarity"][name] = score
            queues[name] = queue
        selected, taken, depth = [], set(), 0
        while len(selected) < limit and any(depth < len(queues[n]) for n in INITIAL_CANDIDATE_CHANNELS):
            for name in INITIAL_CANDIDATE_CHANNELS:
                if len(selected) >= limit:
                    break
                queue = queues[name]
                if depth < len(queue) and queue[depth] not in taken:
                    taken.add(queue[depth])
                    selected.append(evidence[queue[depth]])
            depth += 1
        coverage = {}
        for label, space in (("visual", "visual_space"), ("text", "text_space")):
            try:
                indexed, eligible = self.index_coverage_sets(getattr(self.models, space))
                coverage[label] = {"indexed_count": len(indexed), "eligible_count": len(eligible),
                                   "unindexed_count": len(eligible - indexed)}
            except Exception as e:
                errors["coverage_" + label] = type(e).__name__
        return {
            "limit": limit,
            # Which query sources ran, never the query text or any photo id.
            "text_queries": {source: any(s == source for s, _ in queries)
                             for source in ("label", "ocr")},
            "channels": {n: len(set(queues[n])) for n in INITIAL_CANDIDATE_CHANNELS},
            "coverage": coverage,
            "channel_errors": errors,
            "candidates": selected,
            "seconds": round(time.monotonic() - started, 3),
        }

    def search_location(self, args):
        import math

        hits = []
        eligible = self.candidate_ids()
        for p in self.store.photos(
            self.request.explore.year if self.request.explore else None
        ):
            if p.id not in eligible or p.latitude is None or p.longitude is None:
                continue
            lat1, lat2 = map(math.radians, (args.latitude, p.latitude))
            dlat = lat2 - lat1
            dlon = math.radians(p.longitude - args.longitude)
            distance = (
                6371
                * 2
                * math.asin(
                    min(
                        1,
                        math.sqrt(
                            math.sin(dlat / 2) ** 2
                            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                        ),
                    )
                )
            )
            if distance <= args.radius_km:
                hits.append({"photo_id": p.id, "distance_km": distance})
        return {"candidates": hits}

    def read_spaces(self, args):
        return {
            "spaces": self.store.spaces(),
            "feedback": [
                json.loads(r["data"])
                for r in self.store.rows("SELECT data FROM feedback")
            ],
        }

    def search_time(self, args):
        photos = self.store.photos(self.request.explore.year if self.request.explore else None)
        eligible = self.candidate_ids()
        center = args.center or args.start + (args.end - args.start) / 2
        candidates = []
        unknown = 0
        for p in photos:
            if p.id not in eligible:
                continue
            if p.captured_at is None or p.captured_at.tzinfo is None or p.time_source not in ("exif", "media_store", "demo_fixture"):
                unknown += 1
                continue
            if args.start <= p.captured_at <= args.end:
                candidates.append({"photo_id": p.id, "captured_at": p.captured_at,
                                   "time_source": p.time_source,
                                   "distance_seconds": abs((p.captured_at - center).total_seconds())})
        candidates.sort(key=lambda p: p["distance_seconds"])
        return {"candidates": candidates[:args.limit], "total_in_window": len(candidates),
                "unknown_capture_time_count": unknown,
                "constraint": "Temporal candidates only. Inspect images before declaring a shared event."}

    def submit_photo_analysis(self, args):
        # Reject an oversized submission and let the agent choose the primary
        # subjects in its existing repair budget. Never truncate or categorize.
        args = PhotoAnalysisSubmission.model_validate(args.model_dump(mode="json"))
        if args.photo_id != self.request.photo_ids[0] or args.photo_id not in self.seen:
            raise ValueError("Inspect requested photo before submission")
        self.authorize(args.photo_id)
        # Indexing encodes the photo and the agent's evidence; it makes no
        # semantic decisions. Compute outside the repository lock, then commit both.
        from connected_gallery.application.indexing import AnalysisIndexing
        version = self.versions[args.photo_id]
        vectors = AnalysisIndexing(self.store, self.models).prepare(args, version) if self.models is not None else []
        with self.store.lock:
            self.authorize(args.photo_id)
            persisted_run = self.store.rows("SELECT id FROM runs WHERE id=?", (self.run_id,))
            self.store.save_analysis(args, vectors=vectors, expected_version=version,
                                     run_id=self.run_id if persisted_run else None)
            self.result = args.model_dump(mode="json")
        return {"saved": True}

    def submit_exploration_result(self, args):
        if args.empty_evidence is not None:
            raise ValueError("Independent negative evidence cannot be supplied by the retrieval agent")
        if args.groups or args.grouping_status != "legacy":
            raise ValueError("Submit candidates only; groups are created after independent evidence review")
        ids = [x.photo_id for x in args.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate result IDs")
        with self.tracking:
            observed = self.seen | self.searched
        if (
            not ids
            and args.complete
            and not self.allowed().issubset(observed)
        ):
            raise ValueError(
                "Unsearched photos remain. An empty index is not evidence of no matches. Inspect unindexed photos or submit incomplete."
            )
        anchor = self.request.explore.anchor.photo_id
        if anchor in ids:
            raise ValueError("The anchor photo is already being viewed; return other verified photos")
        if anchor not in self.seen:
            raise ValueError("Inspect anchor first")
        for pid in ids:
            self.authorize(pid, source=False)
            if pid not in self.seen:
                raise ValueError("Inspect candidate images before selecting them")
        self.result = args.model_dump(mode="json", exclude={"groups", "grouping_status", "empty_evidence"})
        if not self.defer_results:
            self.store.event(self.run_id, "results", self.result)
        else:
            self.store.event(self.run_id, "candidate_proposal", self.result)
        return {"saved": True, "complete": args.complete}

    def submit_space_proposal(self, args):
        with self.tracking:
            covered = set(self.covered)
        if not self.allowed().issubset(covered):
            coverage = self.coverage_status()
            raise ValueError(f"Page through the whole library before finalizing Spaces. "
                             f"Covered {coverage['covered_count']}/{coverage['total_count']}; "
                             f"list_photos next_uncovered_offset={coverage['next_uncovered_offset']}.")
        edits = [
            json.loads(r["data"]) for r in self.store.rows("SELECT data FROM feedback")
        ]
        old = {s["id"]: s for s in self.store.spaces()}
        incoming = {s.id: s.model_dump() for s in args.spaces}
        # Preserve explicitly edited Spaces, even when the agent omits one from a new proposal.
        for edit in edits:
            sid = edit.get("space_id")
            if sid in old and sid not in incoming:
                incoming[sid] = old[sid]
        for sid, space in incoming.items():
            for item in space["items"]:
                self.authorize(item["photo_id"])
            for edit in edits:
                if edit.get("space_id") != sid:
                    continue
                pid = edit.get("photo_id")
                if edit["kind"] == "space_exclude":
                    space["items"] = [x for x in space["items"] if x["photo_id"] != pid]
                elif (
                    edit["kind"] == "space_include"
                    and pid in self.allowed()
                    and not any(x["photo_id"] == pid for x in space["items"])
                ):
                    space["items"].append(
                        {"photo_id": pid, "reason": "사용자가 포함한 사진"}
                    )
        if getattr(self, "defer_spaces", False):
            self.result = {"spaces": list(incoming.values())}
            self.store.event(self.run_id, "space_candidate_proposal", self.result)
            return {"saved": False, "pending_review": True}
        with self.store.lock, self.store.db:
            states = self.store.rows("SELECT status FROM runs WHERE id=?", (self.run_id,))
            if states and states[0]["status"] not in ("running", "queued"):
                raise ValueError("Run is no longer active")
            for space in incoming.values():
                for item in space["items"]:
                    self.authorize(item["photo_id"])
            self.store.db.execute("DELETE FROM spaces")
            for sid, space in incoming.items():
                self.store.db.execute(
                    "INSERT INTO spaces VALUES(?,?)", (sid, encoded(space))
                )
        self.store.bump()
        self.result = {"spaces": list(incoming.values())}
        return {"saved": True}
